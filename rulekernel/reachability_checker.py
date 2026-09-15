"""Independent complete replay of rule reachability certificates.

Only syntax/type validation, canonical JSON and hashing are shared.  This module
does not import the reachability searcher or either existing decision evaluator.
"""
from __future__ import annotations

from .model import (KernelError, MAX_CERTIFICATE_BYTES, MAX_CONTEXTS,
                    canonical_json, digest, validate_model)


CHECKER_VERSION = "0.1.0"
_ENGINE_VERSION = "0.1.0"
_CERTIFICATE_FORMAT = "finite-decisions-reachability-certificate/1"


def _invalid(message):
    raise KernelError("CERTIFICATE_INVALID", message)


def _certificate_text(certificate):
    pending = [(certificate, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 32:
            _invalid("Certificate nesting exceeds the certificate structure.")
        kind = type(value)
        if kind is dict:
            if any(type(key) is not str for key in value):
                _invalid("Certificate object keys must be strings.")
            pending.extend((child, depth + 1) for child in value.values())
        elif kind is list:
            pending.extend((child, depth + 1) for child in value)
        elif value is None or kind in (bool, int, str):
            continue
        else:
            _invalid("Certificate values must use the exact JSON value types.")
    try:
        text = canonical_json(certificate)
        size = len(text.encode("utf-8"))
    except (KernelError, ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        _invalid("Certificate cannot be represented as canonical UTF-8 JSON.")
    if size > MAX_CERTIFICATE_BYTES:
        _invalid("Certificate exceeds the byte limit.")
    return text


def _scope(inputs, limit):
    if type(limit) is not int or not 1 <= limit <= MAX_CONTEXTS:
        raise KernelError("LIMIT_REACHED", f"max_contexts must be an integer from 1 to {MAX_CONTEXTS}.")
    widths, total = {}, 1
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
            raise KernelError("LIMIT_REACHED", "The full input domain exceeds max_contexts.")
    return total, widths


def _assignment_at(index, inputs, widths):
    """Decode a mixed-radix index instead of invoking the searcher's product."""
    assignment = {}
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
        assignment[name] = value
    return {name: assignment[name] for name in sorted(inputs)}


def _evaluate(expression, assignment):
    """Evaluate all pure operands using an explicit postorder value stack."""
    pending, values = [(expression, False)], []
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
            if operation == "and":
                result = all(operands)
            elif operation == "or":
                result = any(operands)
            elif operation == "not":
                result = not operands[0]
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
                raise KernelError("UNSUPPORTED", "Unknown operator in checked reachability model.")
            values.append(result)
    return values[0]


def _override_order(rules):
    by_id = {rule["id"]: rule for rule in rules}
    predecessors = {rule_id: [] for rule_id in by_id}
    for rule in rules:
        for target in rule["overrides"]:
            predecessors[target].append(rule["id"])
    degree = {rule_id: len(parents) for rule_id, parents in predecessors.items()}
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
        raise KernelError("UNSUPPORTED", "Override cycle in checked reachability model.")
    return order, predecessors


def _replay(model, total, widths):
    rules = {rule["id"]: rule for rule in model["rules"]}
    order, predecessors = _override_order(model["rules"])
    enabled_counts = dict.fromkeys(rules, 0)
    effective_counts = dict.fromkeys(rules, 0)
    first_enabled = dict.fromkeys(rules, None)
    first_effective = dict.fromkeys(rules, None)
    cases, admitted_contexts, case_bytes = [], 0, 2
    for index in range(total):
        assignment = _assignment_at(index, model["inputs"], widths)
        admitted = all(assignment[fact["var"]] == fact["value"] for fact in model["facts"])
        if admitted:
            admitted = all(_evaluate(condition, assignment) for condition in model["constraints"])
        enabled, effective = [], []
        if admitted:
            admitted_contexts += 1
            guards = {rule_id: _evaluate(rule["when"], assignment) for rule_id, rule in rules.items()}
            surviving = {}
            for rule_id in order:
                surviving[rule_id] = guards[rule_id] and not any(
                    surviving[parent] for parent in predecessors[rule_id])
            enabled = sorted(rule_id for rule_id in rules if guards[rule_id])
            effective = sorted(rule_id for rule_id in rules if surviving[rule_id])
            for rule_id in rules:
                if guards[rule_id]:
                    enabled_counts[rule_id] += 1
                    if first_enabled[rule_id] is None:
                        first_enabled[rule_id] = {"case_index": index, "input": dict(assignment)}
                if surviving[rule_id]:
                    effective_counts[rule_id] += 1
                    if first_effective[rule_id] is None:
                        first_effective[rule_id] = {"case_index": index, "input": dict(assignment)}
        case = {"index": index, "input": assignment, "admitted": admitted,
                "enabled": enabled, "effective": effective}
        case_bytes += len(canonical_json(case).encode("utf-8")) + (1 if cases else 0)
        if case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Independent reachability replay exceeds the certificate byte limit.")
        cases.append(case)
    if not admitted_contexts:
        raise KernelError("BASE_INCONSISTENT", "No input context satisfies the facts and background conditions.")

    summaries = []
    for rule_id in sorted(rules):
        enabled_count, effective_count = enabled_counts[rule_id], effective_counts[rule_id]
        if effective_count == enabled_count:
            classification = "always_effective_when_enabled" if enabled_count else "unreachable"
        elif effective_count:
            classification = "partially_suppressed"
        else:
            classification = "always_suppressed"
        summaries.append({
            "rule_id": rule_id,
            "enabled_count": enabled_count,
            "effective_count": effective_count,
            "enabled_witness": first_enabled[rule_id],
            "effective_witness": first_effective[rule_id],
            "classification": classification,
        })
    expected = {
        "format": _CERTIFICATE_FORMAT,
        "profile": model["profile"],
        "model_hash": digest(model),
        "engine_version": _ENGINE_VERSION,
        "total_contexts": total,
        "admitted_contexts": admitted_contexts,
        "total_rules": len(rules),
        "cases": cases,
        "rules": summaries,
    }
    if len(canonical_json(expected).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Complete reachability replay exceeds the certificate byte limit.")
    return expected


def verify_reachability(model, certificate, max_contexts=MAX_CONTEXTS):
    """Check all rows and all diagnostics against the caller's expected model."""
    validate_model(model)
    total, widths = _scope(model["inputs"], max_contexts)
    supplied_text = _certificate_text(certificate)
    expected = _replay(model, total, widths)
    if supplied_text != canonical_json(expected):
        _invalid("Reachability certificate does not match the complete independent replay.")
    return {
        "status": "VERIFIED",
        "checker_version": CHECKER_VERSION,
        "model_hash": expected["model_hash"],
        "certificate_hash": digest(certificate),
        "total_contexts": total,
        "admitted_contexts": expected["admitted_contexts"],
        "total_rules": expected["total_rules"],
        "rules": expected["rules"],
    }
