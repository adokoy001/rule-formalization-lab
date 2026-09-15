"""Exhaustive revision comparison for the finite-decisions/1 profile."""
from __future__ import annotations

from functools import lru_cache
from itertools import product
from math import prod

from .model import (KernelError, MAX_CERTIFICATE_BYTES, MAX_CONTEXTS,
                    canonical_json, digest, validate_limit, validate_model)

DIFF_FORMAT = "finite-decisions-diff-certificate/1"
DIFF_PROFILE = "finite-decisions-diff/1"
DIFF_VERSION = "0.1.0"


def _compatible(left: dict, right: dict) -> None:
    validate_model(left)
    validate_model(right)
    if (left["profile"] != right["profile"]
            or canonical_json(left["inputs"]) != canonical_json(right["inputs"])
            or canonical_json(left["outputs"]) != canonical_json(right["outputs"])):
        raise KernelError("UNSUPPORTED", "Diff requires identical input and output declarations, including domain order and required.")


def _domain_size(declared: dict) -> int:
    if declared["kind"] == "bool":
        return 2
    if declared["kind"] == "int":
        return declared["max"] - declared["min"] + 1
    return len(declared["values"])


def _domain(declared: dict):
    if declared["kind"] == "bool":
        return (False, True)
    if declared["kind"] == "int":
        return range(declared["min"], declared["max"] + 1)
    return declared["values"]


def _evaluate(expr: dict, context: dict):
    if "var" in expr:
        return context[expr["var"]]
    if "const" in expr:
        return expr["const"]
    op, args = expr["op"], expr["args"]
    if op == "and":
        return all(_evaluate(arg, context) for arg in args)
    if op == "or":
        return any(_evaluate(arg, context) for arg in args)
    if op == "not":
        return not _evaluate(args[0], context)
    a, b = (_evaluate(arg, context) for arg in args)
    if op == "eq":
        return a == b
    if op == "ne":
        return a != b
    if op == "lt":
        return a < b
    if op == "le":
        return a <= b
    if op == "gt":
        return a > b
    if op == "ge":
        return a >= b
    raise KernelError("UNSUPPORTED", "Unsupported operator in revision model.")


def _snapshot(model: dict, context: dict) -> dict:
    admitted = all(context[f["var"]] == f["value"] for f in model["facts"])
    admitted = admitted and all(_evaluate(expr, context) for expr in model["constraints"])
    if not admitted:
        return {"admitted": False, "outputs": {}}
    rules = {rule["id"]: rule for rule in model["rules"]}
    blockers = {name: [] for name in rules}
    for rule in model["rules"]:
        for target in rule["overrides"]:
            blockers[target].append(rule["id"])

    @lru_cache(maxsize=None)
    def effective(name):
        return (_evaluate(rules[name]["when"], context)
                and not any(effective(other) for other in blockers[name]))

    active = sorted(name for name in rules if effective(name))
    outputs = {}
    for output in sorted(model["outputs"]):
        ids = [name for name in active if rules[name]["then"]["output"] == output]
        values_by_json = {canonical_json(rules[name]["then"]["value"]):
                          rules[name]["then"]["value"] for name in ids}
        values = [values_by_json[key] for key in sorted(values_by_json)]
        state = "absent" if not values else "defined" if len(values) == 1 else "conflicting"
        outputs[output] = {"state": state, "values": values, "rule_ids": ids}
    return {"admitted": True, "outputs": outputs}


def _changes(before: dict, after: dict, required: bool) -> list[str]:
    kinds = []
    if (before["state"] != after["state"]
            or canonical_json(before["values"]) != canonical_json(after["values"])):
        kinds.append("semantic_change")
    elif before["rule_ids"] != after["rule_ids"]:
        kinds.append("explanation_only")
    if before["state"] != "conflicting" and after["state"] == "conflicting":
        kinds.append("conflict_introduced")
    if before["state"] == "conflicting" and after["state"] != "conflicting":
        kinds.append("conflict_resolved")
    if required and before["state"] != "absent" and after["state"] == "absent":
        kinds.append("gap_introduced")
    if required and before["state"] == "absent" and after["state"] != "absent":
        kinds.append("gap_resolved")
    return kinds


def analyze_diff(left: dict, right: dict, max_contexts: int = MAX_CONTEXTS) -> dict:
    """Compare the complete declared domain; unilateral admission is a change.

    Semantic and explanation queries range only over commonly admitted cases.
    Scope changes have their own query; no side is interpreted outside its base.
    """
    _compatible(left, right)
    validate_limit(max_contexts)
    names = sorted(left["inputs"])
    total = prod(_domain_size(left["inputs"][name]) for name in names)
    if total > max_contexts:
        raise KernelError("LIMIT_REACHED", "Diff full input domain exceeds max_contexts.")
    queries = [{"kind": "scope_change", "output": None, "count": 0, "witness": None}]
    for output in sorted(left["outputs"]):
        kinds = ["semantic_change", "explanation_only", "conflict_introduced", "conflict_resolved"]
        if left["outputs"][output]["required"]:
            kinds.extend(["gap_introduced", "gap_resolved"])
        queries.extend({"kind": kind, "output": output, "count": 0, "witness": None}
                       for kind in kinds)
    by_query = {(query["output"], query["kind"]): query for query in queries}

    def finding(output, kind, witness):
        query = by_query[(output, kind)]
        query["count"] += 1
        if query["witness"] is None:
            query["witness"] = witness

    cases = []
    case_bytes = 2
    left_count = right_count = common_count = 0
    domains = [_domain(left["inputs"][name]) for name in names]
    for index, values in enumerate(product(*domains)):
        context = dict(zip(names, values))
        before, after = _snapshot(left, context), _snapshot(right, context)
        case = {"index": index, "input": context, "left": before, "right": after}
        case_bytes += len(canonical_json(case).encode("utf-8")) + bool(cases)
        if case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Diff evidence exceeds the certificate byte limit.")
        cases.append(case)
        left_count += int(before["admitted"])
        right_count += int(after["admitted"])
        if before["admitted"] != after["admitted"]:
            finding(None, "scope_change", {"case_index": index, "input": context,
                    "left": before["admitted"], "right": after["admitted"]})
        if not (before["admitted"] and after["admitted"]):
            continue
        common_count += 1
        for output in sorted(left["outputs"]):
            old, new = before["outputs"][output], after["outputs"][output]
            for kind in _changes(old, new, left["outputs"][output]["required"]):
                finding(output, kind, {"case_index": index, "input": context,
                        "left": old, "right": new})
    if not left_count or not right_count:
        sides = " and ".join(side for side, count in (("left", left_count), ("right", right_count)) if not count)
        raise KernelError("BASE_INCONSISTENT", f"No admitted input context on {sides} model.")
    certificate = {
        "format": DIFF_FORMAT, "comparison_profile": DIFF_PROFILE,
        "profile": left["profile"], "engine_version": DIFF_VERSION,
        "left_model_hash": digest(left), "right_model_hash": digest(right),
        "total_contexts": total, "left_admitted_contexts": left_count,
        "right_admitted_contexts": right_count, "common_admitted_contexts": common_count,
        "cases": cases, "queries": queries,
    }
    if len(canonical_json(certificate).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Diff evidence exceeds the certificate byte limit.")
    return certificate
