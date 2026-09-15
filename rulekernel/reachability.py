"""Exhaustive rule reachability diagnostics for finite-decisions/1.

The returned certificate is unverified until independently checked.  A rule's
guard reachability and its survival of explicit overrides are distinct queries.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import product
from math import prod

from .model import (KernelError, MAX_CERTIFICATE_BYTES, MAX_CONTEXTS, PROFILE,
                    canonical_json, digest, validate_limit, validate_model)


ENGINE_VERSION = "0.1.0"
CERTIFICATE_FORMAT = "finite-decisions-reachability-certificate/1"


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
    raise KernelError("UNSUPPORTED", "Unknown operator in reachability model.")


def _classification(enabled_count, effective_count):
    if enabled_count == 0:
        return "unreachable"
    if effective_count == 0:
        return "always_suppressed"
    if effective_count < enabled_count:
        return "partially_suppressed"
    return "always_effective_when_enabled"


def analyze_reachability(model, max_contexts=MAX_CONTEXTS):
    """Return complete evidence; model errors and budget limits never pass."""
    validate_model(model)
    validate_limit(max_contexts)
    names = sorted(model["inputs"])
    total = prod(_domain_size(model["inputs"][name]) for name in names)
    if total > max_contexts:
        raise KernelError("LIMIT_REACHED", "The full input domain exceeds max_contexts.")

    by_id = {rule["id"]: rule for rule in model["rules"]}
    ids = sorted(by_id)
    blockers = {rule_id: [] for rule_id in ids}
    for rule_id in ids:
        for target in by_id[rule_id]["overrides"]:
            blockers[target].append(rule_id)
    summaries = {
        rule_id: {"rule_id": rule_id, "enabled_count": 0, "effective_count": 0,
                  "enabled_witness": None, "effective_witness": None}
        for rule_id in ids
    }
    facts = {fact["var"]: fact["value"] for fact in model["facts"]}
    cases, admitted_count, case_bytes = [], 0, 2
    for index, values in enumerate(product(*[_domain_values(model["inputs"][name]) for name in names])):
        context = dict(zip(names, values))
        admitted = (all(context[name] == value for name, value in facts.items())
                    and all(_evaluate(expr, context) for expr in model["constraints"]))
        enabled, effective = [], []
        if admitted:
            admitted_count += 1
            enabled = [rule_id for rule_id in ids if _evaluate(by_id[rule_id]["when"], context)]
            enabled_set = set(enabled)

            @lru_cache(maxsize=None)
            def survives(rule_id):
                return rule_id in enabled_set and not any(survives(other) for other in blockers[rule_id])

            effective = [rule_id for rule_id in ids if survives(rule_id)]
            for phase, rule_ids in (("enabled", enabled), ("effective", effective)):
                for rule_id in rule_ids:
                    summary = summaries[rule_id]
                    summary[phase + "_count"] += 1
                    if summary[phase + "_witness"] is None:
                        summary[phase + "_witness"] = {"case_index": index, "input": dict(context)}
        case = {"index": index, "input": context, "admitted": admitted,
                "enabled": enabled, "effective": effective}
        case_bytes += len(canonical_json(case).encode("utf-8")) + (1 if cases else 0)
        if case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Reachability evidence exceeds the certificate byte limit.")
        cases.append(case)

    if admitted_count == 0:
        raise KernelError("BASE_INCONSISTENT", "No context satisfies the facts and background constraints.")
    for summary in summaries.values():
        summary["classification"] = _classification(summary["enabled_count"], summary["effective_count"])
    certificate = {
        "format": CERTIFICATE_FORMAT,
        "profile": PROFILE,
        "model_hash": digest(model),
        "engine_version": ENGINE_VERSION,
        "total_contexts": total,
        "admitted_contexts": admitted_count,
        "total_rules": len(ids),
        "cases": cases,
        "rules": [summaries[rule_id] for rule_id in ids],
    }
    if len(canonical_json(certificate).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Complete reachability evidence exceeds the certificate byte limit.")
    return certificate
