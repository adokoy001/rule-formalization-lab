"""Semantic, boundary, and limit tests for finite-procedure-time/1."""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from procedurekernel import checker, engine
from procedurekernel.checker import verify
from procedurekernel.model import INT_MAX, KernelError, digest, validate_model


def at(tick, phase=0):
    return {"tick": tick, "phase": phase}


def observed(slot, tick, phase=0):
    return {"slot": slot, "at": None if tick is None else at(tick, phase)}


def deadline(identifier="O", anchor="start", targets=None, maximum=10, inclusive=True):
    return {
        "id": identifier,
        "source": "架空の期限規則",
        "kind": "deadline",
        "anchor": anchor,
        "targets": ["finish"] if targets is None else targets,
        "min_offset": 0,
        "max_offset": maximum,
        "inclusive": inclusive,
    }


def base_model(*, contexts=None, norms=None, constraints=None, slots=None):
    if slots is None:
        slots = [
            {"id": "start", "actor": "person", "kind": "start"},
            {"id": "finish", "actor": "office", "kind": "finish"},
        ]
    if contexts is None:
        contexts = [{
            "id": "c",
            "observation_end": at(11),
            "observed": [observed("start", 0), observed("finish", 10)],
            "future": [],
        }]
    return {
        "profile": "finite-procedure-time/1",
        "origin_kind": "authored_procedure_core",
        "title": "架空の手続",
        "time_unit": "tick",
        "observation_mode": "closed_prefix",
        "slots": slots,
        "background_constraints": [] if constraints is None else constraints,
        "norms": [deadline()] if norms is None else norms,
        "contexts": contexts,
    }


def case(certificate, identifier):
    return next(row for row in certificate["cases"] if row["context_id"] == identifier)


def norm_state(row, identifier="O"):
    return next(item for item in row["observed_evaluation"]["rules"] if item["norm_id"] == identifier)


class ProcedureKernelTests(unittest.TestCase):
    def assert_status(self, status, function, *args, **kwargs):
        with self.assertRaises(KernelError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)

    def checked(self, model):
        certificate = engine.analyze(model)
        result = verify(model, certificate)
        self.assertEqual(result["status"], "VERIFIED")
        return certificate

    def test_inclusive_observation_cut_before_equal_and_after_due(self):
        contexts = []
        for identifier, tick, phase in (
            ("before", 9, 0), ("equal", 10, 0), ("after", 10, 1)
        ):
            contexts.append({
                "id": identifier,
                "observation_end": at(tick, phase),
                "observed": [observed("start", 0)],
                "future": [],
            })
        certificate = self.checked(base_model(contexts=contexts))
        self.assertEqual(norm_state(case(certificate, "before"))["status"], "pending")
        self.assertEqual(norm_state(case(certificate, "equal"))["status"], "pending")
        self.assertEqual(norm_state(case(certificate, "after"))["status"], "violated_missing")
        self.assertEqual(case(certificate, "before")["observed_outcome"], "pending")
        self.assertEqual(case(certificate, "equal")["observed_outcome"], "pending")
        self.assertEqual(case(certificate, "after")["observed_outcome"], "violated")

    def test_event_exactly_at_due_is_observed_only_after_cut_and_satisfies(self):
        model = base_model(contexts=[{
            "id": "at_due",
            "observation_end": at(10, 1),
            "observed": [observed("start", 0), observed("finish", 10)],
            "future": [],
        }])
        row = case(self.checked(model), "at_due")
        self.assertEqual(norm_state(row)["status"], "satisfied")
        self.assertEqual(row["observed_outcome"], "fulfilled")

    def test_observed_and_future_coordinates_follow_exclusive_cut(self):
        valid = base_model(contexts=[{
            "id": "cut",
            "observation_end": at(10),
            "observed": [observed("start", 0)],
            "future": [{"slot": "finish", "at": [at(10)]}],
        }])
        self.checked(valid)
        changed = deepcopy(valid)
        changed["contexts"][0]["observed"].append(observed("finish", 10))
        changed["contexts"][0]["future"] = []
        self.assert_status("MODEL_INVALID", validate_model, changed)
        changed = deepcopy(valid)
        changed["contexts"][0]["future"][0]["at"] = [at(9, 1)]
        self.assert_status("MODEL_INVALID", validate_model, changed)

    def test_any_of_deadline_accepts_either_alternative(self):
        slots = [
            {"id": "start", "actor": "police", "kind": "start"},
            {"id": "request", "actor": "prosecutor", "kind": "request"},
            {"id": "prosecute", "actor": "prosecutor", "kind": "prosecute"},
        ]
        norm = deadline(targets=["request", "prosecute"], maximum=2)
        contexts = [
            {"id": "request", "observation_end": at(3), "observed": [observed("start", 0), observed("request", 2)], "future": []},
            {"id": "prosecute", "observation_end": at(3), "observed": [observed("start", 0), observed("prosecute", 2)], "future": []},
            {"id": "neither", "observation_end": at(2, 1), "observed": [observed("start", 0)], "future": []},
        ]
        cert = self.checked(base_model(slots=slots, norms=[norm], contexts=contexts))
        self.assertEqual(norm_state(case(cert, "request"))["selected_target"], "request")
        self.assertEqual(norm_state(case(cert, "prosecute"))["selected_target"], "prosecute")
        self.assertEqual(norm_state(case(cert, "neither"))["status"], "violated_missing")

    def test_any_of_keeps_missing_alternative_pending_until_cut_passes_due(self):
        slots = [
            {"id": "start", "actor": "police", "kind": "start"},
            {"id": "request", "actor": "prosecutor", "kind": "request"},
            {"id": "prosecute", "actor": "prosecutor", "kind": "prosecute"},
        ]
        alternative = deadline(targets=["request", "prosecute"], maximum=2)
        alternative["min_offset"] = 1
        model = base_model(
            slots=slots,
            norms=[alternative],
            contexts=[{
                "id": "alternative_open", "observation_end": at(1),
                "observed": [observed("start", 0), observed("request", 0, 1)],
                "future": [],
            }],
        )
        self.assertEqual(
            norm_state(case(self.checked(model), "alternative_open"))["status"],
            "pending",
        )

    def test_same_coordinate_is_simultaneous_and_phase_creates_order(self):
        strict = {"id": "B", "kind": "precedence", "before": "start", "after": "finish", "relation": "strict_before"}
        nonstrict = {**strict, "relation": "not_after"}
        simultaneous = [{"id": "c", "observation_end": at(1), "observed": [observed("start", 0), observed("finish", 0)], "future": []}]
        strict_case = case(self.checked(base_model(contexts=simultaneous, constraints=[strict])), "c")
        loose_case = case(self.checked(base_model(contexts=simultaneous, constraints=[nonstrict])), "c")
        self.assertEqual(strict_case["classification"], "background_trace_impossible")
        self.assertEqual(loose_case["classification"], "compliance_feasible")
        ordered = [{"id": "c", "observation_end": at(1), "observed": [observed("start", 0, 0), observed("finish", 0, 1)], "future": []}]
        self.assertEqual(case(self.checked(base_model(contexts=ordered, constraints=[strict])), "c")["classification"], "compliance_feasible")

    def test_precedence_also_requires_the_prior_transition(self):
        constraint = {"id": "B", "kind": "precedence", "before": "start", "after": "finish", "relation": "not_after"}
        model = base_model(
            constraints=[constraint],
            contexts=[{
                "id": "missing_prior", "observation_end": at(2),
                "observed": [observed("finish", 1)], "future": [],
            }],
        )
        row = case(self.checked(model), "missing_prior")
        self.assertEqual(row["classification"], "background_trace_impossible")
        self.assertEqual(row["observed_outcome"], "background_violated")

    def test_partial_prohibition_leaves_a_later_compliance_candidate(self):
        prohibition = {
            "id": "F_EARLY", "source": "早期は禁止", "kind": "prohibition_window",
            "anchor": "start", "targets": ["finish"], "start_offset": 0,
            "end_offset": 5, "inclusive_start": True, "inclusive_end": True,
        }
        model = base_model(
            norms=[deadline(maximum=10), prohibition],
            contexts=[{
                "id": "window", "observation_end": at(1),
                "observed": [observed("start", 0)],
                "future": [{"slot": "finish", "at": [at(5), at(6)]}],
            }],
        )
        row = case(self.checked(model), "window")
        self.assertEqual(row["candidate_trace_count"], 3)
        self.assertEqual(row["classification"], "compliance_feasible")
        by_choice = {str(trace["choice"]["finish"]): trace for trace in row["traces"]}
        self.assertTrue(by_choice[str(at(5))]["definitely_violated"])
        self.assertTrue(by_choice[str(at(6))]["fully_satisfied"])

    def test_full_prohibition_is_infeasible_while_observed_prefix_is_pending(self):
        prohibition = {
            "id": "F_FULL", "source": "全期間禁止", "kind": "prohibition_window",
            "anchor": "start", "targets": ["finish"], "start_offset": 0,
            "end_offset": 3, "inclusive_start": True, "inclusive_end": True,
        }
        model = base_model(
            norms=[deadline(maximum=3), prohibition],
            contexts=[{
                "id": "full_window", "observation_end": at(1),
                "observed": [observed("start", 0)],
                "future": [{"slot": "finish", "at": [at(2), at(3)]}],
            }],
        )
        row = case(self.checked(model), "full_window")
        self.assertEqual(row["classification"], "normatively_infeasible")
        self.assertEqual(row["observed_outcome"], "pending")
        self.assertTrue(all(trace["definitely_violated"] for trace in row["traces"]))

    def test_background_impossibility_normative_infeasibility_and_success_are_not_merged(self):
        strict = {"id": "B", "kind": "precedence", "before": "start", "after": "finish", "relation": "strict_before"}
        contexts = [
            {"id": "background", "observation_end": at(2), "observed": [observed("start", 1), observed("finish", 0)], "future": []},
            {"id": "normative", "observation_end": at(12), "observed": [observed("start", 0), observed("finish", 11)], "future": []},
            {"id": "success", "observation_end": at(11), "observed": [observed("start", 0), observed("finish", 10)], "future": []},
        ]
        cert = self.checked(base_model(contexts=contexts, constraints=[strict]))
        self.assertEqual(case(cert, "background")["classification"], "background_trace_impossible")
        self.assertEqual(case(cert, "normative")["classification"], "normatively_infeasible")
        self.assertEqual(case(cert, "success")["classification"], "compliance_feasible")

    def test_missing_and_unknown_anchor_remain_unresolved(self):
        contexts = [
            {"id": "missing", "observation_end": at(1), "observed": [], "future": []},
            {"id": "unknown", "observation_end": at(1), "observed": [observed("start", None)], "future": []},
        ]
        cert = self.checked(base_model(contexts=contexts))
        self.assertEqual(norm_state(case(cert, "missing"))["status"], "anchor_missing")
        self.assertEqual(case(cert, "missing")["observed_outcome"], "unresolved_anchor")
        self.assertEqual(norm_state(case(cert, "unknown"))["status"], "anchor_time_unresolved")
        self.assertEqual(case(cert, "unknown")["observed_outcome"], "unresolved_time")

    def test_certificate_json_scalar_types_are_rejected_with_self_anchor(self):
        model = base_model()
        certificate = engine.analyze(model)
        changed = deepcopy(certificate)
        changed["diagnostics"]["has_findings"] = int(
            changed["diagnostics"]["has_findings"]
        )
        self.assertEqual(changed, certificate)  # Python conflates False and 0.
        self.assert_status("CERTIFICATE_INVALID", verify, model, changed)
        self.assert_status(
            "CERTIFICATE_INVALID",
            verify,
            model,
            changed,
            expected_certificate_sha256=digest(changed),
        )

    def test_no_implicit_override_or_unknown_norm_kind(self):
        changed = base_model()
        changed["norms"][0]["priority"] = 10
        self.assert_status("MODEL_INVALID", validate_model, changed)
        changed = base_model()
        changed["norms"][0]["kind"] = "override"
        self.assert_status("UNSUPPORTED", validate_model, changed)
        changed = base_model()
        changed["norms"] = [{
            "id": "F", "source": "禁止", "kind": "prohibition_window",
            "anchor": "start", "targets": ["finish", "start"],
            "start_offset": 0, "end_offset": 1,
            "inclusive_start": True, "inclusive_end": True,
        }]
        self.assert_status("UNSUPPORTED", validate_model, changed)

    def test_slot_and_pre_enumeration_limits_fail_closed(self):
        slots = [
            {"id": f"s{i}", "actor": "actor", "kind": f"kind{i}"}
            for i in range(9)
        ]
        self.assert_status("LIMIT_REACHED", validate_model, base_model(slots=slots))

        slots = [{"id": "start", "actor": "a", "kind": "start"}] + [
            {"id": f"s{i}", "actor": "a", "kind": f"kind{i}"} for i in range(1, 8)
        ]
        context_value = {
            "id": "large", "observation_end": at(1),
            "observed": [observed("start", 0)],
            "future": [
                {"slot": f"s{i}", "at": [at(2), at(3)]} for i in range(1, 8)
            ],
        }
        model = base_model(
            slots=slots,
            norms=[deadline(anchor="start", targets=["s1"])],
            contexts=[context_value],
        )
        self.assert_status("LIMIT_REACHED", engine.analyze, model, max_traces_per_context=1000)

    def test_repeated_kind_and_tick_overflow_are_rejected(self):
        repeated = base_model()
        repeated["slots"][1]["kind"] = "start"
        self.assert_status("UNSUPPORTED", validate_model, repeated)
        overflow = base_model(contexts=[{
            "id": "overflow", "observation_end": at(INT_MAX),
            "observed": [observed("start", INT_MAX - 1)], "future": [],
        }])
        overflow["norms"][0]["max_offset"] = 2
        self.assert_status("MODEL_INVALID", validate_model, overflow)

    def test_model_certificate_and_pair_limits_are_preflighted(self):
        huge = base_model()
        huge["norms"] = [
            {**deadline(identifier=f"O{i}"), "source": "x" * 8192}
            for i in range(256)
        ]
        self.assert_status("LIMIT_REACHED", validate_model, huge)

        contexts = [
            {"id": f"c{i}", "observation_end": at(1), "observed": [observed("start", 0)],
             "future": [{"slot": "finish", "at": [at(2)]}]}
            for i in range(2)
        ]
        paired = base_model(contexts=contexts)
        self.assert_status("LIMIT_REACHED", engine.analyze, paired, max_pairs=3)

        with patch.object(engine, "MAX_CERTIFICATE_BYTES", 1):
            self.assert_status("LIMIT_REACHED", engine.analyze, base_model())

    def test_checker_is_independent_of_producer_module(self):
        tree = ast.parse(Path(checker.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertNotIn("procedurekernel.engine", {item.name for item in node.names})
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, {"engine", "procedurekernel.engine"})
        model = base_model()
        certificate = engine.analyze(model)
        original = engine.analyze
        try:
            engine.analyze = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())
            self.assertEqual(verify(model, certificate)["status"], "VERIFIED")
        finally:
            engine.analyze = original


if __name__ == "__main__":
    unittest.main()
