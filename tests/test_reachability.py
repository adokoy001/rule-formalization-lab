"""Rule reachability semantics, complete evidence and independent replay."""
import ast
from copy import deepcopy
from itertools import permutations, product
from pathlib import Path
import unittest
from unittest.mock import patch

from rulekernel import reachability, reachability_checker
from rulekernel.model import KernelError, canonical_json, digest
from rulekernel.reachability import analyze_reachability
from rulekernel.reachability_checker import verify_reachability


def const(value):
    return {"const": value}


def var(name):
    return {"var": name}


def op(name, *args):
    return {"op": name, "args": list(args)}


def rule(name, guard=True, overrides=(), value=True):
    return {"id": name, "source": "到達可能性の架空例 " + name,
            "when": guard if type(guard) is dict else const(guard),
            "then": {"output": "decision", "value": value},
            "overrides": list(overrides)}


def model(inputs=None):
    return {"profile": "finite-decisions/1", "origin_kind": "authored_core",
            "title": "到達可能性の架空モデル",
            "inputs": {"flag": {"kind": "bool"}} if inputs is None else inputs,
            "outputs": {"decision": {"type": {"kind": "bool"}, "required": True}},
            "constraints": [], "facts": [], "rules": []}


def four_classes():
    doc = model()
    doc["rules"] = [rule("Dead", False), rule("Hidden"), rule("Top", overrides=["Hidden"]),
                    rule("Partial"), rule("Conditional", var("flag"), ["Partial"])]
    return doc


def set_path(value, path, replacement):
    for component in path[:-1]:
        value = value[component]
    value[path[-1]] = replacement


class ReachabilityTests(unittest.TestCase):
    def assert_error(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)

    def checked(self, doc):
        certificate = analyze_reachability(doc)
        result = verify_reachability(doc, certificate)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["rules"], certificate["rules"])
        self.assertEqual(result["total_rules"], len(doc["rules"]))
        self.assertEqual(result["certificate_hash"], digest(certificate))
        for item in result["rules"]:
            self.assertLessEqual(0, item["effective_count"])
            self.assertLessEqual(item["effective_count"], item["enabled_count"])
            self.assertLessEqual(item["enabled_count"], result["admitted_contexts"])
        return certificate

    def test_all_four_classifications_and_first_witnesses(self):
        certificate = self.checked(four_classes())
        summaries = {item["rule_id"]: item for item in certificate["rules"]}
        expected = {
            "Conditional": (1, 1, "always_effective_when_enabled", 1, 1),
            "Dead": (0, 0, "unreachable", None, None),
            "Hidden": (2, 0, "always_suppressed", 0, None),
            "Partial": (2, 1, "partially_suppressed", 0, 0),
            "Top": (2, 2, "always_effective_when_enabled", 0, 0),
        }
        for rule_id, (enabled, effective, classification, ew, fw) in expected.items():
            with self.subTest(rule=rule_id):
                self.assertEqual(summaries[rule_id], {
                    "rule_id": rule_id, "enabled_count": enabled, "effective_count": effective,
                    "classification": classification,
                    "enabled_witness": None if ew is None else {"case_index": ew, "input": {"flag": bool(ew)}},
                    "effective_witness": None if fw is None else {"case_index": fw, "input": {"flag": bool(fw)}},
                })
        self.assertEqual([item["rule_id"] for item in certificate["rules"]], sorted(expected))

    def test_exception_to_exception_revives_original(self):
        doc = model()
        doc["rules"] = [rule("A"), rule("B", overrides=["A"]), rule("C", overrides=["B"])]
        evidence = self.checked(doc)
        self.assertEqual([item["effective_count"] for item in evidence["rules"]], [2, 0, 2])
        self.assertTrue(all(case["effective"] == ["A", "C"] for case in evidence["cases"]))
        doc["rules"][2]["when"] = const(False)
        self.assertEqual([item["effective_count"] for item in self.checked(doc)["rules"]], [0, 2, 0])

    def test_rule_permutation_and_renaming_do_not_define_priority(self):
        doc = model()
        doc["rules"] = [rule("A"), rule("B", overrides=["A"]), rule("C", var("flag"), ["B"])]
        original = self.checked(doc)
        for ordering in permutations(doc["rules"]):
            changed = deepcopy(doc)
            changed["rules"] = list(ordering)
            result = self.checked(changed)
            self.assertEqual(result["cases"], original["cases"])
            self.assertEqual(result["rules"], original["rules"])
        changed = deepcopy(doc)
        names = {"A": "Z", "B": "M", "C": "A"}
        for item in changed["rules"]:
            item["id"] = names[item["id"]]
            item["overrides"] = [names[key] for key in item["overrides"]]
        renamed = {item["rule_id"]: item for item in self.checked(changed)["rules"]}
        for item in original["rules"]:
            self.assertEqual(renamed[names[item["rule_id"]]], {**item, "rule_id": names[item["rule_id"]]})

    def test_all_64_three_rule_dags_and_guard_patterns(self):
        # An independent truth formula for all forward edges and constant guards.
        for cb, ba, ca, a, b, c in product((False, True), repeat=6):
            eb = b and not (cb and c)
            ea = a and not (ba and eb) and not (ca and c)
            doc = model({})
            doc["rules"] = [rule("A", a), rule("B", b, ["A"] if ba else []),
                            rule("C", c, (["B"] if cb else []) + (["A"] if ca else []))]
            with self.subTest(edges=(cb, ba, ca), guards=(a, b, c)):
                results = self.checked(doc)["rules"]
                self.assertEqual([item["enabled_count"] for item in results], [int(a), int(b), int(c)])
                self.assertEqual([item["effective_count"] for item in results], [int(ea), int(eb), int(c)])

    def test_empty_rules_and_inputs_are_explicit(self):
        doc = model({})
        doc["outputs"] = {}
        certificate = self.checked(doc)
        self.assertEqual(certificate["total_contexts"], 1)
        self.assertEqual(certificate["admitted_contexts"], 1)
        self.assertEqual(certificate["total_rules"], 0)
        self.assertEqual(certificate["rules"], [])
        self.assertEqual(certificate["cases"], [{"index": 0, "input": {}, "admitted": True,
                                                  "enabled": [], "effective": []}])

    def test_background_and_duplicate_facts_filter_counts_not_scope(self):
        doc = model({"flag": {"kind": "bool"}, "age": {"kind": "int", "min": 0, "max": 2}})
        doc["facts"] = [{"var": "flag", "value": True}] * 2
        doc["constraints"] = [op("ge", var("age"), const(1))]
        doc["rules"] = [rule("A", op("eq", var("age"), const(0))), rule("B"),
                        rule("C", op("eq", var("age"), const(2)))]
        certificate = self.checked(doc)
        self.assertEqual((certificate["total_contexts"], certificate["admitted_contexts"]), (6, 2))
        self.assertEqual([item["enabled_count"] for item in certificate["rules"]], [0, 2, 1])
        self.assertEqual(certificate["rules"][1]["enabled_witness"], {
            "case_index": 3, "input": {"age": 1, "flag": True}})
        self.assertEqual(certificate["rules"][2]["enabled_witness"]["case_index"], 5)
        for case in certificate["cases"]:
            if not case["admitted"]:
                self.assertEqual((case["enabled"], case["effective"]), ([], []))

    def test_empty_background_is_not_unreachable_success(self):
        doc = model()
        original = analyze_reachability(doc)
        doc["constraints"] = [const(False)]
        self.assert_error("BASE_INCONSISTENT", analyze_reachability, doc)
        original["model_hash"] = digest(doc)
        self.assert_error("BASE_INCONSISTENT", verify_reachability, doc, original)

    def test_conflicting_facts_and_invalid_models_keep_model_status(self):
        doc = model()
        doc["facts"] = [{"var": "flag", "value": True}, {"var": "flag", "value": False}]
        for fn, extra in ((analyze_reachability, ()), (verify_reachability, ({},))):
            self.assert_error("INPUT_INCONSISTENT", fn, doc, *extra)
        doc["facts"] = [{"var": "flag", "value": 1}]
        self.assert_error("MODEL_INVALID", analyze_reachability, doc)
        self.assert_error("MODEL_INVALID", verify_reachability, doc, {})
        doc["facts"] = []
        doc["rules"] = [rule("A", overrides=["B"]), rule("B", overrides=["A"])]
        self.assert_error("UNSUPPORTED", analyze_reachability, doc)
        self.assert_error("UNSUPPORTED", verify_reachability, doc, {})

    def test_comparisons_and_enum_context_order(self):
        for operation, indices in {"eq": [1], "ne": [0, 2], "lt": [0], "le": [0, 1],
                                   "gt": [2], "ge": [1, 2]}.items():
            doc = model({"n": {"kind": "int", "min": -1, "max": 1}})
            doc["rules"] = [rule("R", op(operation, var("n"), const(0)))]
            certificate = self.checked(doc)
            self.assertEqual([row["index"] for row in certificate["cases"] if row["enabled"]], indices)
            self.assertEqual(certificate["rules"][0]["enabled_count"], len(indices))
        doc = model({"z": {"kind": "enum", "values": ["later", "earlier"]},
                     "a": {"kind": "int", "min": -1, "max": 0}})
        doc["rules"] = [rule("R", op("and", op("eq", var("z"), const("earlier")),
                                     op("not", op("lt", var("a"), const(0)))))]
        certificate = self.checked(doc)
        self.assertEqual([row["input"] for row in certificate["cases"]], [
            {"a": -1, "z": "later"}, {"a": -1, "z": "earlier"},
            {"a": 0, "z": "later"}, {"a": 0, "z": "earlier"}])
        self.assertEqual(certificate["rules"][0]["enabled_witness"]["case_index"], 3)

    def test_nested_boolean_guards_and_conflicting_decisions(self):
        doc = model()
        doc["rules"] = [rule("A", op("or", var("flag"), op("not", var("flag")))),
                        rule("B", op("eq", op("and", var("flag"), const(True)), var("flag")), value=False)]
        # Reachability does not silently discard a context with conflicting decisions.
        summaries = self.checked(doc)["rules"]
        self.assertTrue(all(item["effective_count"] == 2 for item in summaries))

    def test_limits_use_declared_cartesian_product(self):
        doc = four_classes()
        doc["facts"] = [{"var": "flag", "value": True}]
        certificate = self.checked(doc)
        self.assert_error("LIMIT_REACHED", analyze_reachability, doc, max_contexts=1)
        self.assert_error("LIMIT_REACHED", verify_reachability, doc, certificate, max_contexts=1)
        for value in [0, -1, True, 2.0, 10001]:
            self.assert_error("LIMIT_REACHED", analyze_reachability, doc, max_contexts=value)
            self.assert_error("LIMIT_REACHED", verify_reachability, doc, certificate, max_contexts=value)
        doc["inputs"] = {"flag": {"kind": "int", "min": -(2**63), "max": 2**63-1}}
        doc["rules"], doc["facts"] = [], []
        self.assert_error("LIMIT_REACHED", analyze_reachability, doc)
        self.assert_error("LIMIT_REACHED", verify_reachability, doc, {})

    def test_certificate_byte_limits_include_headers_and_summaries(self):
        doc = four_classes()
        certificate = analyze_reachability(doc)
        size = len(canonical_json(certificate).encode("utf-8"))
        with patch.object(reachability, "MAX_CERTIFICATE_BYTES", size):
            self.assertEqual(analyze_reachability(doc), certificate)
        with patch.object(reachability_checker, "MAX_CERTIFICATE_BYTES", size):
            self.assertEqual(verify_reachability(doc, certificate)["status"], "VERIFIED")
        with patch.object(reachability, "MAX_CERTIFICATE_BYTES", size - 1):
            self.assert_error("LIMIT_REACHED", analyze_reachability, doc)
        with patch.object(reachability_checker, "MAX_CERTIFICATE_BYTES", size - 1):
            self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, certificate)
            self.assert_error("LIMIT_REACHED", verify_reachability, doc, {})
        with patch.object(reachability, "MAX_CERTIFICATE_BYTES", 32):
            self.assert_error("LIMIT_REACHED", analyze_reachability, doc)
        with patch.object(reachability_checker, "MAX_CERTIFICATE_BYTES", 32):
            self.assert_error("LIMIT_REACHED", verify_reachability, doc, {})

    def test_metadata_rows_counts_classification_and_witness_tampering(self):
        doc = four_classes()
        original = self.checked(doc)
        mutations = [
            (["format"], "finite-decisions-certificate/1"),
            (["profile"], "finite-decisions/2"), (["engine_version"], "0.2.0"),
            (["model_hash"], "0" * 64), (["total_contexts"], 1),
            (["admitted_contexts"], 1), (["total_rules"], 0),
            (["cases", 0, "index"], 1), (["cases", 0, "admitted"], False),
            (["cases", 0, "enabled"], []), (["cases", 0, "effective"], []),
            (["rules", 0, "enabled_count"], 0), (["rules", 0, "effective_count"], 0),
            (["rules", 0, "classification"], "unreachable"),
            (["rules", 0, "enabled_witness"], None),
            (["rules", 0, "effective_witness", "case_index"], 0),
            (["rules", 0, "effective_witness", "input", "flag"], False),
            (["rules", 1, "enabled_witness"], {"case_index": 0, "input": {"flag": False}}),
        ]
        for path, value in mutations:
            with self.subTest(path=path):
                changed = deepcopy(original)
                set_path(changed, path, value)
                self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, changed)

    def test_missing_duplicate_reordered_rows_and_rule_summaries(self):
        doc = four_classes()
        original = self.checked(doc)
        for field in ["cases", "rules"]:
            for replacement in [[], original[field][1:], original[field][:-1],
                                list(reversed(original[field])), original[field] + original[field][:1]]:
                with self.subTest(field=field, replacement=replacement):
                    changed = deepcopy(original)
                    changed[field] = deepcopy(replacement)
                    self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, changed)
        changed = deepcopy(original)
        changed["cases"][0]["enabled"].append(changed["cases"][0]["enabled"][0])
        self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, changed)

    def test_wrong_first_witness_is_rejected_even_if_it_is_enabled(self):
        doc = model()
        doc["rules"] = [rule("R")]
        original = self.checked(doc)
        for key in ["enabled_witness", "effective_witness"]:
            changed = deepcopy(original)
            changed["rules"][0][key] = {"case_index": 1, "input": {"flag": True}}
            self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, changed)

    def test_exact_json_types_and_unknown_or_missing_keys(self):
        doc = four_classes()
        original = self.checked(doc)
        changes = [(["total_contexts"], 2.0), (["total_rules"], True),
                   (["cases", 0, "index"], False), (["cases", 0, "admitted"], 1),
                   (["cases", 1, "input", "flag"], 1), (["cases"], tuple(original["cases"])),
                   (["rules", 0, "enabled_count"], True), (["rules", 0, "effective_count"], 1.0),
                   (["rules", 0, "enabled_witness", "case_index"], True),
                   (["rules", 0, "enabled_witness", "input", "flag"], 1)]
        for path, value in changes:
            changed = deepcopy(original)
            set_path(changed, path, value)
            self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, changed)
        for path in [[], ["cases", 0], ["rules", 0], ["rules", 0, "enabled_witness"]]:
            changed = deepcopy(original)
            target = changed
            for part in path:
                target = target[part]
            target["extra"] = None
            self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, changed)
        for key in original:
            changed = deepcopy(original)
            del changed[key]
            self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, changed)
        for value in [None, [], True, float("nan"), "\ud800", {1: "invalid key"}]:
            self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, value)
        cyclic = []
        cyclic.append(cyclic)
        self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, cyclic)

    def test_certificate_is_bound_to_source_and_rule_array(self):
        doc = four_classes()
        original = self.checked(doc)
        changed = deepcopy(doc)
        changed["rules"][0]["source"] = "変更された原文"
        self.assert_error("CERTIFICATE_INVALID", verify_reachability, changed, original)
        changed = deepcopy(doc)
        changed["rules"].reverse()
        self.assert_error("CERTIFICATE_INVALID", verify_reachability, changed, original)

    def test_filtered_row_cannot_claim_enabled_rules(self):
        doc = four_classes()
        doc["facts"] = [{"var": "flag", "value": True}]
        original = self.checked(doc)
        original["cases"][0]["enabled"] = ["Top"]
        self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, original)

    def test_checker_rejects_search_boundary_and_enumeration_mutations(self):
        doc = model({"n": {"kind": "int", "min": 0, "max": 2}})
        doc["rules"] = [rule("R", op("ge", var("n"), const(1)))]
        evaluate = reachability._evaluate

        def strict_boundary(expression, assignment):
            if expression.get("op") == "ge":
                expression = {**expression, "op": "gt"}
            return evaluate(expression, assignment)

        with patch.object(reachability, "_evaluate", strict_boundary):
            faulty = analyze_reachability(doc)
        self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, faulty)
        doc = model()
        doc["rules"] = [rule("R", var("flag"))]
        with patch.object(reachability, "_domain_values", return_value=(False,)):
            faulty = analyze_reachability(doc)
        self.assert_error("CERTIFICATE_INVALID", verify_reachability, doc, faulty)

    def test_checker_does_not_import_semantic_implementations(self):
        path = Path(reachability_checker.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.fail("The independent checker should only import shared model utilities.")
            if isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, {"__future__", "model"})
        doc = four_classes()
        certificate = analyze_reachability(doc)
        with patch.object(reachability, "analyze_reachability", side_effect=AssertionError("search called")), \
                patch.object(reachability, "_evaluate", side_effect=AssertionError("search evaluation called")):
            self.assertEqual(verify_reachability(doc, certificate)["status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
