import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rulekernel import checker, engine
from rulekernel.__main__ import main
from rulekernel.model import KernelError, canonical_json, load_json

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        # Also prove error diagnostics can actually be encoded by a UTF-8 terminal.
        out.getvalue().encode("utf-8")
        err.getvalue().encode("utf-8")
        return code, out.getvalue(), err.getvalue()

    def test_check_save_verify_roundtrip_and_exit_status(self):
        for filename, expected_code in (("club-broken.json", 1), ("club-fixed.json", 0)):
            with self.subTest(model=filename), tempfile.TemporaryDirectory() as temp:
                source = str(ROOT / "examples" / filename)
                evidence = str(Path(temp) / "nested" / "evidence.json")
                code, out, err = self.invoke(["check", source, "--certificate", evidence, "--json"])
                self.assertEqual(code, expected_code)
                self.assertFalse(err)
                result = json.loads(out)
                self.assertEqual(result["status"], "VERIFIED")
                self.assertEqual(result["total_contexts"], 52)
                code, out, err = self.invoke(["verify", source, evidence, "--json"])
                self.assertEqual(code, expected_code)
                self.assertFalse(err)
                self.assertEqual(json.loads(out)["certificate_hash"], result["certificate_hash"])

    def test_bad_certificate_json_has_distinct_status(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text('{"format":', encoding="utf-8")
            code, out, _ = self.invoke(["verify", str(ROOT / "examples/club-fixed.json"),
                                       str(path), "--json"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")

    def test_input_file_cannot_be_overwritten_by_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.json"
            content = (ROOT / "examples/club-fixed.json").read_bytes()
            path.write_bytes(content)
            code, out, _ = self.invoke(["check", str(path), "--certificate", str(path), "--json"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(path.read_bytes(), content)

    def test_limit_does_not_write_success_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "evidence.json"
            code, out, _ = self.invoke(["check", str(ROOT / "examples/club-fixed.json"),
                                       "--certificate", str(evidence), "--max-contexts", "51", "--json"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "LIMIT_REACHED")
            self.assertEqual(json.loads(out)["finding"], "undetermined")
            self.assertFalse(evidence.exists())

    def test_invalid_unicode_and_duplicate_surrogate_keys_do_not_crash(self):
        for payload in (b'{"\\ud800":1,"\\ud800":2}', b'{"x":"\\ud800"}'):
            for json_output in (True, False):
                with self.subTest(payload=payload, json=json_output), tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "model.json"
                    path.write_bytes(payload)
                    code, out, err = self.invoke(["check", str(path)] + (["--json"] if json_output else []))
                    self.assertEqual(code, 2)
                    self.assertIn("MODEL_INVALID", out if json_output else err)

    def test_empty_query_set_is_explicit_in_human_report(self):
        model = load_json(ROOT / "examples/club-fixed.json")
        model.update(outputs={}, rules=[])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.json"
            path.write_text(canonical_json(model), encoding="utf-8")
            code, out, err = self.invoke(["check", str(path)])
            self.assertEqual(code, 0)
            self.assertIn("照会は0件", out)
            self.assertFalse(err)


class ResourceLimitTests(unittest.TestCase):
    def test_int64_domain_is_rejected_before_materializing_range(self):
        model = load_json(ROOT / "examples/club-fixed.json")
        model["inputs"]["age"].update(min=-(2**63), max=2**63 - 1)
        with self.assertRaises(KernelError) as error:
            engine.analyze(model)
        self.assertEqual(error.exception.status, "LIMIT_REACHED")

    def test_evidence_generation_and_replay_have_byte_budgets(self):
        model = load_json(ROOT / "examples/club-fixed.json")
        for module, call in (
            (engine, lambda: engine.analyze(model)),
            (checker, lambda: checker.verify(model, {})),
        ):
            with self.subTest(module=module.__name__):
                with patch.object(module, "MAX_CERTIFICATE_BYTES", 512):
                    with self.assertRaises(KernelError) as error:
                        call()
                self.assertEqual(error.exception.status, "LIMIT_REACHED")

    def test_checker_rejects_oversized_supplied_evidence(self):
        model = load_json(ROOT / "examples/club-fixed.json")
        with patch.object(checker, "MAX_CERTIFICATE_BYTES", 512):
            with self.assertRaises(KernelError) as error:
                checker.verify(model, {"padding": "x" * 513})
        self.assertEqual(error.exception.status, "CERTIFICATE_INVALID")


if __name__ == "__main__":
    unittest.main()
