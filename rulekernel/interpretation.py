"""Deterministic producer for reviewed interpretation packages."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .interpretation_model import (
    CONVERSION_PROFILE,
    INTERPRETED_PACKAGE_FORMAT,
    LOWERING_DEFINITION_SHA256,
    bind_task_to_source,
    core_rule_id,
    ensure_review_allows_compilation,
    interpretation_digest,
    interpretation_snapshot_digest,
    load_interpretation_json,
    validate_candidate,
    validate_review,
    validate_scope_expectations,
)
from .model import KernelError, validate_model
from .source_checker import verify_source_package
from .source_model import MAX_MANIFEST_BYTES, load_source_json


PRODUCER_VERSION = "0.1.0"


def _load(value):
    return load_interpretation_json(value) if not isinstance(value, dict) else value


def _require_anchor(value, label: str) -> None:
    if (type(value) is not str or len(value) != 64 or
            any(character not in "0123456789abcdef" for character in value)):
        raise KernelError("INTERPRETATION_INVALID", f"{label} must be a lowercase SHA-256")


def _source_manifest(bundle_path):
    return load_source_json(
        Path(bundle_path) / "derived" / "source-units.json",
        max_bytes=MAX_MANIFEST_BYTES,
        label="source unit manifest",
    )


def _source_text(provision, units_by_id) -> str:
    ordered = sorted(
        (units_by_id[unit_id] for unit_id in provision["source_unit_ids"]),
        key=lambda unit: unit["index"],
    )
    return "\n".join(unit["exact"] for unit in ordered)


def _lower_core(task, candidate_index, review, units_by_id):
    rules = []
    for provision_id in sorted(review["selected_provision_ids"]):
        provision = candidate_index["provisions"][provision_id]
        rules.append({
            "id": core_rule_id(provision_id),
            "source": _source_text(provision, units_by_id),
            "when": provision["when"],
            "then": provision["then"],
            "overrides": sorted(core_rule_id(target) for target in provision["overrides"]),
        })
    scope = task["core_scope"]
    core = {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": scope["title"],
        "inputs": scope["inputs"],
        "outputs": scope["outputs"],
        "constraints": scope["constraints"],
        "facts": scope["facts"],
        "rules": rules,
    }
    validate_model(core)
    return core


def _provenance(candidate_index, review, units_by_id):
    result = []
    for provision_id in sorted(review["selected_provision_ids"]):
        provision = candidate_index["provisions"][provision_id]
        units = []
        for unit_id in sorted(provision["source_unit_ids"], key=lambda item: units_by_id[item]["index"]):
            unit = units_by_id[unit_id]
            units.append({
                "source_unit_id": unit_id,
                "index": unit["index"],
                "start_codepoint": unit["start_codepoint"],
                "end_codepoint": unit["end_codepoint"],
                "exact": unit["exact"],
                "text_sha256": unit["text_sha256"],
                "structural_path": unit["structural_path"],
            })
        quote_hashes = [{
            "source_unit_id": quote["source_unit_id"],
            "exact_sha256": hashlib.sha256(quote["exact"].encode("utf-8")).hexdigest(),
        } for quote in sorted(provision["source_quotes"],
                              key=lambda item: units_by_id[item["source_unit_id"]]["index"])]
        result.append({
            "core_rule_id": core_rule_id(provision_id),
            "candidate_provision_id": provision_id,
            "provision_kind": provision["kind"],
            "transformation_rule_id": (
                "copy-sufficient-decision/1" if provision["kind"] == "decision_rule"
                else "copy-replacement-exception/1"
            ),
            "source_units": units,
            "candidate_quote_hashes": quote_hashes,
        })
    return result


def _package(task, candidate, review, scope_expectations, candidate_index,
             units_by_id, core):
    counts = {"selected": 0, "unresolved": 0, "excluded": 0}
    for decision in review["coverage_decisions"]:
        counts[decision["disposition"]] += 1
    return {
        "format": INTERPRETED_PACKAGE_FORMAT,
        "origin_kind": "interpreted_source",
        "conversion_profile": CONVERSION_PROFILE,
        "conversion_definition_sha256": LOWERING_DEFINITION_SHA256,
        "producer_version": PRODUCER_VERSION,
        "bindings": {
            "source": task["source"],
            "task_sha256": interpretation_digest(task),
            "candidate_sha256": interpretation_digest(candidate),
            "review_sha256": interpretation_digest(review),
            "interpretation_snapshot_sha256": interpretation_snapshot_digest(
                task, candidate, review),
            "scope_sha256": interpretation_digest(task["core_scope"]),
            "scope_expectations_sha256": interpretation_digest(scope_expectations),
        },
        "core": core,
        "core_model_hash": interpretation_digest(core),
        "provenance_map": _provenance(candidate_index, review, units_by_id),
        "review_summary": {
            "review_id": review["review_id"],
            "state": review["state"],
            "selected_provision_ids": sorted(review["selected_provision_ids"]),
            "accepted_assumption_ids": sorted(review["accepted_assumption_ids"]),
            "semantic_test_ids": sorted(test["id"] for test in review["semantic_tests"]),
            "coverage_counts": counts,
            "semantic_correspondence": "HOST_REVIEW_RECORDED",
        },
        "scope_expectations": scope_expectations,
    }


def compile_interpretation(
        task_or_path, candidate_or_path, review_or_path, scope_expectations_or_path,
        source_spec_or_path, source_bundle,
        *, expected_source_bundle_sha256, expected_review_sha256,
        expected_scope_expectations_sha256):
    """Compile an approved candidate; the caller must supply host-side anchors."""
    _require_anchor(expected_source_bundle_sha256, "expected_source_bundle_sha256")
    _require_anchor(expected_review_sha256, "expected_review_sha256")
    _require_anchor(expected_scope_expectations_sha256,
                    "expected_scope_expectations_sha256")
    task = _load(task_or_path)
    candidate = _load(candidate_or_path)
    review = _load(review_or_path)
    scope_expectations = _load(scope_expectations_or_path)
    if interpretation_digest(review) != expected_review_sha256:
        raise KernelError("INTERPRETATION_MISMATCH",
                          "host review differs from the external review hash")
    if interpretation_digest(scope_expectations) != expected_scope_expectations_sha256:
        raise KernelError("INTERPRETATION_MISMATCH",
                          "scope expectations differ from the external expectations hash")
    source_result = verify_source_package(
        source_spec_or_path, source_bundle,
        expected_bundle_sha256=expected_source_bundle_sha256,
    )
    source_manifest = _source_manifest(source_bundle)
    units_by_id = bind_task_to_source(task, source_result, source_manifest)
    candidate_index = validate_candidate(task, candidate, units_by_id, source_manifest)
    validate_review(task, candidate, review, candidate_index)
    ensure_review_allows_compilation(review, candidate_index)
    core = _lower_core(task, candidate_index, review, units_by_id)
    core_hash = interpretation_digest(core)
    validate_scope_expectations(
        task, candidate, review, candidate_index, scope_expectations,
        core_model_hash=core_hash,
    )
    return _package(
        task, candidate, review, scope_expectations, candidate_index, units_by_id, core,
    )
