"""T01: independently authored decision-table gold for the 20-rule club pack.

Expected values below were fixed from examples/club20/README.md before running
the models. They neither evaluate the model AST nor resolve its override graph.
"""

from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rulekernel.checker import verify
from rulekernel.engine import analyze
from rulekernel.model import (
    KernelError, MAX_CERTIFICATE_BYTES, canonical_json, load_json, validate_model,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples" / "club20"
INPUT_ORDER = ("age", "event", "member", "student", "training")


def context_tuple(case):
    return tuple(case["input"][name] for name in INPUT_ORDER)


def table_gold(version, context):
    """Piecewise decision table, independent of rule conditions and IDs."""
    age, event, member, student, training = context
    eligible = (False,) if age < 18 else (True,)
    if version == "broken" and age in (18, 19):
        eligible = (False, True)

    if age < 18:
        fee = (500,)
    elif version == "broken" and age in (18, 19):
        fee = ()
    else:
        fee = (800,) if student and not event else (1000,)

    if age < 16:
        loan = (3,) if event and training else (0,)
    elif age == 25 and member:
        loan = (1, 2) if version == "broken" and not training else (2,)
    else:
        loan = (3,) if training else (1,)

    deposit = (0,) if member else ((500,) if student and not event else (1000,))
    return {
        "eligible": eligible,
        "fee_yen": fee,
        "loan_limit": loan,
        "deposit_yen": deposit,
        "handbook": ("digital",) if student else ("paper",),
        "badge": (True,) if member or (age >= 18 and student) else (),
    }


def case_conclusions(model, case):
    """Read constant conclusions from evidence, without evaluating any guard."""
    by_id = {rule["id"]: rule for rule in model["rules"]}
    values = {output: {} for output in model["outputs"]}
    for rule_id in case["effective"]:
        conclusion = by_id[rule_id]["then"]
        value = conclusion["value"]
        values[conclusion["output"]][canonical_json(value)] = value
    return {output: tuple(found[key] for key in sorted(found)) for output, found in values.items()}


def find_case(certificate, context):
    return next(case for case in certificate["cases"] if context_tuple(case) == context)


def find_query(certificate, output, kind):
    return next(item for item in certificate["queries"] if item["output"] == output and item["kind"] == kind)


class Club20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {}
        cls.certificates = {}
        cls.verifications = {}
        for version in ("broken", "fixed"):
            model = load_json(PACK / f"{version}.json")
            certificate = analyze(model)
            cls.models[version] = model
            cls.certificates[version] = certificate
            cls.verifications[version] = verify(model, certificate)

    def test_exactly_twenty_rules_and_explicit_scope(self):
        for version, model in self.models.items():
            with self.subTest(version=version):
                validate_model(model)
                self.assertEqual(model["profile"], "finite-decisions/1")
                self.assertEqual(model["origin_kind"], "authored_core")
                self.assertEqual(model["facts"], [])
                self.assertEqual(model["constraints"], [])
                self.assertEqual(model["inputs"]["age"], {"kind": "int", "min": 0, "max": 25})
                self.assertEqual(set(model["inputs"]), set(INPUT_ORDER))
                self.assertEqual([rule["id"] for rule in model["rules"]], [f"R{i:02}" for i in range(1, 21)])
                for index, rule in enumerate(model["rules"], 1):
                    self.assertTrue(rule["source"].startswith(f"第{index}条　"))
                required = {name for name, declaration in model["outputs"].items() if declaration["required"]}
                self.assertEqual(required, {"eligible", "fee_yen", "loan_limit", "deposit_yen", "handbook"})

    def test_all_416_contexts_and_every_output_match_independent_gold(self):
        expected_contexts = list(product(range(26), (False, True), (False, True), (False, True), (False, True)))
        for version, certificate in self.certificates.items():
            with self.subTest(version=version):
                self.assertEqual(certificate["total_contexts"], 416)
                self.assertEqual(certificate["admitted_contexts"], 416)
                self.assertEqual([context_tuple(case) for case in certificate["cases"]], expected_contexts)
                self.assertTrue(all(case["admitted"] for case in certificate["cases"]))
                self.assertEqual(self.verifications[version]["status"], "VERIFIED")
            for case in certificate["cases"]:
                with self.subTest(version=version, context=context_tuple(case)):
                    self.assertEqual(case_conclusions(self.models[version], case), table_gold(version, context_tuple(case)))

    def test_manual_counts_first_witnesses_and_distinct_problem_contexts(self):
        expected_queries = [
            ("badge", "conflict"),
            ("deposit_yen", "conflict"), ("deposit_yen", "gap"),
            ("eligible", "conflict"), ("eligible", "gap"),
            ("fee_yen", "conflict"), ("fee_yen", "gap"),
            ("handbook", "conflict"), ("handbook", "gap"),
            ("loan_limit", "conflict"), ("loan_limit", "gap"),
        ]
        expected_counts = {("eligible", "conflict"): 32, ("fee_yen", "gap"): 32, ("loan_limit", "conflict"): 4}
        for version, certificate in self.certificates.items():
            self.assertEqual([(item["output"], item["kind"]) for item in certificate["queries"]], expected_queries)
            for item in certificate["queries"]:
                with self.subTest(version=version, output=item["output"], kind=item["kind"]):
                    count = expected_counts.get((item["output"], item["kind"]), 0) if version == "broken" else 0
                    self.assertEqual(item["count"], count)
                    if count == 0:
                        self.assertIsNone(item["witness"])

            affected = set()
            for case in certificate["cases"]:
                values = case_conclusions(self.models[version], case)
                if any(len(conclusions) > 1 or (not conclusions and self.models[version]["outputs"][name]["required"])
                       for name, conclusions in values.items()):
                    affected.add(case["index"])
            self.assertEqual(len(affected), 36 if version == "broken" else 0)

        broken = self.certificates["broken"]
        common_input = dict(zip(INPUT_ORDER, (18, False, False, False, False)))
        self.assertEqual(find_query(broken, "eligible", "conflict")["witness"], {
            "case_index": 288, "input": common_input, "rule_ids": ["R01", "R02"], "values": [False, True],
        })
        self.assertEqual(find_query(broken, "fee_yen", "gap")["witness"], {
            "case_index": 288, "input": common_input, "rule_ids": [], "values": [],
        })
        self.assertEqual(find_query(broken, "loan_limit", "conflict")["witness"], {
            "case_index": 404, "input": dict(zip(INPUT_ORDER, (25, False, True, False, False))),
            "rule_ids": ["R10", "R13"], "values": [1, 2],
        })

    def test_concrete_readme_examples_are_literal_gold(self):
        # These literal rows keep the prose examples independent even of table_gold.
        names = ("eligible", "fee_yen", "loan_limit", "deposit_yen", "handbook", "badge")
        rows = [
            ("broken", (18, False, False, False, False), ((False, True), (), (1,), (1000,), ("paper",), ())),
            ("fixed", (18, False, False, False, False), ((True,), (1000,), (1,), (1000,), ("paper",), ())),
            ("broken", (19, False, True, True, True), ((False, True), (), (3,), (0,), ("digital",), (True,))),
            ("fixed", (19, False, True, True, True), ((True,), (800,), (3,), (0,), ("digital",), (True,))),
            ("broken", (25, False, True, False, False), ((True,), (1000,), (1, 2), (0,), ("paper",), (True,))),
            ("fixed", (25, False, True, False, False), ((True,), (1000,), (2,), (0,), ("paper",), (True,))),
        ]
        shared = [
            ((20, False, False, True, True), ((True,), (800,), (3,), (500,), ("digital",), (True,))),
            ((20, True, False, True, True), ((True,), (1000,), (3,), (1000,), ("digital",), (True,))),
            ((15, False, False, True, True), ((False,), (500,), (0,), (500,), ("digital",), ())),
            ((15, True, False, True, True), ((False,), (500,), (3,), (1000,), ("digital",), ())),
            ((16, False, False, False, False), ((False,), (500,), (1,), (1000,), ("paper",), ())),
        ]
        rows += [(version, context, values) for version in ("broken", "fixed") for context, values in shared]
        for version, context, expected in rows:
            with self.subTest(version=version, context=context):
                case = find_case(self.certificates[version], context)
                self.assertEqual(case_conclusions(self.models[version], case), dict(zip(names, expected)))

    def test_exception_to_exception_revives_fee_and_deposit_baselines(self):
        for version, certificate in self.certificates.items():
            with self.subTest(version=version):
                normal = find_case(certificate, (20, False, False, True, True))
                event = find_case(certificate, (20, True, False, True, True))
                self.assertTrue({"R05", "R16"}.issubset(normal["effective"]))
                self.assertTrue({"R04", "R14"}.isdisjoint(normal["effective"]))
                self.assertTrue({"R04", "R06", "R14", "R17"}.issubset(event["effective"]))
                self.assertTrue({"R05", "R16"}.issubset(event["enabled"]))
                self.assertTrue({"R05", "R16"}.isdisjoint(event["effective"]))
                self.assertEqual(case_conclusions(self.models[version], event)["fee_yen"], (1000,))
                self.assertEqual(case_conclusions(self.models[version], event)["deposit_yen"], (1000,))

    def test_lending_exception_restores_rule_only_when_training_condition_holds(self):
        for version, certificate in self.certificates.items():
            with self.subTest(version=version):
                normal = find_case(certificate, (15, False, False, True, True))
                event = find_case(certificate, (15, True, False, True, True))
                untrained = find_case(certificate, (15, True, False, True, False))
                self.assertIn("R11", normal["effective"])
                self.assertNotIn("R09", normal["effective"])
                self.assertTrue({"R09", "R12"}.issubset(event["effective"]))
                self.assertNotIn("R11", event["effective"])
                self.assertNotIn("R12", untrained["enabled"])
                self.assertIn("R11", untrained["effective"])
                self.assertEqual(case_conclusions(self.models[version], untrained)["loan_limit"], (0,))

    def test_same_value_badge_rules_and_optional_absence_are_not_findings(self):
        for version, certificate in self.certificates.items():
            with self.subTest(version=version):
                both = find_case(certificate, (19, False, True, True, True))
                self.assertTrue({"R07", "R08"}.issubset(both["effective"]))
                self.assertEqual(case_conclusions(self.models[version], both)["badge"], (True,))
                absent = find_case(certificate, (15, False, False, False, False))
                self.assertEqual(case_conclusions(self.models[version], absent)["badge"], ())
                self.assertEqual(find_query(certificate, "badge", "conflict")["count"], 0)
                self.assertFalse(any(item["output"] == "badge" and item["kind"] == "gap" for item in certificate["queries"]))

    def test_out_of_scope_exception_never_fires_but_is_not_globally_dead(self):
        for version, certificate in self.certificates.items():
            with self.subTest(version=version):
                self.assertTrue(all("R20" not in case["enabled"] for case in certificate["cases"]))
                self.assertTrue(all("R20" not in case["effective"] for case in certificate["cases"]))
        expanded = deepcopy(self.models["fixed"])
        expanded["inputs"]["age"]["max"] = 26
        certificate = analyze(expanded)
        self.assertEqual(verify(expanded, certificate)["status"], "VERIFIED")
        nonstudent = find_case(certificate, (26, False, False, False, False))
        self.assertTrue({"R19", "R20"}.issubset(nonstudent["enabled"]))
        self.assertIn("R20", nonstudent["effective"])
        self.assertNotIn("R19", nonstudent["effective"])
        self.assertEqual(case_conclusions(expanded, nonstudent)["handbook"], ("digital",))

    def test_partial_facts_leave_event_and_student_as_all_four_completions(self):
        for version in ("broken", "fixed"):
            with self.subTest(version=version):
                model = deepcopy(self.models[version])
                model["facts"] = [{"var": "age", "value": 20}, {"var": "member", "value": False},
                                  {"var": "training", "value": True}]
                certificate = analyze(model)
                self.assertEqual(verify(model, certificate)["status"], "VERIFIED")
                self.assertEqual(certificate["total_contexts"], 416)
                self.assertEqual(certificate["admitted_contexts"], 4)
                admitted = [case for case in certificate["cases"] if case["admitted"]]
                self.assertEqual({(case["input"]["event"], case["input"]["student"]) for case in admitted},
                                 {(False, False), (False, True), (True, False), (True, True)})
                for case in admitted:
                    self.assertEqual(case_conclusions(model, case), table_gold(version, context_tuple(case)))

    def test_fix_changes_only_the_five_documented_rules(self):
        broken, fixed = self.models["broken"], self.models["fixed"]
        self.assertEqual({old["id"] for old, new in zip(broken["rules"], fixed["rules"]) if old != new},
                         {"R02", "R04", "R05", "R06", "R13"})
        for field in ("profile", "origin_kind", "inputs", "outputs", "facts", "constraints"):
            self.assertEqual(broken[field], fixed[field])
        self.assertEqual(broken["rules"][12]["overrides"], ["R09"])
        self.assertEqual(fixed["rules"][12]["overrides"], ["R09", "R10"])

    def test_each_of_the_three_repairs_has_the_expected_effect(self):
        broken, fixed = self.models["broken"], self.models["fixed"]
        groups = [({"R02"}, {("fee_yen", "gap"): 32, ("loan_limit", "conflict"): 4}),
                  ({"R04", "R05", "R06"}, {("eligible", "conflict"): 32, ("loan_limit", "conflict"): 4}),
                  ({"R13"}, {("eligible", "conflict"): 32, ("fee_yen", "gap"): 32})]
        fixed_rules = {rule["id"]: rule for rule in fixed["rules"]}
        for repaired_ids, remaining in groups:
            with self.subTest(repairs=repaired_ids):
                model = deepcopy(broken)
                model["rules"] = [deepcopy(fixed_rules[rule["id"]]) if rule["id"] in repaired_ids else rule
                                  for rule in model["rules"]]
                certificate = analyze(model)
                self.assertEqual(verify(model, certificate)["status"], "VERIFIED")
                self.assertEqual({(item["output"], item["kind"]): item["count"] for item in certificate["queries"] if item["count"]},
                                 remaining)

    def test_rule_order_does_not_change_twenty_rule_semantics(self):
        for version in ("broken", "fixed"):
            with self.subTest(version=version):
                model = deepcopy(self.models[version])
                model["rules"].reverse()
                certificate = analyze(model)
                self.assertEqual(verify(model, certificate)["status"], "VERIFIED")
                self.assertEqual(certificate["cases"], self.certificates[version]["cases"])
                self.assertEqual(certificate["queries"], self.certificates[version]["queries"])

    def test_scope_and_certificate_size_have_budget_margin(self):
        for version, certificate in self.certificates.items():
            with self.subTest(version=version):
                size = len(canonical_json(certificate).encode("utf-8"))
                self.assertLess(size, 1024 * 1024)
                self.assertLess(size, MAX_CERTIFICATE_BYTES)
                with self.assertRaises(KernelError) as caught:
                    analyze(self.models[version], max_contexts=415)
                self.assertEqual(caught.exception.status, "LIMIT_REACHED")

    def test_cli_save_and_separate_verify_roundtrip_with_expected_exit_codes(self):
        for version, expected_exit in (("broken", 1), ("fixed", 0)):
            with self.subTest(version=version), TemporaryDirectory() as temp:
                path = Path(temp) / "certificate.json"
                checked = subprocess.run(
                    [sys.executable, "-m", "rulekernel", "check", str(PACK / f"{version}.json"),
                     "--certificate", str(path), "--json"], cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
                )
                self.assertEqual(checked.returncode, expected_exit, checked.stderr)
                self.assertEqual(checked.stderr, "")
                first = json.loads(checked.stdout)
                self.assertEqual(first["status"], "VERIFIED")
                self.assertTrue(path.is_file())
                replayed = subprocess.run(
                    [sys.executable, "-m", "rulekernel", "verify", str(PACK / f"{version}.json"), str(path), "--json"],
                    cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
                )
                self.assertEqual(replayed.returncode, expected_exit, replayed.stderr)
                self.assertEqual(replayed.stderr, "")
                second = json.loads(replayed.stdout)
                self.assertEqual(second["status"], "VERIFIED")
                self.assertEqual(second["certificate_hash"], first["certificate_hash"])
                self.assertEqual(second["queries"], first["queries"])
                self.assertEqual(second["total_contexts"], 416)
                self.assertEqual(second["admitted_contexts"], 416)
                stored = load_json(path, max_bytes=MAX_CERTIFICATE_BYTES)
                self.assertEqual(stored, self.certificates[version])


if __name__ == "__main__":
    unittest.main()
