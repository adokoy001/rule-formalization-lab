"""Independent checker for manual source-to-procedure-model bindings.

This module intentionally does not import :mod:`procedurekernel.binding`.  It
revalidates the source package, manual chain, model mapping, acceptance cases,
certificate replay, and the complete deterministic binding document.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from rulekernel.model import KernelError as SourceKernelError
from rulekernel.source_checker import verify_source_package
from rulekernel.source_model import (
    MAX_MANIFEST_BYTES,
    MAX_SOURCE_SPEC_BYTES,
    decode_source_json,
    source_canonical_json,
    source_digest,
)

from .checker import verify as verify_procedure_certificate
from .model import KernelError, canonical_json, digest, validate_model, validate_sha256


TASK_FORMAT = "manual-formalization-task/1"
CANDIDATE_FORMAT = "manual-formalization-candidate/1"
REVIEW_FORMAT = "manual-formalization-review/1"
BINDING_FORMAT = "manual-model-binding/1"
BINDING_CHAIN_FORMAT = "manual-model-binding-chain/1"
BINDING_RESULT = "MANUAL_MODEL_BINDING_VERIFIED"
MAX_BINDING_BYTES = 2 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_COVERAGE = {"partial", "out_of_scope", "unresolved"}


def _fail(message: str) -> None:
    raise KernelError("BINDING_INVALID", message)


def _shape(value: object, fields: set[str], path: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _fail(f"{path}: expected object")
    missing = fields - value.keys()
    extra = value.keys() - fields
    if missing or extra:
        _fail(f"{path}: fields differ; missing={sorted(missing)}, extra={sorted(extra)}")


def _text(value: object, path: str) -> None:
    if type(value) is not str or not value or len(value) > 16384:
        _fail(f"{path}: expected nonempty bounded string")


def _name(value: object, path: str) -> None:
    if type(value) is not str or _NAME.fullmatch(value) is None:
        _fail(f"{path}: invalid identifier")


def _sha(value: object, path: str) -> None:
    try:
        validate_sha256(value, path)
    except KernelError as exc:
        _fail(exc.message)


def _validate_task(task: object, source_result: dict, unit_keys: list[str], source_spec: dict) -> None:
    _shape(task, {
        "format", "task_id", "title", "source", "scope", "required_coverage",
        "acceptance_cases", "constraints", "limitations",
    }, "task")
    if task["format"] != TASK_FORMAT:
        _fail("task.format: unsupported")
    _name(task["task_id"], "task.task_id")
    _text(task["title"], "task.title")
    _shape(task["source"], {
        "document_id", "law_id", "revision_id", "effective_from",
        "source_spec_hash", "source_unit_manifest_sha256", "bundle_sha256",
    }, "task.source")
    source = task["source"]
    for field in ("document_id", "law_id", "revision_id", "effective_from"):
        _text(source[field], f"task.source.{field}")
    for field in ("source_spec_hash", "source_unit_manifest_sha256", "bundle_sha256"):
        _sha(source[field], f"task.source.{field}")
    expected_source = {
        "document_id": source_result["document_id"],
        "law_id": source_spec["source"]["law_id"],
        "revision_id": source_result["revision_id"],
        "effective_from": source_result["effective_from"],
        "source_spec_hash": source_result["source_spec_hash"],
        "source_unit_manifest_sha256": source_result["source_unit_manifest_sha256"],
        "bundle_sha256": source_result["bundle_hash"],
    }
    for field, expected in expected_source.items():
        if source[field] != expected:
            _fail(f"task.source.{field}: verified source anchor mismatch")
    _shape(task["scope"], {
        "diagnostic_kind", "time_unit", "observation_mode", "legal_conclusion",
    }, "task.scope")
    expected_scope = {
        "diagnostic_kind": "limited_numeric_deadline",
        "time_unit": "hour",
        "observation_mode": "closed_prefix",
        "legal_conclusion": False,
    }
    if type(task["scope"]["legal_conclusion"]) is not bool or task["scope"] != expected_scope:
        _fail("task.scope: unsupported scope")
    coverage = task["required_coverage"]
    if type(coverage) is not list or len(coverage) != len(unit_keys):
        _fail("task.required_coverage: every source unit is required")
    found = []
    for index, row in enumerate(coverage):
        path = f"task.required_coverage[{index}]"
        _shape(row, {"unit_key", "status"}, path)
        _name(row["unit_key"], path + ".unit_key")
        if row["unit_key"] not in unit_keys:
            _fail(path + ".unit_key: unknown source unit")
        if type(row["status"]) is not str or row["status"] not in _COVERAGE:
            _fail(path + ".status: unsupported")
        found.append(row["unit_key"])
    if found != unit_keys or len(set(found)) != len(found):
        _fail("task.required_coverage: source-unit order or uniqueness mismatch")
    if type(task["acceptance_cases"]) is not list or not task["acceptance_cases"]:
        _fail("task.acceptance_cases: expected nonempty list")
    if type(task["constraints"]) is not list or not task["constraints"]:
        _fail("task.constraints: expected nonempty list")
    if type(task["limitations"]) is not list or not task["limitations"]:
        _fail("task.limitations: expected nonempty list")
    for group_name in ("constraints", "limitations"):
        for index, item in enumerate(task[group_name]):
            _text(item, f"task.{group_name}[{index}]")


def _validate_candidate(candidate: object, task: dict, manifest_rows: list[dict], model: dict) -> list[dict]:
    _shape(candidate, {
        "format", "candidate_id", "task_id", "task_hash", "source_units",
        "rule_bindings", "decisions",
    }, "candidate")
    if candidate["format"] != CANDIDATE_FORMAT:
        _fail("candidate.format: unsupported")
    _name(candidate["candidate_id"], "candidate.candidate_id")
    _name(candidate["task_id"], "candidate.task_id")
    _sha(candidate["task_hash"], "candidate.task_hash")
    if candidate["task_id"] != task["task_id"] or candidate["task_hash"] != digest(task):
        _fail("candidate: task identity or hash mismatch")
    declared_units = candidate["source_units"]
    if type(declared_units) is not list or len(declared_units) != len(manifest_rows):
        _fail("candidate.source_units: every source unit must be bound")
    evidence = []
    for index, (declared, actual) in enumerate(zip(declared_units, manifest_rows)):
        path = f"candidate.source_units[{index}]"
        _shape(declared, {
            "unit_key", "source_unit_id", "structural_path", "text_sha256", "exact_quote",
        }, path)
        _name(declared["unit_key"], path + ".unit_key")
        _sha(declared["source_unit_id"], path + ".source_unit_id")
        _text(declared["structural_path"], path + ".structural_path")
        _sha(declared["text_sha256"], path + ".text_sha256")
        _text(declared["exact_quote"], path + ".exact_quote")
        expected = {
            "unit_key": actual["unit_key"],
            "source_unit_id": actual["source_unit_id"],
            "structural_path": actual["structural_path"],
            "text_sha256": actual["text_sha256"],
            "exact_quote": actual["exact"],
        }
        if declared != expected:
            _fail(f"candidate.source_units[{index}]: exact quote/unit/hash mismatch")
        evidence.append(expected)
    _shape(candidate["decisions"], {
        "target_semantics", "send_and_receipt_are_distinct",
        "article_204_semantics", "article_206_automatic_extension",
        "article_206_assessment",
    }, "candidate.decisions")
    expected_decisions = {
        "target_semantics": "any_of",
        "send_and_receipt_are_distinct": True,
        "article_204_semantics": "out_of_scope",
        "article_206_automatic_extension": False,
        "article_206_assessment": "unresolved",
    }
    decisions = candidate["decisions"]
    if (type(decisions["send_and_receipt_are_distinct"]) is not bool
            or type(decisions["article_206_automatic_extension"]) is not bool
            or decisions != expected_decisions):
        _fail("candidate.decisions: unsupported or unsafe semantic decision")
    slots = {row["id"] for row in model["slots"]}
    if not {"send_procedure", "prosecutor_receipt"}.issubset(slots):
        _fail("model must keep send_procedure and prosecutor_receipt as separate slots")
    bindings = candidate["rule_bindings"]
    if type(bindings) is not list or not bindings:
        _fail("candidate.rule_bindings: expected nonempty list")
    norm_map = {row["id"]: row for row in model["norms"]}
    seen_rule_ids, seen_norm_ids = set(), set()
    unit_keys = {row["unit_key"] for row in manifest_rows}
    for index, row in enumerate(bindings):
        path = f"candidate.rule_bindings[{index}]"
        _shape(row, {
            "candidate_rule_id", "model_norm_id", "source_unit_keys", "anchor_slot",
            "target_slots", "min_offset", "max_offset", "inclusive",
        }, path)
        _name(row["candidate_rule_id"], path + ".candidate_rule_id")
        _name(row["model_norm_id"], path + ".model_norm_id")
        if row["candidate_rule_id"] in seen_rule_ids or row["model_norm_id"] in seen_norm_ids:
            _fail(path + ": duplicate rule or norm binding")
        seen_rule_ids.add(row["candidate_rule_id"])
        seen_norm_ids.add(row["model_norm_id"])
        source_unit_keys = row["source_unit_keys"]
        if type(source_unit_keys) is not list or not source_unit_keys:
            _fail(path + ".source_unit_keys: expected nonempty list")
        for key_index, key in enumerate(source_unit_keys):
            _name(key, f"{path}.source_unit_keys[{key_index}]")
            if key not in unit_keys:
                _fail(f"{path}.source_unit_keys[{key_index}]: unknown unit")
        if len(set(source_unit_keys)) != len(source_unit_keys):
            _fail(path + ".source_unit_keys: duplicate unit")
        _name(row["anchor_slot"], path + ".anchor_slot")
        if row["anchor_slot"] not in slots:
            _fail(path + ".anchor_slot: unknown slot")
        target_slots = row["target_slots"]
        if type(target_slots) is not list or not target_slots:
            _fail(path + ".target_slots: expected nonempty list")
        for target_index, target in enumerate(target_slots):
            _name(target, f"{path}.target_slots[{target_index}]")
            if target not in slots:
                _fail(f"{path}.target_slots[{target_index}]: unknown slot")
        if len(set(target_slots)) != len(target_slots):
            _fail(path + ".target_slots: duplicate slot")
        if type(row["min_offset"]) is not int or type(row["max_offset"]) is not int:
            _fail(path + ": offsets must be integers")
        if type(row["inclusive"]) is not bool:
            _fail(path + ".inclusive: expected Boolean")
        if "ARTICLE_204" in source_unit_keys or "ARTICLE_206" in source_unit_keys:
            _fail(path + ": out-of-scope or unresolved article cannot create a numeric rule")
        norm = norm_map.get(row["model_norm_id"])
        if norm is None or norm.get("kind") != "deadline":
            _fail(path + ": missing deadline norm")
        expected = {
            "anchor_slot": norm["anchor"],
            "target_slots": norm["targets"],
            "min_offset": norm["min_offset"],
            "max_offset": norm["max_offset"],
            "inclusive": norm["inclusive"],
        }
        if any(row[key] != value for key, value in expected.items()):
            _fail(path + ": candidate/model deadline mismatch")
    if seen_norm_ids != set(norm_map):
        _fail("candidate.rule_bindings: every model norm must be bound exactly once")
    return evidence


def _validate_review(review: object, task: dict, candidate: dict, unit_keys: list[str]) -> dict[str, str]:
    _shape(review, {
        "format", "review_id", "task_id", "task_hash", "candidate_id",
        "candidate_hash", "method", "provisional", "coverage", "rule_decisions",
        "unresolved", "warnings",
    }, "review")
    if review["format"] != REVIEW_FORMAT:
        _fail("review.format: unsupported")
    _name(review["review_id"], "review.review_id")
    _name(review["task_id"], "review.task_id")
    _sha(review["task_hash"], "review.task_hash")
    _name(review["candidate_id"], "review.candidate_id")
    _sha(review["candidate_hash"], "review.candidate_hash")
    if (review["task_id"] != task["task_id"] or review["task_hash"] != digest(task)
            or review["candidate_id"] != candidate["candidate_id"]
            or review["candidate_hash"] != digest(candidate)):
        _fail("review: task/candidate identity or hash mismatch")
    if review["method"] != "manual_fixture_review" or review["provisional"] is not True:
        _fail("review: T10 requires a provisional manual_fixture_review")
    required = {row["unit_key"]: row["status"] for row in task["required_coverage"]}
    if type(review["coverage"]) is not list or len(review["coverage"]) != len(unit_keys):
        _fail("review.coverage: every source unit must have a decision")
    coverage = {}
    for index, row in enumerate(review["coverage"]):
        path = f"review.coverage[{index}]"
        _shape(row, {"unit_key", "status", "note"}, path)
        _name(row["unit_key"], path + ".unit_key")
        if row["unit_key"] not in required:
            _fail(path + ".unit_key: unknown source unit")
        if type(row["status"]) is not str:
            _fail(path + ".status: expected string")
        _text(row["note"], path + ".note")
        if row["unit_key"] in coverage or row["status"] != required[row["unit_key"]]:
            _fail(path + ": required coverage mismatch")
        coverage[row["unit_key"]] = row["status"]
    if list(coverage) != unit_keys:
        _fail("review.coverage: manifest order mismatch")
    rule_ids = [row["candidate_rule_id"] for row in candidate["rule_bindings"]]
    decisions = review["rule_decisions"]
    if type(decisions) is not list or len(decisions) != len(rule_ids):
        _fail("review.rule_decisions: every candidate rule must be reviewed")
    for index, (row, rule_id) in enumerate(zip(decisions, rule_ids)):
        path = f"review.rule_decisions[{index}]"
        _shape(row, {"candidate_rule_id", "status", "note"}, path)
        _name(row["candidate_rule_id"], path + ".candidate_rule_id")
        if type(row["status"]) is not str:
            _fail(path + ".status: expected string")
        if row["candidate_rule_id"] != rule_id or row["status"] != "accepted_limited":
            _fail(f"review.rule_decisions[{index}]: unexpected decision")
        _text(row["note"], f"review.rule_decisions[{index}].note")
    if type(review["unresolved"]) is not list or not review["unresolved"]:
        _fail("review.unresolved: ARTICLE_206 issue must remain explicit")
    issues = set()
    for index, row in enumerate(review["unresolved"]):
        _shape(row, {"issue_id", "status", "effect_on_numeric_diagnostics", "note"}, f"review.unresolved[{index}]")
        _name(row["issue_id"], f"review.unresolved[{index}].issue_id")
        if row["status"] != "unresolved" or row["effect_on_numeric_diagnostics"] != "none":
            _fail(f"review.unresolved[{index}]: unresolved issue cannot rewrite diagnostics")
        _text(row["note"], f"review.unresolved[{index}].note")
        issues.add(row["issue_id"])
    if "ARTICLE_206_JUDICIAL_ASSESSMENT" not in issues:
        _fail("review.unresolved: missing ARTICLE_206_JUDICIAL_ASSESSMENT")
    if type(review["warnings"]) is not list or not review["warnings"]:
        _fail("review.warnings: expected explicit warnings")
    for index, warning in enumerate(review["warnings"]):
        _text(warning, f"review.warnings[{index}]")
    return coverage


def _validate_acceptance(task: dict, model: dict, certificate: dict) -> None:
    context_ids = [row["id"] for row in model["contexts"]]
    model_norm_ids = {row["id"] for row in model["norms"]}
    model_slot_ids = {row["id"] for row in model["slots"]}
    cases = {row["context_id"]: row for row in certificate["cases"]}
    seen = []
    for index, expected_case in enumerate(task["acceptance_cases"]):
        path = f"task.acceptance_cases[{index}]"
        _shape(expected_case, {"context_id", "expected_rule_statuses"}, path)
        context_id = expected_case["context_id"]
        _name(context_id, path + ".context_id")
        seen.append(context_id)
        actual_case = cases.get(context_id)
        if actual_case is None:
            _fail(path + ": certificate case missing")
        actual_rules = {row["norm_id"]: row for row in actual_case["observed_evaluation"]["rules"]}
        rows = expected_case["expected_rule_statuses"]
        if type(rows) is not list or len(rows) != len(model["norms"]):
            _fail(path + ".expected_rule_statuses: every norm must be asserted")
        expected_norm_ids = set()
        for rule_index, expected in enumerate(rows):
            rule_path = f"{path}.expected_rule_statuses[{rule_index}]"
            _shape(expected, {"norm_id", "status", "selected_target"}, rule_path)
            norm_id = expected["norm_id"]
            _name(norm_id, rule_path + ".norm_id")
            if norm_id not in model_norm_ids:
                _fail(rule_path + ".norm_id: unknown model norm")
            if norm_id in expected_norm_ids:
                _fail(rule_path + ".norm_id: duplicate model norm")
            expected_norm_ids.add(norm_id)
            _name(expected["status"], rule_path + ".status")
            selected_target = expected["selected_target"]
            if selected_target is not None:
                _name(selected_target, rule_path + ".selected_target")
                if selected_target not in model_slot_ids:
                    _fail(rule_path + ".selected_target: unknown model slot")
            actual = actual_rules.get(norm_id)
            if (actual is None or actual["status"] != expected["status"]
                    or actual["selected_target"] != selected_target):
                _fail(rule_path + ": replayed status or selected target mismatch")
        if expected_norm_ids != model_norm_ids:
            _fail(path + ".expected_rule_statuses: norm set differs from model")
    if seen != context_ids or len(set(seen)) != len(seen):
        _fail("task.acceptance_cases must cover all model contexts in declared order")


def _pack_diagnostics(certificate: dict, review: dict) -> list[dict]:
    """Derive pack diagnostics from every independently replayed context."""
    release_statuses = {"violated_late", "violated_missing"}
    issues = {}
    unresolved = review.get("unresolved", [])
    if type(unresolved) is list:
        for row in unresolved:
            if type(row) is dict and type(row.get("issue_id")) is str:
                issues[row["issue_id"]] = row
    article206_issue = issues.get("ARTICLE_206_JUDICIAL_ASSESSMENT")

    diagnostics = []
    for case in certificate["cases"]:
        context_id = case["context_id"]
        rules = {
            row["norm_id"]: row["status"]
            for row in case["observed_evaluation"]["rules"]
        }
        trigger_norms = []
        if rules.get("A203_SEND_48H") in release_statuses:
            trigger_norms.append("A203_SEND_48H")
        for norm_id in ("A205_RECEIPT_24H", "A205_RESTRAINT_72H"):
            if rules.get(norm_id) in release_statuses:
                trigger_norms.append(norm_id)
        if trigger_norms:
            diagnostics.append({
                "context_id": context_id,
                "code": "SELECTED_TEXT_RELEASE_TRIGGERED",
                "status": "diagnostic_trigger",
                "basis_norm_ids": trigger_norms,
            })

        slots = {row["slot"] for row in case["observed_events"]}
        if "release" in slots:
            diagnostics.append({
                "context_id": context_id,
                "code": "RELEASE_OBSERVED",
                "status": "observed",
                "basis_norm_ids": [],
            })
        if "article206_explanation" in slots:
            if (article206_issue is None
                    or article206_issue.get("status") != "unresolved"
                    or article206_issue.get("effect_on_numeric_diagnostics") != "none"):
                _fail("ARTICLE_206_ASSESSMENT_UNRESOLVED review prerequisite is absent")
            diagnostics.append({
                "context_id": context_id,
                "code": "ARTICLE_206_ASSESSMENT_UNRESOLVED",
                "status": "unresolved",
                "basis_norm_ids": [],
            })
    return diagnostics


def _read_pinned_source_json(
    path: str | Path,
    *,
    max_bytes: int,
    label: str,
    expected_sha256: str,
    canonical_hash: bool,
) -> dict:
    """Read once, strict-parse those bytes, and bind them to the verified hash."""
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        _fail(f"{label}: missing or unsafe artifact after source verification")
    try:
        with target.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except OSError as exc:
        _fail(f"{label}: read failed after source verification: {exc}")
    if len(raw) > max_bytes:
        _fail(f"{label}: exceeds {max_bytes} bytes")
    try:
        value = decode_source_json(raw, max_bytes=max_bytes, label=label)
        if canonical_hash:
            actual_sha256 = source_digest(value)
        else:
            if source_canonical_json(value).encode("utf-8") != raw:
                _fail(f"{label}: verified artifact is no longer canonical JSON")
            actual_sha256 = hashlib.sha256(raw).hexdigest()
    except SourceKernelError as exc:
        _fail(f"{label}: strict parse failed after source verification: {exc.message}")
    if actual_sha256 != expected_sha256:
        _fail(f"{label}: hash changed after source verification")
    if type(value) is not dict:
        _fail(f"{label}: expected object")
    return value


def _expected_binding(task, candidate, review, model, certificate, source_result, units, coverage):
    hashes = {
        "task": digest(task),
        "candidate": digest(candidate),
        "review": digest(review),
        "model": digest(model),
        "certificate": digest(certificate),
        "source_spec": source_result["source_spec_hash"],
        "source_unit_manifest": source_result["source_unit_manifest_sha256"],
        "source_bundle": source_result["bundle_hash"],
    }
    evidence = []
    for declared in candidate["source_units"]:
        evidence.append({**declared, "coverage": coverage[declared["unit_key"]]})
    return {
        "format": BINDING_FORMAT,
        "result": BINDING_RESULT,
        "task_id": task["task_id"],
        "candidate_id": candidate["candidate_id"],
        "review_id": review["review_id"],
        "source": {
            "document_id": source_result["document_id"],
            "revision_id": source_result["revision_id"],
            "effective_from": source_result["effective_from"],
            "offline_verified": source_result["offline"],
        },
        "artifact_hashes": hashes,
        "chain_hash": digest({"format": BINDING_CHAIN_FORMAT, "artifacts": hashes}),
        "source_units": evidence,
        "coverage": review["coverage"],
        "rule_bindings": candidate["rule_bindings"],
        "pack_diagnostics": _pack_diagnostics(certificate, review),
        "assurance": {
            "review_method": review["method"],
            "provisional": review["provisional"],
            "procedure_certificate_replayed": True,
            "source_package_replayed_offline": True,
            "semantic_lowering_proved": False,
            "legal_conclusion": False,
            "statement": (
                "The exact source units, manual candidate, manual review, finite model, "
                "and replayed certificate are hash-bound. Semantic lowering and legal "
                "correctness are not proved."
            ),
        },
    }


def verify_manual_model_binding(
    task: object,
    candidate: object,
    review: object,
    model: object,
    certificate: object,
    binding: object,
    *,
    source_spec: str | Path,
    source_bundle: str | Path,
    expected_binding_sha256: str | None = None,
) -> dict:
    """Independently replay and verify a complete manual-model binding chain."""
    for name, value in (("task", task), ("candidate", candidate), ("review", review),
                        ("model", model), ("certificate", certificate), ("binding", binding)):
        if type(value) is not dict:
            _fail(f"{name}: expected object")
    try:
        binding_bytes = canonical_json(binding).encode("utf-8")
    except KernelError as exc:
        _fail(exc.message)
    if len(binding_bytes) > MAX_BINDING_BYTES:
        raise KernelError("LIMIT_REACHED", f"Binding exceeds {MAX_BINDING_BYTES} bytes")
    binding_hash = hashlib.sha256(binding_bytes).hexdigest()
    if expected_binding_sha256 is not None:
        _sha(expected_binding_sha256, "expected_binding_sha256")
        if binding_hash != expected_binding_sha256:
            _fail("Binding SHA-256 anchor mismatch")
    task_source = task.get("source")
    if type(task_source) is not dict:
        _fail("task.source: expected object")
    try:
        source_result = verify_source_package(
            source_spec,
            source_bundle,
            expected_bundle_sha256=task_source.get("bundle_sha256"),
        )
    except (SourceKernelError, OSError) as exc:
        message = getattr(exc, "message", str(exc))
        _fail(f"Source package verification failed: {message}")
    source_spec_value = _read_pinned_source_json(
        source_spec,
        max_bytes=MAX_SOURCE_SPEC_BYTES,
        label="source spec",
        expected_sha256=source_result["source_spec_hash"],
        canonical_hash=True,
    )
    units = _read_pinned_source_json(
        Path(source_bundle) / "derived" / "source-units.json",
        max_bytes=MAX_MANIFEST_BYTES,
        label="source-unit manifest",
        expected_sha256=source_result["source_unit_manifest_sha256"],
        canonical_hash=False,
    )
    if type(source_spec_value.get("source")) is not dict:
        _fail("Source spec shape is invalid")
    if type(units.get("units")) is not list:
        _fail("Source-unit manifest shape is invalid")
    manifest_rows = units["units"]
    unit_keys = [row["unit_key"] for row in manifest_rows]
    _validate_task(task, source_result, unit_keys, source_spec_value)
    try:
        validate_model(model)
    except KernelError as exc:
        _fail(f"Model validation failed: {exc.message}")
    if model["time_unit"] != task["scope"]["time_unit"] or model["observation_mode"] != task["scope"]["observation_mode"]:
        _fail("Model time/observation profile differs from task scope")
    _validate_candidate(candidate, task, manifest_rows, model)
    coverage = _validate_review(review, task, candidate, unit_keys)
    certificate_hash = digest(certificate)
    try:
        certificate_result = verify_procedure_certificate(
            model,
            certificate,
            expected_certificate_sha256=certificate_hash,
        )
    except KernelError as exc:
        _fail(f"Procedure certificate verification failed: {exc.message}")
    _validate_acceptance(task, model, certificate)
    expected = _expected_binding(
        task, candidate, review, model, certificate, source_result, units, coverage
    )
    expected_bytes = canonical_json(expected).encode("utf-8")
    if binding_bytes != expected_bytes:
        _fail("Binding differs from independent reconstruction")
    return {
        "status": BINDING_RESULT,
        "binding_hash": binding_hash,
        "binding_hash_anchored": expected_binding_sha256 is not None,
        "chain_hash": expected["chain_hash"],
        "source_bundle_hash": source_result["bundle_hash"],
        "source_unit_count": source_result["unit_count"],
        "model_hash": digest(model),
        "certificate_hash": certificate_result["certificate_hash"],
        "context_count": certificate_result["counts"]["total_contexts"],
        "semantic_lowering_proved": False,
        "legal_conclusion": False,
    }
