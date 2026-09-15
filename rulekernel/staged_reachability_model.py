"""Strict consumer boundary for host-owned scope expectations."""
from __future__ import annotations

import re

from .interpretation_model import (
    MAX_INTERPRETATION_BYTES,
    SCOPE_EXPECTATIONS_FORMAT,
    load_interpretation_json,
)
from .model import KernelError, canonical_json, digest


MAX_RULES = 128
MAX_SOURCE_UNITS_PER_RULE = 4096
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _invalid(message: str) -> None:
    raise KernelError("EXPECTATIONS_INVALID", message)


def _mismatch(message: str) -> None:
    raise KernelError("EXPECTATIONS_MISMATCH", message)


def _shape(value, fields, path: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _invalid(f"{path}: expected object with string keys")
    missing = set(fields) - value.keys()
    extra = value.keys() - set(fields)
    if missing:
        _invalid(f"{path}: missing fields {sorted(missing)}")
    if extra:
        _invalid(f"{path}: unknown fields {sorted(extra)}")


def _sha(value, path: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid(f"{path}: expected lowercase SHA-256")


def _identifier(value, path: str) -> None:
    if type(value) is not str or _NAME.fullmatch(value) is None:
        _invalid(f"{path}: invalid identifier")


def _text(value, path: str, maximum: int = 8192) -> None:
    if type(value) is not str or not value or len(value) > maximum:
        _invalid(f"{path}: expected nonempty string of at most {maximum} codepoints")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _invalid(f"{path}: invalid Unicode")


def core_scope(model) -> dict:
    """Return the exact scope object hashed by rule-scope-expectations/1."""
    return {
        "title": model["title"],
        "inputs": model["inputs"],
        "outputs": model["outputs"],
        "constraints": model["constraints"],
        "facts": model["facts"],
    }


def load_staged_scope_expectations(path):
    try:
        return load_interpretation_json(path)
    except KernelError as exc:
        if exc.status == "INTERPRETATION_INVALID":
            raise KernelError("EXPECTATIONS_INVALID", exc.message) from exc
        raise


def validate_scope_expectations_for_model(
        model, expectations, expected_scope_expectations_sha256):
    """Validate a T05 expectation snapshot as an externally anchored Core input.

    This consumer validates the hash join and fixed rule denominator.  It does
    not reconstruct the T05 source/review chain; callers can run the T05
    package checker separately when that stronger evidence is required.
    """
    if expectations is None:
        if expected_scope_expectations_sha256 is not None:
            _invalid("an expectation hash cannot be supplied without expectations")
        return None
    if expected_scope_expectations_sha256 is None:
        _invalid("scope expectations require an external expected hash")
    _sha(expected_scope_expectations_sha256,
         "expected_scope_expectations_sha256")
    actual_hash = digest(expectations)
    if actual_hash != expected_scope_expectations_sha256:
        _mismatch("scope expectations differ from the external expected hash")

    _shape(expectations, {
        "format", "expectation_id", "task_hash", "candidate_hash", "review_hash",
        "source_unit_manifest_sha256", "interpretation_snapshot_sha256",
        "scope_hash", "core_model_hash", "rules",
    }, "scope_expectations")
    if expectations["format"] != SCOPE_EXPECTATIONS_FORMAT:
        _invalid("scope_expectations.format is not rule-scope-expectations/1")
    _identifier(expectations["expectation_id"],
                "scope_expectations.expectation_id")
    for field in (
            "task_hash", "candidate_hash", "review_hash",
            "source_unit_manifest_sha256", "interpretation_snapshot_sha256",
            "scope_hash", "core_model_hash"):
        _sha(expectations[field], f"scope_expectations.{field}")
    if expectations["core_model_hash"] != digest(model):
        _mismatch("scope expectations belong to another Core model")
    if expectations["scope_hash"] != digest(core_scope(model)):
        _mismatch("scope expectations belong to another Core scope")

    rows = expectations["rules"]
    if type(rows) is not list or len(rows) > MAX_RULES:
        _invalid(f"scope_expectations.rules: expected array with 0..{MAX_RULES} entries")
    by_rule = {}
    for index, row in enumerate(rows):
        path = f"scope_expectations.rules[{index}]"
        _shape(row, {"core_rule_id", "expectation", "source_unit_ids", "rationale"}, path)
        rule_id = row["core_rule_id"]
        _identifier(rule_id, path + ".core_rule_id")
        if rule_id in by_rule:
            _invalid(f"{path}: duplicate core rule ID")
        expectation = row["expectation"]
        if (type(expectation) is not str or expectation not in {
                "expected_in_scope", "expected_inactive", "unspecified"}):
            _invalid(f"{path}.expectation is unsupported")
        source_ids = row["source_unit_ids"]
        if (type(source_ids) is not list or
                not 1 <= len(source_ids) <= MAX_SOURCE_UNITS_PER_RULE):
            _invalid(f"{path}.source_unit_ids: expected a nonempty array")
        for source_index, source_id in enumerate(source_ids):
            _sha(source_id, f"{path}.source_unit_ids[{source_index}]")
        if len(source_ids) != len(set(source_ids)):
            _invalid(f"{path}.source_unit_ids: duplicate hashes")
        _text(row["rationale"], path + ".rationale")
        by_rule[rule_id] = row

    model_rule_ids = {rule["id"] for rule in model["rules"]}
    if set(by_rule) != model_rule_ids:
        _mismatch("scope expectations must cover every Core rule exactly once")
    if len(canonical_json(expectations).encode("utf-8")) > MAX_INTERPRETATION_BYTES:
        raise KernelError("LIMIT_REACHED", "scope expectations exceed the byte limit")
    return by_rule


def scope_expectations_binding(expectations, expected_hash):
    if expectations is None:
        return None
    return {
        "format": expectations["format"],
        "expectation_id": expectations["expectation_id"],
        "scope_expectations_sha256": expected_hash,
        "task_hash": expectations["task_hash"],
        "candidate_hash": expectations["candidate_hash"],
        "review_hash": expectations["review_hash"],
        "source_unit_manifest_sha256": expectations["source_unit_manifest_sha256"],
        "interpretation_snapshot_sha256": expectations["interpretation_snapshot_sha256"],
        "scope_hash": expectations["scope_hash"],
        "core_model_hash": expectations["core_model_hash"],
    }
