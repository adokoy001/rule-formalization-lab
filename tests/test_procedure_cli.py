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

    def test_temp_unlink_failure_rolls_back_link_and_preserves_original_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "certificate.json"
            real_unlink = cli.os.unlink
            failed = False

            def fail_first_temp_unlink(path):
                nonlocal failed
                if Path(path) != destination and not failed:
                    failed = True
                    raise OSError("injected temp unlink failure")
                return real_unlink(path)

            with patch.object(cli.os, "unlink", side_effect=fail_first_temp_unlink):
                code, out, err = self.invoke([
                    "generate", str(MODEL), "--certificate", str(destination), "--json"
                ])
            self.assertEqual(code, 2)
            self.assertFalse(err)
            result = json.loads(out)
            self.assertEqual(result["status"], "IO_ERROR")
            self.assertEqual(result["message"], "injected temp unlink failure")
            self.assertIsNone(result["published_certificate"])
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_unexpected_generation_error_is_sanitized_and_publishes_nothing(self):
        secret = "private procedure input from RuntimeError"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for json_mode in (False, True):
                with self.subTest(json_mode=json_mode):
                    destination = root / f"unexpected-{json_mode}.json"
                    arguments = [
                        "generate", str(MODEL), "--certificate", str(destination)
                    ]
                    if json_mode:
                        arguments.append("--json")
                    with patch.object(cli, "analyze", side_effect=RuntimeError(secret)):
                        code, out, err = self.invoke(arguments)
                    self.assertEqual(code, 2)
                    self.assertFalse(destination.exists())
                    self.assertNotIn(secret, out + err)
                    self.assertNotIn("Traceback", out + err)
                    if json_mode:
                        self.assertFalse(err)
                        self.assertEqual(json.loads(out), {
                            "finding": "undetermined",
                            "message": "An unexpected internal error occurred",
                            "published_certificate": None,
                            "status": "INTERNAL_ERROR",
                        })
                    else:
                        self.assertFalse(out)
                        self.assertIn("INTERNAL_ERROR", err)
                        self.assertIn("Verification is undetermined.", err)

    def test_unexpected_error_after_link_rolls_back_published_inode(self):
        secret = "directory fsync RuntimeError"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "certificate.json"
            real_fsync = cli.os.fsync
            calls = 0

            def fail_second_fsync(file_descriptor):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError(secret)
                return real_fsync(file_descriptor)

            with patch.object(cli.os, "fsync", side_effect=fail_second_fsync):
                code, out, err = self.invoke([
                    "generate", str(MODEL), "--certificate", str(destination), "--json"
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "INTERNAL_ERROR")
            self.assertFalse(err)
            self.assertNotIn(secret, out)
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.iterdir()), [])

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
