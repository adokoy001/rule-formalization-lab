"""CLI publication, exit-status, and external-anchor tests for normkernel."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import normkernel.__main__ as cli
from normkernel.model import canonical_json


def const(value):
    return {"const": value}


def action_ref(name):
    return {"action": name}


def norm(identifier, kind, content):
    return {
        "id": identifier,
        "source": "架空の規範 " + identifier,
        "kind": kind,
        "when": const(True),
        "content": content,
    }


def model(*, inputs=None, actions=None, norms=None):
    return {
        "profile": "finite-norms/1",
        "origin_kind": "authored_normative_core",
        "title": "架空のCLI規範",
        "inputs": {"flag": {"kind": "bool"}} if inputs is None else inputs,
        "facts": [],
        "constraints": [],
        "actions": ["A"] if actions is None else actions,
        "action_constraints": [],
        "norms": [] if norms is None else norms,
    }


class NormativeCliTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(arguments)
        stdout.getvalue().encode("utf-8")
        stderr.getvalue().encode("utf-8")
        return code, stdout.getvalue(), stderr.getvalue()

    def write_model(self, root, value):
        path = Path(root) / "model.json"
        path.write_text(canonical_json(value), encoding="utf-8", newline="\n")
        return path

    def test_check_verify_roundtrip_and_external_certificate_anchor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = self.write_model(root, model())
            certificate_path = root / "nested" / "certificate.json"
            code, out, err = self.invoke([
                "check", str(model_path), "--certificate", str(certificate_path), "--json"
            ])
            self.assertEqual(code, 0)
            self.assertFalse(err)
            generated = json.loads(out)
            self.assertEqual(generated["status"], "VERIFIED")
            self.assertFalse(generated["certificate_hash_anchored"])
            self.assertEqual(generated["published_certificate"], str(certificate_path))
            self.assertTrue(certificate_path.is_file())
            self.assertEqual(
                certificate_path.read_bytes(),
                canonical_json(json.loads(certificate_path.read_bytes())).encode("utf-8"),
            )
            external_hash = hashlib.sha256(certificate_path.read_bytes()).hexdigest()
            self.assertEqual(external_hash, generated["certificate_hash"])

            code, out, err = self.invoke([
                "verify", str(model_path), str(certificate_path),
                "--expected-certificate-sha256", external_hash, "--json",
            ])
            self.assertEqual(code, 0)
            self.assertFalse(err)
            checked = json.loads(out)
            self.assertEqual(checked["status"], "VERIFIED")
            self.assertTrue(checked["certificate_hash_anchored"])
            self.assertEqual(checked["certificate_hash"], external_hash)
            self.assertEqual(checked["certificate"], str(certificate_path))

    def test_each_diagnostic_class_causes_exit_one_after_verified_replay(self):
        cases = []

        normative = model(inputs={}, norms=[norm("O_FALSE", "obligation", const(False))])
        cases.append((normative, {"normatively_infeasible_contexts": 1}))

        background = model(inputs={})
        background["action_constraints"] = [const(False)]
        cases.append((background, {"background_trace_impossible_contexts": 1}))

        permission = model(
            inputs={},
            norms=[
                norm("F_A", "prohibition", action_ref("A")),
                norm("P_A", "explicit_permission", action_ref("A")),
                norm("P_A_AGAIN", "explicit_permission", action_ref("A")),
            ],
        )
        cases.append((permission, {
            "unusable_permission_context_pairs": 2,
            "contexts_with_unusable_permissions": 1,
        }))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, (value, expected_diagnostics) in enumerate(cases):
                with self.subTest(diagnostics=expected_diagnostics):
                    model_path = root / f"model-{index}.json"
                    certificate_path = root / f"certificate-{index}.json"
                    model_path.write_text(canonical_json(value), encoding="utf-8")
                    code, out, err = self.invoke([
                        "check", str(model_path), "--certificate", str(certificate_path),
                        "--json",
                    ])
                    self.assertEqual(code, 1)
                    self.assertFalse(err)
                    result = json.loads(out)
                    self.assertEqual(result["status"], "VERIFIED")
                    self.assertTrue(result["diagnostics"]["has_findings"])
                    for diagnostic, expected in expected_diagnostics.items():
                        self.assertEqual(result["diagnostics"][diagnostic], expected)
                    self.assertTrue(certificate_path.is_file())

    def test_invalid_model_limit_and_bad_certificate_are_exit_two(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            invalid = model()
            invalid["norms"] = [norm("N", "power", action_ref("A"))]
            invalid_path = self.write_model(root, invalid)
            output = root / "invalid.certificate.json"
            code, out, _ = self.invoke([
                "check", str(invalid_path), "--certificate", str(output), "--json"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "UNSUPPORTED")
            self.assertIsNone(json.loads(out)["published_certificate"])
            self.assertFalse(output.exists())

            malformed = model()
            malformed["norms"] = [norm("N", {}, action_ref("A"))]
            malformed_path = root / "malformed-model.json"
            malformed_path.write_text(canonical_json(malformed), encoding="utf-8")
            malformed_output = root / "malformed.certificate.json"
            code, out, _ = self.invoke([
                "check", str(malformed_path), "--certificate", str(malformed_output),
                "--json",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "MODEL_INVALID")
            self.assertIsNone(json.loads(out)["published_certificate"])
            self.assertFalse(malformed_output.exists())

            valid_path = self.write_model(root, model())
            limited_output = root / "limited.certificate.json"
            code, out, _ = self.invoke([
                "check", str(valid_path), "--certificate", str(limited_output),
                "--max-contexts", "1", "--json",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "LIMIT_REACHED")
            self.assertFalse(limited_output.exists())

            malformed_certificate = root / "malformed-certificate.json"
            malformed_certificate.write_bytes(b'{"format":')
            code, out, _ = self.invoke([
                "verify", str(valid_path), str(malformed_certificate), "--json"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")

    def test_existing_or_input_output_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = self.write_model(root, model())
            existing = root / "existing.certificate.json"
            sentinel = b"do not replace"
            existing.write_bytes(sentinel)

            code, out, _ = self.invoke([
                "check", str(model_path), "--certificate", str(existing), "--json"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(existing.read_bytes(), sentinel)

            before = model_path.read_bytes()
            code, out, _ = self.invoke([
                "check", str(model_path), "--certificate", str(model_path), "--json"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertEqual(model_path.read_bytes(), before)

    def test_atomic_link_race_does_not_overwrite_competing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = self.write_model(root, model())
            destination = root / "raced.certificate.json"
            sentinel = b"race winner"
            real_analyze = cli.analyze

            def create_competitor(value, **limits):
                certificate = real_analyze(value, **limits)
                destination.write_bytes(sentinel)
                return certificate

            with patch.object(cli, "analyze", side_effect=create_competitor):
                code, out, _ = self.invoke([
                    "check", str(model_path), "--certificate", str(destination), "--json"
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertIsNone(json.loads(out)["published_certificate"])
            self.assertEqual(destination.read_bytes(), sentinel)
            self.assertFalse(any(root.glob("tmp*")))

    def test_publication_failure_leaves_no_partial_certificate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = self.write_model(root, model())
            destination = root / "new" / "certificate.json"
            with patch.object(cli.os, "link", side_effect=OSError("injected link failure")):
                code, out, _ = self.invoke([
                    "check", str(model_path), "--certificate", str(destination), "--json"
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "IO_ERROR")
            self.assertIsNone(json.loads(out)["published_certificate"])
            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.iterdir()), [])

    def test_wrong_external_anchor_is_exit_two_and_does_not_change_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_path = self.write_model(root, model())
            certificate_path = root / "certificate.json"
            code, _, _ = self.invoke([
                "check", str(model_path), "--certificate", str(certificate_path), "--json"
            ])
            self.assertEqual(code, 0)
            before = certificate_path.read_bytes()
            code, out, _ = self.invoke([
                "verify", str(model_path), str(certificate_path),
                "--expected-certificate-sha256", "0" * 64, "--json",
            ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["status"], "CERTIFICATE_INVALID")
            self.assertEqual(json.loads(out)["finding"], "undetermined")
            self.assertEqual(certificate_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
