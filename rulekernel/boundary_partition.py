"""Deterministic boundary-equivalence partition planning for decision models.

This module only plans cells. It does not evaluate rules and deliberately does
not import the exhaustive engine, so a producer and an independent checker can
derive the same partition from the validated model syntax.
"""
from __future__ import annotations

from itertools import product
from math import prod

from .model import (INT_MAX, MAX_CONTEXTS, KernelError,
                    validate_limit, validate_model)


FORMAT = "finite-decisions-boundary-partition/1"
INTEGER_VARIABLE_COMPARISON = "integer-variable-comparison"
_COMPARISONS = frozenset({"eq", "ne", "lt", "le", "gt", "ge"})
_REVERSED = {
    "eq": "eq",
    "ne": "ne",
    "lt": "gt",
    "le": "ge",
    "gt": "lt",
    "ge": "le",
}


def _cardinality(domain):
    if domain["kind"] == "bool":
        return 2
    if domain["kind"] == "int":
        return domain["max"] - domain["min"] + 1
    return len(domain["values"])


def _integer_variable(expr, inputs):
    if "var" not in expr:
        return None
    name = expr["var"]
    return name if inputs[name]["kind"] == "int" else None


def _integer_constant(expr):
    value = expr.get("const")
    return value if type(value) is int else None


def _successor(value):
    # Constants were already checked as signed 64-bit values by validate_model.
    # Returning no cut at INT_MAX avoids placing INT_MAX + 1 in the plan.
    return None if value == INT_MAX else value + 1


def _cut_starts(operator, constant):
    if operator in {"lt", "ge"}:
        return (constant,)
    if operator in {"le", "gt"}:
        successor = _successor(constant)
        return () if successor is None else (successor,)
    successor = _successor(constant)
    return (constant,) if successor is None else (constant, successor)


def _inspect_expression(expr, inputs, cuts):
    """Collect cut starts and report whether an integer var-var atom occurs."""
    fallback = False
    operator = expr.get("op")
    if operator in _COMPARISONS:
        left, right = expr["args"]
        left_variable = _integer_variable(left, inputs)
        right_variable = _integer_variable(right, inputs)
        left_constant = _integer_constant(left)
        right_constant = _integer_constant(right)

        if left_variable is not None and right_variable is not None:
            fallback = True
        elif left_variable is not None and right_constant is not None:
            for start in _cut_starts(operator, right_constant):
                cuts[left_variable].add(start)
        elif right_variable is not None and left_constant is not None:
            for start in _cut_starts(_REVERSED[operator], left_constant):
                cuts[right_variable].add(start)

    for argument in expr.get("args", ()):
        fallback = _inspect_expression(argument, inputs, cuts) or fallback
    return fallback


def _integer_cells(domain, starts, singleton):
    minimum, maximum = domain["min"], domain["max"]
    if singleton:
        return [{"min": value, "max": value}
                for value in range(minimum, maximum + 1)]

    internal = sorted(start for start in starts if minimum < start <= maximum)
    cell_starts = [minimum, *internal]
    cells = []
    for index, start in enumerate(cell_starts):
        end = cell_starts[index + 1] - 1 if index + 1 < len(cell_starts) else maximum
        cells.append({"min": start, "max": end})
    return cells


def plan_partition(model, max_contexts=MAX_CONTEXTS):
    """Return a canonical, JSON-serializable partition plan for a model.

    The declared concrete Cartesian product remains subject to max_contexts
    even when its boundary partition would contain fewer cells.
    """
    validate_model(model)
    validate_limit(max_contexts)

    inputs = model["inputs"]
    input_order = sorted(inputs)
    concrete_contexts = prod(_cardinality(inputs[name]) for name in input_order)
    if concrete_contexts > max_contexts:
        raise KernelError(
            "LIMIT_REACHED",
            f"Declared Cartesian scope {concrete_contexts} exceeds {max_contexts} contexts",
        )

    cuts = {name: set() for name in input_order if inputs[name]["kind"] == "int"}
    fallback = False
    for constraint in model["constraints"]:
        fallback = _inspect_expression(constraint, inputs, cuts) or fallback
    for rule in model["rules"]:
        fallback = _inspect_expression(rule["when"], inputs, cuts) or fallback
    for fact in model["facts"]:
        name, value = fact["var"], fact["value"]
        if inputs[name]["kind"] == "int":
            for start in _cut_starts("eq", value):
                cuts[name].add(start)

    axes = {}
    for name in input_order:
        domain = inputs[name]
        if domain["kind"] == "int":
            axes[name] = _integer_cells(domain, cuts[name], fallback)
        elif domain["kind"] == "bool":
            axes[name] = [{"value": False}, {"value": True}]
        else:
            axes[name] = [{"value": value} for value in domain["values"]]

    cell_count = prod(len(axes[name]) for name in input_order)
    return {
        "format": FORMAT,
        "concrete_contexts": concrete_contexts,
        "compressed": cell_count < concrete_contexts,
        "fallback_reason": INTEGER_VARIABLE_COMPARISON if fallback else None,
        "input_order": input_order,
        "axes": axes,
        "cell_count": cell_count,
    }


def iter_cells(plan):
    """Yield planned boxes in the original concrete Cartesian order.

    first_case_index is calculated from the representative's mixed-radix
    coordinates. A box can cover non-contiguous concrete indexes when a later
    axis varies, so its weight is kept separate from that index.
    """
    names = plan["input_order"]
    axes = plan["axes"]
    cardinalities = []
    for name in names:
        cells = axes[name]
        if cells and "min" in cells[0]:
            cardinalities.append(cells[-1]["max"] - cells[0]["min"] + 1)
        else:
            cardinalities.append(len(cells))

    strides = [1] * len(names)
    for index in range(len(names) - 2, -1, -1):
        strides[index] = strides[index + 1] * cardinalities[index + 1]

    choices = [range(len(axes[name])) for name in names]
    for cell_index, positions in enumerate(product(*choices)):
        selected = [axes[name][position] for name, position in zip(names, positions)]
        axis_record = {name: dict(cell) for name, cell in zip(names, selected)}
        representative = {}
        weight = 1
        first_case_index = 0
        for axis_index, (name, position, cell) in enumerate(zip(names, positions, selected)):
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
