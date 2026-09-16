"""Saved T09 fixture, producer mutation, and certificate tamper tests."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from procedurekernel import engine
from procedurekernel.checker import verify
from procedurekernel.model import KernelError, digest, load_json


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "procedures" / "t09-application"
MODEL_PATH = FIXTURE / "model.json"
CERTIFICATE_PATH = FIXTURE / "certificate.json"
SOURCE_PATH = FIXTURE / "source.txt"
SOURCE_HASH = "4acc5e7adecac51cade440c5beae5053952ea9c32835a2f75146acec859e929c"
MODEL_HASH = "e614d11bad5a2cd4026c5dc15aac94c547f9233d0acbe32bff0022848218a67c"
CERTIFICATE_HASH = "4d034bb60c7a038fde3747ef26202e6b14a7d560360da200a2efbd438a71bca7"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case(certificate, identifier):
    return next(row for row in certificate["cases"] if row["context_id"] == identifier)


def rule(row, identifier):
    return next(item for item in row["observed_evaluation"]["rules"] if item["norm_id"] == identifier)


class T09SavedExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_json(MODEL_PATH)
        cls.certificate = load_json(CERTIFICATE_PATH, max_bytes=8 * 1024 * 1024)

    def assert_status(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)

    def test_saved_hashes_and_external_replay(self):
        self.assertEqual(file_hash(SOURCE_PATH), SOURCE_HASH)
        self.assertEqual(file_hash(MODEL_PATH), MODEL_HASH)
        self.assertEqual(digest(self.model), MODEL_HASH)
        self.assertEqual(file_hash(CERTIFICATE_PATH), CERTIFICATE_HASH)
        result = verify(
            self.model,
            self.certificate,
            expected_certificate_sha256=CERTIFICATE_HASH,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["certificate_hash_anchored"])
        self.assertEqual(engine.analyze(self.model), self.certificate)

    def test_fictional_source_and_model_have_exact_small_scope(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertEqual(len(self.model["slots"]), 5)
        self.assertEqual(len(self.model["norms"]), 5)
        self.assertEqual(len(self.model["background_constraints"]), 4)
        for norm in self.model["norms"]:
            self.assertIn(norm["source"], source)

    def test_exact_counts_and_one_bad_context_is_not_hidden(self):
        self.assertEqual(self.certificate["enumeration"]["context_count"], 16)
        self.assertEqual(self.certificate["counts"]["feasibility"], {
            "background_trace_impossible": 1,
            "completion_unresolved": 2,
            "compliance_feasible": 10,
            "normatively_infeasible": 3,
        })
        self.assertEqual(self.certificate["counts"]["observed_outcomes"], {
            "background_violated": 1,
            "fulfilled": 5,
            "pending": 2,
            "unresolved_anchor": 4,
            "unresolved_time": 1,
            "violated": 3,
        })
        self.assertEqual(case(self.certificate, "decision_at_deadline")["classification"], "compliance_feasible")
        self.assertEqual(case(self.certificate, "decision_after_deadline")["classification"], "normatively_infeasible")

    def test_before_equal_after_different_anchors_and_same_time(self):
        norm_id = "O_DECISION_BY_RECEIPT_PLUS_5"
        for identifier, expected in (
            ("decision_before_deadline", "satisfied"),
            ("decision_at_deadline", "satisfied"),
            ("decision_after_deadline", "violated_late"),
            ("different_anchors", "satisfied"),
        ):
            self.assertEqual(rule(case(self.certificate, identifier), norm_id)["status"], expected)
        self.assertEqual(case(self.certificate, "same_tick_phase_order")["classification"], "compliance_feasible")
        self.assertEqual(case(self.certificate, "simultaneous_non_strict")["classification"], "compliance_feasible")
        self.assertEqual(case(self.certificate, "simultaneous_strict_background_failure")["classification"], "background_trace_impossible")

    def test_partial_prohibition_has_forbidden_and_later_compliant_branches(self):
        row = case(self.certificate, "partial_prohibition_later_candidate")
        self.assertEqual(row["candidate_trace_count"], 12)
        self.assertEqual(row["classification"], "compliance_feasible")
        by_review = {}
        for trace in row["traces"]:
            choice = trace["choice"]["review"]
            if choice is not None and trace["choice"]["decision"] is not None and trace["choice"]["notice"] is not None:
                by_review[(choice["tick"], choice["phase"])] = trace
        self.assertTrue(by_review[(2, 0)]["definitely_violated"])
        self.assertTrue(by_review[(3, 0)]["fully_satisfied"])

    def test_exclusive_observation_end_before_equal_after_inclusive_deadline(self):
        norm_id = "O_NOTICE_BY_DECISION_PLUS_2"
        before = rule(case(self.certificate, "notice_missing_before_deadline"), norm_id)
        equal = rule(case(self.certificate, "notice_missing_at_inclusive_deadline"), norm_id)
        after = rule(case(self.certificate, "notice_missing_after_inclusive_deadline"), norm_id)
        self.assertEqual(before["status"], "pending")
        self.assertEqual(equal["status"], "pending")
        self.assertEqual(after["status"], "violated_missing")

    def test_anchor_missing_and_time_unknown_are_not_problem_free(self):
        self.assertEqual(case(self.certificate, "anchor_missing")["observed_outcome"], "unresolved_anchor")
        self.assertEqual(case(self.certificate, "anchor_time_unresolved")["observed_outcome"], "unresolved_time")

    def test_checker_rejects_boundary_order_and_observation_mutations(self):
        mutations = []
        with patch.object(engine, "_deadline_allows", side_effect=lambda target, due, inclusive: (target["tick"], target["phase"]) < (due["tick"], due["phase"])):
            mutations.append(engine.analyze(self.model))
        with patch.object(engine, "_coord_lt", side_effect=lambda left, right: (left["tick"], left["phase"]) <= (right["tick"], right["phase"])):
            mutations.append(engine.analyze(self.model))
        with patch.object(engine, "_deadline_missed_at_observation_end", side_effect=lambda end, due, inclusive: (end["tick"], end["phase"]) >= (due["tick"], due["phase"])):
            mutations.append(engine.analyze(self.model))
        for faulty in mutations:
            self.assertNotEqual(faulty, self.certificate)
            self.assert_status("CERTIFICATE_INVALID", verify, self.model, faulty)

    def test_branch_missing_duplicate_order_aggregate_witness_and_hash_tampering(self):
        changes = []
        changed = deepcopy(self.certificate)
        changed["cases"][0]["traces"].pop()
        changes.append(changed)
        changed = deepcopy(self.certificate)
        changed["cases"][7]["traces"][1] = deepcopy(changed["cases"][7]["traces"][0])
        changes.append(changed)
        changed = deepcopy(self.certificate)
        changed["cases"][7]["traces"].reverse()
        changes.append(changed)
        changed = deepcopy(self.certificate)
        changed["counts"]["feasibility"]["compliance_feasible"] += 1
        changes.append(changed)
        changed = deepcopy(self.certificate)
        witness_case = next(
            row for row in changed["cases"] if row["first_compliance_witness"] is not None
        )
        witness_case["first_compliance_witness"]["trace_index"] = 99
        changes.append(changed)
        changed = deepcopy(self.certificate)
        changed["model_hash"] = "0" * 64
        changes.append(changed)
        for changed in changes:
            self.assert_status("CERTIFICATE_INVALID", verify, self.model, changed)

    def test_changed_model_cannot_reuse_certificate(self):
        changed = deepcopy(self.model)
        changed["title"] += " changed"
        self.assert_status("CERTIFICATE_INVALID", verify, changed, self.certificate)


if __name__ == "__main__":
    unittest.main()
