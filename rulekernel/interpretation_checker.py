"""Independent reconstruction of reviewed interpretation packages.

This checker shares strict parsers, validators, hashing, and the existing Core
model boundary with the producer.  It does not import the interpretation
producer and independently rebuilds Core rules, provenance, review summary,
and semantic boundary examples.  This is an implementation cross-check, not a
proof that a host review is correct or authentic.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .interpretation_model import (
    CONVERSION_PROFILE,
    INTERPRETED_PACKAGE_FORMAT,
    LOWERING_DEFINITION_SHA256,
    MAX_INTERPRETATION_BYTES,
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
from .model import KernelError, canonical_json, validate_model
from .source_checker import verify_source_package
from .source_model import MAX_MANIFEST_BYTES, load_source_json


CHECKER_VERSION = "0.1.0"
_PRODUCER_VERSION = "0.1.0"


def _load(value):
    return load_interpretation_json(value) if not isinstance(value, dict) else value


def _require_anchor(value, label: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if (type(value) is not str or len(value) != 64 or
            any(character not in "0123456789abcdef" for character in value)):
        raise KernelError("INTERPRETATION_INVALID", f"{label} must be a lowercase SHA-256")


def _source_manifest(bundle_path):
    return load_source_json(
        Path(bundle_path) / "derived" / "source-units.json",
        max_bytes=MAX_MANIFEST_BYTES,
        label="source unit manifest",
    )


def _whole_source(provision, units_by_id):
    rows = sorted((units_by_id[item] for item in provision["source_unit_ids"]),
                  key=lambda item: item["index"])
    return "\n".join(row["exact"] for row in rows)


def _reconstruct_core(task, candidate_index, review, units_by_id):
    scope = task["core_scope"]
    rules = []
    for provision_id in sorted(review["selected_provision_ids"]):
        provision = candidate_index["provisions"][provision_id]
        rules.append({
            "id": "IR_" + provision_id,
            "source": _whole_source(provision, units_by_id),
            "when": provision["when"],
            "then": provision["then"],
            "overrides": sorted("IR_" + target for target in provision["overrides"]),
        })
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


def _reconstruct_provenance(candidate_index, review, units_by_id):
    mappings = []
    for provision_id in sorted(review["selected_provision_ids"]):
        provision = candidate_index["provisions"][provision_id]
        source_units = []
        for unit_id in sorted(provision["source_unit_ids"],
                              key=lambda item: units_by_id[item]["index"]):
            unit = units_by_id[unit_id]
            source_units.append({
                "source_unit_id": unit_id,
                "index": unit["index"],
                "start_codepoint": unit["start_codepoint"],
                "end_codepoint": unit["end_codepoint"],
                "exact": unit["exact"],
                "text_sha256": unit["text_sha256"],
                "structural_path": unit["structural_path"],
            })
        quote_hashes = []
        for quote in sorted(provision["source_quotes"],
                            key=lambda item: units_by_id[item["source_unit_id"]]["index"]):
            quote_hashes.append({
                "source_unit_id": quote["source_unit_id"],
                "exact_sha256": hashlib.sha256(quote["exact"].encode("utf-8")).hexdigest(),
            })
        mappings.append({
            "core_rule_id": "IR_" + provision_id,
            "candidate_provision_id": provision_id,
            "provision_kind": provision["kind"],
            "transformation_rule_id": (
                "copy-sufficient-decision/1" if provision["kind"] == "decision_rule"
                else "copy-replacement-exception/1"
            ),
            "source_units": source_units,
            "candidate_quote_hashes": quote_hashes,
        })
    return mappings


def _evaluate(expression, assignment):
    if "const" in expression:
        return expression["const"]
    if "var" in expression:
        return assignment[expression["var"]]
    values = [_evaluate(argument, assignment) for argument in expression["args"]]
    operation = expression["op"]
    if operation == "not":
        return not values[0]
    if operation == "and":
        return all(values)
    if operation == "or":
        return any(values)
    left, right = values
    if operation == "eq":
        return left == right
    if operation == "ne":
        return left != right
    if operation == "lt":
        return left < right
    if operation == "le":
        return left <= right
    if operation == "gt":
        return left > right
    if operation == "ge":
        return left >= right
    raise KernelError("UNSUPPORTED", "unknown Core expression operator")


def _effective_rules(core, assignment):
    enabled = {rule["id"]: _evaluate(rule["when"], assignment) for rule in core["rules"]}
    blockers = {rule["id"]: [] for rule in core["rules"]}
    by_id = {rule["id"]: rule for rule in core["rules"]}
    for rule in core["rules"]:
        for target in rule["overrides"]:
            blockers[target].append(rule["id"])
    waiting = {rule_id: len(ids) for rule_id, ids in blockers.items()}
    ready = [rule_id for rule_id, count in waiting.items() if count == 0]
    effective = {}
    while ready:
        rule_id = ready.pop()
        effective[rule_id] = enabled[rule_id] and not any(
            effective[blocker] for blocker in blockers[rule_id]
        )
        for target in by_id[rule_id]["overrides"]:
            waiting[target] -= 1
            if waiting[target] == 0:
                ready.append(target)
    if len(effective) != len(core["rules"]):
        raise KernelError("UNSUPPORTED", "override cycle in reconstructed Core")
    return [by_id[rule_id] for rule_id in sorted(effective) if effective[rule_id]]


def _outcome(core, assignment, output_name):
    values = {}
    for rule in _effective_rules(core, assignment):
        if rule["then"]["output"] == output_name:
            value = rule["then"]["value"]
            values[canonical_json(value)] = value
    ordered = [values[key] for key in sorted(values)]
    if not ordered:
        return {"state": "absent"}
    if len(ordered) == 1:
        return {"state": "defined", "value": ordered[0]}
    return {"state": "conflict", "values": ordered}


def _verify_semantic_tests(core, review):
    for test in review["semantic_tests"]:
        assignment = test["input"]
        admitted = all(
            assignment[fact["var"]] == fact["value"] for fact in core["facts"]
        ) and all(_evaluate(constraint, assignment) for constraint in core["constraints"])
        if not admitted:
            raise KernelError("INTERPRETATION_INVALID",
                              f"semantic test {test['id']} is outside facts/constraints")
        actual = {name: _outcome(core, assignment, name) for name in test["expected"]}
        if canonical_json(actual) != canonical_json(test["expected"]):
            raise KernelError(
                "SEMANTIC_MISMATCH",
                f"host semantic test {test['id']} failed: expected "
                f"{canonical_json(test['expected'])}, got {canonical_json(actual)}",
            )


def _expected_package(task, candidate, review, scope_expectations,
                      candidate_index, units_by_id, core):
    coverage_counts = {"selected": 0, "unresolved": 0, "excluded": 0}
    for entry in review["coverage_decisions"]:
        coverage_counts[entry["disposition"]] += 1
    return {
        "format": INTERPRETED_PACKAGE_FORMAT,
        "origin_kind": "interpreted_source",
        "conversion_profile": CONVERSION_PROFILE,
        "conversion_definition_sha256": LOWERING_DEFINITION_SHA256,
        "producer_version": _PRODUCER_VERSION,
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
        "provenance_map": _reconstruct_provenance(candidate_index, review, units_by_id),
        "review_summary": {
            "review_id": review["review_id"],
            "state": review["state"],
            "selected_provision_ids": sorted(review["selected_provision_ids"]),
            "accepted_assumption_ids": sorted(review["accepted_assumption_ids"]),
            "semantic_test_ids": sorted(test["id"] for test in review["semantic_tests"]),
            "coverage_counts": coverage_counts,
            "semantic_correspondence": "HOST_REVIEW_RECORDED",
        },
        "scope_expectations": scope_expectations,
    }


def verify_interpretation_package(
        task_or_path, candidate_or_path, review_or_path, scope_expectations_or_path,
        source_spec_or_path, source_bundle, package_or_path,
        *, expected_source_bundle_sha256, expected_review_sha256,
        expected_scope_expectations_sha256, expected_package_sha256=None):
    """Reconstruct all lowering output without importing the producer."""
    _require_anchor(expected_source_bundle_sha256, "expected_source_bundle_sha256")
    _require_anchor(expected_review_sha256, "expected_review_sha256")
    _require_anchor(expected_scope_expectations_sha256,
                    "expected_scope_expectations_sha256")
    _require_anchor(expected_package_sha256, "expected_package_sha256", optional=True)
    task = _load(task_or_path)
    candidate = _load(candidate_or_path)
    review = _load(review_or_path)
    scope_expectations = _load(scope_expectations_or_path)
    package = _load(package_or_path)
    if interpretation_digest(review) != expected_review_sha256:
        raise KernelError("INTERPRETATION_MISMATCH",
                          "host review differs from the external review hash")
    if interpretation_digest(scope_expectations) != expected_scope_expectations_sha256:
        raise KernelError("INTERPRETATION_MISMATCH",
                          "scope expectations differ from the external expectations hash")
    actual_package_hash = interpretation_digest(package)
    if expected_package_sha256 is not None and actual_package_hash != expected_package_sha256:
        raise KernelError("INTERPRETATION_MISMATCH",
                          "compiled package differs from the external package hash")
    if len(canonical_json(package).encode("utf-8")) > MAX_INTERPRETATION_BYTES:
        raise KernelError("LIMIT_REACHED", "compiled package exceeds the interpretation byte limit")

    source_result = verify_source_package(
        source_spec_or_path, source_bundle,
        expected_bundle_sha256=expected_source_bundle_sha256,
    )
    source_manifest = _source_manifest(source_bundle)
    units_by_id = bind_task_to_source(task, source_result, source_manifest)
    candidate_index = validate_candidate(task, candidate, units_by_id, source_manifest)
    validate_review(task, candidate, review, candidate_index)
    ensure_review_allows_compilation(review, candidate_index)
    core = _reconstruct_core(task, candidate_index, review, units_by_id)
    core_hash = interpretation_digest(core)
    validate_scope_expectations(
        task, candidate, review, candidate_index, scope_expectations,
        core_model_hash=core_hash,
    )
    _verify_semantic_tests(core, review)
    expected = _expected_package(
        task, candidate, review, scope_expectations, candidate_index, units_by_id, core,
    )
    if canonical_json(package) != canonical_json(expected):
        raise KernelError("INTERPRETATION_PACKAGE_INVALID",
                          "compiled package differs from independent reconstruction")
    counts = expected["review_summary"]["coverage_counts"]
    return {
        "status": "LOWERING_VERIFIED",
        "checker_version": CHECKER_VERSION,
        "package_hash": actual_package_hash,
        "package_hash_anchored": expected_package_sha256 is not None,
        "source_bundle_hash_anchored": True,
        "review_hash_anchored": True,
        "scope_expectations_hash_anchored": True,
        "core_model_hash": core_hash,
        "selected_rule_count": len(core["rules"]),
        "semantic_test_count": len(review["semantic_tests"]),
        "coverage_counts": counts,
        "semantic_correspondence": "HOST_REVIEW_RECORDED",
        "review_method": review["review_method"],
        "provisional": review["review_method"] == "manual_fixture_review",
        "offline": True,
    }
