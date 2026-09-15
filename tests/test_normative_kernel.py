"""Black-box semantics and evidence tests for ``finite-norms/1``."""
from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import normkernel.checker as checker
import normkernel.engine as engine
from normkernel.model import (
    KernelError,
    MAX_ACTION_ASSIGNMENTS,
    MAX_CONTEXTS,
    MAX_CONTEXT_TRACE_PAIRS,
    canonical_json,
    digest,
    load_json,
    validate_model,
)


def const(value):
    return {"const": value}


def input_ref(name):
    return {"input": name}


def action_ref(name):
    return {"action": name}


def operation(name, *arguments):
    return {"op": name, "args": list(arguments)}


def norm(identifier, kind, content, *, when=None):
    return {
        "id": identifier,
        "source": "架空の規範 " + identifier,
        "kind": kind,
        "when": const(True) if when is None else when,
        "content": content,
    }


def small_model(*, inputs=None, actions=None):
    return {
        "profile": "finite-norms/1",
        "origin_kind": "authored_normative_core",
        "title": "架空の最小規範",
        "inputs": {"flag": {"kind": "bool"}} if inputs is None else inputs,
        "facts": [],
        "constraints": [],
        "actions": ["A"] if actions is None else actions,
        "action_constraints": [],
        "norms": [],
    }


def case_for(certificate, **expected_input):
    return next(row for row in certificate["cases"] if row["input"] == expected_input)


class NormativeTestCase(unittest.TestCase):
    def assert_status(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        self.assertIsInstance(caught.exception.message, str)

    def checked(self, model, **limits):
        certificate = engine.analyze(model, **limits)
        result = checker.verify(model, certificate, **limits)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["model_hash"], digest(model))
        self.assertEqual(result["certificate_hash"], digest(certificate))
        return certificate, result


class StrictModelTests(NormativeTestCase):
    def test_valid_model_and_strict_shapes(self):
        model = small_model()
        model["norms"] = [norm("O_A", "obligation", action_ref("A"))]
        validate_model(model)

        mutations = []
        changed = deepcopy(model)
        changed["unknown"] = True
        mutations.append(changed)
        changed = deepcopy(model)
        changed["norms"][0]["approval"] = "approved"
        mutations.append(changed)
        changed = deepcopy(model)
        changed["norms"][0]["content"]["extra"] = False
        mutations.append(changed)
        changed = deepcopy(model)
        changed["actions"].append("A")
        mutations.append(changed)
        changed = deepcopy(model)
        changed["norms"].append(deepcopy(changed["norms"][0]))
        mutations.append(changed)
        changed = deepcopy(model)
        changed["actions"] = ["flag"]
        mutations.append(changed)
        changed = deepcopy(model)
        changed["norms"][0]["id"] = "bad-id"
        mutations.append(changed)

        for changed in mutations:
            with self.subTest(changed=changed):
                self.assert_status("MODEL_INVALID", validate_model, changed)

        for field, value in (("profile", "finite-decisions/1"),
                             ("origin_kind", "authored_core")):
            changed = deepcopy(model)
            changed[field] = value
            self.assert_status("UNSUPPORTED", validate_model, changed)

        for field, value in (("profile", None), ("origin_kind", [])):
            changed = deepcopy(model)
            changed[field] = value
            self.assert_status("MODEL_INVALID", validate_model, changed)

    def test_strict_json_loader_and_unicode_boundary(self):
        payloads = (
            b'{"x":1,"x":2}',
            b'{"x":NaN}',
            b'{"x":"\\ud800"}',
            b'\xff',
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            for payload in payloads:
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    self.assert_status("MODEL_INVALID", load_json, path)
        self.assert_status("MODEL_INVALID", canonical_json, {"x": "\ud800"})

    def test_expression_types_arity_and_namespaces_are_strict(self):
        valid = small_model()
        valid["action_constraints"] = [
            operation("or", action_ref("A"), input_ref("flag"))
        ]
        valid["norms"] = [
            norm(
                "O_MATCH",
                "obligation",
                operation("eq", action_ref("A"), input_ref("flag")),
                when=input_ref("flag"),
            )
        ]
        validate_model(valid)

        invalid_expressions = []
        changed = deepcopy(valid)
        changed["constraints"] = [action_ref("A")]
        invalid_expressions.append(changed)
        changed = deepcopy(valid)
        changed["norms"][0]["when"] = action_ref("A")
        invalid_expressions.append(changed)
        changed = deepcopy(valid)
        changed["norms"][0]["content"] = action_ref("MISSING")
        invalid_expressions.append(changed)
        changed = deepcopy(valid)
        changed["constraints"] = [input_ref("missing")]
        invalid_expressions.append(changed)
        changed = deepcopy(valid)
        changed["constraints"] = [operation("and", input_ref("flag"))]
        invalid_expressions.append(changed)
        changed = deepcopy(valid)
        changed["constraints"] = [operation("lt", input_ref("flag"), const(True))]
        invalid_expressions.append(changed)
        changed = deepcopy(valid)
        changed["norms"][0]["content"] = const(1.5)
        invalid_expressions.append(changed)
        for malformed_operator in (None, 1, True, [], {}):
            changed = deepcopy(valid)
            changed["constraints"] = [
                {"op": malformed_operator, "args": [const(True), const(False)]}
            ]
            invalid_expressions.append(changed)

        for changed in invalid_expressions:
            with self.subTest(changed=changed):
                self.assert_status("MODEL_INVALID", validate_model, changed)

    def test_condition_expression_truth_tables(self):
        model = small_model(
            inputs={"age": {"kind": "int", "min": 0, "max": 2},
                    "flag": {"kind": "bool"}},
            actions=[],
        )
        age = input_ref("age")
        flag = input_ref("flag")
        model["norms"] = [
            norm("N_AND", "obligation", const(True),
                 when=operation("and", flag, operation("not", const(False)))),
            norm("N_EQ", "obligation", const(True), when=operation("eq", age, const(1))),
            norm("N_GE", "obligation", const(True), when=operation("ge", age, const(1))),
            norm("N_GT", "obligation", const(True), when=operation("gt", age, const(1))),
            norm("N_LE", "obligation", const(True), when=operation("le", age, const(1))),
            norm("N_LT", "obligation", const(True), when=operation("lt", age, const(1))),
            norm("N_NE", "obligation", const(True), when=operation("ne", age, const(1))),
            norm("N_OR", "obligation", const(True),
                 when=operation("or", flag, operation("not", flag))),
        ]
        certificate, _ = self.checked(model)
        for row in certificate["cases"]:
            age_value, flag_value = row["input"]["age"], row["input"]["flag"]
            expected = {"N_OR"}
            expected.update({
                name for name, holds in {
                    "N_AND": flag_value,
                    "N_EQ": age_value == 1,
                    "N_GE": age_value >= 1,
                    "N_GT": age_value > 1,
                    "N_LE": age_value <= 1,
                    "N_LT": age_value < 1,
                    "N_NE": age_value != 1,
                }.items() if holds
            })
            self.assertEqual(set(row["active_norm_ids"]["obligation"]), expected)

    def test_conflicting_facts_are_not_overwritten(self):
        model = small_model()
        model["facts"] = [
            {"var": "flag", "value": False},
            {"var": "flag", "value": True},
        ]
        self.assert_status("INPUT_INCONSISTENT", validate_model, model)
        self.assert_status("INPUT_INCONSISTENT", engine.analyze, model)
        self.assert_status("INPUT_INCONSISTENT", checker.verify, model, {})

        model["facts"] = [
            {"var": "flag", "value": True},
            {"var": "flag", "value": True},
        ]
        certificate, _ = self.checked(model)
        self.assertEqual(certificate["counts"]["admitted_contexts"], 1)

    def test_unknown_string_discriminants_are_unsupported(self):
        for kind in ("date", "real", "record"):
            with self.subTest(discriminant="domain", kind=kind):
                model = small_model(inputs={"value": {"kind": kind}})
                self.assert_status("UNSUPPORTED", validate_model, model)

        for operator in ("xor", "implies", "until"):
            with self.subTest(discriminant="operator", operator=operator):
                model = small_model()
                model["constraints"] = [
                    {"op": operator, "args": [const(True), const(False)]}
                ]
                self.assert_status("UNSUPPORTED", validate_model, model)

        for kind in ("decision", "permission", "power", "discretion", "deadline"):
            with self.subTest(kind=kind):
                model = small_model()
                model["norms"] = [norm("N", kind, action_ref("A"))]
                self.assert_status("UNSUPPORTED", validate_model, model)

    def test_non_string_discriminants_are_structurally_invalid(self):
        for kind in (None, 1, True, [], {}):
            with self.subTest(discriminant="domain", kind=kind):
                model = small_model(inputs={"value": {"kind": kind}})
                self.assert_status("MODEL_INVALID", validate_model, model)

            with self.subTest(discriminant="norm", kind=kind):
                model = small_model()
                model["norms"] = [norm("N", kind, action_ref("A"))]
                self.assert_status("MODEL_INVALID", validate_model, model)


class NormativeSemanticsTests(NormativeTestCase):
    def test_empty_inputs_and_actions_still_have_one_context_and_trace(self):
        model = small_model(inputs={}, actions=[])
        certificate, result = self.checked(model)
        self.assertEqual(certificate["enumeration"], {
            "input_order": [],
            "action_order": [],
            "context_count": 1,
            "action_assignment_count": 1,
            "potential_context_trace_pairs": 1,
            "evaluated_context_trace_pairs": 1,
        })
        self.assertEqual(certificate["cases"][0]["input"], {})
        self.assertEqual(certificate["cases"][0]["traces"][0]["actions"], {})
        self.assertEqual(certificate["cases"][0]["classification"], "compliance_feasible")
        self.assertFalse(result["diagnostics"]["has_findings"])

    def test_no_norms_and_inactive_norms_do_not_add_requirements(self):
        for include_inactive in (False, True):
            with self.subTest(include_inactive=include_inactive):
                model = small_model()
                if include_inactive:
                    model["norms"] = [
                        norm("O_INACTIVE", "obligation", action_ref("A"), when=const(False)),
                        norm("P_INACTIVE", "explicit_permission", action_ref("A"),
                             when=const(False)),
                    ]
                certificate, result = self.checked(model)
                self.assertEqual(certificate["counts"], {
                    "total_contexts": 2,
                    "admitted_contexts": 2,
                    "excluded": 0,
                    "background_trace_impossible": 0,
                    "normatively_infeasible": 0,
                    "compliance_feasible": 2,
                })
                self.assertTrue(all(row["compliant_trace_count"] == 2
                                    for row in certificate["cases"]))
                if include_inactive:
                    self.assertTrue(all(
                        row["permissions"][0]["status"] == "not_applicable"
                        for row in certificate["cases"]
                    ))
                self.assertFalse(result["diagnostics"]["has_findings"])

    def test_prohibition_of_conjunction_does_not_forbid_each_action(self):
        model = small_model(inputs={}, actions=["A", "B"])
        model["norms"] = [
            norm("F_BOTH", "prohibition",
                 operation("and", action_ref("A"), action_ref("B")))
        ]
        certificate, _ = self.checked(model)
        row = certificate["cases"][0]
        self.assertEqual(row["background_trace_count"], 4)
        self.assertEqual(row["compliant_trace_count"], 3)
        by_actions = {tuple(trace["actions"].items()): trace for trace in row["traces"]}
        self.assertTrue(by_actions[(("A", True), ("B", False))]["compliant"])
        self.assertTrue(by_actions[(("A", False), ("B", True))]["compliant"])
        self.assertFalse(by_actions[(("A", True), ("B", True))]["compliant"])

    def test_three_norms_together_first_make_choice_impossible(self):
        model = small_model(inputs={}, actions=["A", "B"])
        model["norms"] = [
            norm("O_CHOOSE", "obligation",
                 operation("or", action_ref("A"), action_ref("B"))),
            norm("F_A", "prohibition", action_ref("A")),
            norm("F_B", "prohibition", action_ref("B")),
        ]
        certificate, result = self.checked(model)
        self.assertEqual(certificate["cases"][0]["classification"], "normatively_infeasible")
        self.assertEqual(certificate["cases"][0]["background_trace_count"], 4)
        self.assertEqual(certificate["cases"][0]["compliant_trace_count"], 0)
        self.assertEqual(result["diagnostics"]["normatively_infeasible_contexts"], 1)

        for removed in ("O_CHOOSE", "F_A", "F_B"):
            with self.subTest(removed=removed):
                reduced = deepcopy(model)
                reduced["norms"] = [item for item in reduced["norms"] if item["id"] != removed]
                reduced_certificate, reduced_result = self.checked(reduced)
                self.assertEqual(
                    reduced_certificate["cases"][0]["classification"],
                    "compliance_feasible",
                )
                self.assertFalse(reduced_result["diagnostics"]["has_findings"])

    def test_each_explicit_permission_has_its_own_existential_trace(self):
        model = small_model(inputs={}, actions=["A"])
        model["norms"] = [
            norm("P_A", "explicit_permission", action_ref("A")),
            norm("P_NOT_A", "explicit_permission",
                 operation("not", action_ref("A"))),
        ]
        certificate, result = self.checked(model)
        row = certificate["cases"][0]
        self.assertEqual(row["compliant_trace_count"], 2)
        permissions = {item["permission_id"]: item for item in row["permissions"]}
        self.assertEqual(permissions["P_A"]["status"], "usable")
        self.assertEqual(permissions["P_NOT_A"]["status"], "usable")
        self.assertEqual(permissions["P_A"]["usable_count"], 1)
        self.assertEqual(permissions["P_NOT_A"]["usable_count"], 1)
        self.assertEqual(permissions["P_A"]["usable_witness"]["actions"], {"A": True})
        self.assertEqual(permissions["P_NOT_A"]["usable_witness"]["actions"], {"A": False})
        self.assertFalse(result["diagnostics"]["has_findings"])

    def test_permission_can_be_unusable_while_the_context_remains_feasible(self):
        model = small_model(inputs={}, actions=["A"])
        model["norms"] = [
            norm("F_A", "prohibition", action_ref("A")),
            norm("P_A", "explicit_permission", action_ref("A")),
            norm("P_A_AGAIN", "explicit_permission", action_ref("A")),
        ]
        certificate, result = self.checked(model)
        row = certificate["cases"][0]
        self.assertEqual(row["classification"], "compliance_feasible")
        self.assertEqual(row["compliance_witness"]["actions"], {"A": False})
        self.assertEqual(
            {permission["permission_id"] for permission in row["permissions"]},
            {"P_A", "P_A_AGAIN"},
        )
        self.assertTrue(all(
            permission["status"] == "unusable"
            and permission["usable_count"] == 0
            for permission in row["permissions"]
        ))
        self.assertEqual(result["diagnostics"], {
            "background_trace_impossible_contexts": 0,
            "normatively_infeasible_contexts": 0,
            "unusable_permission_context_pairs": 2,
            "contexts_with_unusable_permissions": 1,
            "has_findings": True,
        })

    def test_every_context_may_require_a_distinct_existential_trace(self):
        model = small_model(actions=["A"])
        model["norms"] = [
            norm(
                "O_MATCH_FLAG",
                "obligation",
                operation("eq", action_ref("A"), input_ref("flag")),
            )
        ]
        certificate, result = self.checked(model)
        false_case = case_for(certificate, flag=False)
        true_case = case_for(certificate, flag=True)
        self.assertEqual(false_case["compliance_witness"]["actions"], {"A": False})
        self.assertEqual(true_case["compliance_witness"]["actions"], {"A": True})
        self.assertEqual(certificate["counts"]["compliance_feasible"], 2)
        self.assertEqual(certificate["counts"]["normatively_infeasible"], 0)
        self.assertFalse(result["diagnostics"]["has_findings"])

    def test_one_feasible_context_does_not_hide_an_infeasible_context(self):
        model = small_model(inputs={"strict": {"kind": "bool"}}, actions=["A", "B"])
        model["norms"] = [
            norm("O_CHOOSE", "obligation",
                 operation("or", action_ref("A"), action_ref("B"))),
            norm("F_A", "prohibition", action_ref("A")),
            norm("F_B_STRICT", "prohibition", action_ref("B"),
                 when=input_ref("strict")),
        ]
        certificate, result = self.checked(model)
        ordinary = case_for(certificate, strict=False)
        strict = case_for(certificate, strict=True)
        self.assertEqual(ordinary["classification"], "compliance_feasible")
        self.assertEqual(ordinary["compliance_witness"]["actions"], {"A": False, "B": True})
        self.assertEqual(strict["classification"], "normatively_infeasible")
        self.assertIsNone(strict["compliance_witness"])
        self.assertEqual(certificate["counts"]["compliance_feasible"], 1)
        self.assertEqual(certificate["counts"]["normatively_infeasible"], 1)
        self.assertTrue(result["diagnostics"]["has_findings"])

    def test_background_impossibility_has_priority_over_normative_infeasibility(self):
        model = small_model(inputs={}, actions=["A"])
        model["action_constraints"] = [const(False)]
        model["norms"] = [
            norm("O_FALSE", "obligation", const(False)),
            norm("P_A", "explicit_permission", action_ref("A")),
        ]
        certificate, result = self.checked(model)
        row = certificate["cases"][0]
        self.assertEqual(row["classification"], "background_trace_impossible")
        self.assertEqual(row["background_trace_count"], 0)
        self.assertEqual(row["compliant_trace_count"], 0)
        self.assertEqual(row["permissions"][0]["status"], "background_impossible")
        self.assertEqual(result["diagnostics"]["background_trace_impossible_contexts"], 1)
        self.assertEqual(result["diagnostics"]["normatively_infeasible_contexts"], 0)

    def test_all_contexts_excluded_is_base_inconsistent(self):
        model = small_model()
        model["constraints"] = [const(False)]
        self.assert_status("BASE_INCONSISTENT", engine.analyze, model)
        certificate = engine.analyze(small_model())
        self.assert_status("BASE_INCONSISTENT", checker.verify, model, certificate)


class LimitsAndCheckerTests(NormativeTestCase):
    def test_cartesian_action_and_pair_limits_are_preflighted(self):
        model = small_model()
        cases = (
            ({"max_contexts": 1}, "context"),
            ({"max_action_assignments": 1}, "action"),
            ({"max_pairs": 3}, "pair"),
        )
        for limits, label in cases:
            with self.subTest(limit=label):
                self.assert_status("LIMIT_REACHED", engine.analyze, model, **limits)
                self.assert_status("LIMIT_REACHED", checker.verify, model, {}, **limits)

        for argument, hard in (("max_contexts", MAX_CONTEXTS),
                               ("max_action_assignments", MAX_ACTION_ASSIGNMENTS),
                               ("max_pairs", MAX_CONTEXT_TRACE_PAIRS)):
            for value in (0, True, hard + 1):
                with self.subTest(argument=argument, value=value):
                    self.assert_status(
                        "LIMIT_REACHED", engine.analyze, model, **{argument: value}
                    )

    def test_certificate_byte_limits_fail_closed(self):
        model = small_model()
        certificate = engine.analyze(model)
        with patch.object(engine, "MAX_CERTIFICATE_BYTES", 128):
            self.assert_status("LIMIT_REACHED", engine.analyze, model)
        with patch.object(checker, "MAX_CERTIFICATE_BYTES", 128):
            self.assert_status("CERTIFICATE_INVALID", checker.verify, model, certificate)

    def test_checker_is_independent_and_external_hash_can_anchor_evidence(self):
        source = inspect.getsource(checker)
        self.assertNotIn("from .engine import", source)
        self.assertNotIn("import normkernel.engine", source)
        model = small_model()
        model["norms"] = [norm("O_A", "obligation", action_ref("A"))]
        certificate = engine.analyze(model)
        certificate_hash = digest(certificate)
        unanchored = checker.verify(model, certificate)
        anchored = checker.verify(
            model, certificate, expected_certificate_sha256=certificate_hash
        )
        self.assertFalse(unanchored["certificate_hash_anchored"])
        self.assertTrue(anchored["certificate_hash_anchored"])
        self.assertEqual(anchored["certificate_hash"], certificate_hash)
        self.assert_status(
            "CERTIFICATE_INVALID",
            checker.verify,
            model,
            certificate,
            expected_certificate_sha256="0" * 64,
        )

    def test_checker_rejects_tampered_complete_evidence(self):
        model = small_model(inputs={}, actions=["A"])
        model["norms"] = [
            norm("F_A", "prohibition", action_ref("A")),
            norm("P_A", "explicit_permission", action_ref("A")),
        ]
        certificate = engine.analyze(model)
        mutations = []
        changed = deepcopy(certificate)
        changed["model_hash"] = "0" * 64
        mutations.append(changed)
        changed = deepcopy(certificate)
        changed["counts"]["normatively_infeasible"] += 1
        mutations.append(changed)
        changed = deepcopy(certificate)
        changed["cases"][0]["traces"][0]["compliant"] = False
        mutations.append(changed)
        changed = deepcopy(certificate)
        changed["cases"][0]["traces"].pop()
        mutations.append(changed)
        changed = deepcopy(certificate)
        changed["cases"][0]["permissions"][0]["status"] = "usable"
        mutations.append(changed)
        changed = deepcopy(certificate)
        changed["enumeration"]["action_order"] = []
        mutations.append(changed)

        for changed in mutations:
            with self.subTest(changed=changed):
                self.assert_status("CERTIFICATE_INVALID", checker.verify, model, changed)

    def test_checker_rejects_a_certificate_from_a_mutated_producer(self):
        model = small_model(inputs={}, actions=["A"])
        model["norms"] = [norm("O_A", "obligation", action_ref("A"))]
        original_evaluate = engine._evaluate

        def flipped_action(expression, context, actions):
            value = original_evaluate(expression, context, actions)
            return not value if "action" in expression else value

        with patch.object(engine, "_evaluate", side_effect=flipped_action):
            bad_certificate = engine.analyze(model)
        self.assert_status("CERTIFICATE_INVALID", checker.verify, model, bad_certificate)

        good_certificate = engine.analyze(model)
        with patch.object(engine, "_evaluate", side_effect=AssertionError("producer called")):
            checked = checker.verify(model, good_certificate)
        self.assertEqual(checked["status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
