"""Reference producer for the finite procedure-and-time profile."""
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
)

ENGINE_VERSION = "procedurekernel-engine/0.1.0"
SEMANTICS_VERSION = "1"


def _coord_lt(left: dict, right: dict) -> bool:
    return coordinate_key(left) < coordinate_key(right)


def _coord_le(left: dict, right: dict) -> bool:
    return coordinate_key(left) <= coordinate_key(right)


def _deadline_allows(target: dict, deadline: dict, inclusive: bool) -> bool:
    return _coord_le(target, deadline) if inclusive else _coord_lt(target, deadline)


def _deadline_missed_at_observation_end(observation_end: dict, deadline: dict, inclusive: bool) -> bool:
    # closed_prefix records every declared event strictly before observation_end.
    if inclusive:
        return coordinate_key(observation_end) > coordinate_key(deadline)
    return coordinate_key(observation_end) >= coordinate_key(deadline)


def _in_window(
    target: dict,
    start: dict,
    end: dict,
    inclusive_start: bool,
    inclusive_end: bool,
) -> bool:
    target_key, start_key, end_key = map(coordinate_key, (target, start, end))
    lower = target_key >= start_key if inclusive_start else target_key > start_key
    upper = target_key <= end_key if inclusive_end else target_key < end_key
    return lower and upper


def _event_map(context: dict, selected: dict[str, dict | None]) -> dict[str, dict]:
    events = {
        event["slot"]: {"at": event["at"], "source": "observed"}
        for event in context["observed"]
    }
    for slot, coordinate in selected.items():
        if coordinate is not None:
            events[slot] = {"at": coordinate, "source": "future"}
    return events


def _stored_events(events: dict[str, dict], slots: dict[str, dict]) -> list[dict]:
    # Slot-id order is only a canonical serialization order, never temporal order.
    return [
        {
            "slot": slot_id,
            "actor": slots[slot_id]["actor"],
            "kind": slots[slot_id]["kind"],
            "at": events[slot_id]["at"],
            "source": events[slot_id]["source"],
        }
        for slot_id in sorted(events)
    ]


def _evaluate_constraint(constraint: dict, events: dict[str, dict]) -> dict:
    before = events.get(constraint["before"])
    after = events.get(constraint["after"])
    if after is None:
        status = "satisfied"
    elif before is None:
        status = "violated"
    elif before["at"] is None or after["at"] is None:
        status = "unresolved_time"
    elif constraint["relation"] == "strict_before":
        status = "satisfied" if _coord_lt(before["at"], after["at"]) else "violated"
    else:
        status = "satisfied" if _coord_le(before["at"], after["at"]) else "violated"
    return {
        "constraint_id": constraint["id"],
        "relation": constraint["relation"],
        "status": status,
    }


def _rule_base(norm: dict, anchor, targets: list[dict]) -> dict:
    return {
        "norm_id": norm["id"],
        "kind": norm["kind"],
        "anchor_present": anchor is not None,
        "anchor_at": None if anchor is None else anchor["at"],
        "target_slots": sorted(norm["targets"]),
        "targets": targets,
        "selected_target": None,
    }


def _target_rows(norm: dict, events: dict[str, dict]) -> list[dict]:
    return [
        {
            "slot": slot_id,
            "present": slot_id in events,
            "at": None if slot_id not in events else events[slot_id]["at"],
        }
        for slot_id in sorted(norm["targets"])
    ]


def _evaluate_rule(
    norm: dict,
    events: dict[str, dict],
    observation_end: dict,
    *,
    pending_anchor_slots: set[str] = frozenset(),
    observed_prefix: bool = False,
) -> dict:
    anchor = events.get(norm["anchor"])
    target_rows = _target_rows(norm, events)
    result = _rule_base(norm, anchor, target_rows)
    if norm["kind"] == "deadline":
        result.update({"window_start": None, "deadline": None})
    else:
        result.update({"window_start": None, "window_end": None})

    if anchor is None:
        result["status"] = (
            "pending_anchor" if norm["anchor"] in pending_anchor_slots else "anchor_missing"
        )
        return result
    if anchor["at"] is None:
        result["status"] = "anchor_time_unresolved"
        return result
    known_targets = [row for row in target_rows if row["present"] and row["at"] is not None]
    unknown_targets = [row for row in target_rows if row["present"] and row["at"] is None]
    if norm["kind"] == "deadline":
        start = checked_coordinate_add(anchor["at"], norm["min_offset"])
        deadline = checked_coordinate_add(anchor["at"], norm["max_offset"])
        result["window_start"] = start
        result["deadline"] = deadline
        qualifying = [
            row for row in known_targets
            if not _coord_lt(row["at"], start)
            and _deadline_allows(row["at"], deadline, norm["inclusive"])
        ]
        if qualifying:
            selected = min(qualifying, key=lambda row: (coordinate_key(row["at"]), row["slot"]))
            result["selected_target"] = selected["slot"]
            result["status"] = "satisfied"
        elif unknown_targets:
            result["status"] = "target_time_unresolved"
        elif (observed_prefix
              and any(not row["present"] for row in target_rows)
              and not _deadline_missed_at_observation_end(
                  observation_end, deadline, norm["inclusive"]
              )):
            result["status"] = "pending"
        elif known_targets:
            too_early = all(_coord_lt(row["at"], start) for row in known_targets)
            too_late = all(
                not _deadline_allows(row["at"], deadline, norm["inclusive"])
                and not _coord_lt(row["at"], start)
                for row in known_targets
            )
            if too_early:
                result["status"] = "violated_too_early"
            elif too_late:
                result["status"] = "violated_late"
            else:
                result["status"] = "violated_no_qualifying_target"
        else:
            if observed_prefix:
                result["status"] = (
                    "violated_missing"
                    if _deadline_missed_at_observation_end(
                        observation_end, deadline, norm["inclusive"]
                    )
                    else "pending"
                )
            else:
                result["status"] = "violated_missing"
        return result

    start = checked_coordinate_add(anchor["at"], norm["start_offset"])
    end = checked_coordinate_add(anchor["at"], norm["end_offset"])
    result["window_start"] = start
    result["window_end"] = end
    prohibited = [
        row for row in known_targets
        if _in_window(
            row["at"], start, end, norm["inclusive_start"], norm["inclusive_end"]
        )
    ]
    if prohibited:
        selected = min(prohibited, key=lambda row: (coordinate_key(row["at"]), row["slot"]))
        result["selected_target"] = selected["slot"]
        result["status"] = "violated_prohibited_window"
    elif unknown_targets:
        result["status"] = "target_time_unresolved"
    elif known_targets:
        result["status"] = "satisfied"
    else:
        if observed_prefix:
            closed = (
                coordinate_key(observation_end) > coordinate_key(end)
                if norm["inclusive_end"]
                else coordinate_key(observation_end) >= coordinate_key(end)
            )
            result["status"] = "satisfied" if closed else "pending"
        else:
            result["status"] = "satisfied"
    return result


def _evaluate(
    model: dict,
    context: dict,
    events: dict[str, dict],
    *,
    pending_anchor_slots: set[str] = frozenset(),
    observed_prefix: bool = False,
) -> dict:
    background = [
        _evaluate_constraint(item, events)
        for item in sorted(model["background_constraints"], key=lambda row: row["id"])
    ]
    rules = [
        _evaluate_rule(
            item,
            events,
            context["observation_end"],
            pending_anchor_slots=pending_anchor_slots,
            observed_prefix=observed_prefix,
        )
        for item in sorted(model["norms"], key=lambda row: row["id"])
    ]
    background_possible = not any(row["status"] == "violated" for row in background)
    background_resolved = all(row["status"] == "satisfied" for row in background)
    definitely_violated = any(row["status"].startswith("violated") for row in rules)
    fully_satisfied = background_resolved and all(
        row["status"] == "satisfied" for row in rules
    )
    return {
        "background": background,
        "rules": rules,
        "background_possible": background_possible,
        "background_resolved": background_resolved,
        "definitely_violated": definitely_violated,
        "fully_satisfied": fully_satisfied,
        "viable": background_possible and not definitely_violated,
    }


def _observed_outcome(evaluation: dict) -> str:
    background_statuses = {row["status"] for row in evaluation["background"]}
    statuses = {row["status"] for row in evaluation["rules"]}
    if "violated" in background_statuses:
        return "background_violated"
    if any(status.startswith("violated") for status in statuses):
        return "violated"
    if "unresolved_time" in background_statuses or statuses & {
        "anchor_time_unresolved", "target_time_unresolved"
    }:
        return "unresolved_time"
    if statuses & {"anchor_missing", "pending_anchor"}:
        return "unresolved_anchor"
    if "pending" in statuses:
        return "pending"
    return "fulfilled"


def _witness(index: int, trace: dict) -> dict:
    return {"trace_index": index, "choice": trace["choice"]}


def analyze(
    model: object,
    *,
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
    slots = {slot["id"]: slot for slot in model["slots"]}
    contexts = {context["id"]: context for context in model["contexts"]}
    cases = []
    enumeration_contexts = []

    feasibility_names = (
        "background_trace_impossible",
        "normatively_infeasible",
        "compliance_feasible",
        "completion_unresolved",
    )
    outcome_names = (
        "fulfilled",
        "pending",
        "violated",
        "unresolved_anchor",
        "unresolved_time",
        "background_violated",
    )
    feasibility_counts = {name: 0 for name in feasibility_names}
    outcome_counts = {name: 0 for name in outcome_names}

    for context_id in metadata["context_order"]:
        context = contexts[context_id]
        future = {branch["slot"]: branch["at"] for branch in context["future"]}
        future_order = sorted(future)
        option_lists = [
            [None] + sorted(future[slot_id], key=coordinate_key)
            for slot_id in future_order
        ]
        traces = []
        for values in product(*option_lists):
            selected = dict(zip(future_order, values))
            events = _event_map(context, selected)
            evaluation = _evaluate(model, context, events)
            traces.append(
                {
                    "choice": {slot: selected[slot] for slot in future_order},
                    "events": _stored_events(events, slots),
                    **evaluation,
                }
            )

        background_indices = [
            index for index, trace in enumerate(traces) if trace["background_possible"]
        ]
        viable_indices = [index for index, trace in enumerate(traces) if trace["viable"]]
        satisfying_indices = [
            index for index, trace in enumerate(traces) if trace["fully_satisfied"]
        ]
        if not background_indices:
            classification = "background_trace_impossible"
        elif satisfying_indices:
            classification = "compliance_feasible"
        elif not viable_indices:
            classification = "normatively_infeasible"
        else:
            classification = "completion_unresolved"

        observed_events = _event_map(context, {})
        observed_evaluation = _evaluate(
            model,
            context,
            observed_events,
            pending_anchor_slots=set(future),
            observed_prefix=True,
        )
        observed_outcome = _observed_outcome(observed_evaluation)
        feasibility_counts[classification] += 1
        outcome_counts[observed_outcome] += 1
        cases.append(
            {
                "context_id": context_id,
                "observation_end": context["observation_end"],
                "observed_events": _stored_events(observed_events, slots),
                "future_slot_order": future_order,
                "candidate_trace_count": len(traces),
                "classification": classification,
                "observed_outcome": observed_outcome,
                "observed_evaluation": observed_evaluation,
                "background_trace_count": len(background_indices),
                "viable_trace_count": len(viable_indices),
                "satisfying_trace_count": len(satisfying_indices),
                "first_background_witness": (
                    None if not background_indices else _witness(background_indices[0], traces[background_indices[0]])
                ),
                "first_compliance_witness": (
                    None if not satisfying_indices else _witness(satisfying_indices[0], traces[satisfying_indices[0]])
                ),
                "traces": traces,
            }
        )
        enumeration_contexts.append(
            {
                "context_id": context_id,
                "future_slot_order": future_order,
                "candidate_trace_count": len(traces),
            }
        )

    diagnostics = {
        "has_findings": any(name != "compliance_feasible" and count for name, count in feasibility_counts.items())
        or any(name != "fulfilled" and count for name, count in outcome_counts.items()),
        "feasibility": feasibility_counts,
        "observed_outcomes": outcome_counts,
    }
    certificate = {
        "format": CERTIFICATE_FORMAT,
        "profile": model["profile"],
        "semantics_version": SEMANTICS_VERSION,
        "model_hash": digest(model),
        "engine_version": ENGINE_VERSION,
        "enumeration": {
            "slot_order": metadata["slot_order"],
            "context_order": metadata["context_order"],
            "contexts": enumeration_contexts,
            "context_count": len(cases),
            "total_candidate_traces": metadata["total_candidate_traces"],
        },
        "counts": {
            "total_contexts": len(cases),
            "feasibility": feasibility_counts,
            "observed_outcomes": outcome_counts,
        },
        "cases": cases,
        "diagnostics": diagnostics,
    }
    size = len(canonical_json(certificate).encode("utf-8"))
    if size > MAX_CERTIFICATE_BYTES:
        raise KernelError(
            "LIMIT_REACHED", f"Certificate would exceed {MAX_CERTIFICATE_BYTES} bytes"
        )
    return certificate
