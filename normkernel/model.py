"""Strict model and JSON boundary for the finite normative profile."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROFILE = "finite-norms/1"
ORIGIN_KIND = "authored_normative_core"
MAX_MODEL_BYTES = 1024 * 1024
MAX_CERTIFICATE_BYTES = 8 * 1024 * 1024
MAX_CONTEXTS = 10_000
MAX_ACTION_ASSIGNMENTS = 4_096
MAX_CONTEXT_TRACE_PAIRS = 100_000
INT_MIN, INT_MAX = -(2**63), 2**63 - 1
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class KernelError(Exception):
    """A fail-closed error with a stable machine-readable status."""

    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def canonical_json(value: object) -> str:
    """Return the sole canonical JSON representation used for evidence hashes."""
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
    except (UnicodeError, ValueError, RecursionError) as exc:
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


def _domain(domain: object, path: str) -> None:
    if type(domain) is not dict:
        _invalid(f"{path}: expected type object")
    kind = domain.get("kind")
    if kind == "bool":
        _shape(domain, {"kind"}, path)
    elif kind == "int":
        _shape(domain, {"kind", "min", "max"}, path)
        _integer(domain["min"], path + ".min")
        _integer(domain["max"], path + ".max")
        if domain["min"] > domain["max"]:
            _invalid(f"{path}: empty integer domain")
    elif kind == "enum":
        _shape(domain, {"kind", "values"}, path)
        values = domain["values"]
        if type(values) is not list or not 1 <= len(values) <= 256:
            _invalid(f"{path}: enum requires 1..256 values")
        for index, member in enumerate(values):
            _text(member, f"{path}.values[{index}]", 256)
        if len(set(values)) != len(values):
            _invalid(f"{path}: duplicate enum value")
    else:
        if type(kind) is not str:
            _invalid(f"{path}.kind: expected type name string")
        raise KernelError("UNSUPPORTED", f"{path}: unsupported type {kind!r}")


def _member(value: object, domain: dict, path: str) -> None:
    kind = domain["kind"]
    valid = (
        type(value) is bool
        if kind == "bool"
        else type(value) is int and domain["min"] <= value <= domain["max"]
        if kind == "int"
        else type(value) is str and value in domain["values"]
    )
    if not valid:
        _invalid(f"{path}: value outside declared {kind} domain")


def _expression_type(
    expression: object,
    inputs: dict,
    actions: set[str],
    *,
    allow_actions: bool,
    path: str,
    budget: list[int],
    depth: int = 0,
) -> tuple[str, object]:
    budget[0] += 1
    if budget[0] > 8192 or depth > 32:
        raise KernelError("LIMIT_REACHED", "Expressions exceed 8192 nodes or depth 32")
    if type(expression) is not dict:
        _invalid(f"{path}: expected expression object")
    if "const" in expression:
        _shape(expression, {"const"}, path)
        value = expression["const"]
        if type(value) is bool:
            return ("bool", None)
        if type(value) is int:
            _integer(value, path + ".const")
            return ("int", None)
        if type(value) is str:
            _text(value, path + ".const", 256)
            return ("literal", value)
        _invalid(f"{path}: constants are limited to bool, int, and enum strings")
    if "input" in expression:
        _shape(expression, {"input"}, path)
        name = expression["input"]
        _name(name, path + ".input")
        if name not in inputs:
            _invalid(f"{path}: undeclared input {name}")
        domain = inputs[name]
        members = frozenset(domain["values"]) if domain["kind"] == "enum" else None
        return (domain["kind"], members)
    if "action" in expression:
        _shape(expression, {"action"}, path)
        name = expression["action"]
        _name(name, path + ".action")
        if not allow_actions:
            _invalid(f"{path}: action references are unavailable in this expression")
        if name not in actions:
            _invalid(f"{path}: undeclared action {name}")
        return ("bool", None)
    _shape(expression, {"op", "args"}, path)
    operation, arguments = expression["op"], expression["args"]
    supported = {"eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not"}
    if type(operation) is not str:
        _invalid(f"{path}.op: expected operator name string")
    if operation not in supported:
        raise KernelError("UNSUPPORTED", f"{path}: unsupported operator {operation!r}")
    if type(arguments) is not list:
        _invalid(f"{path}.args: expected array")
    if operation in {"and", "or"}:
        if not 2 <= len(arguments) <= 64:
            _invalid(f"{path}: {operation} requires 2..64 arguments")
    elif operation == "not":
        if len(arguments) != 1:
            _invalid(f"{path}: not requires exactly one argument")
    elif len(arguments) != 2:
        _invalid(f"{path}: {operation} requires exactly two arguments")
    types = [
        _expression_type(
            argument,
            inputs,
            actions,
            allow_actions=allow_actions,
            path=f"{path}.args[{index}]",
            budget=budget,
            depth=depth + 1,
        )
        for index, argument in enumerate(arguments)
    ]
    if operation in {"and", "or", "not"}:
        if any(kind != "bool" for kind, _ in types):
            _invalid(f"{path}: Boolean operands required")
    elif operation in {"lt", "le", "gt", "ge"}:
        if any(kind != "int" for kind, _ in types):
            _invalid(f"{path}: ordered comparisons require integers")
    else:
        left, right = types
        compatible = (
            left[0] == right[0] and (left[0] != "enum" or left[1] == right[1])
        ) or (
            left[0] == "enum" and right[0] == "literal" and right[1] in left[1]
        ) or (
            right[0] == "enum" and left[0] == "literal" and left[1] in right[1]
        )
        if not compatible:
            _invalid(f"{path}: incompatible equality operands")
    return ("bool", None)


def _boolean_expression(
    expression: object,
    inputs: dict,
    actions: set[str],
    *,
    allow_actions: bool,
    path: str,
    budget: list[int],
) -> None:
    if _expression_type(
        expression,
        inputs,
        actions,
        allow_actions=allow_actions,
        path=path,
        budget=budget,
    )[0] != "bool":
        _invalid(f"{path}: Boolean expression required")


def validate_model(model: object) -> None:
    """Validate the exact finite-norms/1 surface without interpreting it."""
    _shape(
        model,
        {
            "profile",
            "origin_kind",
            "title",
            "inputs",
            "facts",
            "constraints",
            "actions",
            "action_constraints",
            "norms",
        },
        "model",
    )
    if type(model["profile"]) is not str:
        _invalid("model.profile: expected profile name string")
    if type(model["origin_kind"]) is not str:
        _invalid("model.origin_kind: expected origin kind string")
    if model["profile"] != PROFILE or model["origin_kind"] != ORIGIN_KIND:
        raise KernelError(
            "UNSUPPORTED",
            f"Requires {PROFILE} with origin_kind {ORIGIN_KIND}",
        )
    _text(model["title"], "title", 256)
    if len(canonical_json(model).encode("utf-8")) > MAX_MODEL_BYTES:
        raise KernelError("LIMIT_REACHED", "Model exceeds 1 MiB")

    inputs = model["inputs"]
    if type(inputs) is not dict or len(inputs) > 32:
        _invalid("inputs: expected object with at most 32 entries")
    for name, domain in inputs.items():
        _name(name, "inputs")
        _domain(domain, f"inputs.{name}")

    actions_value = model["actions"]
    if type(actions_value) is not list or len(actions_value) > 32:
        _invalid("actions: expected array with at most 32 Boolean atom names")
    for index, name in enumerate(actions_value):
        _name(name, f"actions[{index}]")
    if len(set(actions_value)) != len(actions_value):
        _invalid("actions: duplicate action name")
    overlap = set(inputs).intersection(actions_value)
    if overlap:
        _invalid(f"actions: names overlap inputs {sorted(overlap)}")
    actions = set(actions_value)

    facts = model["facts"]
    if type(facts) is not list or len(facts) > 1024:
        _invalid("facts: expected array of at most 1024 facts")
    observed = {}
    for index, fact in enumerate(facts):
        path = f"facts[{index}]"
        _shape(fact, {"var", "value"}, path)
        name, value = fact["var"], fact["value"]
        _name(name, path + ".var")
        if name not in inputs:
            _invalid(f"{path}: undeclared input {name}")
        _member(value, inputs[name], path + ".value")
        if name in observed and canonical_json(observed[name]) != canonical_json(value):
            raise KernelError("INPUT_INCONSISTENT", f"Conflicting facts for {name}")
        observed[name] = value

    for field, maximum in (("constraints", 128), ("action_constraints", 128)):
        expressions = model[field]
        if type(expressions) is not list or len(expressions) > maximum:
            _invalid(f"{field}: expected array of at most {maximum} expressions")

    norms = model["norms"]
    if type(norms) is not list or len(norms) > 128:
        _invalid("norms: expected array of at most 128 norms")

    budget = [0]
    for index, expression in enumerate(model["constraints"]):
        _boolean_expression(
            expression,
            inputs,
            actions,
            allow_actions=False,
            path=f"constraints[{index}]",
            budget=budget,
        )
    for index, expression in enumerate(model["action_constraints"]):
        _boolean_expression(
            expression,
            inputs,
            actions,
            allow_actions=True,
            path=f"action_constraints[{index}]",
            budget=budget,
        )

    identifiers = set()
    kinds = {"obligation", "prohibition", "explicit_permission"}
    for index, norm in enumerate(norms):
        path = f"norms[{index}]"
        _shape(norm, {"id", "source", "kind", "when", "content"}, path)
        identifier = norm["id"]
        _name(identifier, path + ".id")
        if identifier in identifiers:
            _invalid(f"{path}: duplicate norm ID {identifier}")
        identifiers.add(identifier)
        _text(norm["source"], path + ".source")
        kind = norm["kind"]
        if type(kind) is not str:
            _invalid(f"{path}.kind: expected norm kind string")
        if kind not in kinds:
            raise KernelError("UNSUPPORTED", f"{path}.kind: unsupported norm kind {kind!r}")
        _boolean_expression(
            norm["when"],
            inputs,
            actions,
            allow_actions=False,
            path=path + ".when",
            budget=budget,
        )
        _boolean_expression(
            norm["content"],
            inputs,
            actions,
            allow_actions=True,
            path=path + ".content",
            budget=budget,
        )


def validate_enumeration_limits(
    model: dict,
    *,
    max_contexts: int = MAX_CONTEXTS,
    max_action_assignments: int = MAX_ACTION_ASSIGNMENTS,
    max_pairs: int = MAX_CONTEXT_TRACE_PAIRS,
) -> dict:
    """Preflight every Cartesian bound before any context or trace is enumerated."""
    for value, hard, label in (
        (max_contexts, MAX_CONTEXTS, "max_contexts"),
        (max_action_assignments, MAX_ACTION_ASSIGNMENTS, "max_action_assignments"),
        (max_pairs, MAX_CONTEXT_TRACE_PAIRS, "max_pairs"),
    ):
        if type(value) is not int or not 1 <= value <= hard:
            raise KernelError("LIMIT_REACHED", f"{label} must be an integer from 1 to {hard}")

    contexts = 1
    for name in sorted(model["inputs"]):
        domain = model["inputs"][name]
        width = (
            2
            if domain["kind"] == "bool"
            else domain["max"] - domain["min"] + 1
            if domain["kind"] == "int"
            else len(domain["values"])
        )
        contexts *= width
        if contexts > max_contexts:
            raise KernelError(
                "LIMIT_REACHED",
                f"Declared Cartesian scope exceeds {max_contexts} contexts",
            )

    action_assignments = 2 ** len(model["actions"])
    if action_assignments > max_action_assignments:
        raise KernelError(
            "LIMIT_REACHED",
            f"Declared action space {action_assignments} exceeds {max_action_assignments}",
        )
    potential_pairs = contexts * action_assignments
    if potential_pairs > max_pairs:
        raise KernelError(
            "LIMIT_REACHED",
            f"Potential context/trace pairs {potential_pairs} exceed {max_pairs}",
        )
    return {
        "context_count": contexts,
        "action_assignment_count": action_assignments,
        "potential_context_trace_pairs": potential_pairs,
    }


def validate_sha256(value: object, label: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise KernelError(
            "CERTIFICATE_INVALID",
            f"{label} must be 64 lowercase hexadecimal characters",
        )
