"""Small finite oracles and deliberate search bugs, beyond example snapshots."""
import ast
from copy import deepcopy
from itertools import product
from pathlib import Path
import unittest
from unittest.mock import patch

from rulekernel import engine
from rulekernel.checker import verify
from rulekernel.model import KernelError


def model(inputs=None):
    return {"profile": "finite-decisions/1", "origin_kind": "authored_core",
            "title": "有限組合せの独立正解", "inputs": inputs or {},
            "outputs": {"answer": {"type": {"kind": "bool"}, "required": True}},
            "constraints": [], "facts": [], "rules": []}


def rule(name, guard=True, value=True, overrides=None):
    return {"id": name, "source": "テスト用の架空規則 " + name,
            "when": guard if type(guard) is dict else {"const": guard},
            "then": {"output": "answer", "value": value},
            "overrides": overrides or []}


class ExhaustiveOracles(unittest.TestCase):
    def test_512_dag_guard_and_conclusion_combinations(self):
        # All 8 forward-edge DAGs, all 8 guard patterns, all 8 bool decisions.
        # The three-node truth formula is an oracle independent of either walk.
        for cb, ba, ca in product((False, True), repeat=3):
            for a, b, c in product((False, True), repeat=3):
                expected_c = c
                expected_b = b and not (cb and expected_c)
                expected_a = a and not (ba and expected_b) and not (ca and expected_c)
                expected_ids = [key for key, yes in
                                (("A", expected_a), ("B", expected_b), ("C", expected_c)) if yes]
                for va, vb, vc in product((False, True), repeat=3):
                    with self.subTest(edges=(cb, ba, ca), guards=(a, b, c), values=(va, vb, vc)):
                        doc = model()
                        doc["rules"] = [
                            rule("A", a, va),
                            rule("B", b, vb, ["A"] if ba else []),
                            rule("C", c, vc, (["B"] if cb else []) + (["A"] if ca else [])),
                        ]
                        certificate = engine.analyze(doc)
                        self.assertEqual(certificate["cases"][0]["effective"], expected_ids)
                        active_values = {value for key, value in zip(("A", "B", "C"), (va, vb, vc))
                                         if key in expected_ids}
                        result = verify(doc, certificate)
                        self.assertEqual(result["queries"][0]["count"], int(len(active_values) > 1))
                        self.assertEqual(result["queries"][1]["count"], int(not active_values))

    def test_boolean_truth_tables(self):
        expressions = {
            "and": ({"op": "and", "args": [{"var": "a"}, {"var": "b"}]}, [False, False, False, True]),
            "or": ({"op": "or", "args": [{"var": "a"}, {"var": "b"}]}, [False, True, True, True]),
            "not": ({"op": "not", "args": [{"var": "a"}]}, [True, True, False, False]),
            "eq": ({"op": "eq", "args": [{"var": "a"}, {"var": "b"}]}, [True, False, False, True]),
            "ne": ({"op": "ne", "args": [{"var": "a"}, {"var": "b"}]}, [False, True, True, False]),
        }
        for label, (expression, truth_table) in expressions.items():
            with self.subTest(operator=label):
                doc = model({"a": {"kind": "bool"}, "b": {"kind": "bool"}})
                doc["rules"] = [rule("R", expression)]
                evidence = engine.analyze(doc)
                self.assertEqual([bool(row["effective"]) for row in evidence["cases"]], truth_table)
                verify(doc, evidence)

    def test_integer_comparison_boundaries(self):
        expected = {"lt": [True, False, False], "le": [True, True, False],
                    "gt": [False, False, True], "ge": [False, True, True],
                    "eq": [False, True, False], "ne": [True, False, True]}
        for operator, table in expected.items():
            with self.subTest(operator=operator):
                doc = model({"n": {"kind": "int", "min": -1, "max": 1}})
                doc["rules"] = [rule("R", {"op": operator, "args": [{"var": "n"}, {"const": 0}]})]
                evidence = engine.analyze(doc)
                self.assertEqual([bool(row["effective"]) for row in evidence["cases"]], table)
                verify(doc, evidence)

    def test_enum_declaration_order_and_equality(self):
        doc = model({"member": {"kind": "enum", "values": ["guest", "student", "member"]}})
        doc["rules"] = [rule("R", {"op": "eq", "args": [{"var": "member"}, {"const": "student"}]})]
        evidence = engine.analyze(doc)
        self.assertEqual([row["input"]["member"] for row in evidence["cases"]],
                         ["guest", "student", "member"])
        self.assertEqual([bool(row["effective"]) for row in evidence["cases"]], [False, True, False])
        verify(doc, evidence)

    def test_checker_rejects_search_boundary_mutation(self):
        doc = model({"age": {"kind": "int", "min": 17, "max": 19}})
        doc["rules"] = [rule("R", {"op": "ge", "args": [{"var": "age"}, {"const": 18}]})]
        original = engine._evaluate

        def mutated(expression, context):
            if expression.get("op") == "ge":
                expression = {**expression, "op": "gt"}
            return original(expression, context)

        with patch.object(engine, "_evaluate", mutated):
            faulty = engine.analyze(doc)
        with self.assertRaises(KernelError) as raised:
            verify(doc, faulty)
        self.assertEqual(raised.exception.status, "CERTIFICATE_INVALID")

    def test_checker_rejects_search_omitting_unknown_true(self):
        doc = model({"unknown": {"kind": "bool"}})
        doc["rules"] = [rule("R", {"var": "unknown"})]
        with patch.object(engine, "_domain_values", return_value=(False,)):
            faulty = engine.analyze(doc)
        with self.assertRaises(KernelError) as raised:
            verify(doc, faulty)
        self.assertEqual(raised.exception.status, "CERTIFICATE_INVALID")

    def test_runtime_imports_are_standard_library_or_local(self):
        import sys
        package = Path(__file__).resolve().parents[1] / "rulekernel"
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [node.module.split(".")[0]]
                else:
                    continue
                self.assertTrue(set(modules) <= sys.stdlib_module_names, (path, modules))


if __name__ == "__main__":
    unittest.main()
