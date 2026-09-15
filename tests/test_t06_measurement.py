"""Measurement-contract tests for the T06 fresh-process harness."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from benchmarks.t06.generate import DEFAULT_CONFIG, DEFAULT_OUTPUT, build_boundary
from benchmarks.t06.measure import (
    REPORT_FORMAT,
    _measure_workflow,
    _run,
    _time_summary,
    characterize_model,
)
from rulekernel.model import canonical_json, digest, load_json


class T06MeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_json(DEFAULT_CONFIG)

    def test_characterization_reports_exact_independent_density(self):
        model = load_json(DEFAULT_OUTPUT / "matrix-100-dense-eighth.json")
        result = characterize_model(model)
        self.assertEqual((result["total_contexts"],
                          result["facts_matching_contexts"],
                          result["constraints_matching_contexts"],
                          result["admitted_contexts"]),
                         (8192, 4096, 2048, 1024))
        self.assertEqual(result["guard_density"], {
            "numerator": 716800, "denominator": 819200,
        })
        self.assertEqual(result["enabled_density_declared_scope"], {
            "numerator": 89600, "denominator": 819200,
        })
        self.assertEqual(result["per_rule_guard_min_max"], [7168, 7168])
        self.assertEqual(result["per_rule_enabled_min_max"], [896, 896])
        self.assertEqual(result["rules_with_no_enabled_witness"], 0)

    def test_fresh_process_workflow_requires_independent_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = build_boundary(self.config, 4)
            path = root / "model.json"
            path.write_text(canonical_json(model), encoding="utf-8")
            result = _measure_workflow(
                "check", path, None, repetitions=1, timeout_seconds=30.0)
        self.assertTrue(result["measurement_complete"])
        self.assertEqual(result["prepare"]["status"], "verified")
        self.assertEqual(result["prepare"]["certificate"]["checker_status"],
                         "VERIFIED")
        self.assertEqual(result["producer_time"]["verified_samples"], 1)
        self.assertEqual(result["checker_time"]["verified_samples"], 1)
        self.assertEqual(result["producer_memory"]["status"], "verified")
        self.assertEqual(result["checker_memory"]["status"], "verified")

    def test_empty_selection_report_is_hash_bound_and_atomic(self):
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
            summary = _run(args)
            report = load_json(report_path)
        self.assertEqual(summary["status"], "MEASURED")
        self.assertEqual(report["format"], REPORT_FORMAT)
        self.assertEqual(report["body_sha256"], digest(report["body"]))
        self.assertEqual(report["body"]["static_matrix"], {})
        self.assertEqual(report["body"]["boundaries"], {})

    def test_error_durations_are_timed_but_not_verified(self):
        summary = _time_summary([
            {"status": "kernel_error", "elapsed_ns": 12},
            {"status": "verified", "elapsed_ns": 8},
            {"status": "worker_timeout"},
        ])
        self.assertEqual(summary["raw_ns"], [12, 8, None])
        self.assertEqual(summary["timed_samples"], 2)
        self.assertEqual(summary["verified_samples"], 1)
        self.assertEqual((summary["min_ns"], summary["max_ns"]), (8, 12))


if __name__ == "__main__":
    unittest.main()
