"""CLI and atomic-publication tests for procedurekernel."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import procedurekernel.__main__ as cli
from procedurekernel.model import canonical_json


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "examples" / "procedures" / "t09-application" / "model.json"


class ProcedureCliTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_generate_verify_json_and_external_anchor(self):
        with tempfile.TemporaryDirectory() as temporary:
            certificate = Path(temporary) / "nested" / "certificate.json"
            code, out, err = self.invoke([
                "generate", str(MODEL), "--certificate", str(certificate), "--json"
            ])
            self.assertEqual(code, 1)
            self.assertFalse(err)
            generated = json.loads(out)
            self.assertEqual(generated["status"], "VERIFIED")
            self.assertTrue(generated["diagnostics"]["has_findings"])
            self.assertEqual(
                certificate.read_bytes(),
                canonical_json(json.loads(certificate.read_bytes())).encode("utf-8"),
            )
            anchor = hashlib.sha256(certificate.read_bytes()).hexdigest()
            code, out, err = self.invoke([
                "verify", str(MODEL), str(certificate),
                "--expected-certificate-sha256", anchor, "--json",
            ])
            self.assertEqual(code, 1)
            self.assertFalse(err)
            self.assertTrue(json.loads(out)["certificate_hash_anchored"])

    def test_existing_model_path_and_limit_never_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing.json"
            sentinel = b"keep"
            existing.write_bytes(sentinel)
            code, out, _ = self.invoke([
                "generate", str(MODEL), "--certificate", str(existing), "--json"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(existing.read_bytes(), sentinel)

            before = MODEL.read_bytes()
            code, out, _ = self.invoke([
                "generate", str(MODEL), "--certificate", str(MODEL), "--json"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(MODEL.read_bytes(), before)

            limited = root / "limited.json"
            code, out, _ = self.invoke([
                "generate", str(MODEL), "--certificate", str(limited),
                "--max-traces-per-context", "10", "--json",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "LIMIT_REACHED")
            self.assertFalse(limited.exists())

    def test_publication_failure_and_race_leave_no_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            failed = root / "new" / "certificate.json"
            with patch.object(cli.os, "link", side_effect=OSError("injected")):
                code, out, _ = self.invoke([
                    "generate", str(MODEL), "--certificate", str(failed), "--json"
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertFalse(failed.exists())
            self.assertEqual(list(failed.parent.iterdir()), [])

            raced = root / "raced.json"
            sentinel = b"winner"
            real_analyze = cli.analyze

            def competing(model, **limits):
                result = real_analyze(model, **limits)
                raced.write_bytes(sentinel)
                return result

            with patch.object(cli, "analyze", side_effect=competing):
                code, out, _ = self.invoke([
                    "generate", str(MODEL), "--certificate", str(raced), "--json"
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(raced.read_bytes(), sentinel)

    def test_bad_certificate_and_wrong_anchor_are_indeterminate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / "bad.json"
            malformed.write_bytes(b'{"format":')
            code, out, _ = self.invoke([
                "verify", str(MODEL), str(malformed), "--json"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")

            saved = ROOT / "examples" / "procedures" / "t09-application" / "certificate.json"
            before = saved.read_bytes()
            code, out, _ = self.invoke([
                "verify", str(MODEL), str(saved),
                "--expected-certificate-sha256", "0" * 64, "--json",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")
            self.assertEqual(saved.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
