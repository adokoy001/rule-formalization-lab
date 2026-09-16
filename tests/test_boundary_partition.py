"""Boundary-equivalence planner contracts and finite examples."""
from pathlib import Path
import unittest

from rulekernel.boundary_partition import iter_cells, plan_partition
from rulekernel.model import INT_MAX, INT_MIN, MAX_CONTEXTS, KernelError, load_json


ROOT = Path(__file__).resolve().parents[1]


def literal(value):
    return {"const": value}


def variable(name):
    return {"var": name}


def operation(name, left, right):
    return {"op": name, "args": [left, right]}


def model(inputs, guards=(), facts=(), constraints=()):
    rules = []
    for index, guard in enumerate(guards):
        rules.append({
            "id": f"R{index}",
            "source": f"Fictional boundary-partition test rule {index}",
            "when": guard,
            "then": {"output": "answer", "value": True},
            "overrides": [],
        })
    return {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": "Boundary partition test",
        "inputs": inputs,
        "outputs": {"answer": {"type": {"kind": "bool"}, "required": True}},
        "constraints": list(constraints),
        "facts": list(facts),
        "rules": rules,
    }


def integer_cells(plan, name="x"):
    return [(cell["min"], cell["max"]) for cell in plan["axes"][name]]


class BoundaryPartitionTests(unittest.TestCase):
    def test_all_integer_operators_place_exact_cut_starts(self):
        expected = {
            "lt": [(-2, -1), (0, 3)],
            "ge": [(-2, -1), (0, 3)],
            "le": [(-2, 0), (1, 3)],
            "gt": [(-2, 0), (1, 3)],
            "eq": [(-2, -1), (0, 0), (1, 3)],
            "ne": [(-2, -1), (0, 0), (1, 3)],
        }
        domain = {"x": {"kind": "int", "min": -2, "max": 3}}
        for operator, cells in expected.items():
            with self.subTest(operator=operator):
                plan = plan_partition(model(
                    domain, [operation(operator, variable("x"), literal(0))]))
                self.assertEqual(integer_cells(plan), cells)

    def test_reversed_constant_operand_reverses_ordered_operator(self):
        expected = {
            "lt": [(-2, 0), (1, 3)],       # 0 < x  == x > 0
            "ge": [(-2, 0), (1, 3)],       # 0 >= x == x <= 0
            "le": [(-2, -1), (0, 3)],      # 0 <= x == x >= 0
            "gt": [(-2, -1), (0, 3)],      # 0 > x  == x < 0
            "eq": [(-2, -1), (0, 0), (1, 3)],
            "ne": [(-2, -1), (0, 0), (1, 3)],
        }
        domain = {"x": {"kind": "int", "min": -2, "max": 3}}
        for operator, cells in expected.items():
            with self.subTest(operator=operator):
                plan = plan_partition(model(
                    domain, [operation(operator, literal(0), variable("x"))]))
                self.assertEqual(integer_cells(plan), cells)

    def test_constraints_and_facts_both_contribute_cuts(self):
        doc = model(
            {"x": {"kind": "int", "min": 0, "max": 9}},
            facts=[{"var": "x", "value": 5}],
            constraints=[operation("lt", variable("x"), literal(8))],
        )
        self.assertEqual(integer_cells(plan_partition(doc)),
                         [(0, 4), (5, 5), (6, 7), (8, 9)])

    def test_out_of_domain_constants_do_not_create_empty_cells(self):
        guards = [
            operation("eq", variable("x"), literal(-10)),
            operation("ne", variable("x"), literal(10)),
            operation("le", variable("x"), literal(-1)),
            operation("ge", variable("x"), literal(4)),
        ]
        doc = model({"x": {"kind": "int", "min": 0, "max": 3}}, guards)
        self.assertEqual(integer_cells(plan_partition(doc)), [(0, 3)])

    def test_signed_64_bit_ends_never_emit_successor_of_int_max(self):
        lower = model(
            {"x": {"kind": "int", "min": INT_MIN, "max": INT_MIN + 2}},
            [operation("eq", variable("x"), literal(INT_MIN))],
        )
        self.assertEqual(integer_cells(plan_partition(lower)),
                         [(INT_MIN, INT_MIN), (INT_MIN + 1, INT_MIN + 2)])

        upper = model(
            {"x": {"kind": "int", "min": INT_MAX - 2, "max": INT_MAX}},
            [operation("eq", variable("x"), literal(INT_MAX)),
             operation("le", variable("x"), literal(INT_MAX))],
        )
        plan = plan_partition(upper)
        self.assertEqual(integer_cells(plan),
                         [(INT_MAX - 2, INT_MAX - 1), (INT_MAX, INT_MAX)])
        serialized_values = [value for cell in plan["axes"]["x"] for value in cell.values()]
        self.assertTrue(all(INT_MIN <= value <= INT_MAX for value in serialized_values))

    def test_integer_variable_comparison_falls_back_all_integer_axes(self):
        inputs = {
            "z": {"kind": "int", "min": 0, "max": 2},
            "x": {"kind": "int", "min": 0, "max": 1},
            "y": {"kind": "int", "min": 3, "max": 4},
        }
        guards = [operation("lt", variable("x"), variable("y")),
                  operation("ge", variable("z"), literal(2))]
        plan = plan_partition(model(inputs, guards))
        self.assertEqual(plan["fallback_reason"], "integer-variable-comparison")
        self.assertFalse(plan["compressed"])
        self.assertEqual(plan["cell_count"], plan["concrete_contexts"])
        self.assertEqual(integer_cells(plan, "x"), [(0, 0), (1, 1)])
        self.assertEqual(integer_cells(plan, "y"), [(3, 3), (4, 4)])
        self.assertEqual(integer_cells(plan, "z"), [(0, 0), (1, 1), (2, 2)])

    def test_boolean_variable_equality_does_not_trigger_integer_fallback(self):
        doc = model(
            {"a": {"kind": "bool"}, "b": {"kind": "bool"}},
            [operation("eq", variable("a"), variable("b"))],
        )
        plan = plan_partition(doc)
        self.assertIsNone(plan["fallback_reason"])
        self.assertEqual(plan["axes"]["a"], [{"value": False}, {"value": True}])

    def test_multiple_axes_weights_representatives_and_first_indexes(self):
        inputs = {
            "y": {"kind": "int", "min": 10, "max": 12},
            "a": {"kind": "bool"},
            "x": {"kind": "int", "min": 0, "max": 3},
        }
        guards = [operation("ge", variable("x"), literal(2)),
                  operation("le", variable("y"), literal(10))]
        plan = plan_partition(model(inputs, guards))
        self.assertEqual(plan["input_order"], ["a", "x", "y"])
        self.assertEqual(plan["concrete_contexts"], 24)
        self.assertEqual(plan["cell_count"], 8)
        self.assertTrue(plan["compressed"])

        cells = list(iter_cells(plan))
        self.assertEqual([cell["cell_index"] for cell in cells], list(range(8)))
        self.assertEqual([cell["first_case_index"] for cell in cells],
                         [0, 1, 6, 7, 12, 13, 18, 19])
        self.assertEqual([cell["weight"] for cell in cells], [2, 4, 2, 4, 2, 4, 2, 4])
        self.assertEqual(sum(cell["weight"] for cell in cells), 24)
        self.assertEqual(cells[1], {
            "cell_index": 1,
            "axes": {
                "a": {"value": False},
                "x": {"min": 0, "max": 1},
                "y": {"min": 11, "max": 12},
            },
            "representative": {"a": False, "x": 0, "y": 11},
            "weight": 4,
            "first_case_index": 1,
        })
        # The first cell covers original indexes 0 and 3, not the contiguous
        # range 0..1; first_case_index and weight are intentionally separate.
        self.assertEqual(cells[0]["first_case_index"], 0)
        self.assertEqual(cells[0]["weight"], 2)

    def test_enum_order_and_empty_input_cartesian_identity(self):
        doc = model({
            "mode": {"kind": "enum", "values": ["third", "first", "second"]},
            "active": {"kind": "bool"},
        })
        plan = plan_partition(doc)
        self.assertEqual(plan["input_order"], ["active", "mode"])
        self.assertEqual(plan["axes"]["mode"],
                         [{"value": "third"}, {"value": "first"}, {"value": "second"}])

        empty = plan_partition(model({}))
        self.assertEqual(empty["concrete_contexts"], 1)
        self.assertEqual(empty["cell_count"], 1)
        self.assertEqual(list(iter_cells(empty)), [{
            "cell_index": 0, "axes": {}, "representative": {},
            "weight": 1, "first_case_index": 0,
        }])

    def test_concrete_context_limit_is_retained_before_compression(self):
        doc = model({"x": {"kind": "int", "min": 0, "max": MAX_CONTEXTS}})
        with self.assertRaises(KernelError) as caught:
            plan_partition(doc)
        self.assertEqual(caught.exception.status, "LIMIT_REACHED")

    def test_club20_boundary_counts_match_design_measurement(self):
        expected = {
            "broken.json": (80, [(0, 15), (16, 17), (18, 19), (20, 24), (25, 25)]),
            "fixed.json": (64, [(0, 15), (16, 17), (18, 24), (25, 25)]),
        }
        for filename, (cell_count, age_cells) in expected.items():
            with self.subTest(filename=filename):
                doc = load_json(ROOT / "examples" / "club20" / filename)
                plan = plan_partition(doc)
                self.assertEqual(plan["format"], "finite-decisions-boundary-partition/1")
                self.assertEqual(plan["concrete_contexts"], 416)
                self.assertEqual(plan["cell_count"], cell_count)
                self.assertEqual(integer_cells(plan, "age"), age_cells)
                self.assertEqual(sum(cell["weight"] for cell in iter_cells(plan)), 416)


if __name__ == "__main__":
    unittest.main()
