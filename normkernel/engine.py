"""Direct exhaustive producer for ``finite-norms/1``.

For every declared input context ``c`` the engine evaluates
``D(c) = facts(c) and constraints(c)``.  For every admitted context it stores
all Boolean action assignments ``tau`` and evaluates ``T(c,tau)`` from the
action constraints.  Active obligations require their content, active
prohibitions require the negation of their content, and their conjunction is
``H(c,tau)``; compliance is ``C(c,tau) = T(c,tau) and H(c,tau)``.  Explicit
permissions never enter H.  A permission is usable in a context exactly when
there exists a compliant trace satisfying its content.  Each permission is
quantified separately; no trace must exercise multiple permissions together.
"""
from __future__ import annotations

from itertools import product

from .model import (
    MAX_ACTION_ASSIGNMENTS,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    MAX_CONTEXT_TRACE_PAIRS,
    KernelError,
    canonical_json,
    digest,
    validate_enumeration_limits,
    validate_model,
)

_ENGINE_VERSION = "0.1.0"
_SEMANTICS_VERSION = "finite-norms-semantics/1"
_CERTIFICATE_FORMAT = "finite-norms-certificate/1"
_PERMISSION_STATUSES = (
    "not_applicable",
    "background_impossible",
    "base_norms_infeasible",
    "unusable",
    "usable",
)


def _domain_values(domain: dict):
    if domain["kind"] == "bool":
        return (False, True)
    if domain["kind"] == "int":
        return range(domain["min"], domain["max"] + 1)
    return domain["values"]


def _input_contexts(model: dict):
    names = sorted(model["inputs"])
    domains = [_domain_values(model["inputs"][name]) for name in names]
    for values in product(*domains):
        yield dict(zip(names, values))


def _action_assignments(model: dict):
    names = sorted(model["actions"])
    for values in product((False, True), repeat=len(names)):
        yield dict(zip(names, values))


def _evaluate(expression: dict, context: dict, actions: dict):
    if "const" in expression:
        return expression["const"]
    if "input" in expression:
        return context[expression["input"]]
    if "action" in expression:
        return actions[expression["action"]]
    operation = expression["op"]
    arguments = expression["args"]
    if operation == "and":
        return all(_evaluate(arg, context, actions) for arg in arguments)
    if operation == "or":
        return any(_evaluate(arg, context, actions) for arg in arguments)
    if operation == "not":
        return not _evaluate(arguments[0], context, actions)
    left, right = (_evaluate(arg, context, actions) for arg in arguments)
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
    raise AssertionError("validated expression has an unknown operator")


def _trace_witness(trace: dict) -> dict:
    return {"trace_index": trace["index"], "actions": dict(trace["actions"])}


def _summary_witness(case_index: int, context: dict, witness: dict) -> dict:
    return {
        "case_index": case_index,
        "input": dict(context),
        "trace_index": witness["trace_index"],
        "actions": dict(witness["actions"]),
    }


def analyze(
    model: dict,
    *,
    max_contexts: int = MAX_CONTEXTS,
    max_action_assignments: int = MAX_ACTION_ASSIGNMENTS,
    max_pairs: int = MAX_CONTEXT_TRACE_PAIRS,
) -> dict:
    """Produce complete evidence after preflighting all quantifier bounds.

    The potential bound is ``|contexts| * 2**|actions|`` and is checked before
    enumeration even when facts would exclude most contexts.  Excluded contexts
    remain in the certificate but have no traces.  No partial certificate is
    returned when any bound or final byte limit is exceeded.
    """
    validate_model(model)
    sizes = validate_enumeration_limits(
        model,
        max_contexts=max_contexts,
        max_action_assignments=max_action_assignments,
        max_pairs=max_pairs,
    )
    input_order = sorted(model["inputs"])
    action_order = sorted(model["actions"])
    facts = {fact["var"]: fact["value"] for fact in model["facts"]}
    norms = sorted(model["norms"], key=lambda norm: norm["id"])
    permissions = [norm for norm in norms if norm["kind"] == "explicit_permission"]

    permission_summaries = []
    summary_by_id = {}
    for norm in permissions:
        summary = {
            "permission_id": norm["id"],
            "applicable_context_count": 0,
            "status_counts": {status: 0 for status in _PERMISSION_STATUSES},
            "usable_count": 0,
            "usable_witness": None,
            "nonexercise_count": 0,
            "nonexercise_witness": None,
        }
        permission_summaries.append(summary)
        summary_by_id[norm["id"]] = summary

    counts = {
        "total_contexts": sizes["context_count"],
        "admitted_contexts": 0,
        "excluded": 0,
        "background_trace_impossible": 0,
        "normatively_infeasible": 0,
        "compliance_feasible": 0,
    }
    cases = []
    approximate_case_bytes = 2
    evaluated_pairs = 0

    for case_index, context in enumerate(_input_contexts(model)):
        admitted = (
            all(context[name] == value for name, value in facts.items())
            and all(_evaluate(expr, context, {}) for expr in model["constraints"])
        )
        active = {kind: [] for kind in ("obligation", "prohibition", "explicit_permission")}
        traces = []
        background_count = 0
        compliant_count = 0
        background_witness = None
        compliance_witness = None

        if admitted:
            counts["admitted_contexts"] += 1
            for norm in norms:
                if _evaluate(norm["when"], context, {}):
                    active[norm["kind"]].append(norm["id"])
            active_base_ids = set(active["obligation"] + active["prohibition"])
            active_base = [norm for norm in norms if norm["id"] in active_base_ids]
            for trace_index, actions in enumerate(_action_assignments(model)):
                background_satisfied = all(
                    _evaluate(expr, context, actions)
                    for expr in model["action_constraints"]
                )
                base_rows = []
                hard_norms_satisfied = True
                for norm in active_base:
                    content_holds = bool(_evaluate(norm["content"], context, actions))
                    compliance_satisfied = (
                        content_holds if norm["kind"] == "obligation" else not content_holds
                    )
                    hard_norms_satisfied = hard_norms_satisfied and compliance_satisfied
                    base_rows.append({
                        "norm_id": norm["id"],
                        "kind": norm["kind"],
                        "content_holds": content_holds,
                        "compliance_satisfied": compliance_satisfied,
                    })
                compliant = background_satisfied and hard_norms_satisfied
                trace = {
                    "index": trace_index,
                    "actions": actions,
                    "background_satisfied": background_satisfied,
                    "active_base_norms": base_rows,
                    "hard_norms_satisfied": hard_norms_satisfied,
                    "compliant": compliant,
                }
                traces.append(trace)
                if background_satisfied:
                    background_count += 1
                    if background_witness is None:
                        background_witness = _trace_witness(trace)
                if compliant:
                    compliant_count += 1
                    if compliance_witness is None:
                        compliance_witness = _trace_witness(trace)
            evaluated_pairs += len(traces)
            if background_count == 0:
                classification = "background_trace_impossible"
            elif compliant_count == 0:
                classification = "normatively_infeasible"
            else:
                classification = "compliance_feasible"
        else:
            classification = "excluded"

        counts[classification] += 1
        permission_rows = []
        for permission in permissions:
            applicable = admitted and permission["id"] in active["explicit_permission"]
            usable_count = 0
            usable_witness = None
            nonexercise_count = 0
            nonexercise_witness = None
            if applicable:
                for trace in traces:
                    if not trace["compliant"]:
                        continue
                    holds = bool(_evaluate(permission["content"], context, trace["actions"]))
                    if holds:
                        usable_count += 1
                        if usable_witness is None:
                            usable_witness = _trace_witness(trace)
                    else:
                        nonexercise_count += 1
                        if nonexercise_witness is None:
                            nonexercise_witness = _trace_witness(trace)
                if background_count == 0:
                    status = "background_impossible"
                elif compliant_count == 0:
                    status = "base_norms_infeasible"
                elif usable_count == 0:
                    status = "unusable"
                else:
                    status = "usable"
            else:
                status = "not_applicable"
            row = {
                "permission_id": permission["id"],
                "applicable": applicable,
                "status": status,
                "usable_count": usable_count,
                "usable_witness": usable_witness,
                "nonexercise_count": nonexercise_count,
                "nonexercise_witness": nonexercise_witness,
            }
            permission_rows.append(row)

            summary = summary_by_id[permission["id"]]
            summary["status_counts"][status] += 1
            if applicable:
                summary["applicable_context_count"] += 1
            summary["usable_count"] += usable_count
            summary["nonexercise_count"] += nonexercise_count
            if summary["usable_witness"] is None and usable_witness is not None:
                summary["usable_witness"] = _summary_witness(
                    case_index, context, usable_witness
                )
            if summary["nonexercise_witness"] is None and nonexercise_witness is not None:
                summary["nonexercise_witness"] = _summary_witness(
                    case_index, context, nonexercise_witness
                )

        case = {
            "index": case_index,
            "input": context,
            "admitted": admitted,
            "classification": classification,
            "active_norm_ids": active,
            "background_trace_count": background_count,
            "compliant_trace_count": compliant_count,
            "background_witness": background_witness,
            "compliance_witness": compliance_witness,
            "traces": traces,
            "permissions": permission_rows,
        }
        approximate_case_bytes += len(canonical_json(case).encode("utf-8")) + 1
        if approximate_case_bytes > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Evidence exceeds 8 MiB; no complete result")
        cases.append(case)

    if counts["admitted_contexts"] == 0:
        raise KernelError(
            "BASE_INCONSISTENT",
            "No input context satisfies the facts and background constraints",
        )

    certificate = {
        "format": _CERTIFICATE_FORMAT,
        "profile": model["profile"],
        "semantics_version": _SEMANTICS_VERSION,
        "model_hash": digest(model),
        "engine_version": _ENGINE_VERSION,
        "enumeration": {
            "input_order": input_order,
            "action_order": action_order,
            **sizes,
            "evaluated_context_trace_pairs": evaluated_pairs,
        },
        "counts": counts,
        "cases": cases,
        "permission_summaries": permission_summaries,
    }
    if len(canonical_json(certificate).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Complete evidence exceeds 8 MiB")
    return certificate
