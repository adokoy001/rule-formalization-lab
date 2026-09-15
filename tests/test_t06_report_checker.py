"""Fast mutation tests for the saved T06 report checker."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import unittest

from benchmarks.t06.generate import DEFAULT_CONFIG, DEFAULT_OUTPUT
from benchmarks.t06.measure import _run
from benchmarks.t06.report_checker import (
    ReportVerificationError,
    _verify_endpoint,
    _verify_partial,
    _verify_search,
    verify_report,
)
from rulekernel.model import canonical_json, digest, load_json


OFFICIAL_REPORT = (
    Path(__file__).parents[1]
    / "benchmarks"
    / "t06"
    / "results"
    / "2026-09-15.json"
)
OFFICIAL_REPORT_SHA256 = (
    "6bda457de5e19dbcbd74bb7df50f528b"
    "1c4dd6ca1e1040a972af35c7d3af1068"
)


def _write_report(path, report, *, bind_output=True):
    if bind_output:
        report["body"]["command"]["arguments"]["output"] = str(
            path.resolve()
        )
    _rebind_body(report)
    path.write_text(canonical_json(report), encoding="utf-8", newline="\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rebind_body(report):
    report["body_sha256"] = digest(report["body"])
    return report


class T06ReportCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = load_json(OFFICIAL_REPORT, max_bytes=64 * 1024 * 1024)
        cls.config = load_json(DEFAULT_CONFIG)

    def test_saved_official_report_verifies_with_external_anchor(self):
        result = verify_report(
            OFFICIAL_REPORT,
            expected_report_sha256=OFFICIAL_REPORT_SHA256,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["externally_anchored"])
        self.assertTrue(result["full_official_run"])
        self.assertEqual(result["static_scenarios"], 8)
        self.assertEqual(result["boundary_operations"], 4)
        self.assertEqual(result["verified_workflows"], 27)
        self.assertEqual(result["limit_reached_workflows"], 13)

    def test_external_report_hash_mismatch_fails_before_self_hash(self):
        with self.assertRaisesRegex(
            ReportVerificationError, "external report SHA-256 mismatch"
        ):
            verify_report(
                OFFICIAL_REPORT,
                expected_report_sha256="0" * 64,
            )

    def test_reported_paths_and_source_collision_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            wrong_output = deepcopy(self.report)
            wrong_output["body"]["command"]["arguments"]["output"] = str(
                DEFAULT_CONFIG.resolve()
            )
            wrong_path = root / "wrong-output.json"
            external_hash = _write_report(
                wrong_path, wrong_output, bind_output=False
            )
            with self.assertRaisesRegex(
                ReportVerificationError,
                "reported output path differs from report path",
            ):
                verify_report(
                    wrong_path, expected_report_sha256=external_hash
                )

            colliding_endpoints = deepcopy(self.report)
            colliding_endpoints["body"]["command"]["arguments"][
                "endpoints"
            ] = str(DEFAULT_OUTPUT.resolve())
            collision_path = root / "colliding-endpoints.json"
            external_hash = _write_report(
                collision_path, colliding_endpoints
            )
            with self.assertRaisesRegex(
                ReportVerificationError,
                "endpoint tree overlaps generated inputs",
            ):
                verify_report(
                    collision_path, expected_report_sha256=external_hash
                )

            source_collision = deepcopy(self.report)
            measure_source = (
                Path(__file__).parents[1]
                / "benchmarks"
                / "t06"
                / "measure.py"
            ).resolve()
            source_collision["body"]["command"]["arguments"][
                "endpoints"
            ] = str(measure_source)
            source_path = root / "source-collision.json"
            external_hash = _write_report(source_path, source_collision)
            with self.assertRaisesRegex(
                ReportVerificationError,
                "endpoint tree contains a bound input",
            ):
                verify_report(
                    source_path, expected_report_sha256=external_hash
                )

    def test_rehashed_current_source_binding_tamper_is_rejected(self):
        report = deepcopy(self.report)
        report["body"]["bindings"]["files"]["measure"]["sha256"] = "0" * 64
        _rebind_body(report)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            external_hash = _write_report(path, report)
            with self.assertRaisesRegex(
                ReportVerificationError, "bound file hash mismatch"
            ):
                verify_report(
                    path, expected_report_sha256=external_hash
                )

    def test_rehashed_worker_summary_tamper_is_rejected(self):
        report = deepcopy(self.report)
        workflow = report["body"]["static_matrix"][
            "matrix-100-dense-eighth"
        ]["operations"]["check"]
        workflow["producer_time"]["verified_samples"] = 2
        _rebind_body(report)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            external_hash = _write_report(path, report)
            with self.assertRaisesRegex(
                ReportVerificationError,
                "time summary does not match raw samples",
            ):
                verify_report(
                    path, expected_report_sha256=external_hash
                )

    def test_boundary_search_and_endpoint_tampering_are_rejected(self):
        boundary = self.report["body"]["boundaries"]["check"]
        search = deepcopy(boundary["search"])
        _verify_search(search, "search", "check", self.config)
        search["last_success_contexts"] -= 1
        with self.assertRaisesRegex(
            ReportVerificationError,
            "recorded endpoints are not the replayed adjacent pair",
        ):
            _verify_search(search, "search", "check", self.config)

        endpoint = deepcopy(boundary["last_success_endpoint"])
        contexts = boundary["search"]["last_success_contexts"]
        endpoints_dir = (
            Path(__file__).parents[1]
            / "benchmarks"
            / "t06"
            / "results"
            / "boundary-endpoints"
        )
        _verify_endpoint(
            endpoint,
            "endpoint",
            "check",
            "last-success",
            contexts,
            self.config,
            endpoints_dir,
        )
        endpoint["base"]["model_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            ReportVerificationError, "endpoint binding mismatch"
        ):
            _verify_endpoint(
                endpoint,
                "endpoint",
                "check",
                "last-success",
                contexts,
                self.config,
                endpoints_dir,
            )

    def test_full_report_requires_four_consecutive_boundaries(self):
        report = deepcopy(self.report)
        boundary = report["body"]["boundaries"]["check"]
        search = boundary["search"]
        by_context = {
            probe["contexts"]: probe for probe in search["probes"]
        }
        upper = by_context[10000]
        lower_response = deepcopy(by_context[1]["response"])
        lower_response["certificate"]["total_contexts"] = 10000
        lower_response["certificate"]["admitted_contexts"] = 10000
        upper["outcome"] = "success"
        upper["response"] = lower_response
        upper["certificate_published"] = True
        upper["certificate_file_sha256"] = lower_response[
            "certificate"
        ]["sha256"]
        search["search_status"] = "no_limit_within_1_to_10000"
        search["last_success_contexts"] = 10000
        search["first_failure_contexts"] = None
        search["probe_order"] = [1, 10000]
        search["probes"] = [by_context[1], upper]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "no-consecutive-boundary.json"
            external_hash = _write_report(path, report)
            with self.assertRaisesRegex(
                ReportVerificationError,
                "full official run requires a consecutive boundary",
            ):
                verify_report(
                    path, expected_report_sha256=external_hash
                )

    def test_partial_artifact_assertion_tamper_is_rejected(self):
        body = self.report["body"]
        partial = deepcopy(
            body["boundaries"]["staged"]["partial_artifact_check"]
        )
        executable = body["environment"]["python"]["executable"]
        _verify_partial(partial, "partial", "staged", executable)
        partial["checks"]["existing_target_bytes_unchanged"] = False
        with self.assertRaisesRegex(
            ReportVerificationError,
            "atomic failure assertion is false",
        ):
            _verify_partial(partial, "partial", "staged", executable)

    def test_partial_smoke_report_requires_explicit_allow_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "report.json"
            args = SimpleNamespace(
                repetitions=1,
                timeout_seconds=30.0,
                config=DEFAULT_CONFIG,
                generated=DEFAULT_OUTPUT,
                regenerate_static=False,
                profile=None,
                operation=None,
                skip_static=True,
                skip_boundaries=True,
                endpoints=root / "endpoints",
                output=report_path,
                overwrite=False,
            )
            _run(args)
            external_hash = hashlib.sha256(
                report_path.read_bytes()
            ).hexdigest()
            accepted = verify_report(
                report_path,
                expected_report_sha256=external_hash,
                require_full=False,
            )
            self.assertFalse(accepted["full_official_run"])
            with self.assertRaisesRegex(
                ReportVerificationError,
                "not the complete official T06 run",
            ):
                verify_report(
                    report_path,
                    expected_report_sha256=external_hash,
                    require_full=True,
                )

    def test_generated_model_byte_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "generated"
            shutil.copytree(DEFAULT_OUTPUT, generated)
            report_path = root / "report.json"
            args = SimpleNamespace(
                repetitions=1,
                timeout_seconds=30.0,
                config=DEFAULT_CONFIG,
                generated=generated,
                regenerate_static=False,
                profile=None,
                operation=None,
                skip_static=True,
                skip_boundaries=True,
                endpoints=root / "endpoints",
                output=report_path,
                overwrite=False,
            )
            _run(args)
            external_hash = hashlib.sha256(
                report_path.read_bytes()
            ).hexdigest()
            model = generated / "matrix-50-sparse-full.json"
            model.write_bytes(model.read_bytes() + b"\n")
            with self.assertRaisesRegex(
                ReportVerificationError,
                "generated model is not canonical bytes",
            ):
                verify_report(
                    report_path,
                    expected_report_sha256=external_hash,
                    generated_dir=generated,
                    require_full=False,
                )


if __name__ == "__main__":
    unittest.main()
