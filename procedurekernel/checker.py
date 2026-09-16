"""Independent replay checker for finite procedure-and-time evidence.

This module intentionally does not import procedurekernel.engine.  Enumeration,
coordinate comparison, rule evaluation, classification, witnesses, and all
aggregates are reconstructed here.
"""
from __future__ import annotations

from itertools import product

from .model import (
    CERTIFICATE_FORMAT,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    MAX_CONTEXT_TRACE_PAIRS,
    MAX_TRACES_PER_CONTEXT,
    KernelError,
    canonical_json,
    checked_coordinate_add,
    coordinate_key,
    digest,
    validate_model,
    validate_sha256,
)

CHECKER_ENGINE_VERSION = "procedurekernel-engine/0.1.0"
SEMANTICS_VERSION = "1"


def _earlier(left: dict, right: dict) -> bool:
    left_pair = (left["tick"], left["phase"])
    right_pair = (right["tick"], right["phase"])
    return left_pair < right_pair


def _no_later(left: dict, right: dict) -> bool:
    left_pair = (left["tick"], left["phase"])
    right_pair = (right["tick"], right["phase"])
    return left_pair <= right_pair


def _deadline_ok(target: dict, deadline: dict, inclusive: bool) -> bool:
    if inclusive:
        return (target["tick"], target["phase"]) <= (deadline["tick"], deadline["phase"])
    return (target["tick"], target["phase"]) < (deadline["tick"], deadline["phase"])


def _past_deadline(observation_end: dict, deadline: dict, inclusive: bool) -> bool:
    # closed_prefix contains positions strictly before observation_end.
    end_key = (observation_end["tick"], observation_end["phase"])
    due_key = (deadline["tick"], deadline["phase"])
    return end_key > due_key if inclusive else end_key >= due_key


def _prohibited(target, start, end, include_start, include_end):
    point = (target["tick"], target["phase"])
    low = (start["tick"], start["phase"])
    high = (end["tick"], end["phase"])
    return (point >= low if include_start else point > low) and (
        point <= high if include_end else point < high
    )


def _make_events(context: dict, branch: dict[str, dict | None]) -> dict[str, dict]:
    result = {}
    for row in context["observed"]:
        result[row["slot"]] = {"at": row["at"], "source": "observed"}
    for slot_id, at in branch.items():
        if at is not None:
            result[slot_id] = {"at": at, "source": "future"}
    return result


def _serialize_events(event_map: dict[str, dict], slot_map: dict[str, dict]) -> list[dict]:
    rows = []
    for slot_id in sorted(event_map.keys()):
        slot = slot_map[slot_id]
        rows.append(
            {
                "slot": slot_id,
                "actor": slot["actor"],
                "kind": slot["kind"],
                "at": event_map[slot_id]["at"],
                "source": event_map[slot_id]["source"],
            }
        )
    return rows


def _check_precedence(item: dict, event_map: dict[str, dict]) -> dict:
    left = event_map.get(item["before"])
    right = event_map.get(item["after"])
    if right is None:
        state = "satisfied"
    elif left is None:
        state = "violated"
    elif left["at"] is None or right["at"] is None:
        state = "unresolved_time"
    elif item["relation"] == "strict_before":
        state = "satisfied" if _earlier(left["at"], right["at"]) else "violated"
    else:
        state = "satisfied" if _no_later(left["at"], right["at"]) else "violated"
    return {"constraint_id": item["id"], "relation": item["relation"], "status": state}


def _norm_shell(item: dict, start, target_rows: list[dict]) -> dict:
    return {
        "norm_id": item["id"],
        "kind": item["kind"],
        "anchor_present": start is not None,
        "anchor_at": None if start is None else start["at"],
        "target_slots": sorted(item["targets"]),
        "targets": target_rows,
        "selected_target": None,
    }


def _listed_targets(item: dict, event_map: dict[str, dict]) -> list[dict]:
    result = []
    for slot_id in sorted(item["targets"]):
        event = event_map.get(slot_id)
        result.append(
            {
                "slot": slot_id,
                "present": event is not None,
                "at": None if event is None else event["at"],
            }
        )
    return result


def _check_norm(
    item,
    event_map,
    observation_end,
    possible_future_anchors=frozenset(),
    observed_prefix=False,
):
    anchor = event_map.get(item["anchor"])
    target_rows = _listed_targets(item, event_map)
    row = _norm_shell(item, anchor, target_rows)
    if item["kind"] == "deadline":
        row.update({"window_start": None, "deadline": None})
    else:
        row.update({"window_start": None, "window_end": None})
    if anchor is None:
        row["status"] = (
            "pending_anchor" if item["anchor"] in possible_future_anchors else "anchor_missing"
        )
        return row
    if anchor["at"] is None:
        row["status"] = "anchor_time_unresolved"
        return row
    known = [entry for entry in target_rows if entry["present"] and entry["at"] is not None]
    unknown = [entry for entry in target_rows if entry["present"] and entry["at"] is None]
    if item["kind"] == "deadline":
        opening = checked_coordinate_add(anchor["at"], item["min_offset"])
        cutoff = checked_coordinate_add(anchor["at"], item["max_offset"])
        row["window_start"] = opening
        row["deadline"] = cutoff
        valid = [
            entry for entry in known
            if not _earlier(entry["at"], opening)
            and _deadline_ok(entry["at"], cutoff, item["inclusive"])
        ]
        if valid:
            chosen = min(
                valid,
                key=lambda entry: ((entry["at"]["tick"], entry["at"]["phase"]), entry["slot"]),
            )
            row["selected_target"] = chosen["slot"]
            row["status"] = "satisfied"
        elif unknown:
            row["status"] = "target_time_unresolved"
        elif (observed_prefix
              and any(not entry["present"] for entry in target_rows)
              and not _past_deadline(observation_end, cutoff, item["inclusive"])):
            row["status"] = "pending"
        elif known:
            all_early = all(_earlier(entry["at"], opening) for entry in known)
            all_late = all(
                not _deadline_ok(entry["at"], cutoff, item["inclusive"])
                and not _earlier(entry["at"], opening)
                for entry in known
            )
            if all_early:
                row["status"] = "violated_too_early"
            elif all_late:
                row["status"] = "violated_late"
            else:
                row["status"] = "violated_no_qualifying_target"
        else:
            if observed_prefix:
                row["status"] = (
                    "violated_missing"
                    if _past_deadline(observation_end, cutoff, item["inclusive"])
                    else "pending"
                )
            else:
                row["status"] = "violated_missing"
        return row
    low = checked_coordinate_add(anchor["at"], item["start_offset"])
    high = checked_coordinate_add(anchor["at"], item["end_offset"])
    row["window_start"] = low
    row["window_end"] = high
    blocked = [
        entry for entry in known
        if _prohibited(
            entry["at"], low, high, item["inclusive_start"], item["inclusive_end"]
        )
    ]
    if blocked:
        chosen = min(
            blocked,
            key=lambda entry: ((entry["at"]["tick"], entry["at"]["phase"]), entry["slot"]),
        )
        row["selected_target"] = chosen["slot"]
        row["status"] = "violated_prohibited_window"
    elif unknown:
        row["status"] = "target_time_unresolved"
    elif known:
        row["status"] = "satisfied"
    else:
        if observed_prefix:
            end_key = (observation_end["tick"], observation_end["phase"])
            high_key = (high["tick"], high["phase"])
            closed = end_key > high_key if item["inclusive_end"] else end_key >= high_key
            row["status"] = "satisfied" if closed else "pending"
        else:
            row["status"] = "satisfied"
    return row


def _replay_state(
    model,
    context,
    event_map,
    possible_future_anchors=frozenset(),
    observed_prefix=False,
):
    bg = [
        _check_precedence(item, event_map)
        for item in sorted(model["background_constraints"], key=lambda value: value["id"])
    ]
    rules = [
        _check_norm(
            item,
            event_map,
            context["observation_end"],
            possible_future_anchors,
            observed_prefix,
        )
        for item in sorted(model["norms"], key=lambda value: value["id"])
    ]
    possible = all(item["status"] != "violated" for item in bg)
    resolved = all(item["status"] == "satisfied" for item in bg)
    breached = any(item["status"].startswith("violated") for item in rules)
    complete = resolved and all(item["status"] == "satisfied" for item in rules)
    return {
        "background": bg,
        "rules": rules,
        "background_possible": possible,
        "background_resolved": resolved,
        "definitely_violated": breached,
        "fully_satisfied": complete,
        "viable": possible and not breached,
    }


def _prefix_result(replayed):
    bg_states = {item["status"] for item in replayed["background"]}
    norm_states = {item["status"] for item in replayed["rules"]}
    if "violated" in bg_states:
        return "background_violated"
    if any(value.startswith("violated") for value in norm_states):
        return "violated"
    if "unresolved_time" in bg_states or norm_states.intersection(
        {"anchor_time_unresolved", "target_time_unresolved"}
    ):
        return "unresolved_time"
    if norm_states.intersection({"anchor_missing", "pending_anchor"}):
        return "unresolved_anchor"
    if "pending" in norm_states:
        return "pending"
    return "fulfilled"


def _serialized_size(value: object) -> int:
    return len(canonical_json(value).encode("utf-8"))


def _next_array_payload_size(current_size: int, current_count: int, value: object) -> int:
    """Measure the exact canonical bytes between an array's brackets."""

    return _next_array_payload_size_from_item_size(
        current_size, current_count, _serialized_size(value)
    )


def _next_array_payload_size_from_item_size(
    current_size: int, current_count: int, item_size: int
) -> int:
    separator = 1 if current_count else 0
    return current_size + separator + item_size


def _minimum_replay_size(model, metadata, enumeration_rows, model_hash):
    """Compute a lower bound that no complete replay certificate can undercut.

    Counts are non-negative, making ``0`` their shortest JSON spelling, and
    ``true`` is the shorter boolean.  The remaining envelope fields already
    have their final values.  Case and trace payload bytes can safely be added
    to this bound without rejecting a certificate that could fit.
    """

    feasibility = {
        "background_trace_impossible": 0,
        "normatively_infeasible": 0,
        "compliance_feasible": 0,
        "completion_unresolved": 0,
    }
    outcomes = {
        "fulfilled": 0,
        "pending": 0,
        "violated": 0,
        "unresolved_anchor": 0,
        "unresolved_time": 0,
        "background_violated": 0,
    }
    lower_bound = {
        "format": CERTIFICATE_FORMAT,
        "profile": model["profile"],
        "semantics_version": SEMANTICS_VERSION,
        "model_hash": model_hash,
        "engine_version": CHECKER_ENGINE_VERSION,
        "enumeration": {
            "slot_order": metadata["slot_order"],
            "context_order": metadata["context_order"],
            "contexts": enumeration_rows,
            "context_count": 0,
            "total_candidate_traces": metadata["total_candidate_traces"],
        },
        "counts": {
            "total_contexts": 0,
            "feasibility": feasibility,
            "observed_outcomes": outcomes,
        },
        "cases": [],
        "diagnostics": {
            "has_findings": True,
            "feasibility": feasibility,
            "observed_outcomes": outcomes,
        },
    }
    return _serialized_size(lower_bound)


def _enforce_replay_limit(minimum_size: int, payload_size: int) -> None:
    if minimum_size + payload_size > MAX_CERTIFICATE_BYTES:
        raise KernelError(
            "LIMIT_REACHED",
            f"Independent replay would exceed {MAX_CERTIFICATE_BYTES} bytes",
        )


def _reconstruct(model, metadata):
    slot_map = {item["id"]: item for item in model["slots"]}
    context_map = {item["id"]: item for item in model["contexts"]}
    cases = []
    enumeration_rows = []
    for context_id in metadata["context_order"]:
        context = context_map[context_id]
        branch_order = sorted(row["slot"] for row in context["future"])
        enumeration_rows.append(
            {
                "context_id": context_id,
                "future_slot_order": branch_order,
                "candidate_trace_count": metadata["candidate_counts"][context_id],
            }
        )
    model_hash = digest(model)
    minimum_replay_size = _minimum_replay_size(
        model, metadata, enumeration_rows, model_hash
    )
    _enforce_replay_limit(minimum_replay_size, 0)
    cases_payload_size = 0
    feasibility = {
        "background_trace_impossible": 0,
        "normatively_infeasible": 0,
        "compliance_feasible": 0,
        "completion_unresolved": 0,
    }
    outcomes = {
        "fulfilled": 0,
        "pending": 0,
        "violated": 0,
        "unresolved_anchor": 0,
        "unresolved_time": 0,
        "background_violated": 0,
    }
    for context_id in metadata["context_order"]:
        context = context_map[context_id]
        option_map = {row["slot"]: row["at"] for row in context["future"]}
        branch_order = sorted(option_map.keys())
        alternatives = []
        for slot_id in branch_order:
            ordered = sorted(
                option_map[slot_id], key=lambda value: (value["tick"], value["phase"])
            )
            alternatives.append([None, *ordered])
        traces = []
        traces_payload_size = 0
        for combination in product(*alternatives):
            branch = {name: value for name, value in zip(branch_order, combination)}
            event_map = _make_events(context, branch)
            replayed = _replay_state(model, context, event_map)
            trace = {
                "choice": {name: branch[name] for name in branch_order},
                "events": _serialize_events(event_map, slot_map),
                **replayed,
            }
            next_traces_payload_size = _next_array_payload_size(
                traces_payload_size, len(traces), trace
            )
            _enforce_replay_limit(
                minimum_replay_size,
                cases_payload_size + next_traces_payload_size,
            )
            traces.append(trace)
            traces_payload_size = next_traces_payload_size
        bg_indexes = [index for index, row in enumerate(traces) if row["background_possible"]]
        viable_indexes = [index for index, row in enumerate(traces) if row["viable"]]
        complete_indexes = [index for index, row in enumerate(traces) if row["fully_satisfied"]]
        if not bg_indexes:
            class_name = "background_trace_impossible"
        elif complete_indexes:
            class_name = "compliance_feasible"
        elif not viable_indexes:
            class_name = "normatively_infeasible"
        else:
            class_name = "completion_unresolved"
        observed_map = _make_events(context, {})
        prefix = _replay_state(
            model,
            context,
            observed_map,
            set(option_map.keys()),
            True,
        )
        outcome = _prefix_result(prefix)
        feasibility[class_name] += 1
        outcomes[outcome] += 1

        def witness(indexes):
            if not indexes:
                return None
            first = indexes[0]
            return {"trace_index": first, "choice": traces[first]["choice"]}

        case = {
            "context_id": context_id,
            "observation_end": context["observation_end"],
            "observed_events": _serialize_events(observed_map, slot_map),
            "future_slot_order": branch_order,
            "candidate_trace_count": len(traces),
            "classification": class_name,
            "observed_outcome": outcome,
            "observed_evaluation": prefix,
            "background_trace_count": len(bg_indexes),
            "viable_trace_count": len(viable_indexes),
            "satisfying_trace_count": len(complete_indexes),
            "first_background_witness": witness(bg_indexes),
            "first_compliance_witness": witness(complete_indexes),
            "traces": traces,
        }
        # Trace rows were measured before insertion.  Measure only the case
        # shell here and add the trace payload, rather than serializing the
        # whole possibly over-limit case merely to discover its size.
        case_without_traces = {**case, "traces": []}
        case_size = _serialized_size(case_without_traces) + traces_payload_size
        next_cases_payload_size = _next_array_payload_size_from_item_size(
            cases_payload_size, len(cases), case_size
        )
        _enforce_replay_limit(
            minimum_replay_size, next_cases_payload_size
        )
        cases.append(case)
        cases_payload_size = next_cases_payload_size
    diagnostic = {
        "has_findings": any(key != "compliance_feasible" and value for key, value in feasibility.items())
        or any(key != "fulfilled" and value for key, value in outcomes.items()),
        "feasibility": feasibility,
        "observed_outcomes": outcomes,
    }
    expected = {
        "format": CERTIFICATE_FORMAT,
        "profile": model["profile"],
        "semantics_version": SEMANTICS_VERSION,
        "model_hash": model_hash,
        "engine_version": CHECKER_ENGINE_VERSION,
        "enumeration": {
            "slot_order": metadata["slot_order"],
            "context_order": metadata["context_order"],
            "contexts": enumeration_rows,
            "context_count": len(cases),
            "total_candidate_traces": metadata["total_candidate_traces"],
        },
        "counts": {
            "total_contexts": len(cases),
            "feasibility": feasibility,
            "observed_outcomes": outcomes,
        },
        "cases": cases,
        "diagnostics": diagnostic,
    }
    expected_without_cases = {**expected, "cases": []}
    exact_size = _serialized_size(expected_without_cases) + cases_payload_size
    _enforce_replay_limit(exact_size, 0)
    return expected


def verify(
    model: object,
    certificate: object,
    *,
    expected_certificate_sha256: str | None = None,
    max_contexts: int = MAX_CONTEXTS,
    max_traces_per_context: int = MAX_TRACES_PER_CONTEXT,
    max_pairs: int = MAX_CONTEXT_TRACE_PAIRS,
) -> dict:
    metadata = validate_model(
        model,
        max_contexts=max_contexts,
        max_traces_per_context=max_traces_per_context,
        max_pairs=max_pairs,
    )
    try:
        certificate_bytes = canonical_json(certificate).encode("utf-8")
    except KernelError as exc:
        raise KernelError("CERTIFICATE_INVALID", exc.message) from exc
    if len(certificate_bytes) > MAX_CERTIFICATE_BYTES:
        raise KernelError("LIMIT_REACHED", f"Certificate exceeds {MAX_CERTIFICATE_BYTES} bytes")
    certificate_hash = __import__("hashlib").sha256(certificate_bytes).hexdigest()
    if expected_certificate_sha256 is not None:
        try:
            validate_sha256(expected_certificate_sha256, "expected_certificate_sha256")
        except KernelError as exc:
            raise KernelError("CERTIFICATE_INVALID", exc.message) from exc
        if certificate_hash != expected_certificate_sha256:
            raise KernelError("CERTIFICATE_INVALID", "Certificate SHA-256 anchor mismatch")
    expected = _reconstruct(model, metadata)
    expected_bytes = canonical_json(expected).encode("utf-8")
    if certificate_bytes != expected_bytes:
        raise KernelError(
            "CERTIFICATE_INVALID",
            "Certificate differs from independent complete replay",
        )
    return {
        "status": "VERIFIED",
        "model_hash": expected["model_hash"],
        "certificate_hash": certificate_hash,
        "certificate_hash_anchored": expected_certificate_sha256 is not None,
        "counts": expected["counts"],
        "diagnostics": expected["diagnostics"],
    }
