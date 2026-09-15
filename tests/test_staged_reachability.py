"""Stage, expectation, tamper, and independence tests for T03.1."""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from rulekernel import staged_reachability, staged_reachability_checker
from rulekernel.model import KernelError, canonical_json, digest, load_json
from rulekernel.staged_reachability import analyze_staged_reachability
from rulekernel.staged_reachability_checker import verify_staged_reachability
from rulekernel.staged_reachability_model import core_scope


ROOT = Path(__file__).resolve().parents[1]
MEMBER = ROOT / "examples" / "interpretations" / "member-eligibility"
MEMBER_EXPECTATIONS_HASH = (
    "51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8"
)


def const(value):
    return {"const": value}


def var(name):
    return {"var": name}


def op(name, *args):
    return {"op": name, "args": list(args)}


def rule(name, when=True, overrides=()):
    return {
        "id": name,
        "source": "段階別到達可能性の架空例 " + name,
        "when": when if type(when) is dict else const(when),
        "then": {"output": "decision", "value": True},
        "overrides": list(overrides),
    }


def model(inputs=None):
    return {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": "段階別到達可能性の架空モデル",
        "inputs": {"flag": {"kind": "bool"}} if inputs is None else inputs,
        "outputs": {"decision": {"type": {"kind": "bool"}, "required": False}},
        "constraints": [],
        "facts": [],
        "rules": [],
    }


def scope_expectations(document, states):
    rows = []
    for item in sorted(document["rules"], key=lambda value: value["id"]):
        rows.append({
            "core_rule_id": item["id"],
            "expectation": states[item["id"]],
            "source_unit_ids": [digest({"test_source": item["id"]})],
            "rationale": "テストホストが固定した期待。",
        })
    return {
        "format": "rule-scope-expectations/1",
        "expectation_id": "STAGED_TEST_EXPECTATIONS",
        "task_hash": "1" * 64,
        "candidate_hash": "2" * 64,
        "review_hash": "3" * 64,
        "source_unit_manifest_sha256": "4" * 64,
        "interpretation_snapshot_sha256": "5" * 64,
        "scope_hash": digest(core_scope(document)),
        "core_model_hash": digest(document),
        "rules": rows,
    }


def set_path(value, path, replacement):
    target = value
    for item in path[:-1]:
        target = target[item]
    target[path[-1]] = replacement


class StagedReachabilityTests(unittest.TestCase):
    def assert_error(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def checked(self, document, expectations=None):
        expected_hash = None if expectations is None else digest(expectations)
        certificate = analyze_staged_reachability(
            document, expectations,
            expected_scope_expectations_sha256=expected_hash,
        )
        result = verify_staged_reachability(
            document, certificate, expectations,
            expected_scope_expectations_sha256=expected_hash,
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["rules"], certificate["rules"])
        self.assertEqual(result["attention"], certificate["attention"])
        self.assertEqual(result["certificate_hash"], digest(certificate))
        return certificate, result

    def test_guard_contradiction_and_atomic_integer_range_hint_stay_distinct(self):
        document = model({
            "age": {"kind": "int", "min": 0, "max": 25},
            "flag": {"kind": "bool"},
        })
        document["rules"] = [
            rule("COMPOUND", op("and", var("flag"), op("not", var("flag")))),
            rule("RANGE", op("ge", var("age"), const(26))),
            rule("BOUNDARY", op("ge", var("age"), const(25))),
        ]
        certificate, result = self.checked(document)
        rows = {item["rule_id"]: item for item in certificate["rules"]}
        self.assertEqual(rows["COMPOUND"]["guard_count"], 0)
        self.assertIsNone(rows["COMPOUND"]["range_hint"])
        self.assertEqual(rows["COMPOUND"]["activation_stage"],
                         "no_guard_witness_in_declared_domain")
        self.assertEqual(rows["RANGE"]["guard_count"], 0)
        self.assertEqual(rows["RANGE"]["range_hint"], {
            "kind": "atomic_integer_comparison_disjoint_from_declared_domain",
            "variable": "age", "operator": "ge", "constant": 26,
            "declared_min": 0, "declared_max": 25,
        })
        self.assertEqual(rows["BOUNDARY"]["guard_count"], 2)
        self.assertIsNone(rows["BOUNDARY"]["range_hint"])
        self.assertEqual(result["attention_count"], 2)

    def test_atomic_range_hint_normalizes_every_comparison_direction(self):
        cases = (
            ("eq", var("age"), const(3), 0, 2, "eq", 3),
            ("lt", var("age"), const(0), 0, 2, "lt", 0),
            ("le", var("age"), const(-1), 0, 2, "le", -1),
            ("gt", var("age"), const(2), 0, 2, "gt", 2),
            ("ge", var("age"), const(3), 0, 2, "ge", 3),
            ("eq", const(3), var("age"), 0, 2, "eq", 3),
            ("gt", const(0), var("age"), 0, 2, "lt", 0),
            ("ge", const(-1), var("age"), 0, 2, "le", -1),
            ("lt", const(2), var("age"), 0, 2, "gt", 2),
            ("le", const(3), var("age"), 0, 2, "ge", 3),
            ("ne", var("age"), const(1), 1, 1, "ne", 1),
            ("ne", const(1), var("age"), 1, 1, "ne", 1),
        )
        for source_operator, left, right, minimum, maximum, operator, constant in cases:
            with self.subTest(source_operator=source_operator, left=left, right=right):
                document = model({
                    "age": {"kind": "int", "min": minimum, "max": maximum},
                })
                document["rules"] = [rule("R", op(source_operator, left, right))]
                certificate, _ = self.checked(document)
                row = certificate["rules"][0]
                self.assertEqual(row["guard_count"], 0)
                self.assertEqual(row["range_hint"], {
                    "kind": "atomic_integer_comparison_disjoint_from_declared_domain",
                    "variable": "age",
                    "operator": operator,
                    "constant": constant,
                    "declared_min": minimum,
                    "declared_max": maximum,
                })

    def test_facts_constraints_and_overlap_have_independent_counts_and_witnesses(self):
        document = model({"a": {"kind": "bool"}, "b": {"kind": "bool"}})
        document["facts"] = [{"var": "a", "value": False}]
        document["constraints"] = [op("not", var("b"))]
        document["rules"] = [
            rule("FACTS_BLOCK", var("a")),
            rule("CONSTRAINTS_BLOCK", var("b")),
            rule("COMBINED", op("ne", var("a"), var("b"))),
            rule("ALL_CELLS", True),
        ]
        certificate, _ = self.checked(document)
        rows = {item["rule_id"]: item for item in certificate["rules"]}
        facts = rows["FACTS_BLOCK"]
        self.assertEqual((facts["guard_count"], facts["guard_and_facts_count"],
                          facts["guard_and_constraints_count"], facts["enabled_count"]),
                         (2, 0, 1, 0))
        self.assertEqual(facts["filter_diagnosis"], "facts_block_all_guard_witnesses")
        constraints = rows["CONSTRAINTS_BLOCK"]
        self.assertEqual((constraints["guard_count"],
                          constraints["guard_and_facts_count"],
                          constraints["guard_and_constraints_count"],
                          constraints["enabled_count"]), (2, 1, 0, 0))
        self.assertEqual(constraints["filter_diagnosis"],
                         "constraints_block_all_guard_witnesses")
        combined = rows["COMBINED"]
        self.assertEqual((combined["guard_count"],
                          combined["guard_and_facts_count"],
                          combined["guard_and_constraints_count"],
                          combined["enabled_count"]), (2, 1, 1, 0))
        self.assertEqual(combined["filter_diagnosis"],
                         "combined_filters_have_no_common_witness")
        partition = rows["ALL_CELLS"]["filter_partition"]
        self.assertEqual([item["count"] for item in partition], [1, 1, 1, 1])
        self.assertEqual([item["witness"]["case_index"] for item in partition],
                         [0, 1, 2, 3])
        self.assertEqual((certificate["facts_matching_contexts"],
                          certificate["constraints_matching_contexts"],
                          certificate["admitted_contexts"]), (2, 2, 1))

    def test_same_guard_witness_can_fail_both_filters_without_single_cause_claim(self):
        document = model({"flag": {"kind": "bool"}, "keep": {"kind": "bool"}})
        document["facts"] = [{"var": "flag", "value": True}]
        document["constraints"] = [op("or", var("flag"), var("keep"))]
        document["rules"] = [
            rule("BOTH", op("and", op("not", var("flag")), op("not", var("keep"))))
        ]
        certificate, _ = self.checked(document)
        row = certificate["rules"][0]
        self.assertEqual((row["guard_count"], row["guard_and_facts_count"],
                          row["guard_and_constraints_count"], row["enabled_count"]),
                         (1, 0, 0, 0))
        self.assertEqual(row["filter_diagnosis"],
                         "facts_and_constraints_each_block_all_guard_witnesses")
        self.assertEqual(row["filter_partition"][3]["count"], 1)

    def test_override_stages_distinguish_always_and_partial_suppression(self):
        document = model()
        document["rules"] = [
            rule("BASE_ALWAYS"), rule("TOP_ALWAYS", overrides=["BASE_ALWAYS"]),
            rule("BASE_PARTIAL"), rule("TOP_PARTIAL", var("flag"), ["BASE_PARTIAL"]),
        ]
        _, result = self.checked(document)
        rows = {item["rule_id"]: item for item in result["rules"]}
        self.assertEqual((rows["BASE_ALWAYS"]["enabled_count"],
                          rows["BASE_ALWAYS"]["effective_count"],
                          rows["BASE_ALWAYS"]["activation_stage"]),
                         (2, 0, "always_suppressed"))
        self.assertEqual(rows["BASE_ALWAYS"]["attention_codes"], ["ALWAYS_SUPPRESSED"])
        self.assertEqual((rows["BASE_PARTIAL"]["enabled_count"],
                          rows["BASE_PARTIAL"]["effective_count"],
                          rows["BASE_PARTIAL"]["activation_stage"]),
                         (2, 1, "partially_suppressed"))
        self.assertEqual(rows["BASE_PARTIAL"]["attention_codes"], [])

    def test_empty_base_remains_undetermined_even_with_inactive_expectation(self):
        document = model()
        document["facts"] = [{"var": "flag", "value": True}]
        document["constraints"] = [op("not", var("flag"))]
        document["rules"] = [rule("R", False)]
        expectations = scope_expectations(document, {"R": "expected_inactive"})
        expected_hash = digest(expectations)
        self.assert_error(
            "BASE_INCONSISTENT", analyze_staged_reachability,
            document, expectations,
            expected_scope_expectations_sha256=expected_hash,
        )
        self.assert_error(
            "BASE_INCONSISTENT", verify_staged_reachability,
            document, {}, expectations,
            expected_scope_expectations_sha256=expected_hash,
        )

    def test_t05_member_fixture_joins_expected_scope_and_exact_stage_counts(self):
        package = load_json(MEMBER / "compiled.json")
        document = package["core"]
        expectations = load_json(MEMBER / "scope-expectations.json")
        certificate, result = self.checked(document, expectations)
        rows = {item["rule_id"]: item for item in certificate["rules"]}
        adult = rows["IR_P_ADULT_MEMBER"]
        exception = rows["IR_P_SUSPENSION_EXCEPTION"]
        self.assertEqual((certificate["total_contexts"], certificate["admitted_contexts"]),
                         (104, 78))
        self.assertEqual((adult["guard_count"], adult["guard_and_facts_count"],
                          adult["guard_and_constraints_count"], adult["enabled_count"],
                          adult["effective_count"]), (16, 16, 16, 16, 8))
        self.assertEqual((exception["guard_count"],
                          exception["guard_and_facts_count"],
                          exception["guard_and_constraints_count"],
                          exception["enabled_count"], exception["effective_count"]),
                         (52, 52, 26, 26, 26))
        self.assertEqual(adult["expectation_result"], "matched_in_scope")
        self.assertEqual(exception["expectation_result"], "matched_in_scope")
        self.assertEqual(result["attention_count"], 0)
        self.assertEqual(result["scope_expectations_binding"]["scope_expectations_sha256"],
                         MEMBER_EXPECTATIONS_HASH)

    def test_expectation_states_control_attention_without_hiding_suppression(self):
        inactive = model()
        inactive["rules"] = [rule("R", False)]
        for state, result_name, codes in (
                ("expected_inactive", "matched_inactive", []),
                ("expected_in_scope", "expected_in_scope_not_reached",
                 ["EXPECTED_IN_SCOPE_NOT_REACHED"]),
                ("unspecified", "inactive_without_expectation",
                 ["INACTIVE_WITHOUT_EXPECTATION"])):
            with self.subTest(state=state):
                expectations = scope_expectations(inactive, {"R": state})
                _, result = self.checked(inactive, expectations)
                self.assertEqual(result["rules"][0]["expectation_result"], result_name)
                self.assertEqual(result["rules"][0]["attention_codes"], codes)
        _, no_expectation = self.checked(inactive)
        self.assertEqual(no_expectation["rules"][0]["attention_codes"],
                         ["INACTIVE_WITHOUT_EXPECTATION"])

        active = model()
        active["rules"] = [rule("R", True)]
        expectations = scope_expectations(active, {"R": "expected_inactive"})
        _, reached = self.checked(active, expectations)
        self.assertEqual(reached["rules"][0]["attention_codes"],
                         ["EXPECTED_INACTIVE_BUT_REACHED"])

        suppressed = model()
        suppressed["rules"] = [rule("BASE"), rule("TOP", overrides=["BASE"])]
        expectations = scope_expectations(suppressed, {
            "BASE": "expected_in_scope", "TOP": "expected_in_scope",
        })
        _, suppressed_result = self.checked(suppressed, expectations)
        base = next(item for item in suppressed_result["rules"] if item["rule_id"] == "BASE")
        self.assertEqual(base["expectation_result"], "matched_in_scope")
        self.assertEqual(base["attention_codes"], ["ALWAYS_SUPPRESSED"])

    def test_expectation_anchor_bindings_and_fixed_rule_denominator_are_strict(self):
        document = model()
        document["rules"] = [rule("A"), rule("B")]
        original = scope_expectations(document, {
            "A": "expected_in_scope", "B": "expected_in_scope",
        })
        self.assert_error(
            "EXPECTATIONS_INVALID", analyze_staged_reachability,
            document, original,
        )
        self.assert_error(
            "EXPECTATIONS_INVALID", analyze_staged_reachability,
            document, None, expected_scope_expectations_sha256=digest(original),
        )
        self.assert_error(
            "EXPECTATIONS_MISMATCH", analyze_staged_reachability,
            document, original, expected_scope_expectations_sha256="0" * 64,
        )
        mutations = []
        changed = deepcopy(original)
        changed["core_model_hash"] = "0" * 64
        mutations.append(("EXPECTATIONS_MISMATCH", changed))
        changed = deepcopy(original)
        changed["scope_hash"] = "0" * 64
        mutations.append(("EXPECTATIONS_MISMATCH", changed))
        changed = deepcopy(original)
        changed["source_unit_manifest_sha256"] = "bad"
        mutations.append(("EXPECTATIONS_INVALID", changed))
        changed = deepcopy(original)
        changed["rules"].pop()
        mutations.append(("EXPECTATIONS_MISMATCH", changed))
        changed = deepcopy(original)
        changed["rules"][1]["core_rule_id"] = "C"
        mutations.append(("EXPECTATIONS_MISMATCH", changed))
        changed = deepcopy(original)
        changed["rules"][1]["core_rule_id"] = "A"
        mutations.append(("EXPECTATIONS_INVALID", changed))
        for status, changed in mutations:
            with self.subTest(status=status, change=changed):
                self.assert_error(
                    status, analyze_staged_reachability,
                    document, changed,
                    expected_scope_expectations_sha256=digest(changed),
                )
        candidate = {"format": "rule-interpretation-candidate/1"}
        self.assert_error(
            "EXPECTATIONS_INVALID", analyze_staged_reachability,
            document, candidate,
            expected_scope_expectations_sha256=digest(candidate),
        )

    def test_certificate_tamper_and_old_format_are_rejected(self):
        document = model()
        document["rules"] = [rule("R", var("flag"))]
        certificate, _ = self.checked(document)
        mutations = [
            (["format"], "finite-decisions-reachability-certificate/1"),
            (["model_hash"], "0" * 64),
            (["facts_matching_contexts"], 0),
            (["cases", 0, "constraints_match"], False),
            (["cases", 1, "guard"], []),
            (["rules", 0, "guard_count"], 0),
            (["rules", 0, "guard_witness"], None),
            (["rules", 0, "filter_partition", 0, "count"], 2),
            (["rules", 0, "activation_stage"], "unreachable"),
            (["rules", 0, "range_hint"], {"kind": "invented"}),
            (["rules", 0, "attention_codes"], ["ALWAYS_SUPPRESSED"]),
            (["attention"], [{"code": "ALWAYS_SUPPRESSED", "rule_id": "R",
                               "detail": "invented"}]),
        ]
        for path, replacement in mutations:
            with self.subTest(path=path):
                changed = deepcopy(certificate)
                set_path(changed, path, replacement)
                self.assert_error(
                    "CERTIFICATE_INVALID", verify_staged_reachability,
                    document, changed,
                )
        for malformed in (None, [], True, {1: "bad"}):
            self.assert_error(
                "CERTIFICATE_INVALID", verify_staged_reachability,
                document, malformed,
            )

    def test_bound_and_unbound_certificates_cannot_be_reinterpreted(self):
        document = model()
        document["rules"] = [rule("R", False)]
        expectations = scope_expectations(document, {"R": "expected_inactive"})
        expected_hash = digest(expectations)
        bound = analyze_staged_reachability(
            document, expectations,
            expected_scope_expectations_sha256=expected_hash,
        )
        unbound = analyze_staged_reachability(document)
        self.assert_error(
            "CERTIFICATE_INVALID", verify_staged_reachability,
            document, bound,
        )
        self.assert_error(
            "CERTIFICATE_INVALID", verify_staged_reachability,
            document, unbound, expectations,
            expected_scope_expectations_sha256=expected_hash,
        )

    def test_checker_rejects_mutated_producer_boundary_and_has_no_producer_import(self):
        document = model({"age": {"kind": "int", "min": 0, "max": 2}})
        document["rules"] = [rule("R", op("ge", var("age"), const(1)))]
        evaluate = staged_reachability._evaluate

        def strict_boundary(expression, assignment):
            if expression.get("op") == "ge":
                expression = {**expression, "op": "gt"}
            return evaluate(expression, assignment)

        with patch.object(staged_reachability, "_evaluate", strict_boundary):
            faulty = analyze_staged_reachability(document)
        self.assert_error(
            "CERTIFICATE_INVALID", verify_staged_reachability,
            document, faulty,
        )
        tree = ast.parse(Path(staged_reachability_checker.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.fail("staged checker should not import producer modules")
            if isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, {
                    "__future__", "model", "staged_reachability_model",
                })

    def test_limits_and_exact_types_remain_fail_closed(self):
        document = model()
        document["rules"] = [rule("R")]
        certificate = analyze_staged_reachability(document)
        for limit in (0, -1, True, 2.0, 10001):
            self.assert_error(
                "LIMIT_REACHED", analyze_staged_reachability,
                document, max_contexts=limit,
            )
            self.assert_error(
                "LIMIT_REACHED", verify_staged_reachability,
                document, certificate, max_contexts=limit,
            )
        size = len(canonical_json(certificate).encode("utf-8"))
        with patch.object(staged_reachability, "MAX_CERTIFICATE_BYTES", size - 1):
            self.assert_error("LIMIT_REACHED", analyze_staged_reachability, document)
        with patch.object(staged_reachability_checker, "MAX_CERTIFICATE_BYTES", size - 1):
            self.assert_error(
                "CERTIFICATE_INVALID", verify_staged_reachability,
                document, certificate,
            )

    def test_cyclic_python_certificate_is_rejected_before_replay(self):
        document = model()
        document["rules"] = [rule("R")]
        cyclic = {}
        cyclic["branches"] = [cyclic, cyclic]
        error = self.assert_error(
            "CERTIFICATE_INVALID", verify_staged_reachability,
            document, cyclic,
        )
        self.assertIn("cyclic container", error.message)


if __name__ == "__main__":
    unittest.main()
