"""CLI integration for immutable source packages."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rulekernel.__main__ import main
from rulekernel.source_model import source_canonical_json
from tests.test_source_package import FICTIONAL_RAW, egov_fixture, fictional_spec


class SourceCliTests(unittest.TestCase):
    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        stdout.getvalue().encode("utf-8")
        stderr.getvalue().encode("utf-8")
        return code, stdout.getvalue(), stderr.getvalue()

    def inputs(self, root):
        root = Path(root)
        spec_path = root / "source-spec.json"
        raw_path = root / "source.xml"
        spec_path.write_bytes(source_canonical_json(fictional_spec()).encode("utf-8"))
        raw_path.write_bytes(FICTIONAL_RAW)
        return spec_path, raw_path

    def test_build_and_offline_verify_roundtrip_with_unresolved_reference_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, raw = self.inputs(root)
            bundle = root / "bundle"
            code, out, err = self.invoke([
                "source-build", str(spec), str(raw),
                "--retrieved-at", "2026-09-15T10:00:00Z",
                "--bundle", str(bundle), "--json",
            ])
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            built = json.loads(out)
            self.assertEqual(built["status"], "VERIFIED")
            self.assertEqual(built["unresolved_reference_count"], 1)
            self.assertEqual(built["published_bundle"], str(bundle))
            self.assertTrue(bundle.is_dir())

            code, out, err = self.invoke(
                ["verify-source", str(spec), str(bundle), "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            checked = json.loads(out)
            self.assertEqual(checked["bundle_hash"], built["bundle_hash"])
            self.assertTrue(checked["offline"])

            code, out, err = self.invoke([
                "verify-source", str(spec), str(bundle),
                "--expected-bundle-sha256", built["bundle_hash"], "--json",
            ])
            self.assertEqual((code, err), (1, ""))
            self.assertTrue(json.loads(out)["bundle_hash_anchored"])

            code, out, _ = self.invoke([
                "verify-source", str(spec), str(bundle),
                "--expected-bundle-sha256", "0" * 64, "--json",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "SOURCE_MISMATCH")

    def test_zero_exit_when_every_reference_is_resolved_or_absent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec_value = fictional_spec()
            spec_value["references"] = []
            spec = root / "spec.json"
            raw = root / "source.xml"
            spec.write_bytes(source_canonical_json(spec_value).encode("utf-8"))
            raw.write_bytes(FICTIONAL_RAW)
            bundle = root / "bundle"
            code, out, err = self.invoke([
                "source-build", str(spec), str(raw),
                "--retrieved-at", "2026-09-15T10:00:00Z",
                "--bundle", str(bundle), "--json",
            ])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(out)["unresolved_reference_count"], 0)

    def test_human_output_exposes_bundle_hash_for_external_recording(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec_value = fictional_spec()
            spec_value["references"] = []
            spec = root / "spec.json"
            raw = root / "source.xml"
            bundle = root / "bundle"
            spec.write_bytes(source_canonical_json(spec_value).encode("utf-8"))
            raw.write_bytes(FICTIONAL_RAW)
            code, out, err = self.invoke([
                "source-build", str(spec), str(raw),
                "--retrieved-at", "2026-09-15T10:00:00Z",
                "--bundle", str(bundle),
            ])
            self.assertEqual((code, err), (0, ""))
            lock_hash = hashlib.sha256((bundle / "bundle.lock.json").read_bytes()).hexdigest()
            self.assertIn(f"bundle.lock SHA-256: {lock_hash}", out)
            self.assertIn("外部bundle hash照合: なし", out)

    def test_failed_build_has_no_published_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, raw = self.inputs(root)
            changed = bytearray(raw.read_bytes())
            changed[-2] ^= 1
            raw.write_bytes(changed)
            bundle = root / "bundle"
            code, out, _ = self.invoke([
                "source-build", str(spec), str(raw),
                "--retrieved-at", "2026-09-15T10:00:00Z",
                "--bundle", str(bundle), "--json",
            ])
            self.assertEqual(code, 2)
            failure = json.loads(out)
            self.assertEqual(failure["status"], "SOURCE_MISMATCH")
            self.assertIsNone(failure["published_bundle"])
            self.assertEqual(failure["finding"], "undetermined")
            self.assertFalse(bundle.exists())

    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec, raw = self.inputs(root)
            spec.write_text(json.dumps(fictional_spec(), ensure_ascii=False, indent=2),
                            encoding="utf-8")
            bundle = root / "bundle"
            bundle.mkdir()
            marker = bundle / "keep"
            marker.write_text("old", encoding="utf-8")
            code, out, _ = self.invoke([
                "source-build", str(spec), str(raw),
                "--retrieved-at", "2026-09-15T10:00:00Z",
                "--bundle", str(bundle), "--json",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(marker.read_text(encoding="utf-8"), "old")

    def test_fetch_timeout_must_be_finite_before_network_dispatch(self):
        spec_value, _, _ = egov_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = root / "spec.json"
            spec.write_bytes(source_canonical_json(spec_value).encode("utf-8"))
            with mock.patch("rulekernel.__main__.fetch_egov_source_package") as fetch:
                code, out, _ = self.invoke([
                    "source-fetch-egov", str(spec), "--bundle", str(root / "bundle"),
                    "--timeout", "nan", "--json",
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "SOURCE_INVALID")
            fetch.assert_not_called()

    def test_fetch_dispatches_valid_timeout_and_reports_published_bundle(self):
        spec_value, _, _ = egov_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = root / "spec.json"
            bundle = root / "bundle"
            spec.write_bytes(source_canonical_json(spec_value).encode("utf-8"))
            fetched = {
                "status": "VERIFIED",
                "bundle_hash": "a" * 64,
                "unit_count": 1,
                "unresolved_reference_count": 0,
                "offline": True,
            }
            with mock.patch("rulekernel.__main__.fetch_egov_source_package",
                            return_value=fetched) as fetch:
                code, out, err = self.invoke([
                    "source-fetch-egov", str(spec), "--bundle", str(bundle),
                    "--timeout", "2.5", "--json",
                ])
            self.assertEqual((code, err), (0, ""))
            result = json.loads(out)
            self.assertEqual(result["published_bundle"], str(bundle))
            self.assertEqual(result["bundle_hash"], "a" * 64)
            fetch.assert_called_once_with(str(spec), str(bundle), timeout=2.5)


if __name__ == "__main__":
    unittest.main()
