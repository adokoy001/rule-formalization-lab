"""Revision semantics, independent small oracles and adversarial evidence."""
import ast
from copy import deepcopy
from itertools import product
from pathlib import Path
import unittest
from unittest.mock import patch

from rulekernel import diff, diff_checker
from rulekernel.diff import analyze_diff
from rulekernel.diff_checker import verify_diff
from rulekernel.engine import analyze
from rulekernel.model import KernelError, MAX_CERTIFICATE_BYTES, canonical_json, digest


def model(inputs=None, required=True):
    return {"profile": "finite-decisions/1", "origin_kind": "authored_core",
            "title": "改定差分の架空モデル", "inputs": {} if inputs is None else inputs,
            "outputs": {"answer": {"type": {"kind": "bool"}, "required": required}},
            "constraints": [], "facts": [], "rules": []}


def rule(name, value=True, when=None, overrides=None):
    return {"id": name, "source": "架空の規則 " + name,
            "when": {"const": True} if when is None else when,
            "then": {"output": "answer", "value": value},
            "overrides": [] if overrides is None else overrides}


def query(certificate, kind, output="answer"):
    return next(row for row in certificate["queries"]
                if row["kind"] == kind and row["output"] == output)


class DiffTests(unittest.TestCase):
    def assert_status(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.status, status)
        return raised.exception

    def checked(self, left, right, **kwargs):
        evidence = analyze_diff(left, right, **kwargs)
        verified = verify_diff(left, right, evidence, **kwargs)
        self.assertEqual(verified["status"], "VERIFIED")
        self.assertEqual(verified["left_model_hash"], digest(left))
        self.assertEqual(verified["right_model_hash"], digest(right))
        self.assertEqual(verified["certificate_hash"], digest(evidence))
        for actual, expected in zip(verified["queries"], evidence["queries"]):
            self.assertEqual(actual, {**expected, "status": "WITNESS_VERIFIED" if expected["count"]
                                     else "NO_WITNESS_IN_SCOPE_VERIFIED"})
        return evidence

    def test_threshold_change_has_first_witness_and_reverse_gap_resolution(self):
        left = model({"age": {"kind": "int", "min": 17, "max": 20}})
        left["rules"] = [rule("R", when={"op": "ge", "args": [{"var": "age"}, {"const": 18}]})]
        right = deepcopy(left)
        right["rules"][0]["when"]["args"][1]["const"] = 20
        evidence = self.checked(left, right)
        changed = query(evidence, "semantic_change")
        self.assertEqual(changed["count"], 2)
        self.assertEqual(changed["witness"]["case_index"], 1)
        self.assertEqual(changed["witness"]["input"], {"age": 18})
        self.assertEqual(query(evidence, "gap_introduced")["count"], 2)
        self.assertEqual(query(evidence, "explanation_only")["count"], 0)
        reverse = self.checked(right, left)
        self.assertEqual(query(reverse, "gap_resolved")["count"], 2)

    def test_rule_rename_changes_explanation_only(self):
        left = model()
        left["rules"] = [rule("Original")]
        right = deepcopy(left)
        right["rules"][0]["id"] = "Renamed"
        evidence = self.checked(left, right)
        self.assertEqual(query(evidence, "semantic_change")["count"], 0)
        changed = query(evidence, "explanation_only")
        self.assertEqual(changed["count"], 1)
        self.assertEqual(changed["witness"]["left"]["rule_ids"], ["Original"])
        self.assertEqual(changed["witness"]["right"]["rule_ids"], ["Renamed"])

    def test_rule_array_and_override_order_do_not_change_results(self):
        left = model({"x": {"kind": "bool"}})
        left["rules"] = [rule("A", False), rule("B"), rule("C", overrides=["A", "B"])]
        right = deepcopy(left)
        right["rules"][2]["overrides"].reverse()
        right["rules"].reverse()
        evidence = self.checked(left, right)
        self.assertNotEqual(evidence["left_model_hash"], evidence["right_model_hash"])
        self.assertTrue(all(row["count"] == 0 for row in evidence["queries"]))
        self.assertTrue(all(row["left"] == row["right"] for row in evidence["cases"]))

    def test_source_and_title_are_hash_bound_but_not_semantic_or_id_changes(self):
        left = model()
        left["rules"] = [rule("A")]
        right = deepcopy(left)
        right["rules"][0]["source"] = "同じIDの別の架空原文"
        right["title"] = "別の題名"
        evidence = self.checked(left, right)
        self.assertNotEqual(evidence["left_model_hash"], evidence["right_model_hash"])
        self.assertTrue(all(row["count"] == 0 for row in evidence["queries"]))

    def test_duplicate_same_value_adds_only_an_explanation(self):
        left = model()
        left["rules"] = [rule("A", False)]
        right = deepcopy(left)
        right["rules"].append(rule("B", False))
        evidence = self.checked(left, right)
        self.assertEqual(query(evidence, "semantic_change")["count"], 0)
        self.assertEqual(query(evidence, "conflict_introduced")["count"], 0)
        self.assertEqual(query(evidence, "explanation_only")["count"], 1)
        self.assertEqual(evidence["cases"][0]["right"]["outputs"]["answer"]["values"], [False])

    def test_all_boolean_output_state_transitions_with_optional_and_required(self):
        possibilities = [[], [False], [True], [False, True]]
        for required, before, after in product((False, True), possibilities, possibilities):
            with self.subTest(required=required, before=before, after=after):
                left, right = model(required=required), model(required=required)
                left["rules"] = [rule("Old" + str(i), value) for i, value in enumerate(before)]
                right["rules"] = [rule("New" + str(i), value) for i, value in enumerate(after)]
                evidence = self.checked(left, right)
                self.assertEqual(query(evidence, "semantic_change")["count"], int(before != after))
                self.assertEqual(query(evidence, "explanation_only")["count"], int(before == after and bool(before)))
                self.assertEqual(query(evidence, "conflict_introduced")["count"], int(len(before) < 2 and len(after) == 2))
                self.assertEqual(query(evidence, "conflict_resolved")["count"], int(len(before) == 2 and len(after) < 2))
                if required:
                    self.assertEqual(query(evidence, "gap_introduced")["count"], int(bool(before) and not after))
                    self.assertEqual(query(evidence, "gap_resolved")["count"], int(not before and bool(after)))
                else:
                    self.assertFalse(any(row["kind"].startswith("gap_") for row in evidence["queries"]))

    def test_conflicting_value_set_change_without_state_change(self):
        left = model()
        left["outputs"]["answer"]["type"] = {"kind": "enum", "values": ["a", "b", "c"]}
        left["rules"] = [rule("A", "a"), rule("B", "b")]
        right = deepcopy(left)
        right["rules"][1]["then"]["value"] = "c"
        evidence = self.checked(left, right)
        self.assertEqual(query(evidence, "semantic_change")["count"], 1)
        self.assertEqual(query(evidence, "conflict_introduced")["count"], 0)
        self.assertEqual(query(evidence, "conflict_resolved")["count"], 0)

    def test_exception_addition_and_removal_restore_original_rule(self):
        left = model()
        left["rules"] = [rule("A", False), rule("B", True, overrides=["A"])]
        right = deepcopy(left)
        right["rules"].append(rule("C", True, overrides=["B"]))
        evidence = self.checked(left, right)
        self.assertEqual(evidence["cases"][0]["left"]["outputs"]["answer"]["rule_ids"], ["B"])
        self.assertEqual(evidence["cases"][0]["right"]["outputs"]["answer"]["rule_ids"], ["A", "C"])
        self.assertEqual(query(evidence, "conflict_introduced")["count"], 1)
        self.assertEqual(query(self.checked(right, left), "conflict_resolved")["count"], 1)

    def test_512_small_override_models_against_direct_boolean_oracle(self):
        left = model()
        for cb, ba, ca, a, b, c, va, vb, vc in product((False, True), repeat=9):
            right = model()
            right["rules"] = [
                rule("A", va, {"const": a}),
                rule("B", vb, {"const": b}, ["A"] if ba else []),
                rule("C", vc, {"const": c}, (["B"] if cb else []) + (["A"] if ca else []))]
            effective_c = c
            effective_b = b and not (cb and effective_c)
            effective_a = a and not ((ba and effective_b) or (ca and effective_c))
            ids = [name for name, yes in (("A", effective_a), ("B", effective_b), ("C", effective_c)) if yes]
            expected_values = sorted({value for name, value in zip(("A", "B", "C"), (va, vb, vc)) if name in ids})
            evidence = self.checked(left, right)
            snapshot = evidence["cases"][0]["right"]["outputs"]["answer"]
            self.assertEqual(snapshot["rule_ids"], ids)
            self.assertEqual(snapshot["values"], expected_values)
            self.assertEqual(query(evidence, "semantic_change")["count"], int(bool(ids)))

    def test_partial_facts_expand_unknowns_and_keep_excluded_contexts(self):
        left = model({"a": {"kind": "bool"}, "b": {"kind": "bool"}})
        left["facts"] = [{"var": "a", "value": True}]
        right = deepcopy(left)
        right["rules"] = [rule("R", when={"var": "b"})]
        evidence = self.checked(left, right)
        self.assertEqual((evidence["total_contexts"], evidence["common_admitted_contexts"]), (4, 2))
        self.assertEqual([row["left"]["admitted"] for row in evidence["cases"]], [False, False, True, True])
        self.assertEqual(evidence["cases"][0]["left"]["outputs"], {})
        self.assertEqual(query(evidence, "semantic_change")["count"], 1)

    def test_domain_order_is_names_then_declared_enum_then_bool_and_integer(self):
        left = model({"z": {"kind": "bool"}, "a": {"kind": "enum", "values": ["second", "first"]},
                      "m": {"kind": "int", "min": -1, "max": 0}})
        evidence = self.checked(left, deepcopy(left))
        self.assertEqual([tuple(row["input"][name] for name in ("a", "m", "z")) for row in evidence["cases"]],
                         [("second", -1, False), ("second", -1, True), ("second", 0, False), ("second", 0, True),
                          ("first", -1, False), ("first", -1, True), ("first", 0, False), ("first", 0, True)])

    def test_boolean_and_comparison_expression_truth_tables(self):
        boolean_tables = {
            "and": [False, False, False, True], "or": [False, True, True, True],
            "eq": [True, False, False, True], "ne": [False, True, True, False]}
        for op, expected in boolean_tables.items():
            left = model({"a": {"kind": "bool"}, "b": {"kind": "bool"}})
            right = deepcopy(left)
            right["rules"] = [rule("R", when={"op": op, "args": [{"var": "a"}, {"var": "b"}]})]
            evidence = self.checked(left, right)
            self.assertEqual([bool(row["right"]["outputs"]["answer"]["values"]) for row in evidence["cases"]], expected)
        integer_tables = {"eq": [False, True, False], "ne": [True, False, True],
                          "lt": [True, False, False], "le": [True, True, False],
                          "gt": [False, False, True], "ge": [False, True, True]}
        for op, expected in integer_tables.items():
            left = model({"n": {"kind": "int", "min": -1, "max": 1}})
            right = deepcopy(left)
            right["rules"] = [rule("R", when={"op": op, "args": [{"var": "n"}, {"const": 0}]})]
            evidence = self.checked(left, right)
            self.assertEqual([bool(row["right"]["outputs"]["answer"]["values"]) for row in evidence["cases"]], expected)

    def test_nested_expression_and_enum_literal(self):
        left = model({"member": {"kind": "enum", "values": ["guest", "member"]}, "student": {"kind": "bool"}})
        right = deepcopy(left)
        right["rules"] = [rule("R", when={"op": "not", "args": [{"op": "or", "args": [
            {"var": "student"}, {"op": "eq", "args": [{"var": "member"}, {"const": "guest"}]}]}]})]
        evidence = self.checked(left, right)
        self.assertEqual([row["right"]["outputs"]["answer"]["state"] for row in evidence["cases"]],
                         ["absent", "absent", "defined", "absent"])

    def test_values_are_sorted_by_canonical_json_not_numeric_order(self):
        left = model()
        left["outputs"]["answer"]["type"] = {"kind": "int", "min": -2, "max": 10}
        right = deepcopy(left)
        right["rules"] = [rule("C", 2), rule("A", -2), rule("B", 10)]
        evidence = self.checked(left, right)
        self.assertEqual(evidence["cases"][0]["right"]["outputs"]["answer"]["values"], [-2, 10, 2])

    def test_unilateral_admission_is_scope_change_and_not_a_gap(self):
        left = model({"student": {"kind": "bool"}})
        left["facts"] = [{"var": "student", "value": False}]
        right = deepcopy(left)
        right["facts"] = []
        right["rules"] = [rule("R", when={"var": "student"})]
        evidence = self.checked(left, right)
        self.assertEqual((evidence["left_admitted_contexts"], evidence["right_admitted_contexts"],
                          evidence["common_admitted_contexts"]), (1, 2, 1))
        scope = query(evidence, "scope_change", None)
        self.assertEqual(scope["count"], 1)
        self.assertEqual(scope["witness"], {"case_index": 1, "input": {"student": True}, "left": False, "right": True})
        self.assertTrue(all(row["count"] == 0 for row in evidence["queries"][1:]))
        reverse = self.checked(right, left)
        self.assertEqual(query(reverse, "scope_change", None)["witness"]["left"], True)

    def test_disjoint_nonempty_backgrounds_report_scope_without_equivalence(self):
        left = model({"x": {"kind": "bool"}})
        left["constraints"] = [{"op": "not", "args": [{"var": "x"}]}]
        left["rules"] = [rule("R", False)]
        right = deepcopy(left)
        right["constraints"] = [{"var": "x"}]
        right["rules"] = [rule("R", True)]
        evidence = self.checked(left, right)
        self.assertEqual(evidence["common_admitted_contexts"], 0)
        self.assertEqual(query(evidence, "scope_change", None)["count"], 2)
        self.assertEqual(query(evidence, "semantic_change")["count"], 0)
        self.assertEqual(len(evidence["cases"]), 2)

    def test_empty_inputs_and_outputs_still_have_one_context_and_scope_query(self):
        left = model()
        left["outputs"] = {}
        evidence = self.checked(left, deepcopy(left))
        self.assertEqual(evidence["total_contexts"], 1)
        self.assertEqual(evidence["cases"], [{"index": 0, "input": {},
                         "left": {"admitted": True, "outputs": {}}, "right": {"admitted": True, "outputs": {}}}])
        self.assertEqual(evidence["queries"], [{"kind": "scope_change", "output": None, "count": 0, "witness": None}])

    def test_output_names_are_sorted_and_each_output_has_its_own_queries(self):
        left = model()
        left["outputs"] = {"z": {"type": {"kind": "bool"}, "required": False},
                           "a": {"type": {"kind": "bool"}, "required": True}}
        right = deepcopy(left)
        item = rule("R")
        item["then"]["output"] = "z"
        right["rules"] = [item]
        evidence = self.checked(left, right)
        self.assertEqual([row["output"] for row in evidence["queries"]], [None] + ["a"] * 6 + ["z"] * 4)
        self.assertEqual(query(evidence, "semantic_change", "z")["count"], 1)
        self.assertEqual(query(evidence, "semantic_change", "a")["count"], 0)

    def test_incompatible_declarations_are_unsupported(self):
        left = model({"x": {"kind": "bool"}})
        alternatives = []
        for inputs in ({}, {"renamed": {"kind": "bool"}}, {"x": {"kind": "int", "min": 0, "max": 1}},
                       {"x": {"kind": "enum", "values": ["a", "b"]}}):
            right = deepcopy(left)
            right["inputs"] = inputs
            alternatives.append(right)
        for outputs in ({}, {"answer": {"type": {"kind": "bool"}, "required": False}},
                        {"answer": {"type": {"kind": "int", "min": 0, "max": 1}, "required": True}}):
            right = deepcopy(left)
            right["outputs"] = outputs
            alternatives.append(right)
        for right in alternatives:
            with self.subTest(right=right):
                self.assert_status("UNSUPPORTED", analyze_diff, left, right)
                self.assert_status("UNSUPPORTED", verify_diff, left, right, {})

    def test_integer_domain_and_enum_declaration_order_changes_are_unsupported(self):
        for declared, changed in [({"kind": "int", "min": 0, "max": 1}, {"kind": "int", "min": 0, "max": 2}),
                                  ({"kind": "enum", "values": ["a", "b"]}, {"kind": "enum", "values": ["b", "a"]})]:
            left = model({"x": declared})
            right = deepcopy(left)
            right["inputs"]["x"] = changed
            self.assert_status("UNSUPPORTED", analyze_diff, left, right)
            self.assert_status("UNSUPPORTED", verify_diff, left, right, {})

    def test_model_validation_errors_are_preserved(self):
        left = model({"x": {"kind": "bool"}})
        facts = deepcopy(left)
        facts["facts"] = [{"var": "x", "value": True}, {"var": "x", "value": False}]
        cyclic = deepcopy(left)
        cyclic["rules"] = [rule("A", overrides=["B"]), rule("B", overrides=["A"])]
        invalid = deepcopy(left)
        invalid["rules"] = [rule("A", 1)]
        for right, status in ((facts, "INPUT_INCONSISTENT"), (cyclic, "UNSUPPORTED"), (invalid, "MODEL_INVALID")):
            self.assert_status(status, analyze_diff, left, right)
            self.assert_status(status, verify_diff, left, right, {})

    def test_empty_base_on_either_side_is_not_a_success(self):
        good = model({"x": {"kind": "bool"}})
        bad = deepcopy(good)
        bad["constraints"] = [{"const": False}]
        for left, right, side in ((bad, good, "left"), (good, bad, "right"), (bad, bad, "left")):
            error = self.assert_status("BASE_INCONSISTENT", analyze_diff, left, right)
            self.assertIn(side, error.message)
            error = self.assert_status("BASE_INCONSISTENT", verify_diff, left, right, {})
            self.assertIn(side, error.message)

    def test_limit_is_strict_integer_and_hard_capped(self):
        left = model()
        for limit in (False, True, 0, -1, 1.0, "1", None, 10001):
            with self.subTest(limit=limit):
                self.assert_status("LIMIT_REACHED", analyze_diff, left, left, max_contexts=limit)
                self.assert_status("LIMIT_REACHED", verify_diff, left, left, {}, max_contexts=limit)
        self.checked(left, left, max_contexts=1)

    def test_full_domain_budget_applies_before_facts_or_domain_materialization(self):
        left = model({"x": {"kind": "int", "min": -(2**63), "max": 2**63 - 1}})
        left["facts"] = [{"var": "x", "value": 0}]
        self.assert_status("LIMIT_REACHED", analyze_diff, left, left)
        self.assert_status("LIMIT_REACHED", verify_diff, left, left, {})
        small = model({"x": {"kind": "bool"}})
        small["facts"] = [{"var": "x", "value": True}]
        self.assert_status("LIMIT_REACHED", analyze_diff, small, small, max_contexts=1)

    def test_exact_context_hard_limit_is_allowed_when_evidence_fits(self):
        left = model({"x": {"kind": "int", "min": 0, "max": 9999}})
        left["outputs"] = {}
        evidence = self.checked(left, left)
        self.assertEqual(evidence["total_contexts"], 10000)
        self.assertEqual(len(evidence["cases"]), 10000)

    def test_certificate_byte_limits_cover_cases_and_final_queries(self):
        left = model()
        full = analyze_diff(left, left)
        case_size = len(canonical_json(full["cases"]).encode("utf-8"))
        for budget in (1, case_size + 10):
            with self.subTest(budget=budget):
                with patch.object(diff, "MAX_CERTIFICATE_BYTES", budget):
                    self.assert_status("LIMIT_REACHED", analyze_diff, left, left)
                # {} fits this budget, allowing the expected-evidence budget to be exercised.
                with patch.object(diff_checker, "MAX_CERTIFICATE_BYTES", max(2, budget)):
                    self.assert_status("LIMIT_REACHED", verify_diff, left, left, {})
        huge = {"padding": "x" * MAX_CERTIFICATE_BYTES}
        with patch.object(diff_checker, "_replay", side_effect=AssertionError("must reject before replay")):
            self.assert_status("CERTIFICATE_INVALID", verify_diff, left, left, huge)

    def test_evidence_tampering_including_scope_and_first_witness_is_rejected(self):
        left = model({"x": {"kind": "int", "min": 0, "max": 2}})
        left["facts"] = [{"var": "x", "value": 0}]
        right = deepcopy(left)
        right["facts"] = []
        right["rules"] = [rule("R")]
        original = analyze_diff(left, right)
        changes = {
            "drop_case": lambda e: e["cases"].pop(),
            "repeat_case": lambda e: e["cases"].append(deepcopy(e["cases"][0])),
            "reorder_cases": lambda e: e["cases"].reverse(),
            "scope_count": lambda e: e["queries"][0].update(count=0, witness=None),
            "later_scope_witness": lambda e: e["queries"][0]["witness"].update(case_index=2, input={"x": 2}),
            "semantic_count": lambda e: e["queries"][1].update(count=0, witness=None),
            "fake_input": lambda e: e["cases"][0]["input"].update(x=1),
            "fake_state": lambda e: e["cases"][0]["left"]["outputs"]["answer"].update(state="defined"),
            "fake_ids": lambda e: e["cases"][0]["right"]["outputs"]["answer"]["rule_ids"].append("Fake"),
            "excluded_output": lambda e: e["cases"][1]["left"].update(outputs={"answer": {"state": "absent", "values": [], "rule_ids": []}}),
            "total": lambda e: e.update(total_contexts=2),
            "common": lambda e: e.update(common_admitted_contexts=3),
            "left_count": lambda e: e.update(left_admitted_contexts=3),
            "right_count": lambda e: e.update(right_admitted_contexts=1),
            "unknown": lambda e: e.update(unknown=True),
            "missing_query": lambda e: e["queries"].pop(),
            "query_order": lambda e: e["queries"].reverse(),
        }
        for name, change in changes.items():
            with self.subTest(tampering=name):
                evidence = deepcopy(original)
                change(evidence)
                self.assert_status("CERTIFICATE_INVALID", verify_diff, left, right, evidence)

    def test_bool_int_and_float_substitutions_are_rejected(self):
        left = model({"x": {"kind": "bool"}})
        right = deepcopy(left)
        right["rules"] = [rule("R")]
        original = analyze_diff(left, right)
        changes = [lambda e: e["cases"][0].update(index=False),
                   lambda e: e["cases"][0]["input"].update(x=0),
                   lambda e: e["cases"][0]["left"].update(admitted=1),
                   lambda e: e["cases"][0]["right"]["outputs"]["answer"].update(values=[1]),
                   lambda e: e["queries"][0].update(count=False),
                   lambda e: e.update(total_contexts=2.0)]
        for change in changes:
            evidence = deepcopy(original)
            change(evidence)
            self.assert_status("CERTIFICATE_INVALID", verify_diff, left, right, evidence)

    def test_metadata_model_hash_and_old_certificate_formats_are_bound(self):
        left = model()
        right = deepcopy(left)
        right["rules"] = [rule("R")]
        original = analyze_diff(left, right)
        for field in ("format", "comparison_profile", "profile", "engine_version", "left_model_hash", "right_model_hash"):
            evidence = deepcopy(original)
            evidence[field] = "forged"
            self.assert_status("CERTIFICATE_INVALID", verify_diff, left, right, evidence)
        changed = deepcopy(right)
        changed["title"] = "差替えたモデル"
        self.assert_status("CERTIFICATE_INVALID", verify_diff, left, changed, original)
        self.assert_status("CERTIFICATE_INVALID", verify_diff, changed, right, original)
        self.assert_status("CERTIFICATE_INVALID", verify_diff, right, left, original)
        self.assert_status("CERTIFICATE_INVALID", verify_diff, left, right, analyze(left))

    def test_non_json_unicode_and_cyclic_evidence_fail_before_replay(self):
        left = model()
        cyclic = {}
        cyclic["cycle"] = cyclic
        for evidence in (None, [], {1: "key"}, {"x": ()}, {"x": b"data"}, {"x": float("nan")},
                         {"x": "\ud800"}, cyclic):
            with patch.object(diff_checker, "_replay", side_effect=AssertionError("must reject before replay")):
                self.assert_status("CERTIFICATE_INVALID", verify_diff, left, left, evidence)

    def test_checker_rejects_producer_boundary_bug(self):
        left = model({"age": {"kind": "int", "min": 17, "max": 19}})
        right = deepcopy(left)
        right["rules"] = [rule("R", when={"op": "ge", "args": [{"var": "age"}, {"const": 18}]})]
        original = diff._evaluate

        def mutated(expr, context):
            if expr.get("op") == "ge":
                expr = {**expr, "op": "gt"}
            return original(expr, context)

        with patch.object(diff, "_evaluate", mutated):
            evidence = analyze_diff(left, right)
        self.assert_status("CERTIFICATE_INVALID", verify_diff, left, right, evidence)

    def test_checker_rejects_producer_omitting_an_input_branch(self):
        left = model({"x": {"kind": "bool"}})
        right = deepcopy(left)
        right["rules"] = [rule("R", when={"var": "x"})]
        with patch.object(diff, "_domain", return_value=[False]):
            evidence = analyze_diff(left, right)
        self.assert_status("CERTIFICATE_INVALID", verify_diff, left, right, evidence)

    def test_checker_rejects_correct_cases_with_forged_producer_aggregation(self):
        left = model()
        right = deepcopy(left)
        right["rules"] = [rule("R")]
        with patch.object(diff, "_changes", return_value=[]):
            evidence = analyze_diff(left, right)
        self.assert_status("CERTIFICATE_INVALID", verify_diff, left, right, evidence)

    def test_checker_does_not_call_other_producers_or_checkers(self):
        left = model()
        evidence = analyze_diff(left, left)
        with patch("rulekernel.diff.analyze_diff", side_effect=AssertionError("producer called")), \
             patch("rulekernel.engine.analyze", side_effect=AssertionError("engine called")), \
             patch("rulekernel.checker.verify", side_effect=AssertionError("ordinary checker called")):
            self.assertEqual(verify_diff(left, left, evidence)["status"], "VERIFIED")
        syntax = ast.parse(Path(diff_checker.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(syntax):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, {"diff", "engine", "checker", "rulekernel.diff", "rulekernel.engine", "rulekernel.checker"})
                if node.level:
                    self.assertEqual(node.module, "model")


if __name__ == "__main__":
    unittest.main()
