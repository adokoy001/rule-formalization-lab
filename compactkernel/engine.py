"""Boundary-cell producer for strict JSON Lines decision evidence.

The producer keeps the existing finite-decisions/1 meaning and concrete
context limit. It stores one record per proven boundary cell while hashing a
virtual replay of every original context. It does not import the exhaustive
producer or the compact checker.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from itertools import product

from rulekernel.boundary_partition import iter_cells, plan_partition
from rulekernel.model import (
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    PROFILE,
    KernelError,
    canonical_json,
    digest,
)


FORMAT = "finite-decisions-compact-jsonl/1"
SEMANTICS = "finite-decisions-boundary-cells/1"
ENGINE_VERSION = "0.1.0"
COMMITMENT_ALGORITHM = "sha256-chain/1"
_CLASS_DOMAIN = b"finite-decisions-compact-jsonl/1:class-records"
_VIRTUAL_DOMAIN = b"finite-decisions-compact-jsonl/1:virtual-cases"


def _domain_values(domain):
    if domain["kind"] == "bool":
        return (False, True)
    if domain["kind"] == "int":
        return range(domain["min"], domain["max"] + 1)
    return domain["values"]


def _contexts(inputs):
    names = sorted(inputs)
    for values in product(*[_domain_values(inputs[name]) for name in names]):
        yield dict(zip(names, values))


def _evaluate(expression, context):
    if "const" in expression:
        return expression["const"]
    if "var" in expression:
        return context[expression["var"]]
    operator = expression["op"]
    arguments = expression["args"]
    if operator == "not":
        return not _evaluate(arguments[0], context)
    if operator == "and":
        return all(_evaluate(argument, context) for argument in arguments)
    if operator == "or":
        return any(_evaluate(argument, context) for argument in arguments)
    left, right = (_evaluate(argument, context) for argument in arguments)
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "lt":
        return left < right
    if operator == "le":
        return left <= right
    if operator == "gt":
        return left > right
    if operator == "ge":
        return left >= right
    raise AssertionError("validated expression has an unknown operator")


def _rule_index(model):
    rules = {rule["id"]: rule for rule in model["rules"]}
    rule_ids = sorted(rules)
    blockers = {rule_id: [] for rule_id in rule_ids}
    for rule_id in rule_ids:
        for target in rules[rule_id]["overrides"]:
            blockers[target].append(rule_id)
    return rules, rule_ids, blockers


def _case_result(model, context, index, rules, rule_ids, blockers, facts):
    admitted = (
        all(context[name] == value for name, value in facts.items())
        and all(_evaluate(condition, context) for condition in model["constraints"])
    )
    enabled = []
    effective = []
    if admitted:
        enabled = [
            rule_id for rule_id in rule_ids
            if _evaluate(rules[rule_id]["when"], context)
        ]
        enabled_set = set(enabled)

        @lru_cache(maxsize=None)
        def is_effective(rule_id):
            return (
                rule_id in enabled_set
                and not any(is_effective(other) for other in blockers[rule_id])
            )

        effective = [rule_id for rule_id in rule_ids if is_effective(rule_id)]
    return {
        "index": index,
        "input": context,
        "admitted": admitted,
        "enabled": enabled,
        "effective": effective,
    }


def _query_templates(model):
    queries = []
    for output in sorted(model["outputs"]):
        kinds = ["conflict", "gap"] if model["outputs"][output]["required"] else ["conflict"]
        for kind in kinds:
            queries.append({
                "kind": kind,
                "output": output,
                "count": 0,
                "witness": None,
            })
    return queries


def _update_queries(queries, rules, case, weight):
    if not case["admitted"]:
        return
    for query in queries:
        relevant = [
            rule_id for rule_id in case["effective"]
            if rules[rule_id]["then"]["output"] == query["output"]
        ]
        distinct = {
            canonical_json(rules[rule_id]["then"]["value"]):
                rules[rule_id]["then"]["value"]
            for rule_id in relevant
        }
        found = (
            len(distinct) > 1
            if query["kind"] == "conflict"
            else len(distinct) == 0
        )
        if found:
            query["count"] += weight
            if query["witness"] is None:
                query["witness"] = {
                    "case_index": case["index"],
                    "input": dict(case["input"]),
                    "rule_ids": relevant,
                    "values": [distinct[key] for key in sorted(distinct)],
                }


def _chain_start(domain):
    return hashlib.sha256(domain + b"\x00start").digest()


def _chain_update(state, domain, index, payload):
    return hashlib.sha256(
        domain
        + b"\x00record"
        + index.to_bytes(8, "big")
        + len(payload).to_bytes(8, "big")
        + state
        + payload
    ).digest()


def _record_payload(record):
    return canonical_json(record).encode("utf-8")


def _record_line(record):
    return _record_payload(record) + b"\n"


def _header(model, plan):
    return {
        "record_type": "header",
        "format": FORMAT,
        "profile": PROFILE,
        "semantics": SEMANTICS,
        "engine_version": ENGINE_VERSION,
        "commitment_algorithm": COMMITMENT_ALGORITHM,
        "model_hash": digest(model),
        "partition_format": plan["format"],
        "input_order": plan["input_order"],
        "axes": plan["axes"],
        "concrete_contexts": plan["concrete_contexts"],
        "cell_count": plan["cell_count"],
        "compressed": plan["compressed"],
        "fallback_reason": plan["fallback_reason"],
    }


def _minimum_cell_record(cell):
    return {
        "record_type": "cell",
        **cell,
        "admitted": True,
        "enabled": [],
        "effective": [],
    }


def _trailer(plan, admitted_contexts, queries, class_commitment, virtual_commitment):
    return {
        "record_type": "trailer",
        "cell_records": plan["cell_count"],
        "concrete_contexts": plan["concrete_contexts"],
        "admitted_contexts": admitted_contexts,
        "queries": queries,
        "class_commitment": class_commitment,
        "virtual_case_commitment": virtual_commitment,
    }


def _estimate_from_plan(model, plan):
    header = _header(model, plan)
    byte_count = len(_record_line(header))
    for cell in iter_cells(plan):
        byte_count += len(_record_line(_minimum_cell_record(cell)))
    minimum_trailer = _trailer(
        plan,
        1,
        _query_templates(model),
        "0" * 64,
        "0" * 64,
    )
    byte_count += len(_record_line(minimum_trailer))
    return {
        "format": FORMAT,
        "partition_format": plan["format"],
        "concrete_contexts": plan["concrete_contexts"],
        "cell_count": plan["cell_count"],
        "compressed": plan["compressed"],
        "fallback_reason": plan["fallback_reason"],
        "guaranteed_min_bytes": byte_count,
        "max_certificate_bytes": MAX_CERTIFICATE_BYTES,
        "guaranteed_min_exceeds_cap": byte_count > MAX_CERTIFICATE_BYTES,
    }


def estimate_certificate(model, max_contexts=MAX_CONTEXTS):
    """Return a syntax-only lower bound before evaluating any rule."""
    plan = plan_partition(model, max_contexts=max_contexts)
    return _estimate_from_plan(model, plan)


def _write_record(stream, record, byte_count):
    line = _record_line(record)
    if len(line) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "One compact evidence record exceeds 8 MiB")
    if byte_count + len(line) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Compact evidence exceeds 8 MiB")
    written = stream.write(line)
    if written is not None and written != len(line):
        raise OSError("Short write while creating compact evidence")
    return byte_count + len(line), line[:-1]


def _virtual_commitment(model, rules, rule_ids, blockers, facts):
    state = _chain_start(_VIRTUAL_DOMAIN)
    for index, context in enumerate(_contexts(model["inputs"])):
        case = _case_result(
            model, context, index, rules, rule_ids, blockers, facts,
        )
        state = _chain_update(
            state, _VIRTUAL_DOMAIN, index, _record_payload(case),
        )
    return state.hex()


def write_certificate(model, stream, max_contexts=MAX_CONTEXTS):
    """Write a complete canonical JSON Lines certificate to a binary stream."""
    plan = plan_partition(model, max_contexts=max_contexts)
    estimate = _estimate_from_plan(model, plan)
    if estimate["guaranteed_min_exceeds_cap"]:
        raise KernelError(
            "LIMIT_REACHED",
            "Guaranteed minimum compact evidence exceeds 8 MiB",
        )

    rules, rule_ids, blockers = _rule_index(model)
    facts = {fact["var"]: fact["value"] for fact in model["facts"]}
    queries = _query_templates(model)
    admitted_contexts = 0
    byte_count = 0
    class_state = _chain_start(_CLASS_DOMAIN)

    header = _header(model, plan)
    byte_count, payload = _write_record(stream, header, byte_count)
    class_state = _chain_update(
        class_state, _CLASS_DOMAIN, 0, payload,
    )

    for cell in iter_cells(plan):
        case = _case_result(
            model,
            cell["representative"],
            cell["first_case_index"],
            rules,
            rule_ids,
            blockers,
            facts,
        )
        record = {
            "record_type": "cell",
            **cell,
            "admitted": case["admitted"],
            "enabled": case["enabled"],
            "effective": case["effective"],
        }
        byte_count, payload = _write_record(stream, record, byte_count)
        class_state = _chain_update(
            class_state,
            _CLASS_DOMAIN,
            cell["cell_index"] + 1,
            payload,
        )
        if case["admitted"]:
            admitted_contexts += cell["weight"]
            _update_queries(queries, rules, case, cell["weight"])

    if admitted_contexts == 0:
        raise KernelError(
            "BASE_INCONSISTENT",
            "No context satisfies the facts and background constraints",
        )

    virtual_commitment = _virtual_commitment(
        model, rules, rule_ids, blockers, facts,
    )
    trailer = _trailer(
        plan,
        admitted_contexts,
        queries,
        class_state.hex(),
        virtual_commitment,
    )
    byte_count, _ = _write_record(stream, trailer, byte_count)
    return {
        **estimate,
        "admitted_contexts": admitted_contexts,
        "queries": queries,
        "certificate_bytes": byte_count,
        "class_commitment": class_state.hex(),
        "virtual_case_commitment": virtual_commitment,
    }
