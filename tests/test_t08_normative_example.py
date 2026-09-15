"""Saved T08 authored normative fixture, evidence, and mutation tests."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from normkernel import checker, engine
from normkernel.checker import verify
from normkernel.model import KernelError, digest, load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "norms" / "t08-three-way"
MODEL_PATH = FIXTURE / "model.json"
CERTIFICATE_PATH = FIXTURE / "certificate.json"
SOURCE_PATH = FIXTURE / "source.txt"
README_PATH = FIXTURE / "README.md"

SOURCE_HASH = "5329107793e80775b1996a2d084451043c217ec55bf8485f77f1eb69cdfc1a82"
MODEL_HASH = "0d71e04b1c43038754638a6e52dca63771318902564df8cca278f495486ed839"
CERTIFICATE_HASH = "a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_for(certificate: dict, **inputs) -> dict:
    return next(case for case in certificate["cases"] if case["input"] == inputs)


class T08NormativeExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_json(MODEL_PATH)
        cls.certificate = load_json(CERTIFICATE_PATH)

    def assert_kernel_error(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)

    def test_saved_certificate_and_public_cli_are_externally_anchored(self):
        result = verify(
            self.model,
            self.certificate,
            expected_certificate_sha256=CERTIFICATE_HASH,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["certificate_hash_anchored"])
        self.assertEqual(result["model_hash"], MODEL_HASH)
        self.assertEqual(result["certificate_hash"], CERTIFICATE_HASH)

        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "certificate.json"
            produced = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "normkernel",
                    "check",
                    str(MODEL_PATH),
                    "--certificate",
                    str(generated),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(produced.returncode, 1, produced.stderr)
            produced_result = json.loads(produced.stdout)
            self.assertEqual(produced_result["status"], "VERIFIED")
            self.assertTrue(produced_result["diagnostics"]["has_findings"])
            self.assertEqual(generated.read_bytes(), CERTIFICATE_PATH.read_bytes())

            rechecked = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "normkernel",
                    "verify",
                    str(MODEL_PATH),
                    str(generated),
                    "--expected-certificate-sha256",
                    CERTIFICATE_HASH,
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(rechecked.returncode, 1, rechecked.stderr)
            rechecked_result = json.loads(rechecked.stdout)
            self.assertEqual(rechecked_result["status"], "VERIFIED")
            self.assertTrue(rechecked_result["certificate_hash_anchored"])

    def test_exact_quantifier_counts_classifications_and_witnesses(self):
        enumeration = self.certificate["enumeration"]
        self.assertEqual(enumeration["input_order"], ["blocked", "in_scope", "strict"])
        self.assertEqual(enumeration["action_order"], ["A", "B", "C"])
        self.assertEqual(enumeration["context_count"], 8)
        self.assertEqual(enumeration["action_assignment_count"], 8)
        self.assertEqual(enumeration["potential_context_trace_pairs"], 64)
        self.assertEqual(enumeration["evaluated_context_trace_pairs"], 32)
        self.assertEqual(
            self.certificate["counts"],
            {
                "total_contexts": 8,
                "admitted_contexts": 4,
                "excluded": 4,
                "background_trace_impossible": 2,
                "normatively_infeasible": 1,
                "compliance_feasible": 1,
            },
        )

        feasible = case_for(
            self.certificate,
            blocked=False,
            in_scope=True,
            strict=False,
        )
        self.assertEqual(feasible["classification"], "compliance_feasible")
        self.assertEqual(feasible["background_trace_count"], 8)
        self.assertEqual(feasible["compliant_trace_count"], 2)
        compliant = [row["actions"] for row in feasible["traces"] if row["compliant"]]
        self.assertEqual(
            compliant,
            [
                {"A": False, "B": True, "C": False},
                {"A": False, "B": True, "C": True},
            ],
        )

        infeasible = case_for(
            self.certificate,
            blocked=False,
            in_scope=True,
            strict=True,
        )
        self.assertEqual(infeasible["classification"], "normatively_infeasible")
        self.assertEqual(infeasible["background_trace_count"], 8)
        self.assertEqual(infeasible["compliant_trace_count"], 0)

        background_impossible = [
            case
            for case in self.certificate["cases"]
            if case["classification"] == "background_trace_impossible"
        ]
        self.assertEqual(len(background_impossible), 2)
        self.assertTrue(all(case["input"]["blocked"] for case in background_impossible))
        self.assertTrue(all(case["background_trace_count"] == 0 for case in background_impossible))

    def test_permission_is_not_hard_norm_and_has_exercise_and_nonexercise(self):
        feasible = case_for(
            self.certificate,
            blocked=False,
            in_scope=True,
            strict=False,
        )
        self.assertEqual(feasible["active_norm_ids"]["explicit_permission"], ["P_C"])
        for trace in feasible["traces"]:
            hard_ids = [row["norm_id"] for row in trace["active_base_norms"]]
            self.assertNotIn("P_C", hard_ids)

        permission = feasible["permissions"][0]
        self.assertEqual(permission["permission_id"], "P_C")
        self.assertEqual(permission["status"], "usable")
        self.assertEqual(permission["usable_count"], 1)
        self.assertEqual(permission["nonexercise_count"], 1)
        self.assertEqual(
            permission["usable_witness"]["actions"],
            {"A": False, "B": True, "C": True},
        )
        self.assertEqual(
            permission["nonexercise_witness"]["actions"],
            {"A": False, "B": True, "C": False},
        )
        self.assertTrue(permission["usable_witness"]["actions"]["C"])
        self.assertFalse(permission["nonexercise_witness"]["actions"]["C"])

    def test_each_member_of_three_way_conflict_is_necessary(self):
        for removed in ("O_CHOOSE_A_OR_B", "F_A", "F_B_STRICT"):
            with self.subTest(removed=removed):
                changed = deepcopy(self.model)
                changed["norms"] = [norm for norm in changed["norms"] if norm["id"] != removed]
                certificate = engine.analyze(changed)
                self.assertEqual(verify(changed, certificate)["status"], "VERIFIED")
                strict_case = case_for(
                    certificate,
                    blocked=False,
                    in_scope=True,
                    strict=True,
                )
                self.assertEqual(strict_case["classification"], "compliance_feasible")
                self.assertGreater(strict_case["compliant_trace_count"], 0)

    def test_checker_does_not_import_or_call_the_producer(self):
        tree = ast.parse(Path(checker.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertNotIn("normkernel.engine", {item.name for item in node.names})
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, {"engine", "normkernel.engine"})

        with patch.object(engine, "analyze", side_effect=AssertionError("producer called")), patch.object(
            engine, "_evaluate", side_effect=AssertionError("producer evaluator called")
        ):
            self.assertEqual(
                verify(
                    self.model,
                    self.certificate,
                    expected_certificate_sha256=CERTIFICATE_HASH,
                )["status"],
                "VERIFIED",
            )

    def test_checker_rejects_a_mutated_producer_evaluation_branch(self):
        original_evaluate = engine._evaluate

        def and_instead_of_or(expression, context, actions):
            if expression.get("op") == "or":
                return all(original_evaluate(arg, context, actions) for arg in expression["args"])
            return original_evaluate(expression, context, actions)

        with patch.object(engine, "_evaluate", and_instead_of_or):
            faulty = engine.analyze(self.model)
        self.assertNotEqual(faulty, self.certificate)
        self.assert_kernel_error("CERTIFICATE_INVALID", verify, self.model, faulty)

    def test_certificate_aggregate_trace_and_permission_tampering_is_rejected(self):
        changes = []
        changed = deepcopy(self.certificate)
        changed["counts"]["compliance_feasible"] = 2
        changes.append(changed)
        changed = deepcopy(self.certificate)
        changed["cases"][2]["traces"][2]["compliant"] = False
        changes.append(changed)
        changed = deepcopy(self.certificate)
        changed["permission_summaries"][0]["usable_witness"]["actions"]["C"] = False
        changes.append(changed)
        for changed in changes:
            with self.subTest(change=changed):
                self.assert_kernel_error("CERTIFICATE_INVALID", verify, self.model, changed)

    def test_model_hash_is_external_and_certificate_cannot_move_to_changed_model(self):
        self.assertEqual(file_sha256(MODEL_PATH), MODEL_HASH)
        self.assertEqual(digest(self.model), MODEL_HASH)
        self.assertEqual(self.certificate["model_hash"], MODEL_HASH)
        changed = deepcopy(self.model)
        changed["title"] += "（変更）"
        self.assertNotEqual(digest(changed), MODEL_HASH)
        self.assert_kernel_error("CERTIFICATE_INVALID", verify, changed, self.certificate)

    def test_fictional_source_readme_and_norm_source_correspondence(self):
        self.assertEqual(file_sha256(SOURCE_PATH), SOURCE_HASH)
        source_lines = SOURCE_PATH.read_text(encoding="utf-8").splitlines()
        norm_sources = [norm["source"] for norm in self.model["norms"]]
        self.assertEqual(len(source_lines), 4)
        self.assertEqual(norm_sources, source_lines)
        for source in norm_sources:
            self.assertEqual(SOURCE_PATH.read_text(encoding="utf-8").count(source), 1)

        readme = README_PATH.read_text(encoding="utf-8")
        for expected in (
            "authored_normative_core",
            "T05のsource packageでも",
            SOURCE_HASH,
            MODEL_HASH,
            CERTIFICATE_HASH,
            "for every admitted c, exists tau",
            "読み替えない",
        ):
            self.assertIn(expected, readme)


if __name__ == "__main__":
    unittest.main()
