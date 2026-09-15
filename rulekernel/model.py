"""Strict JSON syntax and finite type boundary shared by search and checker."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PROFILE = "finite-decisions/1"
VERSION = "0.1.0"
MAX_CONTEXTS = 10_000
MAX_MODEL_BYTES = 1024 * 1024
MAX_CERTIFICATE_BYTES = 8 * 1024 * 1024
INT_MIN, INT_MAX = -(2**63), 2**63 - 1
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


class KernelError(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def canonical_json(obj) -> str:
    try:
        result = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
        result.encode("utf-8")  # Reject lone surrogate codepoints.
        return result
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise KernelError("MODEL_INVALID", f"Not canonical JSON: {exc}") from exc


def digest(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def load_json(path, max_bytes=MAX_MODEL_BYTES):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise KernelError("MODEL_INVALID", f"Duplicate JSON key: {key!r}")
            obj[key] = value
        return obj

    def constant(value):
        raise KernelError("MODEL_INVALID", f"Non-finite JSON number: {value}")

    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise KernelError("LIMIT_REACHED", f"JSON exceeds {max_bytes} bytes")
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=constant)
        canonical_json(parsed)  # Also reject escaped lone surrogates inside strings.
        return parsed
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise KernelError("MODEL_INVALID", f"Invalid JSON: {exc}") from exc


def _invalid(message):
    raise KernelError("MODEL_INVALID", message)


def _shape(obj, fields, path):
    if type(obj) is not dict or any(type(k) is not str for k in obj):
        _invalid(f"{path}: expected object with string keys")
    missing = set(fields) - obj.keys()
    extra = obj.keys() - set(fields)
    if missing:
        _invalid(f"{path}: missing fields {sorted(missing)}")
    if extra:
        raise KernelError("UNSUPPORTED", f"{path}: unknown fields {sorted(extra)}")


def _text(value, path, max_length=8192):
    if type(value) is not str or not value or len(value) > max_length:
        _invalid(f"{path}: expected nonempty string (at most {max_length} characters)")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _invalid(f"{path}: invalid Unicode")


def _name(value, path):
    if type(value) is not str or not _NAME.fullmatch(value):
        _invalid(f"{path}: invalid identifier")


def _integer(value, path):
    if type(value) is not int or not INT_MIN <= value <= INT_MAX:
        _invalid(f"{path}: expected signed 64-bit integer; bool is not integer")


def _domain(domain, path):
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
        for value in values:
            _text(value, path + ".values", 256)
        if len(set(values)) != len(values):
            _invalid(f"{path}: duplicate enum value")
    else:
        raise KernelError("UNSUPPORTED", f"{path}: unsupported type {kind!r}")


def _member(value, domain, path):
    kind = domain["kind"]
    if kind == "bool":
        valid = type(value) is bool
    elif kind == "int":
        valid = (type(value) is int and domain["min"] <= value <= domain["max"])
    else:
        valid = type(value) is str and value in domain["values"]
    if not valid:
        _invalid(f"{path}: value outside declared {kind} type/domain")


def _expr_type(expr, inputs, path, budget, depth=0):
    budget[0] += 1
    if budget[0] > 8192 or depth > 32:
        raise KernelError("LIMIT_REACHED", "Expression exceeds 8192 nodes or depth 32")
    if type(expr) is not dict:
        _invalid(f"{path}: expected expression object")
    if "var" in expr:
        _shape(expr, {"var"}, path)
        name = expr["var"]
        _name(name, path + ".var")
        if name not in inputs:
            _invalid(f"{path}: undeclared input {name}; output references are unavailable")
        domain = inputs[name]
        return (domain["kind"], frozenset(domain["values"]) if domain["kind"] == "enum" else None)
    if "const" in expr:
        _shape(expr, {"const"}, path)
        value = expr["const"]
        if type(value) is bool:
            return ("bool", None)
        if type(value) is int:
            _integer(value, path + ".const")
            return ("int", None)
        if type(value) is str:
            _text(value, path + ".const", 256)
            return ("literal", value)
        _invalid(f"{path}: only bool, int and enum-string constants are supported")
    _shape(expr, {"op", "args"}, path)
    op, args = expr["op"], expr["args"]
    if type(op) is not str or op not in {"eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not"}:
        raise KernelError("UNSUPPORTED", f"{path}: unsupported operator {op!r}")
    if type(args) is not list:
        _invalid(f"{path}: args must be an array")
    needed = 1 if op == "not" else 2
    if (op in {"and", "or"} and not 2 <= len(args) <= 64) or (
            op not in {"and", "or"} and len(args) != needed):
        _invalid(f"{path}: incorrect operator arity")
    types = [_expr_type(arg, inputs, f"{path}.args[{i}]", budget, depth + 1)
             for i, arg in enumerate(args)]
    if op in {"not", "and", "or"}:
        if any(t[0] != "bool" for t in types):
            _invalid(f"{path}: Boolean operands required")
    elif op in {"lt", "le", "gt", "ge"}:
        if any(t[0] != "int" for t in types):
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


def validate_model(model) -> None:
    _shape(model, {"profile", "origin_kind", "title", "inputs", "outputs",
                   "constraints", "facts", "rules"}, "model")
    if model["profile"] != PROFILE or model["origin_kind"] != "authored_core":
        raise KernelError("UNSUPPORTED", "Requires finite-decisions/1 authored_core")
    _text(model["title"], "title", 256)
    if len(canonical_json(model).encode("utf-8")) > MAX_MODEL_BYTES:
        raise KernelError("LIMIT_REACHED", "Model exceeds 1 MiB")
    inputs, outputs = model["inputs"], model["outputs"]
    for mapping, label in ((inputs, "inputs"), (outputs, "outputs")):
        if type(mapping) is not dict or len(mapping) > 32:
            _invalid(f"{label}: expected object with at most 32 entries")
        for name in mapping:
            _name(name, label)
    for name, domain in inputs.items():
        _domain(domain, f"inputs.{name}")
    for name, output in outputs.items():
        _shape(output, {"type", "required"}, f"outputs.{name}")
        _domain(output["type"], f"outputs.{name}.type")
        if type(output["required"]) is not bool:
            _invalid(f"outputs.{name}.required: expected bool")
    for label, limit in (("rules", 128), ("constraints", 128), ("facts", 1024)):
        if type(model[label]) is not list or len(model[label]) > limit:
            _invalid(f"{label}: expected array of at most {limit} entries")
    budget = [0]
    for i, constraint in enumerate(model["constraints"]):
        if _expr_type(constraint, inputs, f"constraints[{i}]", budget)[0] != "bool":
            _invalid(f"constraints[{i}]: Boolean expression required")
    observed = {}
    for i, fact in enumerate(model["facts"]):
        _shape(fact, {"var", "value"}, f"facts[{i}]")
        name, value = fact["var"], fact["value"]
        _name(name, f"facts[{i}].var")
        if name not in inputs:
            _invalid(f"facts[{i}]: undeclared input {name}")
        _member(value, inputs[name], f"facts[{i}].value")
        if name in observed and canonical_json(observed[name]) != canonical_json(value):
            raise KernelError("INPUT_INCONSISTENT", f"Conflicting facts for {name}")
        observed[name] = value
    by_id = {}
    for i, rule in enumerate(model["rules"]):
        path = f"rules[{i}]"
        _shape(rule, {"id", "source", "when", "then", "overrides"}, path)
        rule_id = rule["id"]
        _name(rule_id, path + ".id")
        if rule_id in by_id:
            _invalid(f"{path}: duplicate rule ID {rule_id}")
        by_id[rule_id] = rule
        _text(rule["source"], path + ".source")
        if _expr_type(rule["when"], inputs, path + ".when", budget)[0] != "bool":
            _invalid(f"{path}.when: Boolean expression required")
        conclusion = rule["then"]
        _shape(conclusion, {"output", "value"}, path + ".then")
        _name(conclusion["output"], path + ".then.output")
        if conclusion["output"] not in outputs:
            _invalid(f"{path}.then: undeclared output")
        _member(conclusion["value"], outputs[conclusion["output"]]["type"], path + ".then.value")
        targets = rule["overrides"]
        if type(targets) is not list or len(targets) > 128:
            _invalid(f"{path}.overrides: expected array of at most 128 IDs")
        for target in targets:
            _name(target, path + ".overrides")
        if len(targets) != len(set(targets)) or rule_id in targets:
            _invalid(f"{path}.overrides: duplicate or self target")
    # A topological traversal checks the explicit override graph for cycles.
    incoming = dict.fromkeys(by_id, 0)
    for rule in by_id.values():
        for target in rule["overrides"]:
            if target not in by_id:
                _invalid(f"Unknown override target: {target}")
            incoming[target] += 1
    ready = [key for key, degree in incoming.items() if degree == 0]
    visited = 0
    while ready:
        key = ready.pop()
        visited += 1
        for target in by_id[key]["overrides"]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(by_id):
        raise KernelError("UNSUPPORTED", "Override cycle is outside this semantics profile")


def validate_limit(max_contexts):
    if type(max_contexts) is not int or not 1 <= max_contexts <= MAX_CONTEXTS:
        raise KernelError("LIMIT_REACHED", f"max_contexts must be 1..{MAX_CONTEXTS}")
