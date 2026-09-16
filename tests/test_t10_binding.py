"""Manual binding replay and tamper tests for the T10 pack."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import inspect
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from procedurekernel.binding import build_manual_model_binding
from procedurekernel.binding_checker import verify_manual_model_binding
import procedurekernel.binding as binding_producer
import procedurekernel.binding_checker as independent_checker
import procedurekernel.t10_binding_cli as binding_cli
from procedurekernel.engine import analyze
from procedurekernel.model import KernelError, canonical_json, digest, load_json


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples/procedures/t10-criminal-procedure-203-205"
SOURCE = ROOT / "examples/sources/criminal-procedure-55-203-206"
BINDING_HASH = "e76cf9be471e45a5f83cb35083c15470f8f4ff3be6c1424ad3e97aec3b126811"
TASK_HASH = "7e632ccc46de8a2b14f73c567e6381657d4823f88d0392df13274f9d293f3f98"
CANDIDATE_HASH = "abdc9adba9169e774be3906dc3196b824b0e1a2192c9c584e7dbb60c12b0ca94"
REVIEW_HASH = "421b90a5a58f544aa842b1c1e2a9c1f4bd17eb202bb9f9ad91ccbae0840882cb"


class T10BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = load_json(PACK / "task.json")
        cls.candidate = load_json(PACK / "candidate.json")
        cls.review = load_json(PACK / "review.json")
        cls.model = load_json(PACK / "model.json")
        cls.certificate = load_json(PACK / "certificate.json", max_bytes=8 * 1024 * 1024)
        cls.binding = load_json(PACK / "binding.json", max_bytes=2 * 1024 * 1024)

    def checked(self, *, task=None, candidate=None, review=None, model=None,
                certificate=None, binding=None, source_bundle=None, anchor=BINDING_HASH):
        return verify_manual_model_binding(
            self.task if task is None else task,
            self.candidate if candidate is None else candidate,
            self.review if review is None else review,
            self.model if model is None else model,
            self.certificate if certificate is None else certificate,
            self.binding if binding is None else binding,
            source_spec=SOURCE / "source-spec.json",
            source_bundle=SOURCE / "bundle" if source_bundle is None else source_bundle,
            expected_binding_sha256=anchor,
        )

    def assert_rejected(self, **changes):
        with self.assertRaises(KernelError) as caught:
            self.checked(anchor=None, **changes)
        self.assertEqual(caught.exception.status, "BINDING_INVALID")

    def test_external_anchor_and_complete_independent_replay(self):
        result = self.checked()
        self.assertEqual(result["status"], "MANUAL_MODEL_BINDING_VERIFIED")
        self.assertTrue(result["binding_hash_anchored"])
        self.assertEqual(result["source_unit_count"], 5)
        self.assertEqual(result["context_count"], 13)
        self.assertFalse(result["semantic_lowering_proved"])
        self.assertFalse(result["legal_conclusion"])
        hashes = self.binding["artifact_hashes"]
        self.assertEqual(hashes["task"], TASK_HASH)
        self.assertEqual(hashes["candidate"], CANDIDATE_HASH)
        self.assertEqual(hashes["review"], REVIEW_HASH)

    def test_producer_matches_saved_binding_but_checker_does_not_import_producer(self):
        generated = build_manual_model_binding(
            self.task, self.candidate, self.review, self.model, self.certificate,
            source_spec=SOURCE / "source-spec.json",
            source_bundle=SOURCE / "bundle",
        )
        self.assertEqual(generated, self.binding)
        source = inspect.getsource(independent_checker)
        self.assertNotIn("from .binding import", source)
        self.assertNotIn("import procedurekernel.binding", source)

    def test_quote_unit_id_and_text_hash_tampering_are_each_rejected(self):
        mutations = []
        changed = deepcopy(self.candidate)
        changed["source_units"][1]["exact_quote"] += "改ざん"
        mutations.append(changed)
        changed = deepcopy(self.candidate)
        changed["source_units"][1]["source_unit_id"] = "0" * 64
        mutations.append(changed)
        changed = deepcopy(self.candidate)
        changed["source_units"][1]["text_sha256"] = "0" * 64
        mutations.append(changed)
        for changed in mutations:
            with self.subTest(field=next(
                key for key in ("exact_quote", "source_unit_id", "text_sha256")
                if changed["source_units"][1][key] != self.candidate["source_units"][1][key]
            )):
                self.assert_rejected(candidate=changed)

    def test_candidate_review_model_certificate_coverage_and_binding_tampering(self):
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["rule_bindings"][0]["max_offset"] = 47
        self.assert_rejected(candidate=changed_candidate)

        changed_review = deepcopy(self.review)
        changed_review["warnings"][0] += " changed"
        self.assert_rejected(review=changed_review)

        changed_coverage = deepcopy(self.review)
        changed_coverage["coverage"][3]["status"] = "unresolved"
        self.assert_rejected(review=changed_coverage)

        changed_model = deepcopy(self.model)
        changed_model["norms"][1]["max_offset"] = 23
        self.assert_rejected(model=changed_model)

        changed_certificate = deepcopy(self.certificate)
        changed_certificate["cases"][0]["observed_evaluation"]["rules"][0]["status"] = "pending"
        self.assert_rejected(certificate=changed_certificate)

        changed_binding = deepcopy(self.binding)
        changed_binding["chain_hash"] = "0" * 64
        self.assert_rejected(binding=changed_binding)

    def test_binding_reconstruction_distinguishes_json_scalar_types(self):
        mutations = []
        changed = deepcopy(self.binding)
        changed["assurance"]["semantic_lowering_proved"] = 0
        mutations.append(("false_as_zero", changed))
        changed = deepcopy(self.binding)
        changed["assurance"]["provisional"] = 1
        mutations.append(("true_as_one", changed))
        changed = deepcopy(self.binding)
        changed["rule_bindings"][0]["max_offset"] = 48.0
        mutations.append(("integer_as_float", changed))
        for label, changed in mutations:
            with self.subTest(label=label):
                self.assertEqual(changed, self.binding)  # Python scalar equality is looser than JSON.
                self.assert_rejected(binding=changed)

    def test_task_and_candidate_semantic_booleans_require_boolean_types(self):
        variants = []

        changed_task = deepcopy(self.task)
        changed_task["scope"]["legal_conclusion"] = 0
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["task_hash"] = digest(changed_task)
        changed_review = deepcopy(self.review)
        changed_review["task_hash"] = digest(changed_task)
        changed_review["candidate_hash"] = digest(changed_candidate)
        variants.append(("task_scope_false_as_zero", changed_task, changed_candidate, changed_review))

        for field, replacement in (
            ("send_and_receipt_are_distinct", 1),
            ("article_206_automatic_extension", 0),
        ):
            changed_candidate = deepcopy(self.candidate)
            changed_candidate["decisions"][field] = replacement
            changed_review = deepcopy(self.review)
            changed_review["candidate_hash"] = digest(changed_candidate)
            variants.append((field, self.task, changed_candidate, changed_review))

        for label, task, candidate, review in variants:
            with self.subTest(label=label):
                binding = build_manual_model_binding(
                    task, candidate, review, self.model, self.certificate,
                    source_spec=SOURCE / "source-spec.json",
                    source_bundle=SOURCE / "bundle",
                )
                with self.assertRaises(KernelError) as caught:
                    self.checked(
                        task=task,
                        candidate=candidate,
                        review=review,
                        binding=binding,
                        anchor=None,
                    )
                self.assertEqual(caught.exception.status, "BINDING_INVALID")
                self.assertRegex(caught.exception.message, r"task.scope|candidate.decisions")

    def test_task_source_identity_and_external_binding_anchor_are_enforced(self):
        changed = deepcopy(self.task)
        changed["source"]["law_id"] = "0000000000000000"
        with self.assertRaises(KernelError) as caught:
            self.checked(task=changed, anchor=None)
        self.assertEqual(caught.exception.status, "BINDING_INVALID")
        self.assertIn("task.source.law_id: verified source anchor mismatch", caught.exception.message)
        with self.assertRaises(KernelError) as caught:
            self.checked(anchor="0" * 64)
        self.assertEqual(caught.exception.status, "BINDING_INVALID")

    def test_task_acceptance_rejects_receipt_anchor_changed_to_send(self):
        changed_model = deepcopy(self.model)
        changed_model["norms"][1]["anchor"] = "send_procedure"
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["rule_bindings"][1]["anchor_slot"] = "send_procedure"
        changed_review = deepcopy(self.review)
        changed_review["candidate_hash"] = digest(changed_candidate)
        changed_certificate = analyze(changed_model)
        changed_binding = build_manual_model_binding(
            self.task, changed_candidate, changed_review, changed_model, changed_certificate,
            source_spec=SOURCE / "source-spec.json",
            source_bundle=SOURCE / "bundle",
        )
        with self.assertRaises(KernelError) as caught:
            self.checked(
                candidate=changed_candidate,
                review=changed_review,
                model=changed_model,
                certificate=changed_certificate,
                binding=changed_binding,
                anchor=None,
            )
        self.assertEqual(caught.exception.status, "BINDING_INVALID")
        self.assertIn("replayed status or selected target mismatch", caught.exception.message)

    def test_checker_rejects_deleting_one_article_205_deadline(self):
        changed_model = deepcopy(self.model)
        changed_model["norms"] = [
            row for row in changed_model["norms"] if row["id"] != "A205_RESTRAINT_72H"
        ]
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["rule_bindings"] = [
            row for row in changed_candidate["rule_bindings"]
            if row["model_norm_id"] != "A205_RESTRAINT_72H"
        ]
        changed_review = deepcopy(self.review)
        changed_review["candidate_hash"] = digest(changed_candidate)
        changed_review["rule_decisions"] = [
            row for row in changed_review["rule_decisions"]
            if row["candidate_rule_id"] != "C_A205_RESTRAINT_72H"
        ]
        changed_certificate = analyze(changed_model)
        with self.assertRaises(KernelError) as caught:
            self.checked(
                candidate=changed_candidate,
                review=changed_review,
                model=changed_model,
                certificate=changed_certificate,
                anchor=None,
            )
        self.assertEqual(caught.exception.status, "BINDING_INVALID")
        self.assertIn("every norm must be asserted", caught.exception.message)

    def test_checker_rejects_article_206_automatic_extension_true(self):
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["decisions"]["article_206_automatic_extension"] = True
        changed_review = deepcopy(self.review)
        changed_review["candidate_hash"] = digest(changed_candidate)
        with self.assertRaises(KernelError) as caught:
            self.checked(candidate=changed_candidate, review=changed_review, anchor=None)
        self.assertEqual(caught.exception.status, "BINDING_INVALID")
        self.assertIn("unsafe semantic decision", caught.exception.message)


    def test_acceptance_rejects_duplicate_norm_ids_in_self_consistent_chain(self):
        changed_task = deepcopy(self.task)
        statuses = changed_task["acceptance_cases"][0]["expected_rule_statuses"]
        statuses[:] = [deepcopy(statuses[0]) for _ in statuses]
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["task_hash"] = digest(changed_task)
        changed_review = deepcopy(self.review)
        changed_review["task_hash"] = digest(changed_task)
        changed_review["candidate_hash"] = digest(changed_candidate)
        changed_binding = build_manual_model_binding(
            changed_task, changed_candidate, changed_review, self.model, self.certificate,
            source_spec=SOURCE / "source-spec.json",
            source_bundle=SOURCE / "bundle",
        )
        with self.assertRaises(KernelError) as caught:
            self.checked(
                task=changed_task,
                candidate=changed_candidate,
                review=changed_review,
                binding=changed_binding,
                anchor=None,
            )
        self.assertEqual(caught.exception.status, "BINDING_INVALID")
        self.assertIn("duplicate model norm", caught.exception.message)

    def test_nested_identifier_types_fail_closed_as_binding_invalid(self):
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["rule_bindings"][0]["source_unit_keys"][0] = []
        self.assert_rejected(candidate=changed_candidate)

        changed_candidate = deepcopy(self.candidate)
        changed_candidate["rule_bindings"][0]["target_slots"][0] = []
        self.assert_rejected(candidate=changed_candidate)

        changed_review = deepcopy(self.review)
        changed_review["coverage"][0]["unit_key"] = []
        self.assert_rejected(review=changed_review)

        changed_task = deepcopy(self.task)
        changed_task["acceptance_cases"][0]["expected_rule_statuses"][0]["norm_id"] = []
        changed_candidate = deepcopy(self.candidate)
        changed_candidate["task_hash"] = digest(changed_task)
        changed_review = deepcopy(self.review)
        changed_review["task_hash"] = digest(changed_task)
        changed_review["candidate_hash"] = digest(changed_candidate)
        changed_binding = build_manual_model_binding(
            changed_task, changed_candidate, changed_review, self.model, self.certificate,
            source_spec=SOURCE / "source-spec.json",
            source_bundle=SOURCE / "bundle",
        )
        self.assert_rejected(
            task=changed_task,
            candidate=changed_candidate,
            review=changed_review,
            binding=changed_binding,
        )

    def test_cli_task_source_list_is_structured_without_traceback(self):
        changed_task = deepcopy(self.task)
        changed_task["source"] = []
        with tempfile.TemporaryDirectory() as temporary:
            task_path = Path(temporary) / "task.json"
            task_path.write_text(
                canonical_json(changed_task), encoding="utf-8", newline="\n"
            )
            stdout, stderr = io.StringIO(), io.StringIO()
            arguments = [
                str(task_path),
                str(PACK / "candidate.json"),
                str(PACK / "review.json"),
                str(PACK / "model.json"),
                str(PACK / "certificate.json"),
                str(PACK / "binding.json"),
                str(SOURCE / "source-spec.json"),
                str(SOURCE / "bundle"),
                "--json",
            ]
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = binding_cli.main(arguments)
        self.assertEqual(code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "BINDING_INVALID")
        self.assertIn("task.source: expected object", payload["message"])
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())

    def test_cli_nested_type_error_is_structured_without_traceback(self):
        changed_review = deepcopy(self.review)
        changed_review["coverage"][0]["unit_key"] = []
        with tempfile.TemporaryDirectory() as temporary:
            review_path = Path(temporary) / "review.json"
            review_path.write_text(
                canonical_json(changed_review), encoding="utf-8", newline="\n"
            )
            stdout, stderr = io.StringIO(), io.StringIO()
            arguments = [
                str(PACK / "task.json"),
                str(PACK / "candidate.json"),
                str(review_path),
                str(PACK / "model.json"),
                str(PACK / "certificate.json"),
                str(PACK / "binding.json"),
                str(SOURCE / "source-spec.json"),
                str(SOURCE / "bundle"),
                "--json",
            ]
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = binding_cli.main(arguments)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "BINDING_INVALID")
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())


    def test_checker_rejects_source_spec_swap_immediately_after_source_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_source = Path(temporary) / "source"
            shutil.copytree(SOURCE, copied_source)
            spec_path = copied_source / "source-spec.json"
            real_verify = independent_checker.verify_source_package

            def verify_then_swap(*args, **kwargs):
                result = real_verify(*args, **kwargs)
                spec = json.loads(spec_path.read_bytes())
                spec["source"]["document_id"] += "_swapped"
                spec_path.write_text(
                    json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                    newline="\n",
                )
                return result

            with patch.object(
                independent_checker, "verify_source_package", side_effect=verify_then_swap
            ):
                with self.assertRaises(KernelError) as caught:
                    verify_manual_model_binding(
                        self.task, self.candidate, self.review, self.model,
                        self.certificate, self.binding,
                        source_spec=spec_path,
                        source_bundle=copied_source / "bundle",
                    )
        self.assertEqual(caught.exception.status, "BINDING_INVALID")
        self.assertIn("source spec: hash changed after source verification", caught.exception.message)

    def test_producer_rejects_source_unit_swap_immediately_after_source_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_source = Path(temporary) / "source"
            shutil.copytree(SOURCE, copied_source)
            units_path = copied_source / "bundle/derived/source-units.json"
            real_verify = binding_producer.verify_source_package

            def verify_then_swap(*args, **kwargs):
                result = real_verify(*args, **kwargs)
                units = json.loads(units_path.read_bytes())
                units["units"][0]["exact"] += "swap"
                units_path.write_text(
                    canonical_json(units), encoding="utf-8", newline="\n"
                )
                return result

            with patch.object(
                binding_producer, "verify_source_package", side_effect=verify_then_swap
            ):
                with self.assertRaises(KernelError) as caught:
                    build_manual_model_binding(
                        self.task, self.candidate, self.review, self.model,
                        self.certificate,
                        source_spec=copied_source / "source-spec.json",
                        source_bundle=copied_source / "bundle",
                    )
        self.assertEqual(caught.exception.status, "BINDING_INVALID")
        self.assertIn(
            "source-unit manifest: hash changed after source verification",
            caught.exception.message,
        )

    def test_saved_source_package_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "bundle"
            shutil.copytree(SOURCE / "bundle", copied)
            units = copied / "derived/source-units.json"
            raw = bytearray(units.read_bytes())
            raw[-2] = ord("0") if raw[-2] != ord("0") else ord("1")
            units.write_bytes(bytes(raw))
            self.assert_rejected(source_bundle=copied)


if __name__ == "__main__":
    unittest.main()
