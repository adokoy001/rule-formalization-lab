"""Black-box contract tests for the bounded decision kernel and its checker."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rulekernel.checker import verify
from rulekernel.engine import analyze
from rulekernel.model import KernelError, digest, load_json, validate_model


ROOT = Path(__file__).resolve().parents[1]


def literal(value):
    return {"const": value}


def variable(name):
    return {"var": name}


def operation(name, *args):
    return {"op": name, "args": list(args)}


def rule(rule_id, value, when=None, overrides=(), output="decision"):
    return {
        "id": rule_id,
        "source": "架空の規則 " + rule_id,
        "when": literal(True) if when is None else when,
        "then": {"output": output, "value": value},
        "overrides": list(overrides),
    }


def small_model(required=True):
    return {
        "profile": "finite-decisions/1",
        "origin_kind": "authored_core",
        "title": "架空の小規則",
        "inputs": {"flag": {"kind": "bool"}},
        "outputs": {"decision": {"type": {"kind": "bool"}, "required": required}},
        "constraints": [],
        "facts": [],
        "rules": [],
    }


def query(certificate, kind, output="decision"):
    return next(q for q in certificate["queries"] if q["kind"] == kind and q["output"] == output)


def set_path(value, path, replacement):
    for part in path[:-1]:
        value = value[part]
    value[path[-1]] = replacement


class KernelTestCase(unittest.TestCase):
    def assert_error(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        if status is not None:
            self.assertEqual(caught.exception.status, status)
        self.assertIsInstance(caught.exception.message, str)

    def checked(self, model):
        certificate = analyze(model)
        result = verify(model, certificate)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["total_contexts"], certificate["total_contexts"])
        self.assertEqual(result["admitted_contexts"], certificate["admitted_contexts"])
        for item in result["queries"]:
            expected = "WITNESS_VERIFIED" if item["count"] else "NO_WITNESS_IN_SCOPE_VERIFIED"
            self.assertEqual(item["status"], expected)
        return certificate


class ClubExamplesTests(KernelTestCase):
    def test_broken_rules_show_two_distinct_problems(self):
        model = load_json(ROOT / "examples" / "club-broken.json")
        certificate = self.checked(model)
        self.assertEqual(len(model["rules"]), 6)
        self.assertEqual(certificate["total_contexts"], 52)
        self.assertEqual(certificate["admitted_contexts"], 52)
        self.assertEqual(query(certificate, "conflict", "eligible"), {
            "kind": "conflict", "output": "eligible", "count": 4,
            "witness": {"case_index": 36, "input": {"age": 18, "student": False},
                        "rule_ids": ["R1", "R2"], "values": [False, True]},
        })
        self.assertEqual(query(certificate, "gap", "fee_yen"), {
            "kind": "gap", "output": "fee_yen", "count": 4,
            "witness": {"case_index": 36, "input": {"age": 18, "student": False},
                        "rule_ids": [], "values": []},
        })
        self.assertEqual(query(certificate, "gap", "eligible")["count"], 0)
        self.assertEqual(query(certificate, "conflict", "fee_yen")["count"], 0)
        self.assertEqual(query(certificate, "conflict", "badge")["count"], 0)
        self.assertNotIn(("gap", "badge"), [(q["kind"], q["output"]) for q in certificate["queries"]])
        self.assertEqual([(q["output"], q["kind"]) for q in certificate["queries"]], [
            ("badge", "conflict"), ("eligible", "conflict"), ("eligible", "gap"),
            ("fee_yen", "conflict"), ("fee_yen", "gap"),
        ])

    def test_fixed_boundaries_remove_conflicts_and_gaps(self):
        model = load_json(ROOT / "examples" / "club-fixed.json")
        certificate = self.checked(model)
        self.assertEqual(certificate["total_contexts"], 52)
        self.assertTrue(all(item["count"] == 0 and item["witness"] is None for item in certificate["queries"]))
        expected = {
            34: ["R2", "R3"],       # 17, non-student
            35: ["R2", "R3"],       # 17, student
            36: ["R1", "R4"],       # 18, non-student
            37: ["R1", "R5", "R6"], # 18, student
            39: ["R1", "R5", "R6"], # 19, student
            40: ["R1", "R4"],       # 20, non-student
            51: ["R1", "R5", "R6"], # 25, student
        }
        for index, effective in expected.items():
            with self.subTest(index=index):
                self.assertEqual(certificate["cases"][index]["effective"], effective)
        self.assertIn("R4", certificate["cases"][37]["enabled"])
        self.assertNotIn("R4", certificate["cases"][37]["effective"])


class FiniteSemanticsTests(KernelTestCase):
    def test_missing_fact_is_not_false(self):
        model = small_model()
        model["rules"] = [rule("R1", True, variable("flag"))]
        certificate = self.checked(model)
        self.assertEqual([c["input"] for c in certificate["cases"]], [{"flag": False}, {"flag": True}])
        self.assertEqual(certificate["cases"][1]["effective"], ["R1"])
        self.assertEqual(query(certificate, "gap")["count"], 1)

    def test_fact_filters_but_does_not_remove_certificate_rows(self):
        model = small_model()
        model["facts"] = [{"var": "flag", "value": True}, {"var": "flag", "value": True}]
        model["rules"] = [rule("R1", True, variable("flag"))]
        certificate = self.checked(model)
        self.assertEqual(certificate["total_contexts"], 2)
        self.assertEqual(certificate["admitted_contexts"], 1)
        self.assertEqual(certificate["cases"][0], {
            "index": 0, "input": {"flag": False}, "admitted": False, "enabled": [], "effective": [],
        })
        self.assertEqual(query(certificate, "gap")["count"], 0)

    def test_inconsistent_facts_are_not_overwritten(self):
        model = small_model()
        model["facts"] = [{"var": "flag", "value": False}, {"var": "flag", "value": True}]
        self.assert_error("INPUT_INCONSISTENT", validate_model, model)
        self.assert_error("INPUT_INCONSISTENT", analyze, model)
        self.assert_error("INPUT_INCONSISTENT", verify, model, {})

    def test_empty_admitted_background_is_not_vacuous_success(self):
        for constraint, facts in [
            (literal(False), []),
            (variable("flag"), [{"var": "flag", "value": False}]),
        ]:
            with self.subTest(constraint=constraint):
                model = small_model()
                model["constraints"] = [constraint]
                model["facts"] = facts
                self.assert_error("BASE_INCONSISTENT", analyze, model)

    def test_checker_rejects_fabricated_empty_background_success(self):
        model = small_model()
        model["constraints"] = [literal(False)]
        certificate = analyze(small_model())
        certificate["model_hash"] = digest(model)
        certificate["admitted_contexts"] = 0
        for case in certificate["cases"]:
            case["admitted"] = False
        for item in certificate["queries"]:
            item["count"] = 0
            item["witness"] = None
        self.assert_error("BASE_INCONSISTENT", verify, model, certificate)

    def test_empty_inputs_have_one_empty_assignment(self):
        model = small_model()
        model["inputs"] = {}
        certificate = self.checked(model)
        self.assertEqual(certificate["total_contexts"], 1)
        self.assertEqual(certificate["cases"], [{
            "index": 0, "input": {}, "admitted": True, "enabled": [], "effective": [],
        }])
        self.assertEqual(query(certificate, "gap")["count"], 1)

    def test_equal_conclusions_are_not_conflicts(self):
        model = small_model()
        model["rules"] = [rule("R2", True), rule("R1", True)]
        certificate = self.checked(model)
        self.assertEqual(certificate["cases"][0]["effective"], ["R1", "R2"])
        self.assertEqual(query(certificate, "conflict")["count"], 0)
        self.assertEqual(query(certificate, "gap")["count"], 0)

    def test_conflict_is_not_a_gap_or_background_constraint(self):
        model = small_model()
        model["rules"] = [rule("R1", True), rule("R2", False)]
        certificate = self.checked(model)
        self.assertEqual(certificate["admitted_contexts"], 2)
        self.assertEqual(query(certificate, "conflict")["count"], 2)
        self.assertEqual(query(certificate, "gap")["count"], 0)

    def test_only_required_outputs_generate_gap_queries(self):
        model = small_model(required=False)
        certificate = self.checked(model)
        self.assertEqual(certificate["queries"], [
            {"kind": "conflict", "output": "decision", "count": 0, "witness": None},
        ])

    def test_context_order_uses_names_and_declared_enum_order(self):
        model = small_model()
        model["inputs"] = {
            "z": {"kind": "enum", "values": ["later", "earlier"]},
            "a": {"kind": "int", "min": -1, "max": 0},
        }
        model["rules"] = [rule("R1", True, operation("eq", variable("z"), literal("earlier")))]
        certificate = self.checked(model)
        self.assertEqual([c["input"] for c in certificate["cases"]], [
            {"a": -1, "z": "later"}, {"a": -1, "z": "earlier"},
            {"a": 0, "z": "later"}, {"a": 0, "z": "earlier"},
        ])

    def test_comparison_and_boolean_operators(self):
        expected = {"eq": [1], "ne": [0, 2], "lt": [0], "le": [0, 1], "gt": [2], "ge": [1, 2]}
        for op, indices in expected.items():
            with self.subTest(op=op):
                model = small_model()
                model["inputs"] = {"age": {"kind": "int", "min": 17, "max": 19}}
                model["rules"] = [rule("R1", True, operation(op, variable("age"), literal(18)))]
                certificate = self.checked(model)
                self.assertEqual([c["index"] for c in certificate["cases"] if c["effective"]], indices)
        model = small_model()
        model["rules"] = [rule("R1", True, operation("or", variable("flag"), operation("not", variable("flag")))),
                          rule("R2", False, operation("and", variable("flag"), operation("not", variable("flag"))))]
        self.assertTrue(all(c["effective"] == ["R1"] for c in self.checked(model)["cases"]))

    def test_conflict_values_use_canonical_json_order(self):
        model = small_model()
        model["outputs"]["decision"]["type"] = {"kind": "int", "min": 0, "max": 10}
        model["rules"] = [rule("R1", 2), rule("R2", 10), rule("R3", 2)]
        certificate = self.checked(model)
        witness = query(certificate, "conflict")["witness"]
        self.assertEqual(witness["values"], [10, 2])
        self.assertEqual(witness["rule_ids"], ["R1", "R2", "R3"])


class OverrideTests(KernelTestCase):
    def test_exception_to_exception_revives_base_rule(self):
        model = small_model()
        model["rules"] = [rule("R1", True), rule("R2", False, overrides=["R1"]),
                          rule("R3", True, overrides=["R2"])]
        certificate = self.checked(model)
        self.assertEqual(certificate["cases"][0]["effective"], ["R1", "R3"])
        self.assertEqual(query(certificate, "conflict")["count"], 0)

    def test_disabled_override_does_not_suppress_base(self):
        model = small_model()
        model["rules"] = [rule("R1", True), rule("R2", False, when=variable("flag"), overrides=["R1"])]
        certificate = self.checked(model)
        self.assertEqual(certificate["cases"][0]["effective"], ["R1"])
        self.assertEqual(certificate["cases"][1]["effective"], ["R2"])

    def test_disabled_top_exception_leaves_middle_exception_active(self):
        model = small_model()
        model["rules"] = [rule("R1", True), rule("R2", False, overrides=["R1"]),
                          rule("R3", True, when=literal(False), overrides=["R2"])]
        self.assertEqual(self.checked(model)["cases"][0]["effective"], ["R2"])

    def test_cycle_is_unsupported(self):
        model = small_model()
        model["rules"] = [rule("R1", True, overrides=["R2"]), rule("R2", False, overrides=["R1"])]
        self.assert_error("UNSUPPORTED", analyze, model)
        self.assert_error("UNSUPPORTED", verify, model, {})

    def test_rule_array_permutation_preserves_results(self):
        model = load_json(ROOT / "examples" / "club-broken.json")
        original = self.checked(model)
        model["rules"].reverse()
        reordered = self.checked(model)
        self.assertEqual(original["cases"], reordered["cases"])
        self.assertEqual(original["queries"], reordered["queries"])
        self.assertNotEqual(original["model_hash"], reordered["model_hash"])


class ValidationTests(KernelTestCase):
    def test_invalid_types_and_shapes_are_rejected(self):
        base = small_model()
        base["rules"] = [rule("R1", True)]
        changes = [
            (["profile"], "finite-decisions/2"),
            (["origin_kind"], "llm_approved"),
            (["inputs", "flag", "kind"], "real"),
            (["outputs", "decision", "required"], 1),
            (["rules", 0, "then", "value"], 1),
            (["rules", 0, "when"], literal(1)),
            (["rules", 0, "when"], variable("decision")),
            (["rules", 0, "when"], operation("lt", variable("flag"), literal(True))),
            (["rules", 0, "when"], operation("eq", variable("flag"), literal(1))),
            (["rules", 0, "when"], operation("and", literal(True))),
            (["rules", 0, "when"], operation("add", literal(1), literal(2))),
            (["rules", 0, "when"], {"const": True, "var": "flag"}),
            (["rules", 0, "id"], "bad-id"),
            (["rules", 0, "source"], ""),
            (["rules", 0, "overrides"], ["missing"]),
            (["rules", 0, "overrides"], ["R1"]),
            (["facts"], [{"var": "flag", "value": 1}]),
            (["constraints"], [literal(0)]),
            (["title"], ""),
        ]
        for path, value in changes:
            with self.subTest(path=path, value=value):
                model = deepcopy(base)
                set_path(model, path, value)
                self.assert_error(None, validate_model, model)

    def test_unknown_keys_and_duplicate_rule_ids_are_rejected(self):
        model = small_model()
        model["rules"] = [rule("R1", True)]
        for path in [[], ["inputs", "flag"], ["outputs", "decision"], ["rules", 0], ["rules", 0, "when"]]:
            with self.subTest(path=path):
                changed = deepcopy(model)
                target = changed
                for part in path:
                    target = target[part]
                target["unknown"] = True
                self.assert_error(None, validate_model, changed)
        model["rules"].append(rule("R1", False))
        self.assert_error(None, validate_model, model)

    def test_duplicate_override_targets_are_rejected(self):
        model = small_model()
        model["rules"] = [rule("R1", True), rule("R2", False, overrides=["R1", "R1"])]
        self.assert_error(None, validate_model, model)

    def test_integer_ranges_constants_and_values_are_strict(self):
        base = small_model()
        base["inputs"] = {"age": {"kind": "int", "min": 0, "max": 25}}
        base["rules"] = [rule("R1", True, operation("ge", variable("age"), literal(18)))]
        changes = [
            (["inputs", "age", "min"], False),
            (["inputs", "age", "max"], 25.0),
            (["inputs", "age", "max"], -1),
            (["inputs", "age", "min"], -(2 ** 63) - 1),
            (["rules", 0, "when", "args", 1, "const"], 2 ** 63),
            (["facts"], [{"var": "age", "value": True}]),
            (["facts"], [{"var": "age", "value": 26}]),
        ]
        for path, value in changes:
            with self.subTest(path=path, value=value):
                model = deepcopy(base)
                set_path(model, path, value)
                self.assert_error(None, validate_model, model)
        base["outputs"]["decision"]["type"] = {"kind": "int", "min": 0, "max": 10}
        for value in [True, 10.0, 11, -1]:
            with self.subTest(output_value=value):
                base["rules"][0]["then"]["value"] = value
                self.assert_error(None, validate_model, base)

    def test_enum_membership_and_type_compatibility(self):
        base = small_model()
        base["inputs"] = {"group": {"kind": "enum", "values": ["member", "guest"]}}
        base["rules"] = [rule("R1", True, operation("eq", variable("group"), literal("member")))]
        self.assertEqual(query(self.checked(base), "gap")["count"], 1)
        for values in [[], ["guest", "guest"], [""], [1]]:
            with self.subTest(values=values):
                model = deepcopy(base)
                model["inputs"]["group"]["values"] = values
                self.assert_error(None, validate_model, model)
        model = deepcopy(base)
        model["rules"][0]["when"]["args"][1] = literal("outsider")
        self.assert_error(None, validate_model, model)
        model = deepcopy(base)
        model["inputs"]["other"] = {"kind": "enum", "values": ["member", "staff"]}
        model["rules"][0]["when"]["args"][1] = variable("other")
        self.assert_error(None, validate_model, model)

    def test_loading_rejects_ambiguous_or_invalid_json(self):
        invalid = [b'{"x": 1, "x": 2}', b'{"outer":{"x":1,"x":2}}',
                   b'{"x": NaN}', b'{"x": Infinity}', b'{"x": -Infinity}',
                   b'{"x": "\xff"}', b'{"x":', b'{"x":"\\ud800"}']
        with TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            for payload in invalid:
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    self.assert_error(None, load_json, path)
            path.write_bytes(b'{"x": 1}')
            self.assertEqual(load_json(path), {"x": 1})
            self.assert_error(None, load_json, path, max_bytes=2)


class CertificateTests(KernelTestCase):
    def setUp(self):
        self.model = small_model()
        self.model["rules"] = [rule("R1", True), rule("R2", False, variable("flag"))]
        self.certificate = self.checked(self.model)

    def test_missing_duplicate_reordered_or_extra_case_is_rejected(self):
        variants = {
            "missing": self.certificate["cases"][:-1],
            "duplicate": [self.certificate["cases"][0], self.certificate["cases"][0]],
            "reordered": list(reversed(self.certificate["cases"])),
            "extra": self.certificate["cases"] + [self.certificate["cases"][1]],
        }
        for name, cases in variants.items():
            with self.subTest(name=name):
                certificate = deepcopy(self.certificate)
                certificate["cases"] = deepcopy(cases)
                self.assert_error("CERTIFICATE_INVALID", verify, self.model, certificate)

    def test_counts_admission_witness_scope_and_metadata_tampering(self):
        changes = [
            (["total_contexts"], 1), (["admitted_contexts"], 1),
            (["model_hash"], "0" * 64),
            (["format"], "finite-decisions-certificate/2"),
            (["profile"], "finite-decisions/2"), (["engine_version"], "9.9.9"),
            (["cases", 0, "index"], 1), (["cases", 0, "admitted"], False),
            (["cases", 0, "input", "flag"], True),
            (["cases", 0, "enabled"], []), (["cases", 0, "effective"], []),
            (["cases", 1, "effective"], ["R1", "R1", "R2"]),
            (["cases", 1, "effective"], ["R2", "R1"]),
            (["queries", 0, "count"], 0),
            (["queries", 0, "output"], "absent"),
            (["queries", 0, "witness"], None),
            (["queries", 0, "witness", "case_index"], 0),
            (["queries", 0, "witness", "input", "flag"], False),
            (["queries", 0, "witness", "rule_ids"], ["R1"]),
            (["queries", 0, "witness", "values"], [True]),
            (["queries", 1, "witness"], {"case_index": 0}),
        ]
        for path, value in changes:
            with self.subTest(path=path, value=value):
                certificate = deepcopy(self.certificate)
                set_path(certificate, path, value)
                self.assert_error("CERTIFICATE_INVALID", verify, self.model, certificate)

    def test_bool_integer_and_float_substitutions_are_rejected(self):
        changes = [
            (["total_contexts"], 2.0), (["admitted_contexts"], 2.0),
            (["cases", 0, "index"], False), (["cases", 0, "admitted"], 1),
            (["cases", 1, "input", "flag"], 1),
            (["queries", 0, "count"], True),
            (["queries", 0, "witness", "case_index"], True),
            (["queries", 0, "witness", "input", "flag"], 1),
            (["queries", 0, "witness", "values", 1], 1),
        ]
        for path, value in changes:
            with self.subTest(path=path, value=value):
                certificate = deepcopy(self.certificate)
                set_path(certificate, path, value)
                self.assert_error("CERTIFICATE_INVALID", verify, self.model, certificate)

    def test_unknown_or_missing_keys_and_query_order_are_rejected(self):
        for path in [[], ["cases", 0], ["queries", 0], ["queries", 0, "witness"]]:
            with self.subTest(extra_key_at=path):
                certificate = deepcopy(self.certificate)
                target = certificate
                for part in path:
                    target = target[part]
                target["extra"] = None
                self.assert_error("CERTIFICATE_INVALID", verify, self.model, certificate)
        for key in self.certificate:
            with self.subTest(missing_key=key):
                certificate = deepcopy(self.certificate)
                del certificate[key]
                self.assert_error("CERTIFICATE_INVALID", verify, self.model, certificate)
        for queries in [[], self.certificate["queries"][:1],
                        list(reversed(self.certificate["queries"])),
                        self.certificate["queries"] + self.certificate["queries"][:1]]:
            with self.subTest(queries=queries):
                certificate = deepcopy(self.certificate)
                certificate["queries"] = deepcopy(queries)
                self.assert_error("CERTIFICATE_INVALID", verify, self.model, certificate)

    def test_certificate_is_bound_to_expected_model(self):
        other = deepcopy(self.model)
        other["rules"][0]["source"] = "改訂された別の原文"
        self.assert_error("CERTIFICATE_INVALID", verify, other, self.certificate)

    def test_certificate_with_rejected_context_marked_active_is_rejected(self):
        model = deepcopy(self.model)
        model["facts"] = [{"var": "flag", "value": True}]
        certificate = self.checked(model)
        certificate["cases"][0]["enabled"] = ["R1"]
        certificate["cases"][0]["effective"] = ["R1"]
        self.assert_error("CERTIFICATE_INVALID", verify, model, certificate)

    def test_budget_uses_full_product_even_when_facts_filter(self):
        model = deepcopy(self.model)
        model["facts"] = [{"var": "flag", "value": True}]
        certificate = self.checked(model)
        self.assert_error("LIMIT_REACHED", analyze, model, max_contexts=1)
        self.assert_error("LIMIT_REACHED", verify, model, certificate, max_contexts=1)
        self.assertEqual(analyze(model, max_contexts=2)["total_contexts"], 2)

    def test_invalid_or_above_hard_cap_budget_is_rejected(self):
        for budget in [0, -1, True, 2.0, 10001]:
            with self.subTest(budget=budget):
                self.assert_error("LIMIT_REACHED", analyze, self.model, max_contexts=budget)
                self.assert_error("LIMIT_REACHED", verify, self.model, self.certificate, max_contexts=budget)

    def test_huge_integer_scope_is_rejected_before_materializing(self):
        model = small_model()
        model["inputs"] = {"age": {"kind": "int", "min": -(2 ** 63), "max": 2 ** 63 - 1}}
        self.assert_error("LIMIT_REACHED", analyze, model)
        self.assert_error("LIMIT_REACHED", verify, model, {})


if __name__ == "__main__":
    unittest.main()
