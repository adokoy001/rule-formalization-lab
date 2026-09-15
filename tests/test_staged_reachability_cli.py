"""CLI round trips and exit contracts for staged reachability."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from rulekernel.__main__ import main
from rulekernel.model import canonical_json, digest, load_json
from rulekernel.reachability import analyze_reachability
from rulekernel.staged_reachability_model import core_scope


ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "examples" / "interpretations" / "handbook-scope"
MODEL = HANDBOOK / "core.json"
EXPECTATIONS = HANDBOOK / "scope-expectations.json"
SAVED_CERTIFICATE = HANDBOOK / "staged-reachability.certificate.json"
EXPECTATIONS_HASH = "a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d"
SOURCE = ROOT / "examples" / "sources" / "handbook-scope"
SOURCE_BUNDLE_HASH = "52ca5a149fe1e901b62854ac4b12c613e0ab8261e54a4b6a932f2963bd0dc8e4"
REVIEW_HASH = "493d006fdd1642e7cee25494d144a79a32f06451479d15acd8dac24433cbe2f4"
PACKAGE_HASH = "7d0f1f28e2d84bffffac1281cf5954780e4cbb7ece75aee3f5d00d609608056a"
MEMBER = ROOT / "examples" / "interpretations" / "member-eligibility"
MEMBER_EXPECTATIONS_HASH = (
    "51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8"
)


class StagedReachabilityCliTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(arguments)
        stdout.getvalue().encode("utf-8")
        stderr.getvalue().encode("utf-8")
        return code, stdout.getvalue(), stderr.getvalue()

    def scoped(self, command, *, model=MODEL, certificate=None,
               expectations=EXPECTATIONS, expectation_hash=EXPECTATIONS_HASH):
        arguments = [command, str(model)]
        if command == "verify-reachability-staged":
            arguments.append(str(certificate))
        if expectations is not None:
            arguments.extend(["--scope-expectations", str(expectations)])
        if expectation_hash is not None:
            arguments.extend([
                "--expected-scope-expectations-sha256", expectation_hash,
            ])
        return arguments

    def test_scoped_handbook_fixture_saves_and_rechecks_with_exit_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            certificate = Path(temp) / "staged.json"
            arguments = self.scoped("reachability-staged")
            arguments.extend(["--certificate", str(certificate), "--json"])
            code, out, err = self.invoke(arguments)
            self.assertEqual((code, err), (0, ""))
            result = json.loads(out)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual(result["attention_count"], 0)
            self.assertEqual((result["total_contexts"], result["admitted_contexts"]),
                             (52, 52))
            self.assertTrue(certificate.exists())
            rows = {item["rule_id"]: item for item in result["rules"]}
            self.assertEqual(rows["IR_P_HANDBOOK_AGE_EXCEPTION"]["expectation_result"],
                             "matched_inactive")
            self.assertEqual(rows["IR_P_HANDBOOK_AGE_EXCEPTION"]["guard_count"], 0)
            self.assertEqual(rows["IR_P_HANDBOOK_PAPER"]["effective_count"], 26)

            arguments = self.scoped(
                "verify-reachability-staged", certificate=certificate)
            arguments.append("--json")
            code, replay, err = self.invoke(arguments)
            self.assertEqual((code, err), (0, ""))
            checked = json.loads(replay)
            self.assertEqual(checked["certificate_hash"], result["certificate_hash"])
            self.assertEqual(checked["attention"], [])

    def test_saved_handbook_chain_and_staged_certificate_verify_with_anchors(self):
        code, out, err = self.invoke([
            "verify-source", str(SOURCE / "source-spec.json"),
            str(SOURCE / "bundle"),
            "--expected-bundle-sha256", SOURCE_BUNDLE_HASH, "--json",
        ])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["status"], "VERIFIED")

        code, out, err = self.invoke([
            "verify-interpretation",
            str(HANDBOOK / "task.json"), str(HANDBOOK / "candidate.json"),
            str(HANDBOOK / "review.json"), str(EXPECTATIONS),
            str(HANDBOOK / "compiled.json"),
            "--source-spec", str(SOURCE / "source-spec.json"),
            "--source-bundle", str(SOURCE / "bundle"),
            "--expected-source-bundle-sha256", SOURCE_BUNDLE_HASH,
            "--expected-review-sha256", REVIEW_HASH,
            "--expected-scope-expectations-sha256", EXPECTATIONS_HASH,
            "--expected-package-sha256", PACKAGE_HASH, "--json",
        ])
        self.assertEqual((code, err), (0, ""))
        interpretation = json.loads(out)
        self.assertEqual(interpretation["status"], "LOWERING_VERIFIED")
        compiled = load_json(HANDBOOK / "compiled.json")
        self.assertEqual(load_json(MODEL), compiled["core"])

        arguments = self.scoped(
            "verify-reachability-staged", certificate=SAVED_CERTIFICATE)
        arguments.append("--json")
        code, out, err = self.invoke(arguments)
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["certificate_hash"],
                         "d6e9bf6758ad5277b70accb54647a77b5e3f6f06969974438b4a9a2761082453")

    def test_saved_member_staged_certificate_verifies(self):
        arguments = [
            "verify-reachability-staged", str(MEMBER / "core.json"),
            str(MEMBER / "staged-reachability.certificate.json"),
            "--scope-expectations", str(MEMBER / "scope-expectations.json"),
            "--expected-scope-expectations-sha256", MEMBER_EXPECTATIONS_HASH,
            "--json",
        ]
        code, out, err = self.invoke(arguments)
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["certificate_hash"],
                         "89aee1333f46ddfccf0bfdeac09565297a00b2cd96a9b0fcdf323a0b4ff3202b")
        self.assertEqual(result["attention_count"], 0)

    def test_same_rule_without_expectations_remains_attention_exit_one(self):
        arguments = self.scoped(
            "reachability-staged", expectations=None, expectation_hash=None)
        arguments.append("--json")
        code, out, err = self.invoke(arguments)
        self.assertEqual((code, err), (1, ""))
        result = json.loads(out)
        self.assertEqual(result["attention"], [{
            "code": "INACTIVE_WITHOUT_EXPECTATION",
            "detail": "inactive rule has no explicit expected_inactive decision",
            "rule_id": "IR_P_HANDBOOK_AGE_EXCEPTION",
        }])
        self.assertIsNone(result["scope_expectations_binding"])

    def test_unspecified_and_expected_in_scope_inactive_rule_are_attention(self):
        with tempfile.TemporaryDirectory() as temp:
            for state, code_name in (
                    ("unspecified", "INACTIVE_WITHOUT_EXPECTATION"),
                    ("expected_in_scope", "EXPECTED_IN_SCOPE_NOT_REACHED")):
                with self.subTest(state=state):
                    expectations = deepcopy(load_json(EXPECTATIONS))
                    expectations["rules"][1]["expectation"] = state
                    path = Path(temp) / (state + ".json")
                    path.write_text(canonical_json(expectations), encoding="utf-8")
                    arguments = self.scoped(
                        "reachability-staged", expectations=path,
                        expectation_hash=digest(expectations))
                    arguments.append("--json")
                    exit_code, out, err = self.invoke(arguments)
                    self.assertEqual((exit_code, err), (1, ""))
                    result = json.loads(out)
                    self.assertEqual(result["attention"][0]["code"], code_name)

    def test_stale_model_binding_is_exit_two_without_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            widened = load_json(MODEL)
            widened["inputs"]["age"]["max"] = 26
            model_path = Path(temp) / "widened.json"
            model_path.write_text(canonical_json(widened), encoding="utf-8")
            arguments = self.scoped("reachability-staged", model=model_path)
            arguments.append("--json")
            code, out, err = self.invoke(arguments)
            self.assertEqual((code, err), (2, ""))
            failure = json.loads(out)
            self.assertEqual(failure["status"], "EXPECTATIONS_MISMATCH")
            self.assertEqual(failure["finding"], "undetermined")

    def test_reanchored_inactive_expectation_detects_widened_domain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            widened = load_json(MODEL)
            widened["inputs"]["age"]["max"] = 26
            expectations = load_json(EXPECTATIONS)
            expectations["core_model_hash"] = digest(widened)
            expectations["scope_hash"] = digest(core_scope(widened))
            model_path = root / "widened.json"
            expectations_path = root / "expectations.json"
            model_path.write_text(canonical_json(widened), encoding="utf-8")
            expectations_path.write_text(canonical_json(expectations), encoding="utf-8")
            arguments = self.scoped(
                "reachability-staged", model=model_path,
                expectations=expectations_path,
                expectation_hash=digest(expectations))
            arguments.append("--json")
            code, out, err = self.invoke(arguments)
            self.assertEqual((code, err), (1, ""))
            result = json.loads(out)
            finding = next(item for item in result["attention"]
                           if item["rule_id"] == "IR_P_HANDBOOK_AGE_EXCEPTION")
            self.assertEqual(finding["code"], "EXPECTED_INACTIVE_BUT_REACHED")
            row = next(item for item in result["rules"]
                       if item["rule_id"] == "IR_P_HANDBOOK_AGE_EXCEPTION")
            self.assertEqual(row["guard_count"], 2)
            self.assertEqual(row["guard_witness"], {
                "case_index": 52, "input": {"age": 26, "student": False},
            })

    def test_expectation_path_and_hash_must_be_supplied_together(self):
        cases = [
            self.scoped("reachability-staged", expectation_hash=None),
            self.scoped("reachability-staged", expectations=None),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                arguments.append("--json")
                code, out, err = self.invoke(arguments)
                self.assertEqual((code, err), (2, ""))
                self.assertEqual(json.loads(out)["status"], "EXPECTATIONS_INVALID")

    def test_certificate_cannot_overwrite_model_or_expectations(self):
        for destination in (MODEL, EXPECTATIONS):
            before = Path(destination).read_bytes()
            arguments = self.scoped("reachability-staged")
            arguments.extend(["--certificate", str(destination), "--json"])
            code, out, _ = self.invoke(arguments)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(Path(destination).read_bytes(), before)

    def test_bound_certificate_cannot_be_checked_without_its_expectations(self):
        with tempfile.TemporaryDirectory() as temp:
            certificate = Path(temp) / "staged.json"
            arguments = self.scoped("reachability-staged")
            arguments.extend(["--certificate", str(certificate), "--json"])
            self.assertEqual(self.invoke(arguments)[0], 0)
            arguments = self.scoped(
                "verify-reachability-staged", certificate=certificate,
                expectations=None, expectation_hash=None)
            arguments.append("--json")
            code, out, err = self.invoke(arguments)
            self.assertEqual((code, err), (2, ""))
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")

    def test_legacy_certificate_is_not_accepted_as_staged(self):
        with tempfile.TemporaryDirectory() as temp:
            certificate = Path(temp) / "legacy.json"
            legacy = analyze_reachability(load_json(MODEL))
            certificate.write_text(canonical_json(legacy), encoding="utf-8")
            arguments = self.scoped(
                "verify-reachability-staged", certificate=certificate,
                expectations=None, expectation_hash=None)
            arguments.append("--json")
            code, out, err = self.invoke(arguments)
            self.assertEqual((code, err), (2, ""))
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")

    def test_human_output_explains_finite_hint_and_semantic_boundary(self):
        arguments = self.scoped("reachability-staged")
        code, out, err = self.invoke(arguments)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("段階別到達可能性証拠検査: VERIFIED", out)
        self.assertIn("guard+facts", out)
        self.assertIn("有限範囲hint", out)
        self.assertIn("matched_inactive", out)
        self.assertIn("一般の論理矛盾", out)


if __name__ == "__main__":
    unittest.main()
