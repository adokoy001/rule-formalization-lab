"""Direct exhaustive search. No external solver and no call into the checker."""
from __future__ import annotations

from functools import lru_cache
from itertools import product
from math import prod

from .model import (KernelError, MAX_CERTIFICATE_BYTES, MAX_CONTEXTS, PROFILE,
                    VERSION, canonical_json, digest, validate_limit, validate_model)


def _domain_values(domain):
    if domain["kind"] == "bool":
        return (False, True)
    if domain["kind"] == "int":
        return range(domain["min"], domain["max"] + 1)
    return domain["values"]


def _cardinality(domain):
    if domain["kind"] == "bool":
        return 2
    if domain["kind"] == "int":
        return domain["max"] - domain["min"] + 1
    return len(domain["values"])


def _evaluate(expr, context):
    if "const" in expr:
        return expr["const"]
    if "var" in expr:
        return context[expr["var"]]
    op = expr["op"]
    args = expr["args"]
    if op == "and":
        return all(_evaluate(arg, context) for arg in args)
    if op == "or":
        return any(_evaluate(arg, context) for arg in args)
    if op == "not":
        return not _evaluate(args[0], context)
    left, right = (_evaluate(arg, context) for arg in args)
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    raise AssertionError("validated expression has unknown operator")


def analyze(model, max_contexts=MAX_CONTEXTS):
    """Return full, unverified evidence, or raise KernelError; never partial absence."""
    validate_model(model)
    validate_limit(max_contexts)
    names = sorted(model["inputs"])
    total = prod(_cardinality(model["inputs"][name]) for name in names)
    if total > max_contexts:
        raise KernelError("LIMIT_REACHED",
                          f"Declared Cartesian scope {total} exceeds {max_contexts} contexts")
    rules = {rule["id"]: rule for rule in model["rules"]}
    ids = sorted(rules)
    blockers = {key: [] for key in ids}
    for key in ids:
        for target in rules[key]["overrides"]:
            blockers[target].append(key)
    queries = []
    for output in sorted(model["outputs"]):
        for kind in (["conflict", "gap"] if model["outputs"][output]["required"] else ["conflict"]):
            queries.append({"kind": kind, "output": output, "count": 0, "witness": None})
    facts = {fact["var"]: fact["value"] for fact in model["facts"]}
    cases, admitted_count, case_bytes = [], 0, 0
    for index, values in enumerate(product(*[_domain_values(model["inputs"][name]) for name in names])):
        context = dict(zip(names, values))
        admitted = (all(context[name] == value for name, value in facts.items())
                    and all(_evaluate(expr, context) for expr in model["constraints"]))
        enabled, effective = [], []
        if admitted:
            admitted_count += 1
            enabled = [key for key in ids if _evaluate(rules[key]["when"], context)]
            enabled_set = set(enabled)

            @lru_cache(maxsize=None)
            def is_effective(key):
                return key in enabled_set and not any(is_effective(other) for other in blockers[key])

            effective = [key for key in ids if is_effective(key)]
            for query in queries:
                relevant = [key for key in effective
                            if rules[key]["then"]["output"] == query["output"]]
                unique = {canonical_json(rules[key]["then"]["value"]): rules[key]["then"]["value"]
                          for key in relevant}
                found = len(unique) > 1 if query["kind"] == "conflict" else len(unique) == 0
                if found:
                    query["count"] += 1
                    if query["witness"] is None:
                        query["witness"] = {
                            "case_index": index, "input": context,
                            "rule_ids": relevant,
                            "values": [unique[key] for key in sorted(unique)],
                        }
        case = {"index": index, "input": context, "admitted": admitted,
                "enabled": enabled, "effective": effective}
        case_bytes += len(canonical_json(case).encode("utf-8")) + 1
        if case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Evidence exceeds 8 MiB; no complete result")
        cases.append(case)
    if not admitted_count:
        raise KernelError("BASE_INCONSISTENT", "No context satisfies the facts and background constraints")
    certificate = {
        "format": "finite-decisions-certificate/1",
        "profile": PROFILE,
        "model_hash": digest(model),
        "engine_version": VERSION,
        "total_contexts": total,
        "admitted_contexts": admitted_count,
        "cases": cases,
        "queries": queries,
    }
    if len(canonical_json(certificate).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Complete evidence exceeds 8 MiB")
    return certificate
