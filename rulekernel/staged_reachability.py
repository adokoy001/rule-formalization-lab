"""Complete staged reachability evidence for finite-decisions/1.

The certificate is unverified until staged_reachability_checker reconstructs
it.  The old reachability/1 implementation and certificate remain unchanged.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import product
from math import prod

from .model import (
    KernelError,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    PROFILE,
    canonical_json,
    digest,
    validate_limit,
    validate_model,
)
from .staged_reachability_model import (
    scope_expectations_binding,
    validate_scope_expectations_for_model,
)


ENGINE_VERSION = "0.1.0"
CERTIFICATE_FORMAT = "finite-decisions-staged-reachability-certificate/1"
_PARTITION_ORDER = ((True, True), (True, False), (False, True), (False, False))


def _domain_size(domain):
    if domain["kind"] == "bool":
        return 2
    if domain["kind"] == "int":
        return domain["max"] - domain["min"] + 1
    return len(domain["values"])


def _domain_values(domain):
    if domain["kind"] == "bool":
        return (False, True)
    if domain["kind"] == "int":
        return range(domain["min"], domain["max"] + 1)
    return domain["values"]


def _evaluate(expression, context):
    if "var" in expression:
        return context[expression["var"]]
    if "const" in expression:
        return expression["const"]
    operation, arguments = expression["op"], expression["args"]
    if operation == "not":
        return not _evaluate(arguments[0], context)
    if operation == "and":
        return all(_evaluate(argument, context) for argument in arguments)
    if operation == "or":
        return any(_evaluate(argument, context) for argument in arguments)
    left, right = (_evaluate(argument, context) for argument in arguments)
    if operation == "eq":
        return left == right
    if operation == "ne":
        return left != right
    if operation == "lt":
        return left < right
    if operation == "le":
        return left <= right
    if operation == "gt":
        return left > right
    if operation == "ge":
        return left >= right
    raise KernelError("UNSUPPORTED", "unknown staged reachability operator")


def _witness(index, context):
    return {"case_index": index, "input": dict(context)}


def _atomic_range_hint(expression, inputs, guard_count):
    if guard_count != 0 or type(expression) is not dict:
        return None
    if set(expression) != {"op", "args"} or type(expression["args"]) is not list:
        return None
    if len(expression["args"]) != 2:
        return None
    operation = expression["op"]
    if operation not in {"eq", "ne", "lt", "le", "gt", "ge"}:
        return None
    left, right = expression["args"]
    if (type(left) is dict and set(left) == {"var"} and
            type(right) is dict and set(right) == {"const"}):
        variable, constant = left["var"], right["const"]
    elif (type(left) is dict and set(left) == {"const"} and
          type(right) is dict and set(right) == {"var"}):
        variable, constant = right["var"], left["const"]
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
    minimum, maximum = domain["min"], domain["max"]
    disjoint = {
        "eq": constant < minimum or constant > maximum,
        "ne": minimum == maximum == constant,
        "lt": minimum >= constant,
        "le": minimum > constant,
        "gt": maximum <= constant,
        "ge": maximum < constant,
    }[operation]
    if not disjoint:
        return None
    return {
        "kind": "atomic_integer_comparison_disjoint_from_declared_domain",
        "variable": variable,
        "operator": operation,
        "constant": constant,
        "declared_min": minimum,
        "declared_max": maximum,
    }


def _activation_stage(summary):
    if summary["guard_count"] == 0:
        return "no_guard_witness_in_declared_domain"
    if summary["enabled_count"] == 0:
        return "no_enabled_witness_after_scope_filters"
    if summary["effective_count"] == 0:
        return "always_suppressed"
    if summary["effective_count"] < summary["enabled_count"]:
        return "partially_suppressed"
    return "always_effective_when_enabled"


def _filter_diagnosis(summary):
    if summary["guard_count"] == 0:
        return "not_applicable_without_guard_witness"
    if summary["enabled_count"]:
        return "scope_filters_leave_enabled_witness"
    facts = summary["guard_and_facts_count"]
    constraints = summary["guard_and_constraints_count"]
    if facts == 0 and constraints == 0:
        return "facts_and_constraints_each_block_all_guard_witnesses"
    if facts == 0:
        return "facts_block_all_guard_witnesses"
    if constraints == 0:
        return "constraints_block_all_guard_witnesses"
    return "combined_filters_have_no_common_witness"


def _legacy_classification(enabled_count, effective_count):
    if enabled_count == 0:
        return "unreachable"
    if effective_count == 0:
        return "always_suppressed"
    if effective_count < enabled_count:
        return "partially_suppressed"
    return "always_effective_when_enabled"


def _expectation_outcome(rule_id, enabled_count, effective_count, row):
    codes = []
    if row is None:
        scope_expectation = None
        if enabled_count == 0:
            expectation_result = "inactive_without_expectation"
            codes.append("INACTIVE_WITHOUT_EXPECTATION")
        else:
            expectation_result = "active_without_expectation"
    else:
        scope_expectation = {
            "expectation": row["expectation"],
            "source_unit_ids": list(row["source_unit_ids"]),
            "rationale": row["rationale"],
        }
        expectation = row["expectation"]
        if expectation == "expected_in_scope":
            if enabled_count:
                expectation_result = "matched_in_scope"
            else:
                expectation_result = "expected_in_scope_not_reached"
                codes.append("EXPECTED_IN_SCOPE_NOT_REACHED")
        elif expectation == "expected_inactive":
            if enabled_count == 0:
                expectation_result = "matched_inactive"
            else:
                expectation_result = "expected_inactive_but_reached"
                codes.append("EXPECTED_INACTIVE_BUT_REACHED")
        elif enabled_count == 0:
            expectation_result = "inactive_without_expectation"
            codes.append("INACTIVE_WITHOUT_EXPECTATION")
        else:
            expectation_result = "unspecified_active"
    if enabled_count > 0 and effective_count == 0:
        codes.append("ALWAYS_SUPPRESSED")
    return scope_expectation, expectation_result, codes


def _attention(rule_id, codes):
    details = {
        "EXPECTED_IN_SCOPE_NOT_REACHED":
            "scope expectation requires an enabled witness after facts and constraints",
        "EXPECTED_INACTIVE_BUT_REACHED":
            "scope expectation marks the rule inactive but the rule is enabled",
        "INACTIVE_WITHOUT_EXPECTATION":
            "inactive rule has no explicit expected_inactive decision",
        "ALWAYS_SUPPRESSED":
            "enabled rule is always suppressed by explicit overrides",
    }
    return [{"code": code, "rule_id": rule_id, "detail": details[code]}
            for code in codes]


def analyze_staged_reachability(
        model, scope_expectations=None, *, expected_scope_expectations_sha256=None,
        max_contexts=MAX_CONTEXTS):
    """Return unverified full-domain evidence for all reachability stages."""
    validate_model(model)
    validate_limit(max_contexts)
    expectations_by_rule = validate_scope_expectations_for_model(
        model, scope_expectations, expected_scope_expectations_sha256)
    names = sorted(model["inputs"])
    total = prod(_domain_size(model["inputs"][name]) for name in names)
    if total > max_contexts:
        raise KernelError("LIMIT_REACHED", "the full input domain exceeds max_contexts")

    rules = {rule["id"]: rule for rule in model["rules"]}
    rule_ids = sorted(rules)
    blockers = {rule_id: [] for rule_id in rule_ids}
    for rule_id in rule_ids:
        for target in rules[rule_id]["overrides"]:
            blockers[target].append(rule_id)
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
            "filter_partition": {
                cell: {"count": 0, "witness": None}
                for cell in _PARTITION_ORDER
            },
        }

    cases = []
    case_bytes = 2
    facts_matching_contexts = 0
    constraints_matching_contexts = 0
    admitted_contexts = 0
    for index, values in enumerate(product(
            *[_domain_values(model["inputs"][name]) for name in names])):
        context = dict(zip(names, values))
        facts_match = all(context[name] == value for name, value in facts.items())
        constraints_match = all(
            _evaluate(expression, context) for expression in model["constraints"])
        admitted = facts_match and constraints_match
        facts_matching_contexts += int(facts_match)
        constraints_matching_contexts += int(constraints_match)
        admitted_contexts += int(admitted)
        guard = [rule_id for rule_id in rule_ids
                 if _evaluate(rules[rule_id]["when"], context)]
        enabled = list(guard) if admitted else []
        effective = []
        if admitted:
            enabled_set = set(enabled)

            @lru_cache(maxsize=None)
            def survives(rule_id):
                return rule_id in enabled_set and not any(
                    survives(other) for other in blockers[rule_id])

            effective = [rule_id for rule_id in rule_ids if survives(rule_id)]
        for rule_id in guard:
            summary = summaries[rule_id]
            witness = _witness(index, context)
            summary["guard_count"] += 1
            if summary["guard_witness"] is None:
                summary["guard_witness"] = witness
            if facts_match:
                summary["guard_and_facts_count"] += 1
                if summary["guard_and_facts_witness"] is None:
                    summary["guard_and_facts_witness"] = witness
            if constraints_match:
                summary["guard_and_constraints_count"] += 1
                if summary["guard_and_constraints_witness"] is None:
                    summary["guard_and_constraints_witness"] = witness
            cell = summary["filter_partition"][(facts_match, constraints_match)]
            cell["count"] += 1
            if cell["witness"] is None:
                cell["witness"] = witness
        for phase, ids in (("enabled", enabled), ("effective", effective)):
            for rule_id in ids:
                summary = summaries[rule_id]
                summary[phase + "_count"] += 1
                if summary[phase + "_witness"] is None:
                    summary[phase + "_witness"] = _witness(index, context)
        case = {
            "index": index,
            "input": context,
            "facts_match": facts_match,
            "constraints_match": constraints_match,
            "admitted": admitted,
            "guard": guard,
            "enabled": enabled,
            "effective": effective,
        }
        case_bytes += len(canonical_json(case).encode("utf-8")) + (1 if cases else 0)
        if case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "staged reachability cases exceed the byte limit")
        cases.append(case)
    if admitted_contexts == 0:
        raise KernelError("BASE_INCONSISTENT",
                          "no input context satisfies facts and background constraints")

    rendered_summaries = []
    attention = []
    for rule_id in rule_ids:
        summary = summaries[rule_id]
        partition = [{
            "facts_match": facts_match,
            "constraints_match": constraints_match,
            "count": summary["filter_partition"][(facts_match, constraints_match)]["count"],
            "witness": summary["filter_partition"][(facts_match, constraints_match)]["witness"],
        } for facts_match, constraints_match in _PARTITION_ORDER]
        row = None if expectations_by_rule is None else expectations_by_rule[rule_id]
        scope_row, expectation_result, attention_codes = _expectation_outcome(
            rule_id, summary["enabled_count"], summary["effective_count"], row)
        rendered = {
            key: value for key, value in summary.items() if key != "filter_partition"
        }
        rendered.update({
            "filter_partition": partition,
            "activation_stage": _activation_stage(summary),
            "filter_diagnosis": _filter_diagnosis(summary),
            "range_hint": _atomic_range_hint(
                rules[rule_id]["when"], model["inputs"], summary["guard_count"]),
            "legacy_classification": _legacy_classification(
                summary["enabled_count"], summary["effective_count"]),
            "scope_expectation": scope_row,
            "expectation_result": expectation_result,
            "attention_codes": attention_codes,
        })
        rendered_summaries.append(rendered)
        attention.extend(_attention(rule_id, attention_codes))

    certificate = {
        "format": CERTIFICATE_FORMAT,
        "profile": PROFILE,
        "model_hash": digest(model),
        "engine_version": ENGINE_VERSION,
        "scope_expectations_binding": scope_expectations_binding(
            scope_expectations, expected_scope_expectations_sha256),
        "total_contexts": total,
        "facts_matching_contexts": facts_matching_contexts,
        "constraints_matching_contexts": constraints_matching_contexts,
        "admitted_contexts": admitted_contexts,
        "total_rules": len(rule_ids),
        "cases": cases,
        "rules": rendered_summaries,
        "attention": attention,
    }
    if len(canonical_json(certificate).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "complete staged reachability evidence exceeds the byte limit")
    return certificate
