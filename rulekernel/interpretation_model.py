"""Strict host/candidate boundary for the first interpretation IR profile."""
from __future__ import annotations

from datetime import datetime
import re

from .model import KernelError, canonical_json, digest, load_json, validate_model
from .source_model import SOURCE_PACKAGE_FORMAT, SOURCE_UNIT_MANIFEST_FORMAT


TASK_FORMAT = "rule-interpretation-task/1"
CANDIDATE_FORMAT = "rule-interpretation-candidate/1"
REVIEW_FORMAT = "rule-interpretation-review/1"
SCOPE_EXPECTATIONS_FORMAT = "rule-scope-expectations/1"
INTERPRETED_PACKAGE_FORMAT = "rule-interpreted-core-package/1"
CONVERSION_PROFILE = "candidate-to-finite-decisions/1"
MAX_INTERPRETATION_BYTES = 4 * 1024 * 1024
MAX_PROVISIONS = 128
MAX_SOURCE_UNITS = 4096
MAX_REFERENCES = 4096
MAX_ASSUMPTIONS = 256
MAX_ISSUES = 512
MAX_TESTS = 512

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

LOWERING_DEFINITION = {
    "profile": CONVERSION_PROFILE,
    "selected_scope": "copy task.core_scope exactly",
    "selected_provisions": "sort host-selected provision IDs",
    "core_rule_id": "prefix candidate provision ID with IR_",
    "decision_rule": "copy sufficient Boolean trigger and constant conclusion",
    "exception": "copy explicit replacement conclusion and rewrite selected override IDs",
    "source": "join complete verified source-unit text in manifest order",
    "unsupported": (
        "necessary-only conditions, obligations, prohibitions, permissions, deadlines, "
        "bare exclusions, and unresolved selected dependencies do not lower"
    ),
}
LOWERING_DEFINITION_SHA256 = digest(LOWERING_DEFINITION)


def _error(status: str, message: str) -> None:
    raise KernelError(status, message)


def _invalid(message: str) -> None:
    _error("INTERPRETATION_INVALID", message)


def _unsupported(message: str) -> None:
    _error("UNSUPPORTED", message)


def _mismatch(message: str) -> None:
    _error("INTERPRETATION_MISMATCH", message)


def _shape(value, fields, path: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _invalid(f"{path}: expected object with string keys")
    missing = set(fields) - value.keys()
    extra = value.keys() - set(fields)
    if missing:
        _invalid(f"{path}: missing fields {sorted(missing)}")
    if extra:
        _unsupported(f"{path}: unknown fields {sorted(extra)}")


def _text(value, path: str, maximum: int = 8192) -> None:
    if type(value) is not str or not value or len(value) > maximum:
        _invalid(f"{path}: expected nonempty string of at most {maximum} codepoints")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _invalid(f"{path}: invalid Unicode")


def _identifier(value, path: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _invalid(f"{path}: invalid identifier")


def _sha(value, path: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _invalid(f"{path}: expected lowercase SHA-256")


def _timestamp(value, path: str) -> None:
    if type(value) is not str:
        _invalid(f"{path}: expected UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        _invalid(f"{path}: expected YYYY-MM-DDTHH:MM:SSZ ({exc})")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _invalid(f"{path}: timestamp is not canonical")


def _array(value, path: str, maximum: int, *, minimum: int = 0) -> None:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _invalid(f"{path}: expected array with {minimum}..{maximum} entries")


def _unique_ids(value, path: str, maximum: int, *, minimum: int = 0) -> list[str]:
    _array(value, path, maximum, minimum=minimum)
    for index, item in enumerate(value):
        _identifier(item, f"{path}[{index}]")
    if len(value) != len(set(value)):
        _invalid(f"{path}: duplicate identifiers")
    return value


def _unique_hashes(value, path: str, maximum: int, *, minimum: int = 0) -> list[str]:
    _array(value, path, maximum, minimum=minimum)
    for index, item in enumerate(value):
        _sha(item, f"{path}[{index}]")
    if len(value) != len(set(value)):
        _invalid(f"{path}: duplicate hashes")
    return value


def _member(value, domain, path: str) -> None:
    kind = domain["kind"]
    if kind == "bool":
        valid = type(value) is bool
    elif kind == "int":
        valid = type(value) is int and domain["min"] <= value <= domain["max"]
    else:
        valid = type(value) is str and value in domain["values"]
    if not valid:
        _invalid(f"{path}: value outside the task scope")


def interpretation_digest(value) -> str:
    return digest(value)


def interpretation_snapshot_digest(task, candidate, review) -> str:
    return digest({
        "format": "rule-interpretation-snapshot/1",
        "task": task,
        "candidate": candidate,
        "review": review,
    })


def load_interpretation_json(path):
    try:
        return load_json(path, max_bytes=MAX_INTERPRETATION_BYTES)
    except KernelError as exc:
        if exc.status == "MODEL_INVALID":
            raise KernelError("INTERPRETATION_INVALID", exc.message) from exc
        raise


def core_rule_id(provision_id: str) -> str:
    return "IR_" + provision_id


def _scope_model(scope, rules=None):
    return {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": scope["title"],
        "inputs": scope["inputs"],
        "outputs": scope["outputs"],
        "constraints": scope["constraints"],
        "facts": scope["facts"],
        "rules": [] if rules is None else rules,
    }


def validate_task(task) -> None:
    _shape(task, {"format", "task_id", "source", "allowed_source_unit_ids",
                  "core_scope", "allowed_provision_kinds", "conversion_profile"}, "task")
    if task["format"] != TASK_FORMAT:
        _unsupported("task.format: unsupported interpretation task")
    _identifier(task["task_id"], "task.task_id")
    source = task["source"]
    _shape(source, {"source_package_format", "source_spec_sha256", "source_bundle_sha256",
                    "raw_sha256", "source_unit_manifest_sha256", "document_id",
                    "revision_id"}, "task.source")
    if source["source_package_format"] != SOURCE_PACKAGE_FORMAT:
        _unsupported("task.source.source_package_format is unsupported")
    for field in ("source_spec_sha256", "source_bundle_sha256", "raw_sha256",
                  "source_unit_manifest_sha256"):
        _sha(source[field], f"task.source.{field}")
    _text(source["document_id"], "task.source.document_id", 128)
    _text(source["revision_id"], "task.source.revision_id", 256)
    _unique_hashes(task["allowed_source_unit_ids"], "task.allowed_source_unit_ids",
                   MAX_SOURCE_UNITS, minimum=1)
    scope = task["core_scope"]
    _shape(scope, {"title", "inputs", "outputs", "constraints", "facts"},
           "task.core_scope")
    try:
        validate_model(_scope_model(scope))
    except KernelError as exc:
        if exc.status == "MODEL_INVALID":
            raise KernelError("INTERPRETATION_INVALID", f"task.core_scope: {exc.message}") from exc
        raise
    kinds = task["allowed_provision_kinds"]
    _array(kinds, "task.allowed_provision_kinds", 4, minimum=1)
    permitted = {"decision_rule", "exception", "unresolved"}
    if any(type(kind) is not str or kind not in permitted for kind in kinds):
        _unsupported("task.allowed_provision_kinds contains an unsupported kind")
    if len(kinds) != len(set(kinds)):
        _invalid("task.allowed_provision_kinds contains duplicates")
    if task["conversion_profile"] != CONVERSION_PROFILE:
        _unsupported("task.conversion_profile is unsupported")
    if len(canonical_json(task).encode("utf-8")) > MAX_INTERPRETATION_BYTES:
        _error("LIMIT_REACHED", "task exceeds the interpretation byte limit")


def bind_task_to_source(task, source_result, source_manifest) -> dict:
    validate_task(task)
    expected = {
        "source_package_format": source_result["source_package_format"],
        "source_spec_sha256": source_result["source_spec_hash"],
        "source_bundle_sha256": source_result["bundle_hash"],
        "raw_sha256": source_result["raw_sha256"],
        "source_unit_manifest_sha256": source_result["source_unit_manifest_sha256"],
        "document_id": source_result["document_id"],
        "revision_id": source_result["revision_id"],
    }
    if task["source"] != expected:
        _mismatch("task source binding differs from the independently verified source package")
    if type(source_manifest) is not dict or source_manifest.get("format") != SOURCE_UNIT_MANIFEST_FORMAT:
        _invalid("source unit manifest has an unsupported format")
    units = source_manifest.get("units")
    references = source_manifest.get("references")
    if type(units) is not list or type(references) is not list:
        _invalid("source unit manifest lacks units or references")
    by_unit = {}
    for unit in units:
        if type(unit) is not dict or type(unit.get("source_unit_id")) is not str:
            _invalid("source unit manifest contains an invalid unit")
        by_unit[unit["source_unit_id"]] = unit
    if len(by_unit) != len(units):
        _invalid("source unit manifest contains duplicate source_unit_id")
    if set(task["allowed_source_unit_ids"]) != set(by_unit):
        _mismatch("task must account for every unit in the fixed source manifest")
    return by_unit


def _validate_expected_outputs(expected, outputs, path: str) -> None:
    if type(expected) is not dict or not expected:
        _invalid(f"{path}: expected at least one output expectation")
    if any(name not in outputs for name in expected):
        _invalid(f"{path}: undeclared output")
    for name, outcome in expected.items():
        outcome_path = f"{path}.{name}"
        if type(outcome) is not dict or "state" not in outcome:
            _invalid(f"{outcome_path}: malformed outcome")
        state = outcome["state"]
        if state == "absent":
            _shape(outcome, {"state"}, outcome_path)
        elif state == "defined":
            _shape(outcome, {"state", "value"}, outcome_path)
            _member(outcome["value"], outputs[name]["type"], outcome_path + ".value")
        elif state == "conflict":
            _shape(outcome, {"state", "values"}, outcome_path)
            values = outcome["values"]
            _array(values, outcome_path + ".values", 256, minimum=2)
            for index, value in enumerate(values):
                _member(value, outputs[name]["type"], f"{outcome_path}.values[{index}]")
            rendered = [canonical_json(value) for value in values]
            if rendered != sorted(set(rendered)):
                _invalid(f"{outcome_path}.values must be unique and canonically sorted")
        else:
            _unsupported(f"{outcome_path}: unsupported outcome state {state!r}")


def _validate_tests(tests, scope, path: str, *, minimum: int = 0) -> None:
    _array(tests, path, MAX_TESTS, minimum=minimum)
    ids = set()
    for index, test in enumerate(tests):
        test_path = f"{path}[{index}]"
        _shape(test, {"id", "input", "expected"}, test_path)
        _identifier(test["id"], test_path + ".id")
        if test["id"] in ids:
            _invalid(f"{test_path}: duplicate test ID")
        ids.add(test["id"])
        assignment = test["input"]
        if type(assignment) is not dict or set(assignment) != set(scope["inputs"]):
            _invalid(f"{test_path}.input must assign every task input exactly once")
        for name, value in assignment.items():
            _member(value, scope["inputs"][name], f"{test_path}.input.{name}")
        _validate_expected_outputs(test["expected"], scope["outputs"],
                                   test_path + ".expected")


def validate_candidate(task, candidate, units_by_id, source_manifest) -> dict:
    _shape(candidate, {"format", "task_id", "task_hash", "source_unit_manifest_sha256",
                       "provisions", "references", "proposed_assumptions",
                       "unresolved_issues", "coverage", "proposed_tests"}, "candidate")
    if candidate["format"] != CANDIDATE_FORMAT:
        _unsupported("candidate.format is unsupported")
    if candidate["task_id"] != task["task_id"] or candidate["task_hash"] != digest(task):
        _mismatch("candidate is not bound to this task")
    if candidate["source_unit_manifest_sha256"] != task["source"]["source_unit_manifest_sha256"]:
        _mismatch("candidate is bound to another source unit manifest")

    provisions = candidate["provisions"]
    _array(provisions, "candidate.provisions", MAX_PROVISIONS, minimum=1)
    by_provision = {}
    allowed_units = set(task["allowed_source_unit_ids"])
    for index, provision in enumerate(provisions):
        path = f"candidate.provisions[{index}]"
        _shape(provision, {"id", "kind", "condition_role", "source_unit_ids", "source_quotes", "when",
                           "then", "overrides", "reference_ids", "assumption_ids",
                           "issue_ids"}, path)
        provision_id = provision["id"]
        _identifier(provision_id, path + ".id")
        if provision_id in by_provision:
            _invalid(f"{path}: duplicate provision ID")
        by_provision[provision_id] = provision
        kind = provision["kind"]
        if type(kind) is not str or kind not in task["allowed_provision_kinds"]:
            _unsupported(f"{path}.kind is outside the task contract")
        condition_role = provision["condition_role"]
        if (type(condition_role) is not str or
                condition_role not in {"sufficient_trigger", "necessary_only", "not_applicable"}):
            _unsupported(f"{path}.condition_role is unsupported")
        unit_ids = _unique_hashes(provision["source_unit_ids"], path + ".source_unit_ids",
                                  MAX_SOURCE_UNITS, minimum=1)
        if not set(unit_ids) <= allowed_units:
            _invalid(f"{path}: source unit is outside the fixed manifest")
        quotes = provision["source_quotes"]
        _array(quotes, path + ".source_quotes", len(unit_ids), minimum=len(unit_ids))
        quote_units = set()
        for quote_index, quote in enumerate(quotes):
            quote_path = f"{path}.source_quotes[{quote_index}]"
            _shape(quote, {"source_unit_id", "exact"}, quote_path)
            unit_id = quote["source_unit_id"]
            _sha(unit_id, quote_path + ".source_unit_id")
            _text(quote["exact"], quote_path + ".exact", 262_144)
            if unit_id in quote_units or unit_id not in unit_ids:
                _invalid(f"{quote_path}: duplicate or undeclared quote unit")
            quote_units.add(unit_id)
            unit_text = units_by_id[unit_id]["exact"]
            if unit_text.count(quote["exact"]) != 1:
                _mismatch(f"{quote_path}: quote must occur exactly once in its source unit")
        if quote_units != set(unit_ids):
            _invalid(f"{path}: every source unit requires one exact quote")
        _unique_ids(provision["overrides"], path + ".overrides", MAX_PROVISIONS)
        _unique_ids(provision["reference_ids"], path + ".reference_ids", MAX_REFERENCES)
        _unique_ids(provision["assumption_ids"], path + ".assumption_ids", MAX_ASSUMPTIONS)
        _unique_ids(provision["issue_ids"], path + ".issue_ids", MAX_ISSUES)
        if kind == "unresolved":
            if provision["when"] is not None or provision["then"] is not None:
                _invalid(f"{path}: unresolved provision cannot contain executable semantics")
            if provision["overrides"] or not provision["issue_ids"]:
                _invalid(f"{path}: unresolved provision requires an issue and no override")
        else:
            if provision["when"] is None or provision["then"] is None:
                _invalid(f"{path}: executable provision requires when and then")
            if kind == "decision_rule" and provision["overrides"]:
                _invalid(f"{path}: only an exception may override another provision")
            if kind == "exception" and not provision["overrides"]:
                _invalid(f"{path}: exception requires an explicit override target")
            source_text = " / ".join(quote["exact"] for quote in quotes)
            probe = {
                "id": core_rule_id(provision_id), "source": source_text,
                "when": provision["when"], "then": provision["then"], "overrides": [],
            }
            try:
                validate_model(_scope_model(task["core_scope"], [probe]))
            except KernelError as exc:
                if exc.status == "MODEL_INVALID":
                    raise KernelError("INTERPRETATION_INVALID", f"{path}: {exc.message}") from exc
                raise

    for provision_id, provision in by_provision.items():
        for target in provision["overrides"]:
            if target not in by_provision or by_provision[target]["kind"] == "unresolved":
                _invalid(f"candidate.provisions.{provision_id}: unknown executable override target")
            if target == provision_id:
                _invalid(f"candidate.provisions.{provision_id}: self override")

    assumptions = candidate["proposed_assumptions"]
    _array(assumptions, "candidate.proposed_assumptions", MAX_ASSUMPTIONS)
    by_assumption = {}
    for index, assumption in enumerate(assumptions):
        path = f"candidate.proposed_assumptions[{index}]"
        _shape(assumption, {"id", "text"}, path)
        _identifier(assumption["id"], path + ".id")
        _text(assumption["text"], path + ".text")
        if assumption["id"] in by_assumption:
            _invalid(f"{path}: duplicate assumption ID")
        by_assumption[assumption["id"]] = assumption

    issues = candidate["unresolved_issues"]
    _array(issues, "candidate.unresolved_issues", MAX_ISSUES)
    by_issue = {}
    issue_kinds = {"unresolved_reference", "ambiguous_meaning", "unsupported_construct"}
    for index, issue in enumerate(issues):
        path = f"candidate.unresolved_issues[{index}]"
        _shape(issue, {"id", "kind", "source_unit_ids", "description"}, path)
        _identifier(issue["id"], path + ".id")
        if type(issue["kind"]) is not str or issue["kind"] not in issue_kinds:
            _unsupported(f"{path}.kind is unsupported")
        source_ids = _unique_hashes(issue["source_unit_ids"], path + ".source_unit_ids",
                                    MAX_SOURCE_UNITS, minimum=1)
        if not set(source_ids) <= allowed_units:
            _invalid(f"{path}: source unit is outside the task")
        _text(issue["description"], path + ".description")
        if issue["id"] in by_issue:
            _invalid(f"{path}: duplicate issue ID")
        by_issue[issue["id"]] = issue

    references = candidate["references"]
    _array(references, "candidate.references", MAX_REFERENCES)
    manifest_refs = {
        item["reference_id"]: item for item in source_manifest["references"]
        if item["from_source_unit_id"] in allowed_units
    }
    by_reference = {}
    for index, reference in enumerate(references):
        path = f"candidate.references[{index}]"
        _shape(reference, {"reference_id", "from_source_unit_id", "literal", "status",
                           "target_provision_id"}, path)
        reference_id = reference["reference_id"]
        _identifier(reference_id, path + ".reference_id")
        if reference_id in by_reference:
            _invalid(f"{path}: duplicate reference ID")
        by_reference[reference_id] = reference
        if reference_id not in manifest_refs:
            _invalid(f"{path}: reference is absent from the source manifest")
        expected = manifest_refs[reference_id]
        for field in ("from_source_unit_id", "literal", "status"):
            if reference[field] != expected[field]:
                _mismatch(f"{path}.{field} differs from the source manifest")
        target = reference["target_provision_id"]
        if expected["status"] == "unresolved":
            if target is not None:
                _invalid(f"{path}: unresolved source reference cannot have a target provision")
        elif expected["status"] == "resolved":
            if type(target) is not str or target not in by_provision:
                _invalid(f"{path}: resolved reference requires a known target provision")
            if expected["target_source_unit_id"] not in by_provision[target]["source_unit_ids"]:
                _mismatch(f"{path}: target provision is not derived from the referenced source unit")
        else:
            _unsupported(f"{path}: unsupported reference status")
    if set(by_reference) != set(manifest_refs):
        _error("REFERENCE_MISSING", "candidate must preserve every source-manifest reference")

    for provision_id, provision in by_provision.items():
        if not set(provision["reference_ids"]) <= set(by_reference):
            _invalid(f"candidate.provisions.{provision_id}: unknown reference")
        if not set(provision["assumption_ids"]) <= set(by_assumption):
            _invalid(f"candidate.provisions.{provision_id}: unknown assumption")
        if not set(provision["issue_ids"]) <= set(by_issue):
            _invalid(f"candidate.provisions.{provision_id}: unknown issue")
    for reference_id, reference in by_reference.items():
        if not any(reference_id in provision["reference_ids"] and
                   reference["from_source_unit_id"] in provision["source_unit_ids"]
                   for provision in provisions):
            _error("REFERENCE_MISSING", f"source reference {reference_id} is not attached to a provision")

    coverage = candidate["coverage"]
    _array(coverage, "candidate.coverage", MAX_SOURCE_UNITS, minimum=1)
    coverage_by_unit = {}
    for index, entry in enumerate(coverage):
        path = f"candidate.coverage[{index}]"
        _shape(entry, {"source_unit_id", "provision_ids", "issue_ids"}, path)
        unit_id = entry["source_unit_id"]
        _sha(unit_id, path + ".source_unit_id")
        if unit_id not in allowed_units or unit_id in coverage_by_unit:
            _invalid(f"{path}: duplicate or unknown source unit")
        _unique_ids(entry["provision_ids"], path + ".provision_ids", MAX_PROVISIONS)
        _unique_ids(entry["issue_ids"], path + ".issue_ids", MAX_ISSUES)
        expected_provisions = {pid for pid, item in by_provision.items()
                               if unit_id in item["source_unit_ids"]}
        expected_issues = {iid for iid, item in by_issue.items()
                           if unit_id in item["source_unit_ids"]}
        if set(entry["provision_ids"]) != expected_provisions or set(entry["issue_ids"]) != expected_issues:
            _invalid(f"{path}: coverage must list every candidate provision and issue for the unit")
        coverage_by_unit[unit_id] = entry
    if set(coverage_by_unit) != allowed_units:
        _invalid("candidate.coverage must account for every source unit")

    _validate_tests(candidate["proposed_tests"], task["core_scope"],
                    "candidate.proposed_tests")
    if len(canonical_json(candidate).encode("utf-8")) > MAX_INTERPRETATION_BYTES:
        _error("LIMIT_REACHED", "candidate exceeds the interpretation byte limit")
    return {
        "provisions": by_provision,
        "references": by_reference,
        "assumptions": by_assumption,
        "issues": by_issue,
        "coverage": coverage_by_unit,
    }


def validate_review(task, candidate, review, candidate_index) -> dict:
    _shape(review, {"format", "review_id", "reviewer_id", "review_method", "task_hash",
                    "candidate_hash", "state", "reviewed_at", "selected_provision_ids",
                    "accepted_assumption_ids",
                    "coverage_decisions", "semantic_tests", "findings"}, "review")
    if review["format"] != REVIEW_FORMAT:
        _unsupported("review.format is unsupported")
    _identifier(review["review_id"], "review.review_id")
    _identifier(review["reviewer_id"], "review.reviewer_id")
    if (type(review["review_method"]) is not str or
            review["review_method"] not in {"manual_fixture_review", "human_review"}):
        _unsupported("review.review_method is unsupported")
    if review["task_hash"] != digest(task) or review["candidate_hash"] != digest(candidate):
        _mismatch("review is stale or belongs to another task/candidate")
    if (type(review["state"]) is not str or
            review["state"] not in {"approved", "pending", "rejected"}):
        _unsupported("review.state is unsupported")
    _timestamp(review["reviewed_at"], "review.reviewed_at")
    selected = _unique_ids(review["selected_provision_ids"],
                           "review.selected_provision_ids", MAX_PROVISIONS)
    accepted = _unique_ids(review["accepted_assumption_ids"],
                           "review.accepted_assumption_ids", MAX_ASSUMPTIONS)
    if not set(selected) <= set(candidate_index["provisions"]):
        _invalid("review selects an unknown provision")
    if not set(accepted) <= set(candidate_index["assumptions"]):
        _invalid("review accepts an unknown assumption")

    findings = review["findings"]
    _array(findings, "review.findings", 256)
    for index, finding in enumerate(findings):
        path = f"review.findings[{index}]"
        _shape(finding, {"code", "provision_ids", "description"}, path)
        _identifier(finding["code"], path + ".code")
        ids = _unique_ids(finding["provision_ids"], path + ".provision_ids", MAX_PROVISIONS)
        if not set(ids) <= set(candidate_index["provisions"]):
            _invalid(f"{path}: unknown provision")
        _text(finding["description"], path + ".description")
    if review["state"] == "approved" and findings:
        _invalid("approved review cannot retain rejection findings")
    if review["state"] == "approved" and not selected:
        _invalid("approved review must select at least one provision")
    if review["state"] == "rejected" and not findings:
        _invalid("rejected review requires at least one finding")

    decisions = review["coverage_decisions"]
    _array(decisions, "review.coverage_decisions", MAX_SOURCE_UNITS, minimum=1)
    allowed_units = set(task["allowed_source_unit_ids"])
    by_unit = {}
    for index, decision in enumerate(decisions):
        path = f"review.coverage_decisions[{index}]"
        _shape(decision, {"source_unit_id", "disposition", "provision_ids", "issue_ids",
                          "rationale"}, path)
        unit_id = decision["source_unit_id"]
        _sha(unit_id, path + ".source_unit_id")
        if unit_id not in allowed_units or unit_id in by_unit:
            _invalid(f"{path}: duplicate or unknown source unit")
        disposition = decision["disposition"]
        if (type(disposition) is not str or
                disposition not in {"selected", "unresolved", "excluded"}):
            _unsupported(f"{path}.disposition is unsupported")
        provision_ids = _unique_ids(decision["provision_ids"], path + ".provision_ids",
                                    MAX_PROVISIONS)
        issue_ids = _unique_ids(decision["issue_ids"], path + ".issue_ids", MAX_ISSUES)
        _text(decision["rationale"], path + ".rationale")
        if not set(provision_ids) <= set(selected):
            _invalid(f"{path}: coverage may only list selected provisions")
        if not set(issue_ids) <= set(candidate_index["issues"]):
            _invalid(f"{path}: unknown issue")
        expected_selected = {pid for pid in selected
                             if unit_id in candidate_index["provisions"][pid]["source_unit_ids"]}
        if disposition == "selected":
            if set(provision_ids) != expected_selected or not provision_ids or issue_ids:
                _invalid(f"{path}: selected coverage does not match selected provisions")
        elif disposition == "unresolved":
            if provision_ids or not issue_ids or expected_selected:
                _invalid(f"{path}: unresolved coverage requires issues and no selected provision")
        elif provision_ids or issue_ids or expected_selected:
            _invalid(f"{path}: excluded coverage cannot hide a selected provision or issue")
        by_unit[unit_id] = decision
    if set(by_unit) != allowed_units:
        _invalid("review.coverage_decisions must account for every source unit")

    minimum_tests = 1 if review["state"] == "approved" else 0
    _validate_tests(review["semantic_tests"], task["core_scope"],
                    "review.semantic_tests", minimum=minimum_tests)
    if len(canonical_json(review).encode("utf-8")) > MAX_INTERPRETATION_BYTES:
        _error("LIMIT_REACHED", "review exceeds the interpretation byte limit")
    return {"coverage": by_unit}


def ensure_review_allows_compilation(review, candidate_index) -> None:
    if review["state"] == "pending":
        _error("REVIEW_REQUIRED", "candidate has not been approved by the host review")
    if review["state"] == "rejected":
        codes = ",".join(finding["code"] for finding in review["findings"])
        _error("REVIEW_REJECTED", f"host review rejected the candidate: {codes}")
    selected = set(review["selected_provision_ids"])
    accepted = set(review["accepted_assumption_ids"])
    selected_units = {
        decision["source_unit_id"] for decision in review["coverage_decisions"]
        if decision["disposition"] == "selected"
    }
    # v0.1 does not provide a reviewed sub-unit partition.  Selecting any
    # interpretation from a source unit therefore inherits every unresolved
    # issue and source-manifest reference originating in that whole unit.  A
    # candidate cannot park one on an unselected dummy provision.
    for issue_id, issue in candidate_index["issues"].items():
        if selected_units.intersection(issue["source_unit_ids"]):
            _error("MODEL_INCOMPLETE",
                   f"selected source unit retains unresolved issue {issue_id}")
    for reference_id, reference in candidate_index["references"].items():
        if reference["from_source_unit_id"] not in selected_units:
            continue
        if reference["status"] == "unresolved":
            _error("MODEL_INCOMPLETE",
                   f"selected source unit retains unresolved reference {reference_id}")
        if reference["target_provision_id"] not in selected:
            _error("MODEL_INCOMPLETE",
                   f"selected source reference {reference_id} has an unselected target")
        attached_to_selected = any(
            provision_id in selected and
            reference["from_source_unit_id"] in provision["source_unit_ids"] and
            reference_id in provision["reference_ids"]
            for provision_id, provision in candidate_index["provisions"].items()
        )
        if not attached_to_selected:
            _error("MODEL_INCOMPLETE",
                   f"selected source reference {reference_id} is parked outside selected provisions")
    for provision_id in selected:
        provision = candidate_index["provisions"][provision_id]
        if provision["kind"] == "unresolved":
            _error("MODEL_INCOMPLETE", f"selected provision {provision_id} is unresolved")
        if provision["condition_role"] != "sufficient_trigger":
            _error("MODEL_INCOMPLETE",
                   f"selected provision {provision_id} is not a sufficient trigger")
        missing_assumptions = set(provision["assumption_ids"]) - accepted
        if missing_assumptions:
            _error("MODEL_INCOMPLETE", f"selected provision {provision_id} uses an unaccepted assumption")
        if provision["issue_ids"]:
            _error("MODEL_INCOMPLETE", f"selected provision {provision_id} depends on an unresolved issue")
        if not set(provision["overrides"]) <= selected:
            _error("MODEL_INCOMPLETE", f"selected exception {provision_id} has an unselected target")
        if provision["kind"] == "exception":
            for target in provision["overrides"]:
                if (candidate_index["provisions"][target]["then"]["output"] !=
                        provision["then"]["output"]):
                    _error("MODEL_INCOMPLETE",
                           f"selected exception {provision_id} is not a replacement on the target output")
        for reference_id in provision["reference_ids"]:
            reference = candidate_index["references"][reference_id]
            if reference["status"] == "unresolved":
                _error("MODEL_INCOMPLETE", f"selected provision {provision_id} uses unresolved reference {reference_id}")
            if reference["target_provision_id"] not in selected:
                _error("MODEL_INCOMPLETE", f"selected provision {provision_id} has an unselected reference target")


def validate_scope_expectations(task, candidate, review, candidate_index, expectations,
                                *, core_model_hash=None) -> dict:
    _shape(expectations, {"format", "expectation_id", "task_hash",
                          "candidate_hash", "review_hash", "source_unit_manifest_sha256",
                          "interpretation_snapshot_sha256", "scope_hash", "core_model_hash",
                          "rules"},
           "scope_expectations")
    if expectations["format"] != SCOPE_EXPECTATIONS_FORMAT:
        _unsupported("scope_expectations.format is unsupported")
    _identifier(expectations["expectation_id"], "scope_expectations.expectation_id")
    if expectations["task_hash"] != digest(task):
        _mismatch("scope expectations belong to another task")
    if expectations["candidate_hash"] != digest(candidate):
        _mismatch("scope expectations belong to another candidate")
    if expectations["review_hash"] != digest(review):
        _mismatch("scope expectations belong to another host review")
    if expectations["interpretation_snapshot_sha256"] != interpretation_snapshot_digest(
            task, candidate, review):
        _mismatch("scope expectations belong to another interpretation snapshot")
    if expectations["source_unit_manifest_sha256"] != task["source"]["source_unit_manifest_sha256"]:
        _mismatch("scope expectations belong to another source manifest")
    if expectations["scope_hash"] != digest(task["core_scope"]):
        _mismatch("scope expectations belong to another finite scope")
    _sha(expectations["core_model_hash"], "scope_expectations.core_model_hash")
    if core_model_hash is not None and expectations["core_model_hash"] != core_model_hash:
        _mismatch("scope expectations belong to another Core model")
    rules = expectations["rules"]
    _array(rules, "scope_expectations.rules", MAX_PROVISIONS, minimum=1)
    by_rule = {}
    selected = set(review["selected_provision_ids"])
    expected_rule_ids = {core_rule_id(provision_id) for provision_id in selected}
    for index, rule in enumerate(rules):
        path = f"scope_expectations.rules[{index}]"
        _shape(rule, {"core_rule_id", "expectation", "source_unit_ids", "rationale"}, path)
        _identifier(rule["core_rule_id"], path + ".core_rule_id")
        if rule["core_rule_id"] in by_rule:
            _invalid(f"{path}: duplicate core rule ID")
        if (type(rule["expectation"]) is not str or
                rule["expectation"] not in {"expected_in_scope", "expected_inactive", "unspecified"}):
            _unsupported(f"{path}.expectation is unsupported")
        unit_ids = _unique_hashes(rule["source_unit_ids"], path + ".source_unit_ids",
                                  MAX_SOURCE_UNITS, minimum=1)
        _text(rule["rationale"], path + ".rationale")
        provision_id = rule["core_rule_id"][3:] if rule["core_rule_id"].startswith("IR_") else None
        if provision_id not in selected:
            _invalid(f"{path}: core rule is not selected by the host review")
        if set(unit_ids) != set(candidate_index["provisions"][provision_id]["source_unit_ids"]):
            _mismatch(f"{path}: source units differ from the selected provision")
        by_rule[rule["core_rule_id"]] = rule
    if set(by_rule) != expected_rule_ids:
        _invalid("scope expectations must cover every selected Core rule exactly once")
    if len(canonical_json(expectations).encode("utf-8")) > MAX_INTERPRETATION_BYTES:
        _error("LIMIT_REACHED", "scope expectations exceed the interpretation byte limit")
    return by_rule
