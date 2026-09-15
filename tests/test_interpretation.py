"""Contract, tamper, and semantic-gold tests for interpretation IR v0.1."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest import mock

from rulekernel.checker import verify as verify_core
from rulekernel.engine import analyze
from rulekernel.interpretation import _lower_core, compile_interpretation
from rulekernel.interpretation_checker import verify_interpretation_package
from rulekernel.interpretation_model import (
    KernelError,
    bind_task_to_source,
    core_rule_id,
    interpretation_digest,
    interpretation_snapshot_digest,
    load_interpretation_json,
    validate_candidate,
)
from rulekernel.source_checker import verify_source_package
from rulekernel.source_model import MAX_MANIFEST_BYTES, load_source_json


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "interpretations" / "member-eligibility"
SOURCE = ROOT / "examples" / "sources" / "member-eligibility"
SOURCE_BUNDLE_HASH = "a63021f7766381a75a7cb8b91f285f47122c1f5d3912a2f6132653e91cf4ac32"
REVIEW_HASH = "e5e7f865b2195b64057842c70e25b4a78755e1fbaf82061df6c8e64504ad88a0"
EXPECTATIONS_HASH = "51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8"
PACKAGE_HASH = "25b6fd536726dce2420f49776e961cb8bb0b78d41b1b8865608dd0fc2335a112"


class InterpretationTestCase(unittest.TestCase):
    def setUp(self):
        self.task = load_interpretation_json(EXAMPLE / "task.json")
        self.candidate = load_interpretation_json(EXAMPLE / "candidate.json")
        self.review = load_interpretation_json(EXAMPLE / "review.json")
        self.expectations = load_interpretation_json(EXAMPLE / "scope-expectations.json")
        self.saved = load_interpretation_json(EXAMPLE / "compiled.json")
        source_result = verify_source_package(
            SOURCE / "source-spec.json", SOURCE / "bundle",
            expected_bundle_sha256=SOURCE_BUNDLE_HASH,
        )
        self.manifest = load_source_json(
            SOURCE / "bundle" / "derived" / "source-units.json",
            max_bytes=MAX_MANIFEST_BYTES,
        )
        self.units = bind_task_to_source(self.task, source_result, self.manifest)

    def assert_error(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def anchors(self, review=None, expectations=None):
        review = self.review if review is None else review
        expectations = self.expectations if expectations is None else expectations
        return {
            "expected_source_bundle_sha256": SOURCE_BUNDLE_HASH,
            "expected_review_sha256": interpretation_digest(review),
            "expected_scope_expectations_sha256": interpretation_digest(expectations),
        }

    def compile(self, *, task=None, candidate=None, review=None, expectations=None):
        task = self.task if task is None else task
        candidate = self.candidate if candidate is None else candidate
        review = self.review if review is None else review
        expectations = self.expectations if expectations is None else expectations
        return compile_interpretation(
            task, candidate, review, expectations,
            SOURCE / "source-spec.json", SOURCE / "bundle",
            **self.anchors(review, expectations),
        )

    def verify(self, package, *, task=None, candidate=None, review=None,
               expectations=None, package_anchor=None):
        task = self.task if task is None else task
        candidate = self.candidate if candidate is None else candidate
        review = self.review if review is None else review
        expectations = self.expectations if expectations is None else expectations
        return verify_interpretation_package(
            task, candidate, review, expectations,
            SOURCE / "source-spec.json", SOURCE / "bundle", package,
            expected_package_sha256=package_anchor,
            **self.anchors(review, expectations),
        )

    def refresh_chain(self, candidate, review, expectations):
        review["candidate_hash"] = interpretation_digest(candidate)
        index = validate_candidate(self.task, candidate, self.units, self.manifest)
        core = _lower_core(self.task, index, review, self.units)
        expectations["task_hash"] = interpretation_digest(self.task)
        expectations["candidate_hash"] = interpretation_digest(candidate)
        expectations["review_hash"] = interpretation_digest(review)
        expectations["interpretation_snapshot_sha256"] = interpretation_snapshot_digest(
            self.task, candidate, review)
        expectations["scope_hash"] = interpretation_digest(self.task["core_scope"])
        expectations["core_model_hash"] = interpretation_digest(core)
        selected = set(review["selected_provision_ids"])
        expectations["rules"] = [
            item for item in expectations["rules"]
            if item["core_rule_id"] in {core_rule_id(value) for value in selected}
        ]
        return core


class InterpretationHappyPathTests(InterpretationTestCase):
    def test_saved_example_rebuilds_byte_for_byte_and_verifies_with_all_anchors(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network forbidden")):
            rebuilt = self.compile()
            self.assertEqual(rebuilt, self.saved)
            result = self.verify(self.saved, package_anchor=PACKAGE_HASH)
        self.assertEqual(result["status"], "LOWERING_VERIFIED")
        self.assertEqual(result["core_model_hash"],
                         "b34744e3ea2d98f73d04d8eef9d5867f8d2a553f67bff50f22369c848e50b6e5")
        self.assertEqual(result["selected_rule_count"], 2)
        self.assertEqual(result["semantic_test_count"], 5)
        self.assertEqual(result["coverage_counts"], {
            "selected": 2, "unresolved": 0, "excluded": 0,
        })
        self.assertEqual(result["review_method"], "manual_fixture_review")
        self.assertTrue(result["provisional"])
        self.assertTrue(result["offline"])
        self.assertTrue(result["package_hash_anchored"])

    def test_human_review_is_reported_as_non_provisional(self):
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        review["review_method"] = "human_review"
        self.refresh_chain(self.candidate, review, expectations)
        package = self.compile(review=review, expectations=expectations)
        result = self.verify(package, review=review, expectations=expectations)
        self.assertEqual(result["review_method"], "human_review")
        self.assertFalse(result["provisional"])

    def test_compiled_core_runs_in_existing_kernel_with_the_same_join_hash(self):
        certificate = analyze(self.saved["core"])
        checked = verify_core(self.saved["core"], certificate)
        self.assertEqual(checked["status"], "VERIFIED")
        self.assertEqual(certificate["model_hash"], self.saved["core_model_hash"])
        self.assertEqual(checked["model_hash"], self.saved["core_model_hash"])
        self.assertTrue(all(query["count"] == 0 for query in checked["queries"]))

    def test_wrapper_marks_interpreted_origin_while_legacy_core_stays_compatible(self):
        self.assertEqual(self.saved["origin_kind"], "interpreted_source")
        self.assertEqual(self.saved["core"]["origin_kind"], "authored_core")
        self.assertEqual(self.saved["core"]["profile"], "finite-decisions/1")
        self.assertEqual(interpretation_digest(self.saved["core"]),
                         self.saved["core_model_hash"])
        self.assertEqual(self.saved["review_summary"]["semantic_correspondence"],
                         "HOST_REVIEW_RECORDED")

    def test_provenance_copies_manifest_spans_and_full_text(self):
        mappings = {item["candidate_provision_id"]: item
                    for item in self.saved["provenance_map"]}
        for provision in self.candidate["provisions"]:
            mapping = mappings[provision["id"]]
            for copied in mapping["source_units"]:
                source = self.units[copied["source_unit_id"]]
                for field in ("index", "start_codepoint", "end_codepoint", "exact",
                              "text_sha256", "structural_path"):
                    self.assertEqual(copied[field], source[field])
            core_rule = next(rule for rule in self.saved["core"]["rules"]
                             if rule["id"] == mapping["core_rule_id"])
            self.assertEqual(core_rule["source"], mapping["source_units"][0]["exact"])

    def test_candidate_proposed_tests_are_not_used_as_host_gold(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        candidate["proposed_tests"][0]["expected"] = {
            "eligible": {"state": "defined", "value": True},
        }
        self.refresh_chain(candidate, review, expectations)
        package = self.compile(candidate=candidate, review=review, expectations=expectations)
        result = self.verify(package, candidate=candidate, review=review,
                             expectations=expectations)
        self.assertEqual(result["status"], "LOWERING_VERIFIED")


class CandidateAndReviewBoundaryTests(InterpretationTestCase):
    def test_non_string_enum_values_are_rejected_without_python_type_errors(self):
        cases = []

        candidate = deepcopy(self.candidate)
        candidate["provisions"][0]["kind"] = {}
        cases.append(("candidate kind", {"candidate": candidate}))

        candidate = deepcopy(self.candidate)
        candidate["provisions"][0]["condition_role"] = []
        cases.append(("condition role", {"candidate": candidate}))

        candidate = deepcopy(self.candidate)
        candidate["unresolved_issues"] = [{
            "id": "I_BAD_KIND", "kind": [],
            "source_unit_ids": [candidate["provisions"][0]["source_unit_ids"][0]],
            "description": "型検査用。",
        }]
        cases.append(("issue kind", {"candidate": candidate}))

        review = deepcopy(self.review)
        review["review_method"] = []
        cases.append(("review method", {"review": review}))

        review = deepcopy(self.review)
        review["state"] = {}
        cases.append(("review state", {"review": review}))

        review = deepcopy(self.review)
        review["coverage_decisions"][0]["disposition"] = []
        cases.append(("coverage disposition", {"review": review}))

        expectations = deepcopy(self.expectations)
        expectations["rules"][0]["expectation"] = []
        cases.append(("scope expectation", {"expectations": expectations}))

        for label, arguments in cases:
            with self.subTest(label=label):
                self.assert_error("UNSUPPORTED", self.compile, **arguments)

    def test_candidate_cannot_self_report_approval(self):
        candidate = deepcopy(self.candidate)
        candidate["approved"] = True
        self.assert_error("UNSUPPORTED", self.compile, candidate=candidate)

    def test_candidate_cannot_self_report_scope_expectation(self):
        candidate = deepcopy(self.candidate)
        candidate["scope_expectations"] = []
        self.assert_error("UNSUPPORTED", self.compile, candidate=candidate)

    def test_stale_review_is_rejected_after_candidate_change(self):
        candidate = deepcopy(self.candidate)
        candidate["proposed_assumptions"][0]["text"] += "変更"
        self.assert_error("INTERPRETATION_MISMATCH", self.compile, candidate=candidate)

    def test_pending_review_returns_review_required(self):
        review = deepcopy(self.review)
        review["state"] = "pending"
        self.assert_error("REVIEW_REQUIRED", self.compile, review=review)

    def test_rejected_review_preserves_semantic_finding_code(self):
        review = deepcopy(self.review)
        review["state"] = "rejected"
        review["findings"] = [{
            "code": "NEGATION_REVERSAL",
            "provision_ids": ["P_SUSPENSION_EXCEPTION"],
            "description": "持たないを持つへ反転している。",
        }]
        error = self.assert_error("REVIEW_REJECTED", self.compile, review=review)
        self.assertIn("NEGATION_REVERSAL", error.message)

    def test_unaccepted_assumption_blocks_selected_rule(self):
        review = deepcopy(self.review)
        review["accepted_assumption_ids"] = []
        self.assert_error("MODEL_INCOMPLETE", self.compile, review=review)

    def test_selected_necessary_only_condition_does_not_lower(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        candidate["provisions"][0]["condition_role"] = "necessary_only"
        review["candidate_hash"] = interpretation_digest(candidate)
        self.assert_error("MODEL_INCOMPLETE", self.compile,
                          candidate=candidate, review=review)

    def test_selected_issue_blocks_publication(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        candidate["unresolved_issues"] = [{
            "id": "I_AGE_BASIS",
            "kind": "ambiguous_meaning",
            "source_unit_ids": [candidate["provisions"][0]["source_unit_ids"][0]],
            "description": "年齢の基準時点が未確定。",
        }]
        candidate["provisions"][0]["issue_ids"] = ["I_AGE_BASIS"]
        candidate["coverage"][0]["issue_ids"] = ["I_AGE_BASIS"]
        review["candidate_hash"] = interpretation_digest(candidate)
        self.assert_error("MODEL_INCOMPLETE", self.compile,
                          candidate=candidate, review=review)

    def test_unselected_override_target_blocks_exception(self):
        review = deepcopy(self.review)
        review["selected_provision_ids"] = ["P_SUSPENSION_EXCEPTION"]
        review["coverage_decisions"][0] = {
            "source_unit_id": self.task["allowed_source_unit_ids"][0],
            "disposition": "excluded", "provision_ids": [], "issue_ids": [],
            "rationale": "負例として原則を選択しない。",
        }
        self.assert_error("MODEL_INCOMPLETE", self.compile, review=review)

    def test_unresolved_source_reference_blocks_direct_use_and_dummy_parking(self):
        source = ROOT / "examples" / "sources" / "fictional-unicode"
        source_hash = "baeba5fb46ac6fb33aa5a31983ea58ab9d2a484cc26222dec256fb26f27bec50"
        source_result = verify_source_package(
            source / "source-spec.json", source / "bundle",
            expected_bundle_sha256=source_hash,
        )
        manifest = load_source_json(
            source / "bundle" / "derived" / "source-units.json",
            max_bytes=MAX_MANIFEST_BYTES,
        )
        units = {unit["unit_key"]: unit for unit in manifest["units"]}
        task = {
            "format": "rule-interpretation-task/1",
            "task_id": "unresolved_reference_gate",
            "source": {
                "source_package_format": source_result["source_package_format"],
                "source_spec_sha256": source_result["source_spec_hash"],
                "source_bundle_sha256": source_result["bundle_hash"],
                "raw_sha256": source_result["raw_sha256"],
                "source_unit_manifest_sha256": source_result["source_unit_manifest_sha256"],
                "document_id": source_result["document_id"],
                "revision_id": source_result["revision_id"],
            },
            "allowed_source_unit_ids": [unit["source_unit_id"] for unit in manifest["units"]],
            "core_scope": {
                "title": "未解決参照gate", "inputs": {"flag": {"kind": "bool"}},
                "outputs": {"decision": {"type": {"kind": "bool"}, "required": False}},
                "constraints": [], "facts": [],
            },
            "allowed_provision_kinds": ["decision_rule", "exception", "unresolved"],
            "conversion_profile": "candidate-to-finite-decisions/1",
        }
        provision = {
            "id": "P_UNRESOLVED_REF", "kind": "decision_rule",
            "condition_role": "sufficient_trigger",
            "source_unit_ids": [units["U3"]["source_unit_id"]],
            "source_quotes": [{"source_unit_id": units["U3"]["source_unit_id"],
                               "exact": units["U3"]["exact"]}],
            "when": {"var": "flag"},
            "then": {"output": "decision", "value": True},
            "overrides": [], "reference_ids": ["REF1"],
            "assumption_ids": [], "issue_ids": [],
        }
        candidate = {
            "format": "rule-interpretation-candidate/1", "task_id": task["task_id"],
            "task_hash": interpretation_digest(task),
            "source_unit_manifest_sha256": source_result["source_unit_manifest_sha256"],
            "provisions": [provision],
            "references": [{
                "reference_id": "REF1",
                "from_source_unit_id": units["U3"]["source_unit_id"],
                "literal": "別に定める", "status": "unresolved",
                "target_provision_id": None,
            }],
            "proposed_assumptions": [], "unresolved_issues": [],
            "coverage": [{
                "source_unit_id": unit["source_unit_id"],
                "provision_ids": (["P_UNRESOLVED_REF"] if unit["unit_key"] == "U3" else []),
                "issue_ids": [],
            } for unit in manifest["units"]],
            "proposed_tests": [],
        }
        review = {
            "format": "rule-interpretation-review/1", "review_id": "UNRESOLVED_REVIEW",
            "reviewer_id": "TEST_HOST", "review_method": "manual_fixture_review",
            "task_hash": interpretation_digest(task),
            "candidate_hash": interpretation_digest(candidate), "state": "approved",
            "reviewed_at": "2026-09-15T13:20:00Z",
            "selected_provision_ids": ["P_UNRESOLVED_REF"],
            "accepted_assumption_ids": [],
            "coverage_decisions": [{
                "source_unit_id": unit["source_unit_id"],
                "disposition": "selected" if unit["unit_key"] == "U3" else "excluded",
                "provision_ids": (["P_UNRESOLVED_REF"] if unit["unit_key"] == "U3" else []),
                "issue_ids": [], "rationale": "未解決参照の選択負例。",
            } for unit in manifest["units"]],
            "semantic_tests": [{
                "id": "UNRESOLVED_TEST", "input": {"flag": True},
                "expected": {"decision": {"state": "defined", "value": True}},
            }],
            "findings": [],
        }
        placeholder = {}
        self.assert_error(
            "MODEL_INCOMPLETE", compile_interpretation,
            task, candidate, review, placeholder,
            source / "source-spec.json", source / "bundle",
            expected_source_bundle_sha256=source_hash,
            expected_review_sha256=interpretation_digest(review),
            expected_scope_expectations_sha256=interpretation_digest(placeholder),
        )
        # The reference cannot be moved to an unselected dummy from the same
        # source unit while an executable rule from that unit is selected.
        candidate = deepcopy(candidate)
        review = deepcopy(review)
        executable = candidate["provisions"][0]
        executable["reference_ids"] = []
        dummy = deepcopy(executable)
        dummy.update({
            "id": "P_REFERENCE_DUMMY", "kind": "unresolved",
            "condition_role": "not_applicable", "when": None, "then": None,
            "reference_ids": ["REF1"], "issue_ids": ["I_REFERENCE_DUMMY"],
        })
        candidate["provisions"].append(dummy)
        candidate["unresolved_issues"] = [{
            "id": "I_REFERENCE_DUMMY", "kind": "unresolved_reference",
            "source_unit_ids": dummy["source_unit_ids"],
            "description": "未解決参照をdummyへ隔離した負例。",
        }]
        candidate["coverage"][2]["provision_ids"].append("P_REFERENCE_DUMMY")
        candidate["coverage"][2]["issue_ids"] = ["I_REFERENCE_DUMMY"]
        review["candidate_hash"] = interpretation_digest(candidate)
        self.assert_error(
            "MODEL_INCOMPLETE", compile_interpretation,
            task, candidate, review, placeholder,
            source / "source-spec.json", source / "bundle",
            expected_source_bundle_sha256=source_hash,
            expected_review_sha256=interpretation_digest(review),
            expected_scope_expectations_sha256=interpretation_digest(placeholder),
        )

    def test_unsupported_normative_kind_is_not_recast_as_decision(self):
        candidate = deepcopy(self.candidate)
        candidate["provisions"][0]["kind"] = "obligation"
        self.assert_error("UNSUPPORTED", self.compile, candidate=candidate)


class SourceAndReferenceBindingTests(InterpretationTestCase):
    def test_changed_exact_quote_is_rejected(self):
        candidate = deepcopy(self.candidate)
        candidate["provisions"][0]["source_quotes"][0]["exact"] = "18歳以下"
        self.assert_error("INTERPRETATION_MISMATCH", self.compile, candidate=candidate)

    def test_swapping_same_role_to_another_source_unit_is_rejected(self):
        candidate = deepcopy(self.candidate)
        candidate["provisions"][0]["source_quotes"][0] = deepcopy(
            candidate["provisions"][1]["source_quotes"][0])
        self.assert_error("INTERPRETATION_INVALID", self.compile, candidate=candidate)

    def test_manifest_reference_cannot_be_omitted(self):
        candidate = deepcopy(self.candidate)
        candidate["references"] = []
        candidate["provisions"][1]["reference_ids"] = []
        self.assert_error("REFERENCE_MISSING", self.compile, candidate=candidate)

    def test_reference_target_must_come_from_target_source_unit(self):
        candidate = deepcopy(self.candidate)
        candidate["references"][0]["target_provision_id"] = "P_SUSPENSION_EXCEPTION"
        self.assert_error("INTERPRETATION_MISMATCH", self.compile, candidate=candidate)

    def test_task_cannot_drop_a_unit_from_fixed_manifest(self):
        task = deepcopy(self.task)
        task["allowed_source_unit_ids"].pop()
        candidate = deepcopy(self.candidate)
        candidate["task_hash"] = interpretation_digest(task)
        self.assert_error("INTERPRETATION_MISMATCH", self.compile,
                          task=task, candidate=candidate)

    def test_wrong_external_source_anchor_is_rejected(self):
        anchors = self.anchors()
        anchors["expected_source_bundle_sha256"] = "0" * 64
        self.assert_error(
            "SOURCE_MISMATCH", compile_interpretation,
            self.task, self.candidate, self.review, self.expectations,
            SOURCE / "source-spec.json", SOURCE / "bundle", **anchors,
        )


class HostGoldSemanticTests(InterpretationTestCase):
    def test_threshold_boundary_mutation_fails_host_gold(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        candidate["provisions"][0]["when"]["args"][1]["op"] = "gt"
        self.refresh_chain(candidate, review, expectations)
        package = self.compile(candidate=candidate, review=review, expectations=expectations)
        self.assert_error(
            "SEMANTIC_MISMATCH", self.verify, package,
            candidate=candidate, review=review, expectations=expectations,
        )

    def test_negated_conclusion_mutation_fails_host_gold(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        candidate["provisions"][1]["then"]["value"] = True
        self.refresh_chain(candidate, review, expectations)
        package = self.compile(candidate=candidate, review=review, expectations=expectations)
        self.assert_error(
            "SEMANTIC_MISMATCH", self.verify, package,
            candidate=candidate, review=review, expectations=expectations,
        )

    def test_necessary_sufficient_reversal_fails_reverse_example(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        candidate["provisions"][0]["when"] = {"op": "ge", "args": [
            {"var": "age"}, {"const": 18},
        ]}
        self.refresh_chain(candidate, review, expectations)
        package = self.compile(candidate=candidate, review=review, expectations=expectations)
        self.assert_error(
            "SEMANTIC_MISMATCH", self.verify, package,
            candidate=candidate, review=review, expectations=expectations,
        )

    def test_omitted_exception_fails_exception_example(self):
        candidate = deepcopy(self.candidate)
        review = deepcopy(self.review)
        expectations = deepcopy(self.expectations)
        second = candidate["provisions"][1]
        second["kind"] = "unresolved"
        second["condition_role"] = "not_applicable"
        second["when"] = None
        second["then"] = None
        second["overrides"] = []
        second["issue_ids"] = ["I_EXCEPTION_OMITTED"]
        candidate["unresolved_issues"] = [{
            "id": "I_EXCEPTION_OMITTED",
            "kind": "unsupported_construct",
            "source_unit_ids": second["source_unit_ids"],
            "description": "ただし書を実行規則へ変換していない。",
        }]
        candidate["coverage"][1]["issue_ids"] = ["I_EXCEPTION_OMITTED"]
        review["selected_provision_ids"] = ["P_ADULT_MEMBER"]
        review["coverage_decisions"][1] = {
            "source_unit_id": second["source_unit_ids"][0],
            "disposition": "unresolved", "provision_ids": [],
            "issue_ids": ["I_EXCEPTION_OMITTED"],
            "rationale": "負例として例外を未解決のまま残す。",
        }
        self.refresh_chain(candidate, review, expectations)
        package = self.compile(candidate=candidate, review=review, expectations=expectations)
        self.assert_error(
            "SEMANTIC_MISMATCH", self.verify, package,
            candidate=candidate, review=review, expectations=expectations,
        )


class PackageTamperTests(InterpretationTestCase):
    def test_external_review_anchor_rejects_self_consistent_input_swap(self):
        review = deepcopy(self.review)
        review["reviewed_at"] = "2026-09-15T13:11:00Z"
        self.assert_error(
            "INTERPRETATION_MISMATCH", compile_interpretation,
            self.task, self.candidate, review, self.expectations,
            SOURCE / "source-spec.json", SOURCE / "bundle",
            expected_source_bundle_sha256=SOURCE_BUNDLE_HASH,
            expected_review_sha256=REVIEW_HASH,
            expected_scope_expectations_sha256=EXPECTATIONS_HASH,
        )

    def test_external_scope_expectations_anchor_is_required_to_match(self):
        expectations = deepcopy(self.expectations)
        expectations["rules"][0]["expectation"] = "unspecified"
        self.assert_error(
            "INTERPRETATION_MISMATCH", compile_interpretation,
            self.task, self.candidate, self.review, expectations,
            SOURCE / "source-spec.json", SOURCE / "bundle",
            expected_source_bundle_sha256=SOURCE_BUNDLE_HASH,
            expected_review_sha256=REVIEW_HASH,
            expected_scope_expectations_sha256=EXPECTATIONS_HASH,
        )

    def test_external_package_anchor_rejects_changed_package(self):
        package = deepcopy(self.saved)
        package["core"]["rules"][0]["then"]["value"] = False
        self.assert_error("INTERPRETATION_MISMATCH", self.verify, package,
                          package_anchor=PACKAGE_HASH)

    def test_core_tamper_is_rejected_without_package_anchor(self):
        package = deepcopy(self.saved)
        package["core"]["rules"][0]["when"] = {"const": True}
        self.assert_error("INTERPRETATION_PACKAGE_INVALID", self.verify, package)

    def test_provenance_span_tamper_is_rejected(self):
        package = deepcopy(self.saved)
        package["provenance_map"][0]["source_units"][0]["start_codepoint"] += 1
        self.assert_error("INTERPRETATION_PACKAGE_INVALID", self.verify, package)

    def test_provenance_source_unit_swap_is_rejected(self):
        package = deepcopy(self.saved)
        package["provenance_map"][0]["source_units"][0] = deepcopy(
            package["provenance_map"][1]["source_units"][0])
        self.assert_error("INTERPRETATION_PACKAGE_INVALID", self.verify, package)

    def test_embedded_scope_expectation_tamper_is_rejected(self):
        package = deepcopy(self.saved)
        package["scope_expectations"]["rules"][0]["expectation"] = "unspecified"
        self.assert_error("INTERPRETATION_PACKAGE_INVALID", self.verify, package)

    def test_extra_package_field_is_rejected_by_exact_reconstruction(self):
        package = deepcopy(self.saved)
        package["claimed_legally_correct"] = True
        self.assert_error("INTERPRETATION_PACKAGE_INVALID", self.verify, package)

    def test_scope_expectations_cannot_omit_a_selected_rule(self):
        expectations = deepcopy(self.expectations)
        expectations["rules"].pop()
        self.assert_error("INTERPRETATION_INVALID", self.compile,
                          expectations=expectations)

    def test_conversion_definition_tamper_is_rejected(self):
        package = deepcopy(self.saved)
        package["conversion_definition_sha256"] = "0" * 64
        self.assert_error("INTERPRETATION_PACKAGE_INVALID", self.verify, package)

    def test_candidate_coverage_cannot_drop_a_source_unit(self):
        candidate = deepcopy(self.candidate)
        candidate["coverage"].pop()
        self.assert_error("INTERPRETATION_INVALID", self.compile, candidate=candidate)


if __name__ == "__main__":
    unittest.main()
