"""Determinism and semantic sentinels for the T06 synthetic benchmark."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from benchmarks.t06.generate import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT,
    PROVENANCE,
    build_boundary,
    build_matrix,
    build_sentinel,
    check_static,
    generate_static,
    validate_config,
)
from rulekernel.checker import verify
from rulekernel.diff import analyze_diff
from rulekernel.diff_checker import verify_diff
from rulekernel.engine import analyze
from rulekernel.model import canonical_json, digest, load_json, validate_model
from rulekernel.reachability import analyze_reachability
from rulekernel.reachability_checker import verify_reachability
from rulekernel.staged_reachability import analyze_staged_reachability
from rulekernel.staged_reachability_checker import verify_staged_reachability


class T06GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_json(DEFAULT_CONFIG)

    def test_saved_generation_is_byte_for_byte_reproducible_and_hash_bound(self):
        self.assertEqual(check_static()["status"], "MATCH")
        saved_manifest = load_json(DEFAULT_OUTPUT / "manifest.json")
        self.assertEqual(saved_manifest["provenance"], PROVENANCE)
        self.assertEqual(len(saved_manifest["models"]), 20)
        for entry in saved_manifest["models"]:
            path = DEFAULT_OUTPUT / entry["file"]
            model = load_json(path)
            validate_model(model)
            self.assertEqual(digest(model), entry["model_sha256"])
            self.assertEqual(len(canonical_json(model).encode("utf-8")), entry["bytes"])
            self.assertIsNone(entry["source_unit_count"])
        with tempfile.TemporaryDirectory() as temporary:
            generated = generate_static(DEFAULT_CONFIG, Path(temporary))
            self.assertEqual(generated, saved_manifest)

    def test_regeneration_check_detects_changed_extra_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            generate_static(DEFAULT_CONFIG, output)
            changed = output / "matrix-50-sparse-full.json"
            changed.write_text("{}", encoding="utf-8")
            (output / "extra.json").write_text("{}", encoding="utf-8")
            (output / "sentinel-local-a.json").unlink()
            result = check_static(DEFAULT_CONFIG, output)
            self.assertEqual(result["status"], "MISMATCH")
            self.assertEqual(result["changed"], ["matrix-50-sparse-full.json"])
            self.assertEqual(result["extra"], ["extra.json"])
            self.assertEqual(result["missing"], ["sentinel-local-a.json"])

    def test_config_and_revision_contracts_are_fixed(self):
        validate_config(self.config)
        invalid = deepcopy(self.config)
        invalid["variables"][0] = "renamed"
        with self.assertRaises(ValueError):
            validate_config(invalid)
        left = build_matrix(self.config, 100, "sparse", "full")
        right = build_matrix(self.config, 100, "sparse", "full", revised=True)
        differences = []
        for index, (before, after) in enumerate(zip(left["rules"], right["rules"])):
            if before != after:
                differences.append(index)
                self.assertEqual(before["then"], {"output": "o00", "value": False})
                self.assertEqual(after["then"], {"output": "o00", "value": True})
        self.assertEqual(differences, [0])
        restored = deepcopy(right)
        restored["rules"][0]["then"]["value"] = False
        self.assertEqual(restored, left)
        self.assertEqual(len(left["inputs"]), 13)
        self.assertEqual(len(left["outputs"]), 10)
        self.assertEqual(len(left["rules"]), 100)
        self.assertTrue(all(not rule["overrides"] for rule in left["rules"]))


class T06SemanticSentinelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_json(DEFAULT_CONFIG)

    def checked(self, model):
        certificate = analyze(model)
        result = verify(model, certificate)
        self.assertEqual(result["status"], "VERIFIED")
        return certificate, result

    def test_local_models_are_clean_but_union_has_one_cross_area_conflict(self):
        for sentinel_id in ("local-a", "local-b"):
            _, result = self.checked(build_sentinel(self.config, sentinel_id))
            self.assertEqual(result["queries"][0]["count"], 0)
        _, union = self.checked(build_sentinel(self.config, "union-conflict"))
        conflict = union["queries"][0]
        self.assertEqual(conflict["count"], 1)
        self.assertEqual(conflict["witness"], {
            "case_index": 3,
            "input": {"x": True, "y": True},
            "rule_ids": ["AREA_A", "AREA_B"],
            "values": [False, True],
        })

    def test_exception_to_exception_revival_is_preserved(self):
        model = build_sentinel(self.config, "override-revival")
        certificate, _ = self.checked(model)
        self.assertEqual(certificate["cases"][3]["effective"], ["BASE", "TOP"])
        reachability = analyze_reachability(model)
        checked = verify_reachability(model, reachability)
        rows = {row["rule_id"]: row for row in checked["rules"]}
        self.assertEqual((rows["BASE"]["enabled_count"],
                          rows["BASE"]["effective_count"]), (4, 3))

    def test_matrix_stage_counts_separate_guard_and_background_density(self):
        model = build_matrix(self.config, 100, "sparse", "eighth")
        certificate = analyze_staged_reachability(model)
        result = verify_staged_reachability(model, certificate)
        self.assertEqual((result["total_contexts"], result["facts_matching_contexts"],
                          result["constraints_matching_contexts"],
                          result["admitted_contexts"]), (8192, 4096, 2048, 1024))
        self.assertEqual(result["attention_count"], 0)
        for row in result["rules"]:
            self.assertEqual((row["guard_count"], row["guard_and_facts_count"],
                              row["guard_and_constraints_count"],
                              row["enabled_count"], row["effective_count"]),
                             (1024, 512, 256, 128, 128))

    def test_matrix_revision_gold_is_exact_and_independently_checked(self):
        left = build_matrix(self.config, 50, "sparse", "eighth")
        right = build_matrix(self.config, 50, "sparse", "eighth", revised=True)
        certificate = analyze_diff(left, right)
        result = verify_diff(left, right, certificate)
        query = next(row for row in result["queries"]
                     if row["output"] == "o00" and row["kind"] == "semantic_change")
        self.assertEqual(query["count"], 128)
        self.assertEqual(result["common_admitted_contexts"], 1024)

    def test_small_boundary_family_round_trips_all_four_evidence_formats(self):
        left = build_boundary(self.config, 4)
        right = build_boundary(self.config, 4, revised=True)
        certificate = analyze(left)
        self.assertEqual(verify(left, certificate)["status"], "VERIFIED")
        certificate = analyze_reachability(left)
        self.assertEqual(verify_reachability(left, certificate)["status"], "VERIFIED")
        certificate = analyze_staged_reachability(left)
        self.assertEqual(verify_staged_reachability(left, certificate)["status"], "VERIFIED")
        certificate = analyze_diff(left, right)
        self.assertEqual(verify_diff(left, right, certificate)["status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
