from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from playground.hamilton.core.governed_policy import (
    PolicyThresholds,
    build_llm_action_candidates,
    choose_action,
    diagnostic_snapshot,
    fallback_planner_decision,
    infer_process_state,
    route_memory,
    validate_planner_decision,
    validate_planner_proposal,
)
from playground.hamilton.core.offline_policy_replay import replay_results
from playground.hamilton.core.structural_diagnostics import additive_term_influence


def result_payload(
    score: float,
    *,
    complexity: int = 5,
    maxsize: int = 20,
    state_correlation: float = 0.1,
    temporal_correlation: float = 0.1,
) -> dict:
    return {
        "status": "completed",
        "config": {"search": {"maxsize": maxsize, "parsimony": 0.01}},
        "selected": {
            "scientific_score": score,
            "complexity": complexity,
            "simplified_equation": "x",
        },
        "candidates": [{
            "simplified_equation": "x",
            "ranking": {"validation_nrmse": 0.2},
        }],
        "verification": {
            "residual_diagnostics": {
                "validation": {
                    "state_dependence": {
                        "strongest_absolute_correlation": {
                            "signal": "x",
                            "value": state_correlation,
                        }
                    },
                    "temporal_structure": {
                        "strongest_reported_autocorrelation": {
                            "lag": 1,
                            "value": temporal_correlation,
                        }
                    },
                }
            }
        },
    }


class GovernedPolicyTests(unittest.TestCase):
    def test_planner_is_restricted_to_advisory_frozen_envelope(self) -> None:
        proposal = validate_planner_proposal(
            {
                "hypothesis": "a periodic residual may require cosine",
                "candidate_variables": ["x"],
                "candidate_operators": ["cos"],
                "requested_action": "branch",
                "falsification": "validation residual correlation does not fall",
            },
            allowed_variables=["x", "v"],
            allowed_operators=["sin", "cos"],
        )
        self.assertEqual(proposal["authority"], "advisory_only")
        with self.assertRaisesRegex(ValueError, "unauthorized fields"):
            validate_planner_proposal(
                {
                    "hypothesis": "x",
                    "falsification": "none",
                    "config_patch": {"search.maxsize": 99},
                },
                allowed_variables=["x"],
                allowed_operators=["+"],
            )

    def test_improving_search_continues(self) -> None:
        snapshot = diagnostic_snapshot(
            result_payload(0.7),
            incumbent_score_before=0.8,
            stale_rounds_before=2,
        )
        self.assertEqual(choose_action(snapshot)["action"], "continue")

    def test_llm_can_make_a_binding_choice_only_inside_controller_envelope(self) -> None:
        snapshot = diagnostic_snapshot(
            result_payload(0.8, complexity=5, temporal_correlation=0.7),
            incumbent_score_before=0.8,
            stale_rounds_before=2,
        )
        envelope = build_llm_action_candidates(snapshot, allow_stop=True)
        decision = validate_planner_decision(
            {
                "hypothesis": "the residual may need a less sparse expression",
                "candidate_variables": ["x"],
                "candidate_operators": ["cos"],
                "selected_candidate_id": "decrease_parsimony",
                "rationale": "the selected equation is simple and residual structure remains",
                "expected_effect": "validation residual correlation should decrease",
                "falsification": "score and residual diagnostics do not improve",
            },
            action_candidates=envelope["candidates"],
            allowed_variables=["x"],
            allowed_operators=["sin", "cos"],
        )
        self.assertEqual(decision["planner_status"], "accepted")
        self.assertEqual(decision["selected_action"]["action"], "modify")
        self.assertEqual(
            decision["selected_action"]["authority"],
            "llm_selected_controller_validated",
        )

    def test_llm_cannot_invent_candidate_or_config_patch(self) -> None:
        envelope = build_llm_action_candidates(
            {"parsimony": 0.01, "score_improvement": 0.0}
        )
        with self.assertRaisesRegex(ValueError, "unknown candidate"):
            validate_planner_decision(
                {
                    "hypothesis": "try a much larger search",
                    "candidate_variables": [],
                    "candidate_operators": [],
                    "selected_candidate_id": "set_maxsize_999",
                    "rationale": "more search may help",
                    "expected_effect": "lower score",
                    "falsification": "score does not improve",
                },
                action_candidates=envelope["candidates"],
                allowed_variables=["x"],
                allowed_operators=["+"],
            )

    def test_planner_failure_uses_auditable_fallback(self) -> None:
        envelope = build_llm_action_candidates(
            {"parsimony": 0.01, "score_improvement": 0.1}
        )
        decision = fallback_planner_decision(
            action_candidates=envelope["candidates"],
            fallback_candidate_id=envelope["fallback_candidate_id"],
            reason="provider timeout",
        )
        self.assertEqual(decision["planner_status"], "fallback")
        self.assertEqual(decision["selected_action"]["authority"], "deterministic_fallback")

    def test_stagnant_complex_search_increases_parsimony(self) -> None:
        snapshot = diagnostic_snapshot(
            result_payload(0.8, complexity=18),
            incumbent_score_before=0.8,
            stale_rounds_before=1,
        )
        decision = choose_action(snapshot)
        self.assertEqual(decision["action"], "modify")
        self.assertEqual(decision["config_field"], "search.parsimony")
        self.assertAlmostEqual(decision["config_patch"]["search.parsimony"], 0.02)

    def test_structured_residual_without_safe_change_requests_branch(self) -> None:
        snapshot = diagnostic_snapshot(
            result_payload(0.8, complexity=10, temporal_correlation=0.8),
            incumbent_score_before=0.8,
            stale_rounds_before=1,
        )
        decision = choose_action(snapshot, warm_compatible_fields=[])
        self.assertEqual(decision["action"], "branch")
        self.assertTrue(decision["requires_restart"])
        self.assertEqual(infer_process_state(snapshot), "stagnant_structured")

    def test_tiny_validation_error_blocks_correlation_only_intervention(self) -> None:
        snapshot = diagnostic_snapshot(
            result_payload(0.8, complexity=10, temporal_correlation=1.0),
            incumbent_score_before=0.8,
            stale_rounds_before=2,
        )
        snapshot["validation_nrmse"] = 1e-5
        self.assertEqual(
            choose_action(snapshot, warm_compatible_fields=[])["action"],
            "continue",
        )

    def test_rollback_gate_overrides_other_signals(self) -> None:
        snapshot = diagnostic_snapshot(
            result_payload(0.5),
            incumbent_score_before=0.8,
            stale_rounds_before=3,
            rollback_required=True,
        )
        self.assertEqual(choose_action(snapshot)["action"], "rollback")

    def test_memory_router_does_not_expose_every_partition(self) -> None:
        memory = {
            "routed": {
                "elite": [{"id": 1}],
                "motifs": [{"id": 2}],
                "failures": [{"id": 3}],
                "diagnostics": [{"id": 4}],
            }
        }
        view = route_memory(memory, "improving")
        self.assertEqual(set(view["partitions"]), {"elite", "diagnostics"})

    def test_offline_replay_has_explicit_counterfactual_boundary(self) -> None:
        replay = replay_results(
            [("r1.json", result_payload(0.8)), ("r2.json", result_payload(0.9))],
            thresholds=PolicyThresholds(stale_rounds_before_intervention=2),
        )
        self.assertEqual(replay["summary"]["replayed_records"], 2)
        self.assertIn("does not estimate", replay["scientific_boundary"])


class StructuralDiagnosticTests(unittest.TestCase):
    def test_additive_ablation_identifies_the_useful_term(self) -> None:
        x = np.linspace(-2.0, 2.0, 80)
        z = np.linspace(1.0, 3.0, 80)
        y = 3.0 * x + 2.0
        frame = pd.DataFrame({"x": x, "z": z, "y": y})
        diagnostic = additive_term_influence(
            "x + 0*z",
            train=frame.iloc[:60],
            validation=frame.iloc[60:],
            feature_columns=["x", "z"],
            target_column="y",
        )
        self.assertEqual(diagnostic["status"], "completed")
        self.assertEqual(diagnostic["terms"][0]["term"], "x")
        self.assertGreater(diagnostic["terms"][0]["validation_nrmse_delta"], 0)

    def test_large_additive_expression_is_bounded(self) -> None:
        frame = pd.DataFrame({"x": range(20), "y": range(20)})
        diagnostic = additive_term_influence(
            "x + x**2 + x**3",
            train=frame.iloc[:10],
            validation=frame.iloc[10:],
            feature_columns=["x"],
            target_column="y",
            max_terms=2,
        )
        self.assertEqual(diagnostic["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
