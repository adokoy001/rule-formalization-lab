"""T07 regression tests for the deliberately narrow Penal Code Article 41 pack."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rulekernel.__main__ import main
from rulekernel.interpretation import _lower_core
from rulekernel.interpretation_checker import verify_interpretation_package
from rulekernel.interpretation_model import (
    bind_task_to_source,
    interpretation_digest,
    interpretation_snapshot_digest,
    load_interpretation_json,
    validate_candidate,
)
from rulekernel.model import KernelError, canonical_json, load_json
from rulekernel.source_checker import verify_source_package
from rulekernel.source_model import MAX_MANIFEST_BYTES, load_source_json
from rulekernel.staged_reachability_checker import verify_staged_reachability


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "interpretations" / "penal-code-41"
SOURCE = ROOT / "examples" / "sources" / "penal-code-41"
SOURCE_BUNDLE_HASH = "60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060"
REVIEW_HASH = "944d00c39ec70ba49675e033a44494f3a31e4f10c71566441cfd3edab85171e3"
EXPECTATIONS_HASH = "fcf9f74b059bf44b9cca8763a348ded6e19661e90f7fbe1b240ff1a17f3205b8"
PACKAGE_HASH = "e4a2a41eb531715f2c9ad0732f0b447a77e23c039273ae3d655d87ec17c7b95c"
CORE_HASH = "2f19f4892263e64319a1592f53677e96ab4140402dd5f9fadc9bf4ff1615f1af"
STAGED_CERTIFICATE_HASH = (
    "e5ff411f57fdeb2341dc7e2f24c6530eadd051a35e846910206c2a9616a41406"
)
OUTPUT = "article41_under14_nonpunishment_applies"


class PenalCode41TestCase(unittest.TestCase):
    def setUp(self):
        self.task = load_interpretation_json(EXAMPLE / "task.json")
        self.candidate = load_interpretation_json(EXAMPLE / "candidate.json")
        self.review = load_interpretation_json(EXAMPLE / "review.json")
        self.expectations = load_interpretation_json(
            EXAMPLE / "scope-expectations.json")
        self.package = load_interpretation_json(EXAMPLE / "compiled.json")
        self.core = load_json(EXAMPLE / "core.json")
        self.staged = load_json(EXAMPLE / "staged-reachability.certificate.json")

    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def write_json(path, value):
        Path(path).write_text(canonical_json(value), encoding="utf-8")

    def compile_args(self, candidate, review, expectations, package):
        return [
            "compile-interpretation",
            str(EXAMPLE / "task.json"), str(candidate), str(review),
            str(expectations),
            "--source-spec", str(SOURCE / "source-spec.json"),
            "--source-bundle", str(SOURCE / "bundle"),
            "--expected-source-bundle-sha256", SOURCE_BUNDLE_HASH,
            "--expected-review-sha256",
            interpretation_digest(load_interpretation_json(review)),
            "--expected-scope-expectations-sha256",
            interpretation_digest(load_interpretation_json(expectations)),
            "--package", str(package), "--json",
        ]

    def refresh_chain(self, candidate, review, expectations):
        review["candidate_hash"] = interpretation_digest(candidate)
        source_result = verify_source_package(
            SOURCE / "source-spec.json", SOURCE / "bundle",
            expected_bundle_sha256=SOURCE_BUNDLE_HASH,
        )
        manifest = load_source_json(
            SOURCE / "bundle" / "derived" / "source-units.json",
            max_bytes=MAX_MANIFEST_BYTES,
        )
        units = bind_task_to_source(self.task, source_result, manifest)
        candidate_index = validate_candidate(
            self.task, candidate, units, manifest)
        core = _lower_core(self.task, candidate_index, review, units)
        expectations["task_hash"] = interpretation_digest(self.task)
        expectations["candidate_hash"] = interpretation_digest(candidate)
        expectations["review_hash"] = interpretation_digest(review)
        expectations["interpretation_snapshot_sha256"] = (
            interpretation_snapshot_digest(self.task, candidate, review)
        )
        expectations["scope_hash"] = interpretation_digest(
            self.task["core_scope"])
        expectations["core_model_hash"] = interpretation_digest(core)


class PenalCode41SavedChainTests(PenalCode41TestCase):
    def test_saved_source_interpretation_and_staged_certificate_verify_offline(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network forbidden")):
            source = verify_source_package(
                SOURCE / "source-spec.json", SOURCE / "bundle",
                expected_bundle_sha256=SOURCE_BUNDLE_HASH,
            )
            interpretation = verify_interpretation_package(
                EXAMPLE / "task.json", EXAMPLE / "candidate.json",
                EXAMPLE / "review.json", EXAMPLE / "scope-expectations.json",
                SOURCE / "source-spec.json", SOURCE / "bundle",
                EXAMPLE / "compiled.json",
                expected_source_bundle_sha256=SOURCE_BUNDLE_HASH,
                expected_review_sha256=REVIEW_HASH,
                expected_scope_expectations_sha256=EXPECTATIONS_HASH,
                expected_package_sha256=PACKAGE_HASH,
            )
            staged = verify_staged_reachability(
                self.core, self.staged, self.expectations,
                expected_scope_expectations_sha256=EXPECTATIONS_HASH,
            )
        self.assertEqual(source["status"], "VERIFIED")
        self.assertEqual(source["revision_id"],
                         "140AC0000000045_20260521_507AC0000000039")
        self.assertEqual(interpretation["status"], "LOWERING_VERIFIED")
        self.assertEqual(interpretation["core_model_hash"], CORE_HASH)
        self.assertEqual(interpretation["review_method"], "manual_fixture_review")
        self.assertTrue(interpretation["provisional"])
        self.assertTrue(interpretation["package_hash_anchored"])
        self.assertTrue(interpretation["offline"])
        self.assertEqual(staged["status"], "VERIFIED")
        self.assertEqual(staged["certificate_hash"], STAGED_CERTIFICATE_HASH)
        self.assertEqual(staged["attention_count"], 0)

    def test_pack_has_one_narrow_optional_true_only_conclusion(self):
        self.assertEqual(self.package["core"], self.core)
        self.assertEqual(set(self.core["outputs"]), {OUTPUT})
        self.assertFalse(self.core["outputs"][OUTPUT]["required"])
        self.assertEqual(len(self.core["rules"]), 1)
        rule = self.core["rules"][0]
        self.assertEqual(rule["then"], {"output": OUTPUT, "value": True})
        self.assertEqual(rule["overrides"], [])
        self.assertEqual(
            self.candidate["provisions"][0]["source_quotes"][0]["exact"],
            "十四歳に満たない者の行為は、罰しない。",
        )
        self.assertEqual(self.candidate["references"], [])
        accepted = set(self.review["accepted_assumption_ids"])
        attached = set(self.candidate["provisions"][0]["assumption_ids"])
        self.assertEqual(accepted, attached)
        self.assertIn("A_OTHER_LAW_OUT_OF_SCOPE", accepted)

    def test_host_gold_covers_all_twelve_contexts_and_keeps_absence_one_way(self):
        cases = self.staged["cases"]
        gold = {
            canonical_json(item["input"]): item["expected"][OUTPUT]
            for item in self.review["semantic_tests"]
        }
        self.assertEqual(len(cases), 12)
        self.assertEqual(len(gold), 12)
        self.assertEqual({canonical_json(item["input"]) for item in cases}, set(gold))
        for case in cases:
            expected = gold[canonical_json(case["input"])]
            if case["effective"]:
                self.assertEqual(expected, {"state": "defined", "value": True})
                self.assertEqual(case["input"], {
                    "act_time_status": "established",
                    "age_at_act_status": "established",
                    "age_at_act_years": 13,
                })
            else:
                self.assertEqual(expected, {"state": "absent"})

    def test_staged_counts_show_exactly_one_reachable_context(self):
        self.assertEqual(
            (self.staged["total_contexts"], self.staged["facts_matching_contexts"],
             self.staged["constraints_matching_contexts"],
             self.staged["admitted_contexts"]),
            (12, 12, 12, 12),
        )
        row = self.staged["rules"][0]
        self.assertEqual(
            (row["guard_count"], row["guard_and_facts_count"],
             row["guard_and_constraints_count"], row["enabled_count"],
             row["effective_count"]),
            (1, 1, 1, 1, 1),
        )
        self.assertEqual(row["expectation_result"], "matched_in_scope")
        self.assertEqual(row["attention_codes"], [])

    def test_wrong_package_anchor_is_rejected(self):
        with self.assertRaises(KernelError) as caught:
            verify_interpretation_package(
                self.task, self.candidate, self.review, self.expectations,
                SOURCE / "source-spec.json", SOURCE / "bundle", self.package,
                expected_source_bundle_sha256=SOURCE_BUNDLE_HASH,
                expected_review_sha256=REVIEW_HASH,
                expected_scope_expectations_sha256=EXPECTATIONS_HASH,
                expected_package_sha256="0" * 64,
            )
        self.assertEqual(caught.exception.status, "INTERPRETATION_MISMATCH")


class PenalCode41MutationTests(PenalCode41TestCase):
    def compile_mutation(self, candidate, review, expectations):
        self.refresh_chain(candidate, review, expectations)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate_path = root / "candidate.json"
            review_path = root / "review.json"
            expectations_path = root / "scope-expectations.json"
            package_path = root / "compiled.json"
            self.write_json(candidate_path, candidate)
            self.write_json(review_path, review)
            self.write_json(expectations_path, expectations)
            code, out, err = self.invoke(self.compile_args(
                candidate_path, review_path, expectations_path, package_path))
            return code, json.loads(out), err, package_path.exists()

    def test_less_than_to_less_or_equal_mutation_fails_at_age_fourteen(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        candidate["provisions"][0]["when"]["args"][2]["op"] = "le"
        code, result, err, published = self.compile_mutation(
            candidate, review, expectations)
        self.assertEqual((code, err, published), (1, "", False))
        self.assertEqual(result["status"], "SEMANTIC_MISMATCH")
        self.assertIn("G_14_EST_EST", result["message"])

    def test_removing_either_evidence_gate_is_caught_by_host_gold(self):
        for removed_index, failing_test in ((0, "G_13_UNK_EST"),
                                            (1, "G_13_EST_UNRES")):
            with self.subTest(removed_index=removed_index):
                candidate = deepcopy(self.candidate)
                review = deepcopy(self.review)
                expectations = deepcopy(self.expectations)
                del candidate["provisions"][0]["when"]["args"][removed_index]
                code, result, err, published = self.compile_mutation(
                    candidate, review, expectations)
                self.assertEqual((code, err, published), (1, "", False))
                self.assertEqual(result["status"], "SEMANTIC_MISMATCH")
                self.assertIn(failing_test, result["message"])

    def test_unaccepted_input_contract_assumption_blocks_compilation(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        review["accepted_assumption_ids"].remove("A_COMPLETED_AGE_AT_ACT")
        code, result, err, published = self.compile_mutation(
            candidate, review, expectations)
        self.assertEqual((code, err, published), (1, "", False))
        self.assertEqual(result["status"], "MODEL_INCOMPLETE")

    def test_conflicting_age_facts_are_undetermined_and_publish_nothing(self):
        task = deepcopy(self.task)
        task["core_scope"]["facts"] = [
            {"var": "age_at_act_years", "value": 13},
            {"var": "age_at_act_years", "value": 14},
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task_path = root / "task.json"
            package_path = root / "compiled.json"
            self.write_json(task_path, task)
            args = [
                "compile-interpretation", str(task_path),
                str(EXAMPLE / "candidate.json"), str(EXAMPLE / "review.json"),
                str(EXAMPLE / "scope-expectations.json"),
                "--source-spec", str(SOURCE / "source-spec.json"),
                "--source-bundle", str(SOURCE / "bundle"),
                "--expected-source-bundle-sha256", SOURCE_BUNDLE_HASH,
                "--expected-review-sha256", REVIEW_HASH,
                "--expected-scope-expectations-sha256", EXPECTATIONS_HASH,
                "--package", str(package_path), "--json",
            ]
            code, out, err = self.invoke(args)
            result = json.loads(out)
            self.assertEqual((code, err, package_path.exists()), (2, "", False))
            self.assertEqual(result["status"], "INPUT_INCONSISTENT")
            self.assertEqual(result["finding"], "undetermined")


if __name__ == "__main__":
    unittest.main()
