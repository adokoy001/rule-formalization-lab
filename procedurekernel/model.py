"""Strict model boundary for the finite procedure-and-time profile."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROFILE = "finite-procedure-time/1"
ORIGIN_KIND = "authored_procedure_core"
CERTIFICATE_FORMAT = "finite-procedure-time-certificate/1"
MAX_MODEL_BYTES = 1024 * 1024
MAX_CERTIFICATE_BYTES = 8 * 1024 * 1024
MAX_SLOTS = 8
MAX_CONTEXTS = 10_000
MAX_TRACES_PER_CONTEXT = 4_096
MAX_CONTEXT_TRACE_PAIRS = 100_000
INT_MIN, INT_MAX = -(2**63), 2**63 - 1
MAX_PHASE = 1_000_000
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class KernelError(Exception):
    """A fail-closed error with a stable machine-readable status."""

    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def canonical_json(value: object) -> str:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        text.encode("utf-8")
        return text
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise KernelError("MODEL_INVALID", f"Not canonical JSON: {exc}") from exc


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: str | Path, *, max_bytes: int = MAX_MODEL_BYTES) -> object:
    """Load strict UTF-8 JSON, rejecting duplicate keys and non-finite numbers."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise KernelError("MODEL_INVALID", f"Duplicate JSON key: {key!r}")
            result[key] = value
        return result

    def nonfinite(value):
        raise KernelError("MODEL_INVALID", f"Non-finite JSON number: {value}")

    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise KernelError("LIMIT_REACHED", f"JSON exceeds {max_bytes} bytes")
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=nonfinite,
        )
        canonical_json(parsed)
        return parsed
    except KernelError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, OSError):
            raise
        raise KernelError("MODEL_INVALID", f"Invalid JSON: {exc}") from exc


def _invalid(message: str) -> None:
    raise KernelError("MODEL_INVALID", message)


def _shape(value: object, fields: set[str], path: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _invalid(f"{path}: expected object with string keys")
    missing = fields - value.keys()
    extra = value.keys() - fields
    if missing:
        _invalid(f"{path}: missing fields {sorted(missing)}")
    if extra:
        _invalid(f"{path}: unknown fields {sorted(extra)}")


def _text(value: object, path: str, maximum: int = 8192) -> None:
    if type(value) is not str or not value or len(value) > maximum:
        _invalid(f"{path}: expected nonempty string of at most {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _invalid(f"{path}: invalid Unicode")


def _name(value: object, path: str) -> None:
    if type(value) is not str or _NAME.fullmatch(value) is None:
        _invalid(f"{path}: invalid identifier")


def _integer(value: object, path: str) -> None:
    if type(value) is not int or not INT_MIN <= value <= INT_MAX:
        _invalid(f"{path}: expected signed 64-bit integer; bool is not integer")


def _bool(value: object, path: str) -> None:
    if type(value) is not bool:
        _invalid(f"{path}: expected Boolean")


def _coordinate(value: object, path: str) -> None:
    _shape(value, {"tick", "phase"}, path)
    _integer(value["tick"], path + ".tick")
    if type(value["phase"]) is not int or not 0 <= value["phase"] <= MAX_PHASE:
        _invalid(f"{path}.phase: expected integer in 0..{MAX_PHASE}")


def coordinate_key(value: dict) -> tuple[int, int]:
    return value["tick"], value["phase"]


def checked_coordinate_add(value: dict, offset: int, path: str = "coordinate") -> dict:
    tick = value["tick"] + offset
    if not INT_MIN <= tick <= INT_MAX:
        _invalid(f"{path}: signed 64-bit tick overflow")
    return {"tick": tick, "phase": value["phase"]}


def _reference(value: object, slot_ids: set[str], path: str) -> None:
    _name(value, path)
    if value not in slot_ids:
        _invalid(f"{path}: unknown slot {value!r}")


def _limit(value: object, hard: int, path: str) -> int:
    if type(value) is not int or value < 1:
        raise KernelError("LIMIT_REACHED", f"{path} must be a positive integer")
    if value > hard:
        raise KernelError("LIMIT_REACHED", f"{path} cannot exceed hard limit {hard}")
    return value


def validate_model(
    model: object,
    *,
    max_contexts: int = MAX_CONTEXTS,
    max_traces_per_context: int = MAX_TRACES_PER_CONTEXT,
    max_pairs: int = MAX_CONTEXT_TRACE_PAIRS,
) -> dict:
    """Validate the closed finite profile and return deterministic enumeration metadata."""
    max_contexts = _limit(max_contexts, MAX_CONTEXTS, "max_contexts")
    max_traces_per_context = _limit(
        max_traces_per_context, MAX_TRACES_PER_CONTEXT, "max_traces_per_context"
    )
    max_pairs = _limit(max_pairs, MAX_CONTEXT_TRACE_PAIRS, "max_pairs")

    if len(canonical_json(model).encode("utf-8")) > MAX_MODEL_BYTES:
        raise KernelError("LIMIT_REACHED", f"Model exceeds {MAX_MODEL_BYTES} canonical bytes")
    _shape(
        model,
        {
            "profile",
            "origin_kind",
            "title",
            "time_unit",
            "observation_mode",
            "slots",
            "background_constraints",
            "norms",
            "contexts",
        },
        "model",
    )
    if model["profile"] != PROFILE:
        if type(model["profile"]) is str:
            raise KernelError("UNSUPPORTED", f"Unsupported profile {model['profile']!r}")
        _invalid("model.profile: expected string")
    if model["origin_kind"] != ORIGIN_KIND:
        if type(model["origin_kind"]) is str:
            raise KernelError("UNSUPPORTED", f"Unsupported origin_kind {model['origin_kind']!r}")
        _invalid("model.origin_kind: expected string")
    _text(model["title"], "model.title")
    _name(model["time_unit"], "model.time_unit")
    if model["observation_mode"] != "closed_prefix":
        if type(model["observation_mode"]) is str:
            raise KernelError(
                "UNSUPPORTED",
                f"Unsupported observation_mode {model['observation_mode']!r}",
            )
        _invalid("model.observation_mode: expected string")

    slots = model["slots"]
    if type(slots) is not list or not 1 <= len(slots) <= MAX_SLOTS:
        if type(slots) is list and len(slots) > MAX_SLOTS:
            raise KernelError("LIMIT_REACHED", f"At most {MAX_SLOTS} event slots are allowed")
        _invalid("model.slots: expected 1..8 slots")
    slot_ids: set[str] = set()
    event_kinds: set[str] = set()
    for index, slot in enumerate(slots):
        path = f"model.slots[{index}]"
        _shape(slot, {"id", "actor", "kind"}, path)
        _name(slot["id"], path + ".id")
        _name(slot["actor"], path + ".actor")
        _name(slot["kind"], path + ".kind")
        if slot["id"] in slot_ids:
            _invalid(f"{path}.id: duplicate slot")
        if slot["kind"] in event_kinds:
            raise KernelError(
                "UNSUPPORTED",
                f"{path}.kind: repeated event kind requires multiplicity semantics",
            )
        slot_ids.add(slot["id"])
        event_kinds.add(slot["kind"])

    constraints = model["background_constraints"]
    if type(constraints) is not list:
        _invalid("model.background_constraints: expected list")
    identifiers: set[str] = set()
    for index, constraint in enumerate(constraints):
        path = f"model.background_constraints[{index}]"
        if type(constraint) is not dict:
            _invalid(f"{path}: expected object")
        kind = constraint.get("kind")
        if kind != "precedence":
            if type(kind) is str:
                raise KernelError("UNSUPPORTED", f"{path}: unsupported constraint kind {kind!r}")
            _invalid(f"{path}.kind: expected string")
        _shape(constraint, {"id", "kind", "before", "after", "relation"}, path)
        _name(constraint["id"], path + ".id")
        if constraint["id"] in identifiers:
            _invalid(f"{path}.id: duplicate identifier")
        identifiers.add(constraint["id"])
        _reference(constraint["before"], slot_ids, path + ".before")
        _reference(constraint["after"], slot_ids, path + ".after")
        if constraint["before"] == constraint["after"]:
            _invalid(f"{path}: before and after must differ")
        relation = constraint["relation"]
        if relation not in {"strict_before", "not_after"}:
            if type(relation) is str:
                raise KernelError("UNSUPPORTED", f"{path}: unsupported relation {relation!r}")
            _invalid(f"{path}.relation: expected string")

    norms = model["norms"]
    if type(norms) is not list or not 1 <= len(norms) <= 256:
        _invalid("model.norms: expected 1..256 norms")
    for index, norm in enumerate(norms):
        path = f"model.norms[{index}]"
        if type(norm) is not dict:
            _invalid(f"{path}: expected object")
        kind = norm.get("kind")
        if kind == "deadline":
            _shape(
                norm,
                {
                    "id", "source", "kind", "anchor", "targets",
                    "min_offset", "max_offset", "inclusive",
                },
                path,
            )
            _integer(norm["min_offset"], path + ".min_offset")
            _integer(norm["max_offset"], path + ".max_offset")
            if norm["min_offset"] < 0 or norm["max_offset"] < norm["min_offset"]:
                _invalid(f"{path}: deadline offsets require 0 <= min <= max")
            _bool(norm["inclusive"], path + ".inclusive")
        elif kind == "prohibition_window":
            _shape(
                norm,
                {
                    "id", "source", "kind", "anchor", "targets",
                    "start_offset", "end_offset", "inclusive_start", "inclusive_end",
                },
                path,
            )
            _integer(norm["start_offset"], path + ".start_offset")
            _integer(norm["end_offset"], path + ".end_offset")
            if norm["start_offset"] < 0 or norm["end_offset"] < norm["start_offset"]:
                _invalid(f"{path}: prohibition offsets require 0 <= start <= end")
            _bool(norm["inclusive_start"], path + ".inclusive_start")
            _bool(norm["inclusive_end"], path + ".inclusive_end")
        else:
            if type(kind) is str:
                raise KernelError("UNSUPPORTED", f"{path}: unsupported norm kind {kind!r}")
            _invalid(f"{path}.kind: expected string")
        _name(norm["id"], path + ".id")
        if norm["id"] in identifiers:
            _invalid(f"{path}.id: duplicate identifier")
        identifiers.add(norm["id"])
        _text(norm["source"], path + ".source")
        _reference(norm["anchor"], slot_ids, path + ".anchor")
        targets = norm["targets"]
        if type(targets) is not list or not 1 <= len(targets) <= MAX_SLOTS:
            _invalid(f"{path}.targets: expected 1..{MAX_SLOTS} slot identifiers")
        for target_index, target in enumerate(targets):
            _reference(target, slot_ids, f"{path}.targets[{target_index}]")
        if len(set(targets)) != len(targets):
            _invalid(f"{path}.targets: duplicate slot")
        if kind == "prohibition_window" and len(targets) != 1:
            raise KernelError(
                "UNSUPPORTED",
                f"{path}.targets: prohibition_window supports exactly one target",
            )
        if norm["anchor"] in targets:
            _invalid(f"{path}: anchor cannot also be a target")

    contexts = model["contexts"]
    if type(contexts) is not list or not contexts:
        _invalid("model.contexts: expected nonempty list")
    if len(contexts) > max_contexts:
        raise KernelError("LIMIT_REACHED", f"Context count exceeds {max_contexts}")
    context_ids: set[str] = set()
    candidate_counts: dict[str, int] = {}
    total_pairs = 0
    anchor_coordinates: dict[str, list[dict]] = {slot_id: [] for slot_id in slot_ids}
    for index, context in enumerate(contexts):
        path = f"model.contexts[{index}]"
        _shape(context, {"id", "observation_end", "observed", "future"}, path)
        _name(context["id"], path + ".id")
        if context["id"] in context_ids:
            _invalid(f"{path}.id: duplicate context")
        context_ids.add(context["id"])
        _coordinate(context["observation_end"], path + ".observation_end")
        observation_end_key = coordinate_key(context["observation_end"])
        observed = context["observed"]
        future = context["future"]
        if type(observed) is not list or type(future) is not list:
            _invalid(f"{path}: observed and future must be lists")
        seen_slots: set[str] = set()
        for event_index, event in enumerate(observed):
            event_path = f"{path}.observed[{event_index}]"
            _shape(event, {"slot", "at"}, event_path)
            _reference(event["slot"], slot_ids, event_path + ".slot")
            if event["slot"] in seen_slots:
                _invalid(f"{event_path}.slot: duplicate slot in context")
            seen_slots.add(event["slot"])
            if event["at"] is not None:
                _coordinate(event["at"], event_path + ".at")
                if coordinate_key(event["at"]) >= observation_end_key:
                    _invalid(f"{event_path}.at: observed event must be before exclusive observation_end")
                anchor_coordinates[event["slot"]].append(event["at"])
        candidate_count = 1
        for future_index, branch in enumerate(future):
            branch_path = f"{path}.future[{future_index}]"
            _shape(branch, {"slot", "at"}, branch_path)
            _reference(branch["slot"], slot_ids, branch_path + ".slot")
            if branch["slot"] in seen_slots:
                _invalid(f"{branch_path}.slot: slot is observed or repeated")
            seen_slots.add(branch["slot"])
            coordinates = branch["at"]
            if type(coordinates) is not list or not coordinates:
                _invalid(f"{branch_path}.at: expected nonempty finite coordinate list")
            keys = []
            for coordinate_index, coordinate in enumerate(coordinates):
                coordinate_path = f"{branch_path}.at[{coordinate_index}]"
                _coordinate(coordinate, coordinate_path)
                key = coordinate_key(coordinate)
                if key < observation_end_key:
                    _invalid(f"{coordinate_path}: future event must be at or after exclusive observation_end")
                keys.append(key)
                anchor_coordinates[branch["slot"]].append(coordinate)
            if len(set(keys)) != len(keys):
                _invalid(f"{branch_path}.at: duplicate coordinate")
            candidate_count *= 1 + len(coordinates)
            if candidate_count > max_traces_per_context:
                raise KernelError(
                    "LIMIT_REACHED",
                    f"{path}: candidate trace count exceeds {max_traces_per_context}",
                )
        candidate_counts[context["id"]] = candidate_count
        total_pairs += candidate_count
        if total_pairs > max_pairs:
            raise KernelError("LIMIT_REACHED", f"Context/trace pairs exceed {max_pairs}")

    for norm_index, norm in enumerate(norms):
        offsets = (
            (norm["min_offset"], norm["max_offset"])
            if norm["kind"] == "deadline"
            else (norm["start_offset"], norm["end_offset"])
        )
        for coordinate in anchor_coordinates[norm["anchor"]]:
            for offset in offsets:
                checked_coordinate_add(
                    coordinate,
                    offset,
                    f"model.norms[{norm_index}] anchor arithmetic",
                )

    return {
        "slot_order": sorted(slot_ids),
        "context_order": sorted(context_ids),
        "candidate_counts": candidate_counts,
        "total_candidate_traces": total_pairs,
        "limits": {
            "max_contexts": max_contexts,
            "max_traces_per_context": max_traces_per_context,
            "max_pairs": max_pairs,
        },
    }


def validate_sha256(value: object, path: str = "sha256") -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid(f"{path}: expected lowercase SHA-256")
