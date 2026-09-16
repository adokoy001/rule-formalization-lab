"""Compact boundary-cell evidence, streaming, and independent replay tests."""
from copy import deepcopy
import ast
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compactkernel import checker as compact_checker
from compactkernel import engine as compact_engine
from rulekernel.engine import analyze
from rulekernel.model import (
    KernelError,
    canonical_json,
    load_json,
)


ROOT = Path(__file__).resolve().parents[1]
CLUB20 = ROOT / "examples" / "club20"
T06_ENDPOINT = (
    ROOT / "benchmarks" / "t06" / "results" / "boundary-endpoints"
    / "check-first-failure-05662.json"
)


def write_compact(model, path):
    with Path(path).open("w+b") as stream:
        summary = compact_engine.write_certificate(model, stream)
        stream.flush()
    return summary


def model_with_variable_comparison():
    return {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": "Variable comparison fallback",
        "inputs": {
            "x": {"kind": "int", "min": 0, "max": 1},
            "y": {"kind": "int", "min": 0, "max": 1},
        },
        "outputs": {
            "answer": {"type": {"kind": "bool"}, "required": True},
        },
        "constraints": [],
        "facts": [],
        "rules": [{
            "id": "R1",
            "source": "Fictional x less than y rule",
            "when": {
                "op": "lt",
                "args": [{"var": "x"}, {"var": "y"}],
            },
            "then": {"output": "answer", "value": True},
            "overrides": [],
        }],
    }


class CompactKernelTests(unittest.TestCase):
    def test_club20_compact_results_equal_full_reference(self):
        expected_cells = {"broken": 80, "fixed": 64}
        for version in ("broken", "fixed"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                model = load_json(CLUB20 / f"{version}.json")
                full = analyze(model)
                path = Path(temp) / "certificate.jsonl"
                generated = write_compact(model, path)
                checked = compact_checker.verify_path(model, path)
                compact_queries = [
                    {key: value for key, value in query.items() if key != "status"}
                    for query in checked["queries"]
                ]
                self.assertEqual(compact_queries, full["queries"])
                self.assertEqual(checked["total_contexts"], full["total_contexts"])
                self.assertEqual(
                    checked["admitted_contexts"], full["admitted_contexts"]
                )
                self.assertEqual(checked["cell_count"], expected_cells[version])
                self.assertEqual(
                    path.read_bytes().count(b"\n"), expected_cells[version] + 2
                )
                self.assertEqual(checked["certificate_bytes"], path.stat().st_size)
                self.assertEqual(
                    generated["certificate_bytes"], checked["certificate_bytes"]
                )
                self.assertLess(
                    checked["certificate_bytes"],
                    len(canonical_json(full).encode("utf-8")),
                )

    def test_broken_weighted_counts_and_original_witnesses(self):
        model = load_json(CLUB20 / "broken.json")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "certificate.jsonl"
            write_compact(model, path)
            checked = compact_checker.verify_path(model, path)
        findings = {
            (item["output"], item["kind"]): item
            for item in checked["queries"] if item["count"]
        }
        self.assertEqual(
            {key: item["count"] for key, item in findings.items()},
            {
                ("eligible", "conflict"): 32,
                ("fee_yen", "gap"): 32,
                ("loan_limit", "conflict"): 4,
            },
        )
        self.assertEqual(
            findings[("eligible", "conflict")]["witness"]["case_index"], 288
        )
        self.assertEqual(
            findings[("loan_limit", "conflict")]["witness"]["case_index"], 404
        )

    def test_variable_comparison_falls_back_without_changing_result(self):
        model = model_with_variable_comparison()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "certificate.jsonl"
            write_compact(model, path)
            checked = compact_checker.verify_path(model, path)
        self.assertFalse(checked["compressed"])
        self.assertEqual(checked["fallback_reason"], "integer-variable-comparison")
        self.assertEqual(checked["cell_count"], 4)
        self.assertEqual(
            [
                (query["kind"], query["count"])
                for query in checked["queries"]
            ],
            [("conflict", 0), ("gap", 3)],
        )

    def test_t06_first_full_certificate_failure_becomes_one_compact_cell(self):
        model = load_json(T06_ENDPOINT)
        with self.assertRaises(KernelError) as caught:
            analyze(model)
        self.assertEqual(caught.exception.status, "LIMIT_REACHED")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "certificate.jsonl"
            write_compact(model, path)
            checked = compact_checker.verify_path(model, path)
        self.assertEqual(checked["total_contexts"], 5662)
        self.assertEqual(checked["cell_count"], 1)
        self.assertTrue(checked["compressed"])
        self.assertLess(checked["certificate_bytes"], 32_000)

    def test_syntax_only_lower_bound_rejects_before_semantic_evaluation(self):
        model = load_json(CLUB20 / "fixed.json")
        estimate = compact_engine.estimate_certificate(model)
        with patch.object(
            compact_engine,
            "MAX_CERTIFICATE_BYTES",
            estimate["guaranteed_min_bytes"] - 1,
        ), patch.object(
            compact_engine,
            "_case_result",
            side_effect=AssertionError("semantic evaluation must not start"),
        ):
            with self.assertRaises(KernelError) as caught:
                compact_engine.write_certificate(model, io.BytesIO())
        self.assertEqual(caught.exception.status, "LIMIT_REACHED")

    def test_exact_output_byte_boundary_is_enforced_incrementally(self):
        model = load_json(CLUB20 / "fixed.json")
        baseline = io.BytesIO()
        compact_engine.write_certificate(model, baseline)
        exact = len(baseline.getvalue())
        with patch.object(compact_engine, "MAX_CERTIFICATE_BYTES", exact):
            accepted = io.BytesIO()
            compact_engine.write_certificate(model, accepted)
            self.assertEqual(len(accepted.getvalue()), exact)
        with patch.object(compact_engine, "MAX_CERTIFICATE_BYTES", exact - 1):
            with self.assertRaises(KernelError) as caught:
                compact_engine.write_certificate(model, io.BytesIO())
        self.assertEqual(caught.exception.status, "LIMIT_REACHED")

    def test_concrete_replay_rejects_shared_unsound_partition(self):
        model = {
            "profile": "finite-decisions/1",
            "origin_kind": "authored_core",
            "title": "Unsound boundary mutation",
            "inputs": {"x": {"kind": "int", "min": 0, "max": 2}},
            "outputs": {
                "answer": {"type": {"kind": "bool"}, "required": True},
            },
            "constraints": [],
            "facts": [],
            "rules": [{
                "id": "R1",
                "source": "Fictional threshold rule",
                "when": {
                    "op": "ge",
                    "args": [{"var": "x"}, {"const": 1}],
                },
                "then": {"output": "answer", "value": True},
                "overrides": [],
            }],
        }
        unsound_plan = deepcopy(compact_engine.plan_partition(model))
        unsound_plan["axes"]["x"] = [{"min": 0, "max": 2}]
        unsound_plan["cell_count"] = 1
        unsound_plan["compressed"] = True

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unsound.jsonl"
            with patch.object(
                compact_engine, "plan_partition", return_value=unsound_plan
            ):
                write_compact(model, path)
            with patch.object(
                compact_checker, "_scan_expression", return_value=False
            ):
                with self.assertRaises(KernelError) as caught:
                    compact_checker.verify_path(model, path)
        self.assertEqual(caught.exception.status, "CERTIFICATE_INVALID")
        self.assertIn("concrete replay", caught.exception.message)

    def test_checker_rejects_structural_and_commitment_mutations(self):
        model = load_json(CLUB20 / "fixed.json")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original.jsonl"
            write_compact(model, original)
            lines = original.read_bytes().splitlines(keepends=True)

            mutations = {}
            value = json.loads(lines[1])
            value["weight"] += 1
            mutations["weight"] = [
                lines[0],
                canonical_json(value).encode("utf-8") + b"\n",
                *lines[2:],
            ]
            trailer = json.loads(lines[-1])
            trailer["virtual_case_commitment"] = "0" * 64
            mutations["virtual commitment"] = [
                *lines[:-1],
                canonical_json(trailer).encode("utf-8") + b"\n",
            ]
            mutations["truncated"] = lines[:-1]
            mutations["duplicate"] = [lines[0], lines[1], lines[1], *lines[2:]]
            mutations["reordered"] = [lines[0], lines[2], lines[1], *lines[3:]]
            mutations["extra"] = [*lines, lines[-1]]
            mutations["crlf"] = [
                line[:-1] + b"\r\n" for line in lines
            ]
            mutations["noncanonical"] = [
                b" " + lines[0],
                *lines[1:],
            ]

            for name, changed in mutations.items():
                with self.subTest(name=name):
                    path = root / f"{name.replace(' ', '-')}.jsonl"
                    path.write_bytes(b"".join(changed))
                    with self.assertRaises(KernelError) as caught:
                        compact_checker.verify_path(model, path)
                    self.assertIn(
                        caught.exception.status,
                        {"CERTIFICATE_INVALID", "LIMIT_REACHED"},
                    )

    def test_external_anchor_and_checker_byte_cap(self):
        model = load_json(CLUB20 / "fixed.json")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "certificate.jsonl"
            write_compact(model, path)
            checked = compact_checker.verify_path(model, path)
            anchored = compact_checker.verify_path(
                model,
                path,
                expected_certificate_sha256=checked["certificate_hash"],
            )
            self.assertEqual(anchored["status"], "VERIFIED")
            with self.assertRaises(KernelError) as caught:
                compact_checker.verify_path(
                    model,
                    path,
                    expected_certificate_sha256="0" * 64,
                )
            self.assertEqual(caught.exception.status, "CERTIFICATE_INVALID")
            with patch.object(
                compact_checker,
                "MAX_CERTIFICATE_BYTES",
                path.stat().st_size - 1,
            ):
                with self.assertRaises(KernelError) as caught:
                    compact_checker.verify_path(model, path)
            self.assertEqual(caught.exception.status, "LIMIT_REACHED")

    def test_checker_does_not_import_producer_or_partition_planner(self):
        source = (ROOT / "compactkernel" / "checker.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("compactkernel.engine", imported)
        self.assertNotIn("rulekernel.boundary_partition", imported)
        self.assertNotIn("rulekernel.engine", imported)


if __name__ == "__main__":
    unittest.main()
