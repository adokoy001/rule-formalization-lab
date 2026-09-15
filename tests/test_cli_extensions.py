"""CLI integration for revision diff and rule reachability evidence."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from rulekernel.__main__ import main


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples" / "club20"


class ExtendedCliTests(unittest.TestCase):
    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        out.getvalue().encode("utf-8")
        err.getvalue().encode("utf-8")
        return code, out.getvalue(), err.getvalue()

    def test_diff_save_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "nested" / "diff.json"
            args = ["diff", str(PACK / "broken.json"), str(PACK / "fixed.json"),
                    "--certificate", str(evidence), "--json"]
            code, out, err = self.invoke(args)
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            result = json.loads(out)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual((result["total_contexts"], result["common_admitted_contexts"]),
                             (416, 416))
            findings = {(item["output"], item["kind"]): item["count"]
                        for item in result["queries"] if item["count"]}
            self.assertEqual(findings, {
                ("eligible", "semantic_change"): 32,
                ("eligible", "conflict_resolved"): 32,
                ("fee_yen", "semantic_change"): 32,
                ("fee_yen", "gap_resolved"): 32,
                ("loan_limit", "semantic_change"): 4,
                ("loan_limit", "conflict_resolved"): 4,
            })
            replay = ["verify-diff", str(PACK / "broken.json"), str(PACK / "fixed.json"),
                      str(evidence), "--json"]
            code, out, err = self.invoke(replay)
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            verified = json.loads(out)
            self.assertEqual(verified["certificate_hash"], result["certificate_hash"])
            self.assertEqual(verified["queries"], result["queries"])

    def test_identical_diff_has_zero_exit(self):
        model = str(PACK / "fixed.json")
        code, out, err = self.invoke(["diff", model, model, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        result = json.loads(out)
        self.assertTrue(all(item["count"] == 0 for item in result["queries"]))

    def test_reachability_save_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "reachability.json"
            model = str(PACK / "broken.json")
            code, out, err = self.invoke(
                ["reachability", model, "--certificate", str(evidence), "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            result = json.loads(out)
            rules = {item["rule_id"]: item for item in result["rules"]}
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual((result["total_contexts"], result["admitted_contexts"]),
                             (416, 416))
            self.assertEqual(rules["R20"]["classification"], "unreachable")
            self.assertEqual((rules["R20"]["enabled_count"], rules["R20"]["effective_count"]),
                             (0, 0))
            replay = ["verify-reachability", model, str(evidence), "--json"]
            code, out, err = self.invoke(replay)
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            verified = json.loads(out)
            self.assertEqual(verified["certificate_hash"], result["certificate_hash"])
            self.assertEqual(verified["rules"], result["rules"])

    def test_malformed_extension_certificates_have_certificate_status(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "bad.json"
            evidence.write_text('{"format":', encoding="utf-8")
            broken, fixed = str(PACK / "broken.json"), str(PACK / "fixed.json")
            commands = [
                ["verify-diff", broken, fixed, str(evidence), "--json"],
                ["verify-reachability", broken, str(evidence), "--json"],
            ]
            for command in commands:
                with self.subTest(command=command[0]):
                    code, out, _ = self.invoke(command)
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")

    def test_extension_outputs_cannot_overwrite_model_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            left = Path(temp) / "left.json"
            right = Path(temp) / "right.json"
            left.write_bytes((PACK / "broken.json").read_bytes())
            right.write_bytes((PACK / "fixed.json").read_bytes())
            original_left, original_right = left.read_bytes(), right.read_bytes()
            commands = [
                ["diff", str(left), str(right), "--certificate", str(left), "--json"],
                ["diff", str(left), str(right), "--certificate", str(right), "--json"],
                ["reachability", str(left), "--certificate", str(left), "--json"],
            ]
            for command in commands:
                with self.subTest(command=command[0], target=command[-2]):
                    code, out, _ = self.invoke(command)
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(out)["status"], "IO_ERROR")
                    self.assertEqual(left.read_bytes(), original_left)
                    self.assertEqual(right.read_bytes(), original_right)

    def test_extension_limit_does_not_write_partial_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            broken, fixed = str(PACK / "broken.json"), str(PACK / "fixed.json")
            for command in ("diff", "reachability"):
                with self.subTest(command=command):
                    evidence = Path(temp) / f"{command}.json"
                    argv = ([command, broken, fixed] if command == "diff" else [command, broken])
                    argv += ["--certificate", str(evidence), "--max-contexts", "415", "--json"]
                    code, out, _ = self.invoke(argv)
                    self.assertEqual(code, 2)
                    self.assertEqual(json.loads(out)["status"], "LIMIT_REACHED")
                    self.assertFalse(evidence.exists())


if __name__ == "__main__":
    unittest.main()
