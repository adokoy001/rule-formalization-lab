"""Independent replay of staged reachability certificates.

This checker shares the Core validator, JSON/hash utilities, limits, and the
scope-expectation consumer.  It does not import the staged producer or either
legacy reachability implementation.
"""
from __future__ import annotations

from .model import (
    KernelError,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    canonical_json,
    digest,
    validate_model,
)
from .staged_reachability_model import (
    scope_expectations_binding,
    validate_scope_expectations_for_model,
)


CHECKER_VERSION = "0.1.0"
_ENGINE_VERSION = "0.1.0"
_CERTIFICATE_FORMAT = "finite-decisions-staged-reachability-certificate/1"
_PARTITION_ORDER = ((True, True), (True, False), (False, True), (False, False))


def _invalid(message):
    raise KernelError("CERTIFICATE_INVALID", message)


def _certificate_text(certificate):
    pending = [(certificate, 0, False)]
    active_containers = set()
    while pending:
        value, depth, exiting = pending.pop()
        if exiting:
            active_containers.remove(id(value))
            continue
        if depth > 40:
            _invalid("certificate nesting exceeds the staged certificate structure")
        kind = type(value)
        if kind is dict:
            identity = id(value)
            if identity in active_containers:
                _invalid("certificate contains a cyclic container")
            active_containers.add(identity)
            if any(type(key) is not str for key in value):
                _invalid("certificate object keys must be strings")
            pending.append((value, depth, True))
            pending.extend((child, depth + 1, False) for child in value.values())
        elif kind is list:
            identity = id(value)
            if identity in active_containers:
                _invalid("certificate contains a cyclic container")
            active_containers.add(identity)
            pending.append((value, depth, True))
            pending.extend((child, depth + 1, False) for child in value)
        elif value is None or kind in (bool, int, str):
            continue
        else:
            _invalid("certificate values must use exact JSON value types")
    try:
        rendered = canonical_json(certificate)
        size = len(rendered.encode("utf-8"))
    except (KernelError, ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        _invalid("certificate cannot be represented as canonical UTF-8 JSON")
    if size > MAX_CERTIFICATE_BYTES:
        _invalid("certificate exceeds the byte limit")
    return rendered


def _scope(inputs, limit):
    if type(limit) is not int or not 1 <= limit <= MAX_CONTEXTS:
        raise KernelError("LIMIT_REACHED",
                          f"max_contexts must be an integer from 1 to {MAX_CONTEXTS}")
    widths = {}
    total = 1
    for name in sorted(inputs):
        domain = inputs[name]
        if domain["kind"] == "int":
            width = domain["max"] - domain["min"] + 1
        elif domain["kind"] == "enum":
            width = len(domain["values"])
        else:
            width = 2
        widths[name] = width
        total *= width
        if total > limit:
            raise KernelError("LIMIT_REACHED", "the full input domain exceeds max_contexts")
    return total, widths


def _assignment_at(index, inputs, widths):
    values = {}
    remaining = index
    for name in reversed(sorted(inputs)):
        remaining, digit = divmod(remaining, widths[name])
        domain = inputs[name]
        if domain["kind"] == "enum":
            value = domain["values"][digit]
        elif domain["kind"] == "int":
            value = domain["min"] + digit
        else:
            value = digit == 1
        values[name] = value
    return {name: values[name] for name in sorted(inputs)}


def _evaluate(expression, assignment):
    pending = [(expression, False)]
    values = []
    while pending:
        node, expanded = pending.pop()
        if "const" in node:
            values.append(node["const"])
        elif "var" in node:
            values.append(assignment[node["var"]])
        elif not expanded:
            pending.append((node, True))
            pending.extend((argument, False) for argument in reversed(node["args"]))
        else:
            count = len(node["args"])
            operands = values[-count:]
            del values[-count:]
            operation = node["op"]
            if operation == "not":
                result = not operands[0]
            elif operation == "and":
                result = all(operands)
            elif operation == "or":
                result = any(operands)
            elif operation == "eq":
                result = operands[0] == operands[1]
            elif operation == "ne":
                result = operands[0] != operands[1]
            elif operation == "lt":
                result = operands[0] < operands[1]
            elif operation == "le":
                result = operands[0] <= operands[1]
            elif operation == "gt":
                result = operands[0] > operands[1]
            elif operation == "ge":
                result = operands[0] >= operands[1]
            else:
                raise KernelError("UNSUPPORTED", "unknown operator in staged checker")
            values.append(result)
    return values[0]


def _override_order(rules):
    by_id = {rule["id"]: rule for rule in rules}
    blockers = {rule_id: [] for rule_id in by_id}
    for rule in rules:
        for target in rule["overrides"]:
            blockers[target].append(rule["id"])
    degree = {rule_id: len(parents) for rule_id, parents in blockers.items()}
    ready = [rule_id for rule_id in sorted(degree) if degree[rule_id] == 0]
    order = []
    while ready:
        rule_id = ready.pop()
        order.append(rule_id)
        for target in by_id[rule_id]["overrides"]:
            degree[target] -= 1
            if degree[target] == 0:
                ready.append(target)
    if len(order) != len(rules):
        raise KernelError("UNSUPPORTED", "override cycle in staged checker model")
    return order, blockers


def _witness(index, assignment):
    return {"case_index": index, "input": dict(assignment)}


def _range_hint(expression, inputs, guard_count):
    if guard_count or type(expression) is not dict:
        return None
    if set(expression) != {"op", "args"} or type(expression["args"]) is not list:
        return None
    if len(expression["args"]) != 2:
        return None
    operation = expression["op"]
    if operation not in {"eq", "ne", "lt", "le", "gt", "ge"}:
        return None
    first, second = expression["args"]
    if (type(first) is dict and set(first) == {"var"} and
            type(second) is dict and set(second) == {"const"}):
        variable = first["var"]
        constant = second["const"]
    elif (type(first) is dict and set(first) == {"const"} and
          type(second) is dict and set(second) == {"var"}):
        variable = second["var"]
        constant = first["const"]
        operation = {"eq": "eq", "ne": "ne", "lt": "gt", "le": "ge",
                     "gt": "lt", "ge": "le"}[operation]
    else:
        return None
    if (type(variable) is not str or variable not in inputs or
            type(constant) is not int):
        return None
    domain = inputs[variable]
    if domain["kind"] != "int":
        return None
    lower, upper = domain["min"], domain["max"]
    if operation == "eq":
        impossible = constant < lower or constant > upper
    elif operation == "ne":
        impossible = lower == upper == constant
    elif operation == "lt":
        impossible = lower >= constant
    elif operation == "le":
        impossible = lower > constant
    elif operation == "gt":
        impossible = upper <= constant
    else:
        impossible = upper < constant
    if not impossible:
        return None
    return {
        "kind": "atomic_integer_comparison_disjoint_from_declared_domain",
        "variable": variable,
        "operator": operation,
        "constant": constant,
        "declared_min": lower,
        "declared_max": upper,
    }


def _activation(summary):
    if summary["guard_count"] == 0:
        return "no_guard_witness_in_declared_domain"
    if summary["enabled_count"] == 0:
        return "no_enabled_witness_after_scope_filters"
    if summary["effective_count"] == 0:
        return "always_suppressed"
    if summary["effective_count"] < summary["enabled_count"]:
        return "partially_suppressed"
    return "always_effective_when_enabled"


def _filter_label(summary):
    if summary["guard_count"] == 0:
        return "not_applicable_without_guard_witness"
    if summary["enabled_count"] != 0:
        return "scope_filters_leave_enabled_witness"
    after_facts = summary["guard_and_facts_count"]
    after_constraints = summary["guard_and_constraints_count"]
    if after_facts == 0 and after_constraints == 0:
        return "facts_and_constraints_each_block_all_guard_witnesses"
    if after_facts == 0:
        return "facts_block_all_guard_witnesses"
    if after_constraints == 0:
        return "constraints_block_all_guard_witnesses"
    return "combined_filters_have_no_common_witness"


def _legacy(enabled, effective):
    if enabled == 0:
        return "unreachable"
    if effective == 0:
        return "always_suppressed"
    if effective < enabled:
        return "partially_suppressed"
    return "always_effective_when_enabled"


def _expectation(enabled, effective, row):
    attention_codes = []
    if row is None:
        scope_row = None
        if enabled:
            result = "active_without_expectation"
        else:
            result = "inactive_without_expectation"
            attention_codes.append("INACTIVE_WITHOUT_EXPECTATION")
    else:
        scope_row = {
            "expectation": row["expectation"],
            "source_unit_ids": list(row["source_unit_ids"]),
            "rationale": row["rationale"],
        }
        expected = row["expectation"]
        if expected == "expected_in_scope":
            if enabled:
                result = "matched_in_scope"
            else:
                result = "expected_in_scope_not_reached"
                attention_codes.append("EXPECTED_IN_SCOPE_NOT_REACHED")
        elif expected == "expected_inactive":
            if enabled:
                result = "expected_inactive_but_reached"
                attention_codes.append("EXPECTED_INACTIVE_BUT_REACHED")
            else:
                result = "matched_inactive"
        elif enabled:
            result = "unspecified_active"
        else:
            result = "inactive_without_expectation"
            attention_codes.append("INACTIVE_WITHOUT_EXPECTATION")
    if enabled and effective == 0:
        attention_codes.append("ALWAYS_SUPPRESSED")
    return scope_row, result, attention_codes


def _attention_rows(rule_id, codes):
    messages = {
        "EXPECTED_IN_SCOPE_NOT_REACHED":
            "scope expectation requires an enabled witness after facts and constraints",
        "EXPECTED_INACTIVE_BUT_REACHED":
            "scope expectation marks the rule inactive but the rule is enabled",
        "INACTIVE_WITHOUT_EXPECTATION":
            "inactive rule has no explicit expected_inactive decision",
        "ALWAYS_SUPPRESSED":
            "enabled rule is always suppressed by explicit overrides",
    }
    return [{"code": code, "rule_id": rule_id, "detail": messages[code]}
            for code in codes]


def _replay(model, total, widths, expectations, expected_hash, expectations_by_rule):
    rules = {rule["id"]: rule for rule in model["rules"]}
    rule_ids = sorted(rules)
    order, blockers = _override_order(model["rules"])
    facts = {fact["var"]: fact["value"] for fact in model["facts"]}
    summaries = {}
    for rule_id in rule_ids:
        summaries[rule_id] = {
            "rule_id": rule_id,
            "guard_count": 0,
            "guard_witness": None,
            "guard_and_facts_count": 0,
            "guard_and_facts_witness": None,
            "guard_and_constraints_count": 0,
            "guard_and_constraints_witness": None,
            "enabled_count": 0,
            "enabled_witness": None,
            "effective_count": 0,
            "effective_witness": None,
            "cells": {cell: {"count": 0, "witness": None}
                      for cell in _PARTITION_ORDER},
        }
    cases = []
    case_bytes = 2
    facts_total = 0
    constraints_total = 0
    admitted_total = 0
    for index in range(total):
        assignment = _assignment_at(index, model["inputs"], widths)
        facts_match = all(
            assignment[fact["var"]] == fact["value"] for fact in model["facts"])
        constraints_match = all(
            _evaluate(expression, assignment) for expression in model["constraints"])
        admitted = facts_match and constraints_match
        facts_total += int(facts_match)
        constraints_total += int(constraints_match)
        admitted_total += int(admitted)
        guard_truth = {
            rule_id: _evaluate(rule["when"], assignment)
            for rule_id, rule in rules.items()
        }
        guard = sorted(rule_id for rule_id in rules if guard_truth[rule_id])
        enabled = list(guard) if admitted else []
        effective = []
        if admitted:
            surviving = {}
            for rule_id in order:
                surviving[rule_id] = guard_truth[rule_id] and not any(
                    surviving[parent] for parent in blockers[rule_id])
            effective = sorted(rule_id for rule_id in rules if surviving[rule_id])
        for rule_id in guard:
            summary = summaries[rule_id]
            here = _witness(index, assignment)
            summary["guard_count"] += 1
            if summary["guard_witness"] is None:
                summary["guard_witness"] = here
            if facts_match:
                summary["guard_and_facts_count"] += 1
                if summary["guard_and_facts_witness"] is None:
                    summary["guard_and_facts_witness"] = here
            if constraints_match:
                summary["guard_and_constraints_count"] += 1
                if summary["guard_and_constraints_witness"] is None:
                    summary["guard_and_constraints_witness"] = here
            cell = summary["cells"][(facts_match, constraints_match)]
            cell["count"] += 1
            if cell["witness"] is None:
                cell["witness"] = here
        for rule_id in enabled:
            summary = summaries[rule_id]
            summary["enabled_count"] += 1
            if summary["enabled_witness"] is None:
                summary["enabled_witness"] = _witness(index, assignment)
        for rule_id in effective:
            summary = summaries[rule_id]
            summary["effective_count"] += 1
            if summary["effective_witness"] is None:
                summary["effective_witness"] = _witness(index, assignment)
        case = {
            "index": index,
            "input": assignment,
            "facts_match": facts_match,
            "constraints_match": constraints_match,
            "admitted": admitted,
            "guard": guard,
            "enabled": enabled,
            "effective": effective,
        }
        case_bytes += len(canonical_json(case).encode("utf-8")) + (1 if cases else 0)
        if case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "independent staged replay exceeds the byte limit")
        cases.append(case)
    if admitted_total == 0:
        raise KernelError("BASE_INCONSISTENT",
                          "no input context satisfies facts and background constraints")

    output_summaries = []
    attention = []
    for rule_id in rule_ids:
        summary = summaries[rule_id]
        partition = []
        for facts_match, constraints_match in _PARTITION_ORDER:
            cell = summary["cells"][(facts_match, constraints_match)]
            partition.append({
                "facts_match": facts_match,
                "constraints_match": constraints_match,
                "count": cell["count"],
                "witness": cell["witness"],
            })
        row = None if expectations_by_rule is None else expectations_by_rule[rule_id]
        scope_row, expectation_result, codes = _expectation(
            summary["enabled_count"], summary["effective_count"], row)
        output = {key: value for key, value in summary.items() if key != "cells"}
        output.update({
            "filter_partition": partition,
            "activation_stage": _activation(summary),
            "filter_diagnosis": _filter_label(summary),
            "range_hint": _range_hint(
                rules[rule_id]["when"], model["inputs"], summary["guard_count"]),
            "legacy_classification": _legacy(
                summary["enabled_count"], summary["effective_count"]),
            "scope_expectation": scope_row,
            "expectation_result": expectation_result,
            "attention_codes": codes,
        })
        output_summaries.append(output)
        attention.extend(_attention_rows(rule_id, codes))

    expected = {
        "format": _CERTIFICATE_FORMAT,
        "profile": model["profile"],
        "model_hash": digest(model),
        "engine_version": _ENGINE_VERSION,
        "scope_expectations_binding": scope_expectations_binding(
            expectations, expected_hash),
        "total_contexts": total,
        "facts_matching_contexts": facts_total,
        "constraints_matching_contexts": constraints_total,
        "admitted_contexts": admitted_total,
        "total_rules": len(rule_ids),
        "cases": cases,
        "rules": output_summaries,
        "attention": attention,
    }
    if len(canonical_json(expected).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "complete staged replay exceeds the byte limit")
    return expected


def verify_staged_reachability(
        model, certificate, scope_expectations=None, *,
        expected_scope_expectations_sha256=None, max_contexts=MAX_CONTEXTS):
    """Reconstruct every staged row and finding from the caller's Core model."""
    validate_model(model)
    expectations_by_rule = validate_scope_expectations_for_model(
        model, scope_expectations, expected_scope_expectations_sha256)
    total, widths = _scope(model["inputs"], max_contexts)
    supplied = _certificate_text(certificate)
    expected = _replay(
        model, total, widths, scope_expectations,
        expected_scope_expectations_sha256, expectations_by_rule)
    if supplied != canonical_json(expected):
        _invalid("staged reachability certificate differs from complete independent replay")
    return {
        "status": "VERIFIED",
        "checker_version": CHECKER_VERSION,
        "model_hash": expected["model_hash"],
        "certificate_hash": digest(certificate),
        "scope_expectations_binding": expected["scope_expectations_binding"],
        "total_contexts": expected["total_contexts"],
        "facts_matching_contexts": expected["facts_matching_contexts"],
        "constraints_matching_contexts": expected["constraints_matching_contexts"],
        "admitted_contexts": expected["admitted_contexts"],
        "total_rules": expected["total_rules"],
        "rules": expected["rules"],
        "attention": expected["attention"],
        "attention_count": len(expected["attention"]),
    }
