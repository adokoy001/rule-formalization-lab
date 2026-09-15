"""Independent replay checker for finite-decisions revision evidence.

No evaluator, enumeration, exception resolution, or aggregation is imported
from the producer or the ordinary decision checker.
"""
from __future__ import annotations

import operator

from .model import (KernelError, MAX_CERTIFICATE_BYTES, MAX_CONTEXTS,
                    canonical_json, digest, validate_model)

CHECKER_VERSION = "0.1.0"
_FORMAT = "finite-decisions-diff-certificate/1"
_COMPARISON_PROFILE = "finite-decisions-diff/1"
_PRODUCER_VERSION = "0.1.0"
_COMPARISONS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
                "le": operator.le, "gt": operator.gt, "ge": operator.ge}


def _invalid(message: str):
    raise KernelError("CERTIFICATE_INVALID", message)


def _evidence_json(evidence: object) -> str:
    if type(evidence) is not dict:
        _invalid("Diff certificate must be a JSON object.")
    pending = [(evidence, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 32:
            _invalid("Diff certificate nesting exceeds the allowed shape.")
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                _invalid("Diff certificate object keys must be strings.")
            pending.extend((child, depth + 1) for child in value.values())
        elif type(value) is list:
            pending.extend((child, depth + 1) for child in value)
        elif value is not None and type(value) not in (bool, int, str):
            _invalid("Diff certificate contains a non-JSON value or floating point number.")
    try:
        result = canonical_json(evidence)
        size = len(result.encode("utf-8"))
    except (KernelError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise KernelError("CERTIFICATE_INVALID", "Diff certificate cannot be encoded as strict JSON.") from exc
    if size > MAX_CERTIFICATE_BYTES:
        _invalid("Diff certificate exceeds the certificate byte limit.")
    return result


def _checked_scope(left: dict, right: dict, limit: int) -> int:
    validate_model(left)
    validate_model(right)
    for field in ("profile", "inputs", "outputs"):
        if canonical_json(left[field]) != canonical_json(right[field]):
            raise KernelError("UNSUPPORTED", "Diff requires identical profiles, input declarations and output declarations.")
    if type(limit) is not int or limit < 1 or limit > MAX_CONTEXTS:
        raise KernelError("LIMIT_REACHED", f"max_contexts must be an integer from 1 to {MAX_CONTEXTS}.")
    count = 1
    for declared in left["inputs"].values():
        if declared["kind"] == "int":
            width = declared["max"] + 1 - declared["min"]
        elif declared["kind"] == "enum":
            width = len(declared["values"])
        else:
            width = 2
        count *= width
        if count > limit:
            raise KernelError("LIMIT_REACHED", "Diff full Cartesian domain exceeds max_contexts.")
    return count


def _assignments(inputs: dict, count: int):
    # Recover coordinates from an ordinal rather than using the producer's product.
    variables = sorted(inputs)
    domains = []
    for name in variables:
        declared = inputs[name]
        if declared["kind"] == "enum":
            domain = declared["values"]
        elif declared["kind"] == "bool":
            domain = [False, True]
        else:
            domain = range(declared["min"], declared["max"] + 1)
        domains.append(domain)
    for ordinal in range(count):
        remainder = ordinal
        assignment = {}
        for position in range(len(variables) - 1, -1, -1):
            domain = domains[position]
            remainder, digit = divmod(remainder, len(domain))
            assignment[variables[position]] = domain[digit]
        yield assignment


def _eval(expression: dict, assignment: dict):
    # Explicit postorder stack: each argument is evaluated without recursion.
    work = [(expression, False)]
    results = []
    while work:
        node, expanded = work.pop()
        if "const" in node:
            results.append(node["const"])
        elif "var" in node:
            results.append(assignment[node["var"]])
        elif not expanded:
            work.append((node, True))
            work.extend((child, False) for child in reversed(node["args"]))
        else:
            arity = len(node["args"])
            operands = results[-arity:]
            del results[-arity:]
            operation = node["op"]
            if operation == "and":
                value = all(operands)
            elif operation == "or":
                value = any(operands)
            elif operation == "not":
                value = not operands[0]
            elif operation in _COMPARISONS:
                value = _COMPARISONS[operation](*operands)
            else:
                raise KernelError("UNSUPPORTED", "Unsupported operator in checked revision.")
            results.append(value)
    return results[0]


def _rule_order(rules: list) -> tuple[list, dict]:
    by_id = {rule["id"]: rule for rule in rules}
    incoming = {name: [] for name in by_id}
    for rule in rules:
        for target in rule["overrides"]:
            incoming[target].append(rule["id"])
    waiting = {name: len(parents) for name, parents in incoming.items()}
    ready = [name for name, count in waiting.items() if count == 0]
    ordered = []
    while ready:
        name = ready.pop()
        ordered.append(by_id[name])
        for target in by_id[name]["overrides"]:
            waiting[target] -= 1
            if waiting[target] == 0:
                ready.append(target)
    if len(ordered) != len(rules):
        raise KernelError("UNSUPPORTED", "Cyclic overrides in checked revision.")
    return ordered, incoming


def _side(model: dict, assignment: dict, ordered: list, incoming: dict) -> dict:
    for fact in model["facts"]:
        if assignment[fact["var"]] != fact["value"]:
            return {"admitted": False, "outputs": {}}
    for condition in model["constraints"]:
        if not _eval(condition, assignment):
            return {"admitted": False, "outputs": {}}
    effective = set()
    ids = {output: [] for output in model["outputs"]}
    values = {output: {} for output in model["outputs"]}
    for rule in ordered:
        name = rule["id"]
        blocked = any(parent in effective for parent in incoming[name])
        if not blocked and _eval(rule["when"], assignment):
            effective.add(name)
            conclusion = rule["then"]
            output, value = conclusion["output"], conclusion["value"]
            ids[output].append(name)
            values[output][canonical_json(value)] = value
    result = {}
    for output in sorted(model["outputs"]):
        distinct = [value for key, value in sorted(values[output].items())]
        states = {0: "absent", 1: "defined"}
        result[output] = {"state": states.get(len(distinct), "conflicting"),
                          "values": distinct, "rule_ids": sorted(ids[output])}
    return {"admitted": True, "outputs": result}


def _replay(left: dict, right: dict, total: int) -> dict:
    cases = []
    byte_count = 2
    order_left, incoming_left = _rule_order(left["rules"])
    order_right, incoming_right = _rule_order(right["rules"])
    admitted_counts = [0, 0, 0]
    queries = [{"kind": "scope_change", "output": None, "count": 0, "witness": None}]
    output_queries = {}
    for output, declaration in sorted(left["outputs"].items()):
        labels = ["semantic_change", "explanation_only", "conflict_introduced", "conflict_resolved"]
        if declaration["required"]:
            labels += ["gap_introduced", "gap_resolved"]
        output_queries[output] = {}
        for label in labels:
            query = {"kind": label, "output": output, "count": 0, "witness": None}
            queries.append(query)
            output_queries[output][label] = query

    for index, assignment in enumerate(_assignments(left["inputs"], total)):
        old = _side(left, assignment, order_left, incoming_left)
        new = _side(right, assignment, order_right, incoming_right)
        case = {"index": index, "input": assignment, "left": old, "right": new}
        byte_count += len(canonical_json(case).encode("utf-8")) + (1 if index else 0)
        if byte_count > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Independent diff replay exceeds the certificate byte limit.")
        cases.append(case)
        for position, side in enumerate((old, new)):
            if side["admitted"]:
                admitted_counts[position] += 1
        if old["admitted"] != new["admitted"]:
            query = queries[0]
            query["count"] += 1
            if query["witness"] is None:
                query["witness"] = {"case_index": index, "input": dict(assignment),
                                    "left": old["admitted"], "right": new["admitted"]}
        if not old["admitted"] or not new["admitted"]:
            continue
        admitted_counts[2] += 1
        for output, collection in output_queries.items():
            before, after = old["outputs"][output], new["outputs"][output]
            same_result = (before["state"] == after["state"]
                           and canonical_json(before["values"]) == canonical_json(after["values"]))
            matches = {"semantic_change": not same_result,
                       "explanation_only": same_result and before["rule_ids"] != after["rule_ids"]}
            transition = (before["state"], after["state"])
            matches["conflict_introduced"] = transition in {
                ("absent", "conflicting"), ("defined", "conflicting")}
            matches["conflict_resolved"] = transition in {
                ("conflicting", "absent"), ("conflicting", "defined")}
            matches["gap_introduced"] = transition in {
                ("defined", "absent"), ("conflicting", "absent")}
            matches["gap_resolved"] = transition in {
                ("absent", "defined"), ("absent", "conflicting")}
            for kind, query in collection.items():
                if matches[kind]:
                    query["count"] += 1
                    if query["witness"] is None:
                        query["witness"] = {"case_index": index, "input": dict(assignment),
                                            "left": before, "right": after}
    for position, side in enumerate(("left", "right")):
        if admitted_counts[position] == 0:
            raise KernelError("BASE_INCONSISTENT", f"No admitted input context on {side} model.")
    expected = {
        "format": _FORMAT, "comparison_profile": _COMPARISON_PROFILE,
        "profile": left["profile"], "engine_version": _PRODUCER_VERSION,
        "left_model_hash": digest(left), "right_model_hash": digest(right),
        "total_contexts": total, "left_admitted_contexts": admitted_counts[0],
        "right_admitted_contexts": admitted_counts[1], "common_admitted_contexts": admitted_counts[2],
        "cases": cases, "queries": queries,
    }
    if len(canonical_json(expected).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Independent diff replay exceeds the certificate byte limit.")
    return expected


def verify_diff(left: dict, right: dict, certificate: object,
                max_contexts: int = MAX_CONTEXTS) -> dict:
    """Verify complete revision evidence against independently supplied models."""
    total = _checked_scope(left, right, max_contexts)
    supplied_json = _evidence_json(certificate)
    expected = _replay(left, right, total)
    if supplied_json != canonical_json(expected):
        _invalid("Diff certificate does not match complete independent replay.")
    result = {
        "status": "VERIFIED", "checker_version": CHECKER_VERSION,
        "comparison_profile": _COMPARISON_PROFILE,
        "left_model_hash": expected["left_model_hash"],
        "right_model_hash": expected["right_model_hash"],
        "certificate_hash": digest(certificate),
        "total_contexts": total,
        "left_admitted_contexts": expected["left_admitted_contexts"],
        "right_admitted_contexts": expected["right_admitted_contexts"],
        "common_admitted_contexts": expected["common_admitted_contexts"],
        "queries": [{**query, "status": "WITNESS_VERIFIED" if query["count"]
                     else "NO_WITNESS_IN_SCOPE_VERIFIED"} for query in expected["queries"]],
    }
    return result
