"""Producer for a manually reviewed source-to-procedure-model binding.

The binding is deliberately an integrity artifact.  It records the manual
formalization chain and its exact inputs; it does not claim that natural
language was semantically lowered by a proof-producing translation.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

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
from .model import KernelError, canonical_json, digest


TASK_FORMAT = "manual-formalization-task/1"
CANDIDATE_FORMAT = "manual-formalization-candidate/1"
REVIEW_FORMAT = "manual-formalization-review/1"
BINDING_FORMAT = "manual-model-binding/1"
BINDING_CHAIN_FORMAT = "manual-model-binding-chain/1"
BINDING_RESULT = "MANUAL_MODEL_BINDING_VERIFIED"


def _fail(message: str) -> None:
    raise KernelError("BINDING_INVALID", message)


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


def _artifact_hashes(task, candidate, review, model, certificate, source_result):
    return {
        "task": digest(task),
        "candidate": digest(candidate),
        "review": digest(review),
        "model": digest(model),
        "certificate": digest(certificate),
        "source_spec": source_result["source_spec_hash"],
        "source_unit_manifest": source_result["source_unit_manifest_sha256"],
        "source_bundle": source_result["bundle_hash"],
    }


def _source_evidence(candidate: dict, units: dict, review: dict) -> list[dict]:
    manifest_rows = {}
    for index, row in enumerate(units["units"]):
        if type(row) is not dict or type(row.get("unit_key")) is not str:
            _fail(f"Source-unit manifest row {index} has an invalid unit_key")
        if row["unit_key"] in manifest_rows:
            _fail(f"Source-unit manifest repeats {row['unit_key']!r}")
        manifest_rows[row["unit_key"]] = row

    coverage = {}
    review_rows = review.get("coverage")
    if type(review_rows) is not list:
        _fail("Review coverage must be a list")
    for index, row in enumerate(review_rows):
        if (type(row) is not dict or type(row.get("unit_key")) is not str
                or type(row.get("status")) is not str):
            _fail(f"Review coverage row {index} has invalid nested types")
        if row["unit_key"] in coverage:
            _fail(f"Review coverage repeats {row['unit_key']!r}")
        coverage[row["unit_key"]] = row["status"]

    declared_rows = candidate.get("source_units")
    if type(declared_rows) is not list:
        _fail("Candidate source_units must be a list")
    output = []
    for index, declared in enumerate(declared_rows):
        if type(declared) is not dict or type(declared.get("unit_key")) is not str:
            _fail(f"Candidate source unit {index} has an invalid unit_key")
        actual = manifest_rows.get(declared["unit_key"])
        if actual is None:
            _fail(f"Candidate names an unknown source unit: {declared['unit_key']!r}")
        expected = {
            "unit_key": actual["unit_key"],
            "source_unit_id": actual["source_unit_id"],
            "structural_path": actual["structural_path"],
            "text_sha256": actual["text_sha256"],
            "exact_quote": actual["exact"],
        }
        if declared != expected:
            _fail(f"Candidate quote or source-unit identity differs for {actual['unit_key']}")
        if actual["unit_key"] not in coverage:
            _fail(f"Review omits coverage for {actual['unit_key']}")
        output.append({**expected, "coverage": coverage[actual["unit_key"]]})
    if [row["unit_key"] for row in output] != [row["unit_key"] for row in units["units"]]:
        _fail("Candidate must bind every source unit once, in manifest order")
    return output

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


def build_manual_model_binding(
    task: object,
    candidate: object,
    review: object,
    model: object,
    certificate: object,
    *,
    source_spec: str | Path,
    source_bundle: str | Path,
) -> dict:
    """Build a deterministic binding after independent source/certificate checks."""
    if not all(type(value) is dict for value in (task, candidate, review, model, certificate)):
        _fail("Task, candidate, review, model, and certificate must be objects")
    if task.get("format") != TASK_FORMAT:
        _fail("Unsupported task format")
    if candidate.get("format") != CANDIDATE_FORMAT:
        _fail("Unsupported candidate format")
    if review.get("format") != REVIEW_FORMAT:
        _fail("Unsupported review format")
    if candidate.get("task_hash") != digest(task):
        _fail("Candidate task_hash mismatch")
    if review.get("task_hash") != digest(task) or review.get("candidate_hash") != digest(candidate):
        _fail("Review hash chain mismatch")
    task_source = task.get("source")
    if type(task_source) is not dict:
        _fail("Task source must be an object")
    try:
        source_result = verify_source_package(
            source_spec,
            source_bundle,
            expected_bundle_sha256=task_source.get("bundle_sha256"),
        )
    except (SourceKernelError, OSError) as exc:
        message = getattr(exc, "message", str(exc))
        _fail(f"Source package verification failed: {message}")
    certificate_hash = digest(certificate)
    try:
        verify_procedure_certificate(
            model,
            certificate,
            expected_certificate_sha256=certificate_hash,
        )
    except KernelError as exc:
        _fail(f"Procedure certificate verification failed: {exc.message}")
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
    if type(units.get("units")) is not list:
        _fail("source-unit manifest: units must be a list")
    if (type(task_source) is not dict
            or type(source_spec_value.get("source")) is not dict
            or task_source.get("law_id") != source_spec_value["source"].get("law_id")):
        _fail("Task law_id differs from the verified source spec")
    evidence = _source_evidence(candidate, units, review)
    diagnostics = _pack_diagnostics(certificate, review)
    hashes = _artifact_hashes(task, candidate, review, model, certificate, source_result)
    chain_hash = digest({"format": BINDING_CHAIN_FORMAT, "artifacts": hashes})
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
        "chain_hash": chain_hash,
        "source_units": evidence,
        "coverage": review["coverage"],
        "rule_bindings": candidate["rule_bindings"],
        "pack_diagnostics": diagnostics,
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


def binding_sha256(binding: object) -> str:
    return hashlib.sha256(canonical_json(binding).encode("utf-8")).hexdigest()
