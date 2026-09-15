"""Independently replay a finite-decisions/1 certificate.

Only the input validator, JSON format, and hashing are shared with the engine.
The enumeration, expression evaluator, override resolver, and report construction
below deliberately do not call the search engine.  This is an implementation
cross-check, not a machine-checked proof that this checker is correct.
"""

from __future__ import annotations

from .model import (
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    KernelError,
    canonical_json,
    digest,
    validate_model,
)


CHECKER_VERSION = "0.1.0"
_ENGINE_VERSION = "0.1.0"
_CERTIFICATE_FORMAT = "finite-decisions-certificate/1"


def _invalid(message: str) -> None:
    raise KernelError("CERTIFICATE_INVALID", message)


def _certificate_text(certificate: object) -> str:
    """Reject Python lookalikes and malformed JSON before comparing evidence."""
    pending = [(certificate, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            _invalid("Certificate nesting exceeds the certificate structure.")
        kind = type(item)
        if kind is dict:
            if any(type(key) is not str for key in item):
                _invalid("Certificate object keys must be strings.")
            pending.extend((value, depth + 1) for value in item.values())
        elif kind is list:
            pending.extend((value, depth + 1) for value in item)
        elif item is None or kind in (bool, int, str):
            continue
        else:
            _invalid("Certificate values must use the exact JSON value types.")
    try:
        text = canonical_json(certificate)
        size = len(text.encode("utf-8"))
    except (KernelError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        _invalid("Certificate cannot be represented as canonical UTF-8 JSON.")
    if size > MAX_CERTIFICATE_BYTES:
        _invalid("Certificate exceeds the byte limit.")
    return text


def _context_count(inputs: dict, max_contexts: int) -> int:
    if type(max_contexts) is not int or not 1 <= max_contexts <= MAX_CONTEXTS:
        raise KernelError("LIMIT_REACHED", f"max_contexts must be an integer from 1 to {MAX_CONTEXTS}.")
    size = 1
    for name in sorted(inputs):
        declared = inputs[name]
        kind = declared["kind"]
        width = (
            2
            if kind == "bool"
            else declared["max"] - declared["min"] + 1
            if kind == "int"
            else len(declared["values"])
        )
        size *= width
        if size > max_contexts:
            raise KernelError("LIMIT_REACHED", "The full input domain exceeds max_contexts.")
    return size


def _contexts(inputs: dict):
    """Expand the finite domain directly, with the first name changing last."""
    names = sorted(inputs)
    assignment = {}

    def visit(position: int):
        if position == len(names):
            yield dict(assignment)
            return
        name = names[position]
        declared = inputs[name]
        if declared["kind"] == "bool":
            values = (False, True)
        elif declared["kind"] == "int":
            values = range(declared["min"], declared["max"] + 1)
        else:
            values = declared["values"]
        for value in values:
            assignment[name] = value
            yield from visit(position + 1)
        del assignment[name]

    yield from visit(0)


def _evaluate(expression: dict, assignment: dict):
    if "const" in expression:
        return expression["const"]
    if "var" in expression:
        return assignment[expression["var"]]
    operands = [_evaluate(argument, assignment) for argument in expression["args"]]
    operation = expression["op"]
    if operation == "not":
        return not operands[0]
    if operation == "and":
        return all(operands)
    if operation == "or":
        return any(operands)
    left, right = operands
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
    raise KernelError("UNSUPPORTED", "Unknown expression operator in checked model.")


def _rule_results(rules: list, assignment: dict) -> tuple[list, list]:
    active_guards = {rule["id"]: _evaluate(rule["when"], assignment) for rule in rules}
    overriders = {rule["id"]: [] for rule in rules}
    for rule in rules:
        for target in rule["overrides"]:
            overriders[target].append(rule["id"])
    by_id = {rule["id"]: rule for rule in rules}
    waiting = {rule_id: len(blockers) for rule_id, blockers in overriders.items()}
    ready = [rule_id for rule_id, count in waiting.items() if count == 0]
    resolved = {}
    while ready:
        rule_id = ready.pop()
        resolved[rule_id] = active_guards[rule_id] and not any(
            resolved[other] for other in overriders[rule_id]
        )
        for target in by_id[rule_id]["overrides"]:
            waiting[target] -= 1
            if waiting[target] == 0:
                ready.append(target)
    if len(resolved) != len(rules):
        raise KernelError("UNSUPPORTED", "Override cycle in checked model.")
    enabled = sorted(rule_id for rule_id, value in active_guards.items() if value)
    effective = sorted(rule_id for rule_id, value in resolved.items() if value)
    return enabled, effective


def _replay(model: dict, total_contexts: int) -> dict:
    queries = []
    query_positions = {}
    for output in sorted(model["outputs"]):
        kinds = ["conflict"]
        if model["outputs"][output]["required"]:
            kinds.append("gap")
        for kind in kinds:
            query_positions[(output, kind)] = len(queries)
            queries.append({"kind": kind, "output": output, "count": 0, "witness": None})

    rules_by_id = {rule["id"]: rule for rule in model["rules"]}
    cases = []
    case_bytes = 2  # Array brackets; bound proof growth before storing more cases.
    admitted_contexts = 0
    for index, assignment in enumerate(_contexts(model["inputs"])):
        admitted = all(
            assignment[fact["var"]] == fact["value"] for fact in model["facts"]
        ) and all(_evaluate(condition, assignment) for condition in model["constraints"])
        enabled, effective = _rule_results(model["rules"], assignment) if admitted else ([], [])
        case = {"index": index, "input": assignment, "admitted": admitted,
                "enabled": enabled, "effective": effective}
        case_bytes += len(canonical_json(case).encode("utf-8")) + (1 if cases else 0)
        if case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Independent replay exceeds the certificate byte limit.")
        cases.append(case)
        if not admitted:
            continue
        admitted_contexts += 1
        for output, declared in model["outputs"].items():
            rule_ids = [
                rule_id for rule_id in effective
                if rules_by_id[rule_id]["then"]["output"] == output
            ]
            distinct = {}
            for rule_id in rule_ids:
                value = rules_by_id[rule_id]["then"]["value"]
                distinct[canonical_json(value)] = value
            values = [distinct[key] for key in sorted(distinct)]
            if len(values) > 1:
                kind = "conflict"
            elif not values and declared["required"]:
                kind = "gap"
            else:
                continue
            query = queries[query_positions[(output, kind)]]
            query["count"] += 1
            if query["witness"] is None:
                query["witness"] = {
                    "case_index": index, "input": dict(assignment),
                    "rule_ids": rule_ids, "values": values,
                }

    if admitted_contexts == 0:
        raise KernelError("BASE_INCONSISTENT", "No input context satisfies the background conditions.")
    expected = {
        "format": _CERTIFICATE_FORMAT,
        "profile": model["profile"],
        "model_hash": digest(model),
        "engine_version": _ENGINE_VERSION,
        "total_contexts": total_contexts,
        "admitted_contexts": admitted_contexts,
        "cases": cases,
        "queries": queries,
    }
    if len(canonical_json(expected).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Independent replay exceeds the certificate byte limit.")
    return expected


def verify(model: dict, certificate: object, max_contexts: int = MAX_CONTEXTS) -> dict:
    """Check every finite context and every reported query independently.

    VERIFIED confirms this certificate matches the expected finite model.  It
    does not mean that every query has no finding, or that source prose has been
    interpreted correctly.  Model errors are deliberately not recategorized as
    certificate errors.
    """
    validate_model(model)
    total_contexts = _context_count(model["inputs"], max_contexts)
    supplied_text = _certificate_text(certificate)
    expected = _replay(model, total_contexts)
    if supplied_text != canonical_json(expected):
        _invalid("Certificate does not match the complete independent replay.")

    verified_queries = []
    for query in expected["queries"]:
        verified_queries.append({
            **query,
            "status": "WITNESS_VERIFIED" if query["count"] else "NO_WITNESS_IN_SCOPE_VERIFIED",
        })
    return {
        "status": "VERIFIED",
        "checker_version": CHECKER_VERSION,
        "model_hash": expected["model_hash"],
        "certificate_hash": digest(certificate),
        "total_contexts": total_contexts,
        "admitted_contexts": expected["admitted_contexts"],
        "queries": verified_queries,
    }
