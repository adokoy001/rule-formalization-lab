"""CLI integration tests for reviewed interpretation lowering."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from rulekernel.__main__ import main
from rulekernel.interpretation_model import (
    canonical_json,
    interpretation_digest,
    load_interpretation_json,
)
from tests.test_interpretation import (
    EXAMPLE,
    EXPECTATIONS_HASH,
    PACKAGE_HASH,
    REVIEW_HASH,
    SOURCE,
    SOURCE_BUNDLE_HASH,
)


class InterpretationCliTests(unittest.TestCase):
    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        stdout.getvalue().encode("utf-8")
        stderr.getvalue().encode("utf-8")
        return code, stdout.getvalue(), stderr.getvalue()

    def common(self, command, *, candidate=EXAMPLE / "candidate.json",
               review=EXAMPLE / "review.json",
               review_hash=REVIEW_HASH, output=None):
        args = [
            command,
            str(EXAMPLE / "task.json"),
            str(candidate),
            str(review),
            str(EXAMPLE / "scope-expectations.json"),
        ]
        if command == "verify-interpretation":
            args.append(str(EXAMPLE / "compiled.json") if output is None else str(output))
        args.extend([
            "--source-spec", str(SOURCE / "source-spec.json"),
            "--source-bundle", str(SOURCE / "bundle"),
            "--expected-source-bundle-sha256", SOURCE_BUNDLE_HASH,
            "--expected-review-sha256", review_hash,
            "--expected-scope-expectations-sha256", EXPECTATIONS_HASH,
        ])
        return args

    def test_compile_publishes_only_after_independent_check(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "compiled.json"
            args = self.common("compile-interpretation")
            args.extend(["--package", str(package), "--json"])
            code, out, err = self.invoke(args)
            self.assertEqual((code, err), (0, ""))
            result = json.loads(out)
            self.assertEqual(result["status"], "LOWERING_VERIFIED")
            self.assertEqual(result["published_package"], str(package))
            self.assertEqual(result["package_hash"], PACKAGE_HASH)
            self.assertFalse(result["package_hash_anchored"])
            self.assertEqual(package.read_bytes(),
                             canonical_json(load_interpretation_json(package)).encode("utf-8"))

    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "compiled.json"
            package.write_text("keep", encoding="utf-8")
            before = package.read_bytes()
            args = self.common("compile-interpretation")
            args.extend(["--package", str(package), "--json"])
            code, out, _ = self.invoke(args)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertIsNone(json.loads(out)["published_package"])
            self.assertEqual(package.read_bytes(), before)

    def test_pending_review_returns_attention_and_leaves_no_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            review = deepcopy(load_interpretation_json(EXAMPLE / "review.json"))
            review["state"] = "pending"
            review_path = root / "pending.json"
            review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            package = root / "compiled.json"
            args = self.common(
                "compile-interpretation", review=review_path,
                review_hash=interpretation_digest(review),
            )
            args.extend(["--package", str(package), "--json"])
            code, out, err = self.invoke(args)
            self.assertEqual((code, err), (1, ""))
            failure = json.loads(out)
            self.assertEqual(failure["status"], "REVIEW_REQUIRED")
            self.assertEqual(failure["finding"], "attention")
            self.assertIsNone(failure["published_package"])
            self.assertFalse(package.exists())

    def test_malformed_enum_json_returns_structured_error_and_leaves_no_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = deepcopy(load_interpretation_json(EXAMPLE / "candidate.json"))
            review = deepcopy(load_interpretation_json(EXAMPLE / "review.json"))
            candidate["provisions"][0]["condition_role"] = []
            review["candidate_hash"] = interpretation_digest(candidate)
            candidate_path = root / "candidate.json"
            review_path = root / "review.json"
            candidate_path.write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
            review_path.write_text(
                json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            package = root / "compiled.json"
            args = self.common(
                "compile-interpretation", candidate=candidate_path,
                review=review_path, review_hash=interpretation_digest(review),
            )
            args.extend(["--package", str(package), "--json"])
            code, out, err = self.invoke(args)
            self.assertEqual((code, err), (2, ""))
            failure = json.loads(out)
            self.assertEqual(failure["status"], "UNSUPPORTED")
            self.assertEqual(failure["finding"], "undetermined")
            self.assertIsNone(failure["published_package"])
            self.assertFalse(package.exists())

    def test_verify_saved_package_with_external_hash(self):
        args = self.common("verify-interpretation")
        args.extend(["--expected-package-sha256", PACKAGE_HASH, "--json"])
        code, out, err = self.invoke(args)
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertTrue(result["package_hash_anchored"])
        self.assertTrue(result["source_bundle_hash_anchored"])
        self.assertTrue(result["review_hash_anchored"])
        self.assertEqual(result["semantic_correspondence"], "HOST_REVIEW_RECORDED")
        self.assertEqual(result["review_method"], "manual_fixture_review")
        self.assertTrue(result["provisional"])

    def test_wrong_package_anchor_is_undetermined_exit_two(self):
        args = self.common("verify-interpretation")
        args.extend(["--expected-package-sha256", "0" * 64, "--json"])
        code, out, _ = self.invoke(args)
        self.assertEqual(code, 2)
        failure = json.loads(out)
        self.assertEqual(failure["status"], "INTERPRETATION_MISMATCH")
        self.assertEqual(failure["finding"], "undetermined")

    def test_compile_output_cannot_pollute_immutable_source_bundle(self):
        package = SOURCE / "bundle" / "forbidden.json"
        self.assertFalse(package.exists())
        args = self.common("compile-interpretation")
        args.extend(["--package", str(package), "--json"])
        code, out, _ = self.invoke(args)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["status"], "IO_ERROR")
        self.assertFalse(package.exists())

    def test_human_output_keeps_lowering_and_meaning_review_separate(self):
        args = self.common("verify-interpretation")
        args.extend(["--expected-package-sha256", PACKAGE_HASH])
        code, out, err = self.invoke(args)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("解釈IR package独立再検査: LOWERING_VERIFIED", out)
        self.assertIn("意味対応状態: HOST_REVIEW_RECORDED", out)
        self.assertIn("原文解釈の正しさ", out)
        self.assertIn(PACKAGE_HASH, out)


if __name__ == "__main__":
    unittest.main()
