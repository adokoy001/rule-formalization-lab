"""Independent streaming checker for compact decision evidence.

Only the finite model validator, canonical JSON encoder, and hashing primitive
are shared with the existing kernel. Partition derivation, expression
evaluation, rule resolution, aggregation, JSON Lines parsing, and commitments
are implemented here without importing either compact producer module.
"""
from __future__ import annotations

import hashlib
import json
import re
from itertools import product
from math import prod
from pathlib import Path

from rulekernel.model import (
    INT_MAX,
    MAX_CERTIFICATE_BYTES,
    MAX_CONTEXTS,
    PROFILE,
    KernelError,
    canonical_json,
    digest,
    validate_limit,
    validate_model,
)


FORMAT = "finite-decisions-compact-jsonl/1"
PARTITION_FORMAT = "finite-decisions-boundary-partition/1"
SEMANTICS = "finite-decisions-boundary-cells/1"
ENGINE_VERSION = "0.1.0"
CHECKER_VERSION = "0.1.0"
COMMITMENT_ALGORITHM = "sha256-chain/1"
_CLASS_DOMAIN = b"finite-decisions-compact-jsonl/1:class-records"
_VIRTUAL_DOMAIN = b"finite-decisions-compact-jsonl/1:virtual-cases"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMPARISONS = frozenset({"eq", "ne", "lt", "le", "gt", "ge"})
_REVERSED = {
    "eq": "eq",
    "ne": "ne",
    "lt": "gt",
    "le": "ge",
    "gt": "lt",
    "ge": "le",
}


def _invalid(message):
    raise KernelError("CERTIFICATE_INVALID", message)


def _cardinality(domain):
    if domain["kind"] == "bool":
        return 2
    if domain["kind"] == "int":
        return domain["max"] - domain["min"] + 1
    return len(domain["values"])


def _int_variable(expression, inputs):
    if type(expression) is not dict or "var" not in expression:
        return None
    name = expression["var"]
    return name if inputs[name]["kind"] == "int" else None


def _int_constant(expression):
    if type(expression) is not dict:
        return None
    value = expression.get("const")
    return value if type(value) is int else None


def _cut_starts(operator, constant):
    successor = None if constant == INT_MAX else constant + 1
    if operator in {"lt", "ge"}:
        return (constant,)
    if operator in {"le", "gt"}:
        return () if successor is None else (successor,)
    return (constant,) if successor is None else (constant, successor)


def _scan_expression(expression, inputs, cuts):
    fallback = False
    operator = expression.get("op")
    if operator in _COMPARISONS:
        left, right = expression["args"]
        left_variable = _int_variable(left, inputs)
        right_variable = _int_variable(right, inputs)
        left_constant = _int_constant(left)
        right_constant = _int_constant(right)
        if left_variable is not None and right_variable is not None:
            fallback = True
        elif left_variable is not None and right_constant is not None:
            cuts[left_variable].update(_cut_starts(operator, right_constant))
        elif right_variable is not None and left_constant is not None:
            cuts[right_variable].update(
                _cut_starts(_REVERSED[operator], left_constant)
            )
    for argument in expression.get("args", ()):
        fallback = _scan_expression(argument, inputs, cuts) or fallback
    return fallback


def _partition_plan(model, max_contexts):
    validate_model(model)
    validate_limit(max_contexts)
    inputs = model["inputs"]
    names = sorted(inputs)
    concrete_contexts = prod(_cardinality(inputs[name]) for name in names)
    if concrete_contexts > max_contexts:
        raise KernelError(
            "LIMIT_REACHED",
            f"Declared Cartesian scope {concrete_contexts} exceeds {max_contexts} contexts",
        )

    cuts = {name: set() for name in names if inputs[name]["kind"] == "int"}
    fallback = False
    for condition in model["constraints"]:
        fallback = _scan_expression(condition, inputs, cuts) or fallback
    for rule in model["rules"]:
        fallback = _scan_expression(rule["when"], inputs, cuts) or fallback
    for fact in model["facts"]:
        name = fact["var"]
        if inputs[name]["kind"] == "int":
            cuts[name].update(_cut_starts("eq", fact["value"]))

    axes = {}
    for name in names:
        domain = inputs[name]
        if domain["kind"] == "bool":
            axes[name] = [{"value": False}, {"value": True}]
        elif domain["kind"] == "enum":
            axes[name] = [{"value": value} for value in domain["values"]]
        elif fallback:
            axes[name] = [
                {"min": value, "max": value}
                for value in range(domain["min"], domain["max"] + 1)
            ]
        else:
            internal = sorted(
                cut for cut in cuts[name]
                if domain["min"] < cut <= domain["max"]
            )
            starts = [domain["min"], *internal]
            axes[name] = [
                {
                    "min": start,
                    "max": (
                        starts[index + 1] - 1
                        if index + 1 < len(starts)
                        else domain["max"]
                    ),
                }
                for index, start in enumerate(starts)
            ]
    cell_count = prod(len(axes[name]) for name in names)
    return {
        "format": PARTITION_FORMAT,
        "concrete_contexts": concrete_contexts,
        "compressed": cell_count < concrete_contexts,
        "fallback_reason": "integer-variable-comparison" if fallback else None,
        "input_order": names,
        "axes": axes,
        "cell_count": cell_count,
    }


def _cells(plan):
    names = plan["input_order"]
    axes = plan["axes"]
    cardinalities = []
    for name in names:
        declared = axes[name]
        if declared and "min" in declared[0]:
            cardinalities.append(declared[-1]["max"] - declared[0]["min"] + 1)
        else:
            cardinalities.append(len(declared))
    strides = [1] * len(names)
    for index in range(len(names) - 2, -1, -1):
        strides[index] = strides[index + 1] * cardinalities[index + 1]

    positions_by_axis = [range(len(axes[name])) for name in names]
    for cell_index, positions in enumerate(product(*positions_by_axis)):
        selected = [axes[name][position] for name, position in zip(names, positions)]
        axis_record = {}
        representative = {}
        weight = 1
        first_case_index = 0
        for axis_index, (name, position, cell) in enumerate(
            zip(names, positions, selected)
        ):
            axis_record[name] = dict(cell)
            if "min" in cell:
                representative[name] = cell["min"]
                weight *= cell["max"] - cell["min"] + 1
                offset = cell["min"] - axes[name][0]["min"]
            else:
                representative[name] = cell["value"]
                offset = position
            first_case_index += offset * strides[axis_index]
        yield {
            "cell_index": cell_index,
            "axes": axis_record,
            "representative": representative,
            "weight": weight,
            "first_case_index": first_case_index,
        }


def _domain_values(domain):
    if domain["kind"] == "bool":
        return (False, True)
    if domain["kind"] == "int":
        return range(domain["min"], domain["max"] + 1)
    return domain["values"]


def _contexts(inputs):
    names = sorted(inputs)
    assignment = {}

    def visit(position):
        if position == len(names):
            yield dict(assignment)
            return
        name = names[position]
        for value in _domain_values(inputs[name]):
            assignment[name] = value
            yield from visit(position + 1)
        del assignment[name]

    yield from visit(0)


def _evaluate(expression, assignment):
    if "const" in expression:
        return expression["const"]
    if "var" in expression:
        return assignment[expression["var"]]
    operands = [_evaluate(argument, assignment) for argument in expression["args"]]
    operator = expression["op"]
    if operator == "not":
        return not operands[0]
    if operator == "and":
        return all(operands)
    if operator == "or":
        return any(operands)
    left, right = operands
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
    raise KernelError("UNSUPPORTED", "Unknown operator in a validated model")


def _rule_results(rules, assignment):
    active = {rule["id"]: _evaluate(rule["when"], assignment) for rule in rules}
    blockers = {rule["id"]: [] for rule in rules}
    by_id = {rule["id"]: rule for rule in rules}
    for rule in rules:
        for target in rule["overrides"]:
            blockers[target].append(rule["id"])

    waiting = {rule_id: len(items) for rule_id, items in blockers.items()}
    ready = [rule_id for rule_id, count in waiting.items() if count == 0]
    effective = {}
    while ready:
        rule_id = ready.pop()
        effective[rule_id] = active[rule_id] and not any(
            effective[other] for other in blockers[rule_id]
        )
        for target in by_id[rule_id]["overrides"]:
            waiting[target] -= 1
            if waiting[target] == 0:
                ready.append(target)
    if len(effective) != len(rules):
        raise KernelError("UNSUPPORTED", "Override cycle in checked model")
    return (
        sorted(rule_id for rule_id, value in active.items() if value),
        sorted(rule_id for rule_id, value in effective.items() if value),
    )


def _case(model, assignment, index):
    admitted = (
        all(
            assignment[fact["var"]] == fact["value"]
            for fact in model["facts"]
        )
        and all(
            _evaluate(condition, assignment)
            for condition in model["constraints"]
        )
    )
    enabled, effective = (
        _rule_results(model["rules"], assignment)
        if admitted
        else ([], [])
    )
    return {
        "index": index,
        "input": assignment,
        "admitted": admitted,
        "enabled": enabled,
        "effective": effective,
    }


def _queries(model):
    result = []
    for output in sorted(model["outputs"]):
        kinds = ["conflict"]
        if model["outputs"][output]["required"]:
            kinds.append("gap")
        for kind in kinds:
            result.append({
                "kind": kind,
                "output": output,
                "count": 0,
                "witness": None,
            })
    return result


def _accumulate_queries(queries, model, case, weight):
    if not case["admitted"]:
        return
    rules = {rule["id"]: rule for rule in model["rules"]}
    for query in queries:
        relevant = [
            rule_id for rule_id in case["effective"]
            if rules[rule_id]["then"]["output"] == query["output"]
        ]
        values_by_json = {}
        for rule_id in relevant:
            value = rules[rule_id]["then"]["value"]
            values_by_json[canonical_json(value)] = value
        values = [values_by_json[key] for key in sorted(values_by_json)]
        found = (
            len(values) > 1
            if query["kind"] == "conflict"
            else len(values) == 0
        )
        if found:
            query["count"] += weight
            if query["witness"] is None:
                query["witness"] = {
                    "case_index": case["index"],
                    "input": dict(case["input"]),
                    "rule_ids": relevant,
                    "values": values,
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


def _virtual_replay(model):
    """Replay concrete cases for both the commitment and a partition cross-check."""
    state = _chain_start(_VIRTUAL_DOMAIN)
    admitted_contexts = 0
    queries = _queries(model)
    for index, assignment in enumerate(_contexts(model["inputs"])):
        case = _case(model, assignment, index)
        payload = canonical_json(case).encode("utf-8")
        state = _chain_update(state, _VIRTUAL_DOMAIN, index, payload)
        if case["admitted"]:
            admitted_contexts += 1
            _accumulate_queries(queries, model, case, 1)
    return state.hex(), admitted_contexts, queries


def _json_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _invalid(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _json_constant(value):
    _invalid(f"Non-finite JSON number: {value}")


class _RecordReader:
    def __init__(self, path):
        self.path = Path(path)
        self.stream = self.path.open("rb")
        self.byte_count = 0
        self.record_count = 0
        self.hasher = hashlib.sha256()

    def close(self):
        self.stream.close()

    def read(self):
        line = self.stream.readline(MAX_CERTIFICATE_BYTES + 2)
        if not line:
            return None
        self.byte_count += len(line)
        if self.byte_count > MAX_CERTIFICATE_BYTES:
            raise KernelError("LIMIT_REACHED", "Compact certificate exceeds 8 MiB")
        if len(line) > MAX_CERTIFICATE_BYTES + 1:
            _invalid("One JSON Lines record exceeds the byte limit")
        self.hasher.update(line)
        if not line.endswith(b"\n"):
            _invalid("Every compact certificate record must end with LF")
        if b"\r" in line:
            _invalid("CR bytes are forbidden in canonical JSON Lines")
        payload = line[:-1]
        if not payload:
            _invalid("Blank JSON Lines records are forbidden")
        try:
            text = payload.decode("utf-8")
            value = json.loads(
                text,
                object_pairs_hook=_json_pairs,
                parse_constant=_json_constant,
            )
            canonical = canonical_json(value).encode("utf-8")
        except KernelError as exc:
            if exc.status == "CERTIFICATE_INVALID":
                raise
            _invalid("Record is not canonical UTF-8 JSON")
        except (UnicodeError, ValueError, RecursionError):
            _invalid("Record is not valid UTF-8 JSON")
        if canonical != payload:
            _invalid("Every record must use canonical JSON encoding")
        self.record_count += 1
        return value, payload

    @property
    def certificate_hash(self):
        return self.hasher.hexdigest()


def _require(reader, label):
    item = reader.read()
    if item is None:
        _invalid(f"Compact certificate ended before {label}")
    return item


def verify_path(
    model,
    certificate_path,
    *,
    expected_certificate_sha256=None,
    max_contexts=MAX_CONTEXTS,
):
    """Stream and independently reconstruct every compact evidence record."""
    plan = _partition_plan(model, max_contexts)
    if expected_certificate_sha256 is not None and (
        type(expected_certificate_sha256) is not str
        or not _SHA256.fullmatch(expected_certificate_sha256)
    ):
        _invalid("Expected certificate SHA-256 must be 64 lowercase hex characters")

    reader = _RecordReader(certificate_path)
    try:
        header, header_payload = _require(reader, "header")
        expected_header = _header(model, plan)
        if header != expected_header:
            _invalid("Header does not match the model and independent partition")

        class_state = _chain_start(_CLASS_DOMAIN)
        class_state = _chain_update(
            class_state, _CLASS_DOMAIN, 0, header_payload,
        )
        queries = _queries(model)
        admitted_contexts = 0

        for cell in _cells(plan):
            supplied, payload = _require(
                reader, f"cell record {cell['cell_index']}"
            )
            case = _case(
                model,
                cell["representative"],
                cell["first_case_index"],
            )
            expected = {
                "record_type": "cell",
                **cell,
                "admitted": case["admitted"],
                "enabled": case["enabled"],
                "effective": case["effective"],
            }
            if supplied != expected:
                _invalid(
                    f"Cell record {cell['cell_index']} does not match independent replay"
                )
            class_state = _chain_update(
                class_state,
                _CLASS_DOMAIN,
                cell["cell_index"] + 1,
                payload,
            )
            if case["admitted"]:
                admitted_contexts += cell["weight"]
                _accumulate_queries(
                    queries, model, case, cell["weight"]
                )

        if admitted_contexts == 0:
            raise KernelError(
                "BASE_INCONSISTENT",
                "No context satisfies the facts and background constraints",
            )

        (
            virtual_commitment,
            concrete_admitted_contexts,
            concrete_queries,
        ) = _virtual_replay(model)
        if (
            admitted_contexts != concrete_admitted_contexts
            or queries != concrete_queries
        ):
            _invalid(
                "Boundary-cell aggregates or witnesses differ from concrete replay"
            )
        supplied_trailer, _ = _require(reader, "trailer")
        expected_trailer = _trailer(
            plan,
            admitted_contexts,
            queries,
            class_state.hex(),
            virtual_commitment,
        )
        if supplied_trailer != expected_trailer:
            _invalid("Trailer, aggregate, witness, or commitment does not match")
        if reader.read() is not None:
            _invalid("Extra records follow the trailer")

        certificate_hash = reader.certificate_hash
        if (
            expected_certificate_sha256 is not None
            and certificate_hash != expected_certificate_sha256
        ):
            _invalid("Compact certificate SHA-256 does not match the external anchor")
        verified_queries = [
            {
                **query,
                "status": (
                    "WITNESS_VERIFIED"
                    if query["count"]
                    else "NO_WITNESS_IN_SCOPE_VERIFIED"
                ),
            }
            for query in queries
        ]
        return {
            "status": "VERIFIED",
            "checker_version": CHECKER_VERSION,
            "model_hash": expected_header["model_hash"],
            "certificate_hash": certificate_hash,
            "certificate_bytes": reader.byte_count,
            "format": FORMAT,
            "total_contexts": plan["concrete_contexts"],
            "admitted_contexts": admitted_contexts,
            "cell_count": plan["cell_count"],
            "compressed": plan["compressed"],
            "fallback_reason": plan["fallback_reason"],
            "class_commitment": class_state.hex(),
            "virtual_case_commitment": virtual_commitment,
            "queries": verified_queries,
        }
    finally:
        reader.close()
