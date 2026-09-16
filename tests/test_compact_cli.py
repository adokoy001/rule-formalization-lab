"""CLI contracts for compact JSON Lines evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compactkernel import __main__ as cli


ROOT = Path(__file__).resolve().parents[1]
CLUB20 = ROOT / "examples" / "club20"


class CompactCliTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_estimate_check_verify_and_external_anchor(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixed.jsonl"
            code, out, err = self.invoke([
                "estimate", str(CLUB20 / "fixed.json"), "--json",
            ])
            self.assertEqual(code, 0)
            self.assertFalse(err)
            estimate = json.loads(out)
            self.assertEqual(estimate["status"], "ESTIMATE_AVAILABLE")
            self.assertEqual(estimate["concrete_contexts"], 416)
            self.assertEqual(estimate["cell_count"], 64)
            self.assertFalse(estimate["guaranteed_min_exceeds_cap"])

            code, out, err = self.invoke([
                "check", str(CLUB20 / "fixed.json"),
                "--certificate", str(path), "--json",
            ])
            self.assertEqual(code, 0)
            self.assertFalse(err)
            generated = json.loads(out)
            self.assertEqual(generated["status"], "VERIFIED")
            self.assertEqual(generated["published_certificate"], str(path))
            self.assertTrue(path.exists())

            code, out, err = self.invoke([
                "verify", str(CLUB20 / "fixed.json"), str(path),
                "--expected-certificate-sha256",
                generated["certificate_hash"], "--json",
            ])
            self.assertEqual(code, 0)
            self.assertFalse(err)
            self.assertEqual(
                json.loads(out)["certificate_hash"],
                generated["certificate_hash"],
            )

    def test_findings_are_verified_exit_one(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.jsonl"
            code, out, err = self.invoke([
                "check", str(CLUB20 / "broken.json"),
                "--certificate", str(path), "--json",
            ])
            self.assertEqual(code, 1)
            self.assertFalse(err)
            result = json.loads(out)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual(
                sum(query["count"] for query in result["queries"]), 68
            )
            self.assertTrue(path.exists())

    def test_existing_destination_and_model_input_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "existing.jsonl"
            sentinel = b"keep existing bytes"
            existing.write_bytes(sentinel)
            code, out, err = self.invoke([
                "check", str(CLUB20 / "fixed.json"),
                "--certificate", str(existing), "--json",
            ])
            self.assertEqual(code, 2)
            self.assertFalse(err)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(existing.read_bytes(), sentinel)

            model_copy = root / "model.json"
            original = (CLUB20 / "fixed.json").read_bytes()
            model_copy.write_bytes(original)
            code, out, err = self.invoke([
                "check", str(model_copy),
                "--certificate", str(model_copy), "--json",
            ])
            self.assertEqual(code, 2)
            self.assertFalse(err)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(model_copy.read_bytes(), original)

    def test_atomic_link_race_preserves_competing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "raced.jsonl"
            sentinel = b"race winner"
            real_verify = cli.verify_path

            def create_competitor(*args, **kwargs):
                result = real_verify(*args, **kwargs)
                destination.write_bytes(sentinel)
                return result

            with patch.object(cli, "verify_path", side_effect=create_competitor):
                code, out, err = self.invoke([
                    "check", str(CLUB20 / "fixed.json"),
                    "--certificate", str(destination), "--json",
                ])
            self.assertEqual(code, 2)
            self.assertFalse(err)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertIsNone(json.loads(out)["published_certificate"])
            self.assertEqual(destination.read_bytes(), sentinel)
            self.assertFalse(any(root.glob(".compact-*.tmp")))

    def test_temp_unlink_failure_rolls_back_link_and_preserves_original_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "certificate.jsonl"
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
                    "check", str(CLUB20 / "fixed.json"),
                    "--certificate", str(destination), "--json",
                ])
            self.assertEqual(code, 2)
            self.assertFalse(err)
            result = json.loads(out)
            self.assertEqual(result["status"], "IO_ERROR")
            self.assertEqual(result["message"], "injected temp unlink failure")
            self.assertIsNone(result["published_certificate"])
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_unexpected_error_is_sanitized_and_publishes_nothing(self):
        secret = "private compact model fragment"
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "certificate.jsonl"
            with patch.object(
                cli,
                "write_certificate",
                side_effect=RuntimeError(secret),
            ):
                code, out, err = self.invoke([
                    "check", str(CLUB20 / "fixed.json"),
                    "--certificate", str(destination), "--json",
                ])
            self.assertEqual(code, 2)
            self.assertFalse(err)
            result = json.loads(out)
            self.assertEqual(result, {
                "finding": "undetermined",
                "message": "An unexpected internal error occurred",
                "published_certificate": None,
                "status": "INTERNAL_ERROR",
            })
            self.assertNotIn(secret, out)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_truncated_certificate_is_indeterminate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "truncated.jsonl"
            path.write_text('{"record_type":"header"}\n', encoding="utf-8")
            code, out, err = self.invoke([
                "verify", str(CLUB20 / "fixed.json"), str(path), "--json",
            ])
            self.assertEqual(code, 2)
            self.assertFalse(err)
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")


if __name__ == "__main__":
    unittest.main()
