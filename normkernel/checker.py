"""Independent replay checker for ``finite-norms-certificate/1``.

Only strict model validation, canonical JSON, hashing, and limit validation are
shared with the producer.  This module does not import ``normkernel.engine``.
It independently quantifies every input context and, for each admitted context,
every Boolean action assignment.  Thus VERIFIED means that the supplied bytes'
parsed value equals the complete canonical replay; it is separate from the
reported normative diagnostics and is not a claim that the model is sound law.
"""
from __future__ import annotations

from .model import (
    MAX_ACTION_ASSIGNMENTS,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    MAX_CONTEXT_TRACE_PAIRS,
    KernelError,
    canonical_json,
    digest,
    validate_model,
)

CHECKER_VERSION = "0.1.0"
_EXPECTED_ENGINE_VERSION = "0.1.0"
_EXPECTED_SEMANTICS_VERSION = "finite-norms-semantics/1"
_EXPECTED_FORMAT = "finite-norms-certificate/1"
_PERMISSION_STATUSES = (
    "not_applicable",
    "background_impossible",
    "base_norms_infeasible",
    "unusable",
    "usable",
)


def _certificate_invalid(message: str) -> None:
    raise KernelError("CERTIFICATE_INVALID", message)


def _preflight(model: dict, max_contexts: int, max_actions: int, max_pairs: int) -> dict:
    """Independently enforce hard and caller-lowered Cartesian limits."""
    for value, hard, label in (
        (max_contexts, MAX_CONTEXTS, "max_contexts"),
        (max_actions, MAX_ACTION_ASSIGNMENTS, "max_action_assignments"),
        (max_pairs, MAX_CONTEXT_TRACE_PAIRS, "max_pairs"),
    ):
        if type(value) is not int or value < 1 or value > hard:
            raise KernelError(
                "LIMIT_REACHED", f"{label} must be an integer from 1 to {hard}"
            )
    context_count = 1
    for name in sorted(model["inputs"]):
        domain = model["inputs"][name]
        if domain["kind"] == "bool":
            width = 2
        elif domain["kind"] == "enum":
            width = len(domain["values"])
        else:
            width = domain["max"] - domain["min"] + 1
        context_count *= width
        if context_count > max_contexts:
            raise KernelError(
                "LIMIT_REACHED",
                f"Declared Cartesian scope exceeds {max_contexts} contexts",
            )
    action_count = 1 << len(model["actions"])
    if action_count > max_actions:
        raise KernelError(
            "LIMIT_REACHED",
            f"Declared action space {action_count} exceeds {max_actions}",
        )
    pair_count = context_count * action_count
    if pair_count > max_pairs:
        raise KernelError(
            "LIMIT_REACHED",
            f"Potential context/trace pairs {pair_count} exceed {max_pairs}",
        )
    return {
        "context_count": context_count,
        "action_assignment_count": action_count,
        "potential_context_trace_pairs": pair_count,
    }


def _validate_anchor(value: object) -> None:
    if value is None:
        return
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _certificate_invalid(
            "expected_certificate_sha256 must be 64 lowercase hexadecimal characters"
        )


def _certificate_text(certificate: object) -> str:
    """Reject non-JSON Python lookalikes, deep data, and oversized evidence."""
    pending = [(certificate, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 32:
            _certificate_invalid("Certificate nesting exceeds 32 levels")
        kind = type(value)
        if kind is dict:
            if any(type(key) is not str for key in value):
                _certificate_invalid("Certificate object keys must be strings")
            pending.extend((member, depth + 1) for member in value.values())
        elif kind is list:
            pending.extend((member, depth + 1) for member in value)
        elif value is None or kind in (bool, int, str):
            continue
        else:
            _certificate_invalid("Certificate contains a non-JSON value type")
    try:
        text = canonical_json(certificate)
    except KernelError as exc:
        raise KernelError("CERTIFICATE_INVALID", exc.message) from exc
    if len(text.encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        _certificate_invalid("Certificate exceeds 8 MiB")
    return text


def _values(domain: dict):
    kind = domain["kind"]
    if kind == "bool":
        return (False, True)
    if kind == "enum":
        return tuple(domain["values"])
    return tuple(range(domain["min"], domain["max"] + 1))


def _contexts(inputs: dict):
    """Enumerate lexical input names; the rightmost name changes fastest."""
    names = sorted(inputs)
    assignment = {}

    def visit(position: int):
        if position == len(names):
            yield dict(assignment)
            return
        name = names[position]
        for value in _values(inputs[name]):
            assignment[name] = value
            yield from visit(position + 1)
        del assignment[name]

    yield from visit(0)


def _traces(action_names: list[str]):
    """Enumerate lexical action names with False before True independently."""
    names = sorted(action_names)
    assignment = {}

    def visit(position: int):
        if position == len(names):
            yield dict(assignment)
            return
        name = names[position]
        for value in (False, True):
            assignment[name] = value
            yield from visit(position + 1)
        del assignment[name]

    yield from visit(0)


def _eval(expression: dict, context: dict, trace: dict):
    if "const" in expression:
        return expression["const"]
    if "input" in expression:
        return context[expression["input"]]
    if "action" in expression:
        return trace[expression["action"]]
    operation = expression["op"]
    operands = [_eval(argument, context, trace) for argument in expression["args"]]
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
    raise KernelError("UNSUPPORTED", "Unknown operator in validated model")


def _local_witness(row: dict) -> dict:
    return {"trace_index": row["index"], "actions": dict(row["actions"])}


def _global_witness(case_index: int, context: dict, witness: dict) -> dict:
    return {
        "case_index": case_index,
        "input": dict(context),
        "trace_index": witness["trace_index"],
        "actions": dict(witness["actions"]),
    }


def _replay(model: dict, sizes: dict) -> dict:
    norms = sorted(model["norms"], key=lambda item: item["id"])
    permissions = [item for item in norms if item["kind"] == "explicit_permission"]
    fixed = {fact["var"]: fact["value"] for fact in model["facts"]}

    summaries = []
    summary_positions = {}
    for permission in permissions:
        record = {
            "permission_id": permission["id"],
            "applicable_context_count": 0,
            "status_counts": {name: 0 for name in _PERMISSION_STATUSES},
            "usable_count": 0,
            "usable_witness": None,
            "nonexercise_count": 0,
            "nonexercise_witness": None,
        }
        summary_positions[permission["id"]] = len(summaries)
        summaries.append(record)

    totals = {
        "total_contexts": sizes["context_count"],
        "admitted_contexts": 0,
        "excluded": 0,
        "background_trace_impossible": 0,
        "normatively_infeasible": 0,
        "compliance_feasible": 0,
    }
    cases = []
    evidence_growth = 2
    evaluated_pairs = 0

    for case_index, context in enumerate(_contexts(model["inputs"])):
        admitted = all(context[key] == expected for key, expected in fixed.items())
        if admitted:
            for condition in model["constraints"]:
                if not _eval(condition, context, {}):
                    admitted = False
                    break

        active = {
            "obligation": [],
            "prohibition": [],
            "explicit_permission": [],
        }
        rows = []
        t_count = 0
        c_count = 0
        first_t = None
        first_c = None

        if admitted:
            totals["admitted_contexts"] += 1
            active_norms = []
            for norm in norms:
                if bool(_eval(norm["when"], context, {})):
                    active[norm["kind"]].append(norm["id"])
                    active_norms.append(norm)
            base_norms = [
                norm for norm in active_norms
                if norm["kind"] in {"obligation", "prohibition"}
            ]
            for trace_index, assignment in enumerate(_traces(model["actions"])):
                t_value = True
                for condition in model["action_constraints"]:
                    if not _eval(condition, context, assignment):
                        t_value = False
                        break
                norm_rows = []
                h_value = True
                for norm in base_norms:
                    content = bool(_eval(norm["content"], context, assignment))
                    satisfied = content if norm["kind"] == "obligation" else not content
                    if not satisfied:
                        h_value = False
                    norm_rows.append({
                        "norm_id": norm["id"],
                        "kind": norm["kind"],
                        "content_holds": content,
                        "compliance_satisfied": satisfied,
                    })
                c_value = t_value and h_value
                trace_row = {
                    "index": trace_index,
                    "actions": assignment,
                    "background_satisfied": t_value,
                    "active_base_norms": norm_rows,
                    "hard_norms_satisfied": h_value,
                    "compliant": c_value,
                }
                rows.append(trace_row)
                if t_value:
                    t_count += 1
                    if first_t is None:
                        first_t = _local_witness(trace_row)
                if c_value:
                    c_count += 1
                    if first_c is None:
                        first_c = _local_witness(trace_row)
            evaluated_pairs += len(rows)
            if t_count == 0:
                classification = "background_trace_impossible"
            elif c_count == 0:
                classification = "normatively_infeasible"
            else:
                classification = "compliance_feasible"
        else:
            classification = "excluded"

        totals[classification] += 1
        permission_rows = []
        for permission in permissions:
            applicable = admitted and permission["id"] in active["explicit_permission"]
            exercise_count = 0
            exercise_witness = None
            omission_count = 0
            omission_witness = None
            if applicable:
                for row in rows:
                    if not row["compliant"]:
                        continue
                    content = bool(_eval(permission["content"], context, row["actions"]))
                    if content:
                        exercise_count += 1
                        if exercise_witness is None:
                            exercise_witness = _local_witness(row)
                    else:
                        omission_count += 1
                        if omission_witness is None:
                            omission_witness = _local_witness(row)
                if t_count == 0:
                    permission_status = "background_impossible"
                elif c_count == 0:
                    permission_status = "base_norms_infeasible"
                elif exercise_count == 0:
                    permission_status = "unusable"
                else:
                    permission_status = "usable"
            else:
                permission_status = "not_applicable"

            permission_row = {
                "permission_id": permission["id"],
                "applicable": applicable,
                "status": permission_status,
                "usable_count": exercise_count,
                "usable_witness": exercise_witness,
                "nonexercise_count": omission_count,
                "nonexercise_witness": omission_witness,
            }
            permission_rows.append(permission_row)

            summary = summaries[summary_positions[permission["id"]]]
            summary["status_counts"][permission_status] += 1
            summary["applicable_context_count"] += int(applicable)
            summary["usable_count"] += exercise_count
            summary["nonexercise_count"] += omission_count
            if summary["usable_witness"] is None and exercise_witness is not None:
                summary["usable_witness"] = _global_witness(
                    case_index, context, exercise_witness
                )
            if summary["nonexercise_witness"] is None and omission_witness is not None:
                summary["nonexercise_witness"] = _global_witness(
                    case_index, context, omission_witness
                )

        case = {
            "index": case_index,
            "input": context,
            "admitted": admitted,
            "classification": classification,
            "active_norm_ids": active,
            "background_trace_count": t_count,
            "compliant_trace_count": c_count,
            "background_witness": first_t,
            "compliance_witness": first_c,
            "traces": rows,
            "permissions": permission_rows,
        }
        evidence_growth += len(canonical_json(case).encode("utf-8")) + 1
        if evidence_growth > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Independent replay exceeds 8 MiB")
        cases.append(case)

    if totals["admitted_contexts"] == 0:
        raise KernelError(
            "BASE_INCONSISTENT",
            "No input context satisfies the facts and background constraints",
        )

    expected = {
        "format": _EXPECTED_FORMAT,
        "profile": model["profile"],
        "semantics_version": _EXPECTED_SEMANTICS_VERSION,
        "model_hash": digest(model),
        "engine_version": _EXPECTED_ENGINE_VERSION,
        "enumeration": {
            "input_order": sorted(model["inputs"]),
            "action_order": sorted(model["actions"]),
            **sizes,
            "evaluated_context_trace_pairs": evaluated_pairs,
        },
        "counts": totals,
        "cases": cases,
        "permission_summaries": summaries,
    }
    if len(canonical_json(expected).encode("utf-8")) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", "Independent replay exceeds 8 MiB")
    return expected


def verify(
    model: dict,
    certificate: object,
    *,
    expected_certificate_sha256: str | None = None,
    max_contexts: int = MAX_CONTEXTS,
    max_action_assignments: int = MAX_ACTION_ASSIGNMENTS,
    max_pairs: int = MAX_CONTEXT_TRACE_PAIRS,
) -> dict:
    """Verify the canonical complete replay and return separate diagnostics."""
    validate_model(model)
    _validate_anchor(expected_certificate_sha256)
    sizes = _preflight(
        model, max_contexts, max_action_assignments, max_pairs
    )
    supplied_text = _certificate_text(certificate)
    actual_hash = digest(certificate)
    if (
        expected_certificate_sha256 is not None
        and actual_hash != expected_certificate_sha256
    ):
        _certificate_invalid("Certificate hash does not match the external anchor")
    expected = _replay(model, sizes)
    if supplied_text != canonical_json(expected):
        _certificate_invalid("Certificate does not match the complete independent replay")

    unusable_pairs = sum(
        1
        for case in expected["cases"]
        for permission in case["permissions"]
        if permission["applicable"] and permission["status"] == "unusable"
    )
    unusable_contexts = sum(
        1
        for case in expected["cases"]
        if any(
            permission["applicable"] and permission["status"] == "unusable"
            for permission in case["permissions"]
        )
    )
    diagnostics = {
        "background_trace_impossible_contexts": expected["counts"][
            "background_trace_impossible"
        ],
        "normatively_infeasible_contexts": expected["counts"][
            "normatively_infeasible"
        ],
        "unusable_permission_context_pairs": unusable_pairs,
        "contexts_with_unusable_permissions": unusable_contexts,
    }
    diagnostics["has_findings"] = any(diagnostics.values())
    return {
        "status": "VERIFIED",
        "checker_version": CHECKER_VERSION,
        "model_hash": expected["model_hash"],
        "certificate_hash": actual_hash,
        "certificate_hash_anchored": expected_certificate_sha256 is not None,
        "enumeration": expected["enumeration"],
        "counts": expected["counts"],
        "permission_summaries": expected["permission_summaries"],
        "diagnostics": diagnostics,
    }
