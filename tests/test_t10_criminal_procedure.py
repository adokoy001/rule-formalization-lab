"""T10 saved criminal-procedure deadline fixture tests."""
from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from procedurekernel.checker import verify
from procedurekernel.model import digest, load_json


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples/procedures/t10-criminal-procedure-203-205"
MODEL_HASH = "e255570d7ff365b4c79afbbcdf2a65bb7e036ee9b10fa507216579560a192f6f"
CERTIFICATE_HASH = "a4e62ff42528c1abe55d4635f7ec3a85019a6fa39b45a47715cf824e647d62b3"
BINDING_HASH = "e76cf9be471e45a5f83cb35083c15470f8f4ff3be6c1424ad3e97aec3b126811"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case(certificate, identifier):
    return next(row for row in certificate["cases"] if row["context_id"] == identifier)


def rule(row, identifier):
    return next(item for item in row["observed_evaluation"]["rules"] if item["norm_id"] == identifier)


class T10CriminalProcedureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_json(PACK / "model.json")
        cls.certificate = load_json(PACK / "certificate.json", max_bytes=8 * 1024 * 1024)
        cls.binding = load_json(PACK / "binding.json", max_bytes=2 * 1024 * 1024)

    def test_saved_hashes_and_independent_certificate_replay(self):
        self.assertEqual(file_hash(PACK / "model.json"), MODEL_HASH)
        self.assertEqual(digest(self.model), MODEL_HASH)
        self.assertEqual(file_hash(PACK / "certificate.json"), CERTIFICATE_HASH)
        self.assertEqual(file_hash(PACK / "binding.json"), BINDING_HASH)
        result = verify(
            self.model,
            self.certificate,
            expected_certificate_sha256=CERTIFICATE_HASH,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["certificate_hash_anchored"])
        self.assertEqual(result["counts"]["total_contexts"], 13)

    def test_article_203_inclusive_edge_and_exclusive_observation_end(self):
        norm = "A203_SEND_48H"
        self.assertEqual(rule(case(self.certificate, "a203_send_at_48"), norm)["status"], "satisfied")
        self.assertEqual(rule(case(self.certificate, "a203_send_after_48"), norm)["status"], "violated_late")
        self.assertEqual(rule(case(self.certificate, "a203_missing_at_48"), norm)["status"], "pending")
        self.assertEqual(rule(case(self.certificate, "a203_missing_after_48"), norm)["status"], "violated_missing")

    def test_article_205_keeps_both_deadlines_independent(self):
        receipt = rule(case(self.certificate, "receipt_24_only_exceeded"), "A205_RECEIPT_24H")
        restraint = rule(case(self.certificate, "receipt_24_only_exceeded"), "A205_RESTRAINT_72H")
        self.assertEqual((receipt["status"], restraint["status"]), ("violated_late", "satisfied"))
        receipt = rule(case(self.certificate, "restraint_72_only_exceeded"), "A205_RECEIPT_24H")
        restraint = rule(case(self.certificate, "restraint_72_only_exceeded"), "A205_RESTRAINT_72H")
        self.assertEqual((receipt["status"], restraint["status"]), ("satisfied", "violated_late"))

    def test_public_prosecution_is_an_any_of_substitute(self):
        row = case(self.certificate, "prosecution_substitute_at_72")
        for norm_id in ("A205_RECEIPT_24H", "A205_RESTRAINT_72H"):
            checked = rule(row, norm_id)
            self.assertEqual(checked["status"], "satisfied")
            self.assertEqual(checked["selected_target"], "public_prosecution")

    def test_no_event_equal_and_after_205_deadline_are_distinct(self):
        at_due = case(self.certificate, "a205_missing_at_72")
        after_due = case(self.certificate, "a205_missing_after_72")
        for norm_id in ("A205_RECEIPT_24H", "A205_RESTRAINT_72H"):
            self.assertEqual(rule(at_due, norm_id)["status"], "pending")
            self.assertEqual(rule(after_due, norm_id)["status"], "violated_missing")

    def test_send_and_receipt_are_separate_events(self):
        row = case(self.certificate, "separate_send_and_receipt")
        events = {item["slot"]: item["at"] for item in row["observed_events"]}
        self.assertEqual(events["send_procedure"], {"tick": 47, "phase": 0})
        self.assertEqual(events["prosecutor_receipt"], {"tick": 60, "phase": 0})
        self.assertNotEqual(events["send_procedure"], events["prosecutor_receipt"])

    def test_article_206_claim_does_not_erase_numeric_exceedance(self):
        row = case(self.certificate, "article206_unresolved_late_request")
        slots = {item["slot"] for item in row["observed_events"]}
        self.assertIn("article206_explanation", slots)
        self.assertEqual(rule(row, "A205_RECEIPT_24H")["status"], "satisfied")
        self.assertEqual(rule(row, "A205_RESTRAINT_72H")["status"], "violated_late")
        self.assertNotIn("article206_assessment", slots)
        self.assertTrue(all("206" not in norm["id"] for norm in self.model["norms"]))

    def test_pack_diagnostics_scan_all_contexts_and_keep_codes_separate(self):
        actual = [
            (row["context_id"], row["code"], row["basis_norm_ids"])
            for row in self.binding["pack_diagnostics"]
        ]
        self.assertEqual(actual, [
            ("a203_missing_after_48", "SELECTED_TEXT_RELEASE_TRIGGERED", ["A203_SEND_48H"]),
            ("a203_send_after_48", "SELECTED_TEXT_RELEASE_TRIGGERED", ["A203_SEND_48H"]),
            ("a205_missing_after_72", "SELECTED_TEXT_RELEASE_TRIGGERED", ["A205_RECEIPT_24H", "A205_RESTRAINT_72H"]),
            ("article206_unresolved_late_request", "SELECTED_TEXT_RELEASE_TRIGGERED", ["A205_RESTRAINT_72H"]),
            ("article206_unresolved_late_request", "ARTICLE_206_ASSESSMENT_UNRESOLVED", []),
            ("receipt_24_only_exceeded", "SELECTED_TEXT_RELEASE_TRIGGERED", ["A205_RECEIPT_24H"]),
            ("release_after_missed_deadlines", "SELECTED_TEXT_RELEASE_TRIGGERED", ["A205_RECEIPT_24H", "A205_RESTRAINT_72H"]),
            ("release_after_missed_deadlines", "RELEASE_OBSERVED", []),
            ("restraint_72_only_exceeded", "SELECTED_TEXT_RELEASE_TRIGGERED", ["A205_RESTRAINT_72H"]),
        ])
        diagnostic_contexts = {row[0] for row in actual}
        self.assertTrue({
            "a203_missing_at_48", "a203_send_at_48", "a205_missing_at_72",
            "all_deadlines_at_edges", "prosecution_substitute_at_72",
            "separate_send_and_receipt",
        }.isdisjoint(diagnostic_contexts))
        self.assertFalse(self.binding["assurance"]["semantic_lowering_proved"])
        self.assertFalse(self.binding["assurance"]["legal_conclusion"])


if __name__ == "__main__":
    unittest.main()
