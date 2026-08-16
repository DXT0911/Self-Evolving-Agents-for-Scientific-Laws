"""Offline contract tests for the v6 atomic-action policy layer.

These tests never import or invoke an LLM, PySR, or Julia.
"""

from __future__ import annotations

import unittest

from playground.hamilton.core.governed_policy import (
    ATOMIC_ACTIONS,
    RESTART_REQUIRING_ACTIONS,
    choose_atomic_action,
    normalize_atomic_action,
)
from playground.hamilton.core.search_control import review_planner_proposal

ENV = dict(
    current_operators=["sin", "cos", "exp"],
    allowed_operators=["sin", "cos", "exp", "tanh"],
    parsimony_bounds=(1e-8, 1.0),
)


def stagnant_complex_snapshot() -> dict:
    return {
        "scientific_score": 0.3,
        "validation_nrmse": 0.1,
        "score_improvement": 0.0,
        "improved": False,
        "complexity_fraction": 0.9,
        "parsimony": 0.001,
        "state_residual_correlation": 0.1,
        "temporal_residual_correlation": 0.1,
        "material_residual_correlation": 0.1,
        "positive_influence_terms": 0,
        "stale_rounds_before": 3,
        "rollback_required": False,
    }


class AtomicActionNormalizationTests(unittest.TestCase):
    def test_continue_warm_maps_to_continue(self) -> None:
        binding = normalize_atomic_action({"action": "continue_warm"}, **ENV)
        self.assertEqual(binding["action"], "continue")
        self.assertEqual(binding["config_patch"], {})
        self.assertFalse(binding["requires_restart"])

    def test_adjust_parsimony_maps_to_warm_modify(self) -> None:
        binding = normalize_atomic_action(
            {"action": "adjust_parsimony", "value": 0.002}, **ENV
        )
        self.assertEqual(binding["action"], "modify")
        self.assertEqual(binding["config_patch"], {"search.parsimony": 0.002})
        self.assertFalse(binding["requires_restart"])

    def test_add_operator_computes_patch_from_current_set(self) -> None:
        binding = normalize_atomic_action(
            {"action": "add_operator", "operator": "tanh"}, **ENV
        )
        self.assertEqual(binding["action"], "restart")
        self.assertEqual(
            binding["config_patch"]["search.unary_operators"],
            ["cos", "exp", "sin", "tanh"],
        )
        self.assertTrue(binding["requires_restart"])

    def test_remove_operator_computes_patch(self) -> None:
        binding = normalize_atomic_action(
            {"action": "remove_operator", "operator": "sin"}, **ENV
        )
        self.assertEqual(
            binding["config_patch"]["search.unary_operators"], ["cos", "exp"]
        )
        self.assertTrue(binding["requires_restart"])

    def test_restart_same_maps_to_empty_restart(self) -> None:
        binding = normalize_atomic_action({"action": "restart_same"}, **ENV)
        self.assertEqual(binding["action"], "restart")
        self.assertEqual(binding["config_patch"], {})
        self.assertTrue(binding["requires_restart"])

    def test_operator_change_is_single_field_and_restart_requiring(self) -> None:
        self.assertEqual(RESTART_REQUIRING_ACTIONS, {"add_operator", "remove_operator", "restart_same"})
        self.assertIn("continue_warm", ATOMIC_ACTIONS)

    def test_add_existing_operator_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "already present"):
            normalize_atomic_action({"action": "add_operator", "operator": "sin"}, **ENV)

    def test_operator_outside_envelope_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "frozen envelope"):
            normalize_atomic_action({"action": "add_operator", "operator": "log"}, **ENV)

    def test_parsimony_outside_bounds_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "frozen bounds"):
            normalize_atomic_action({"action": "adjust_parsimony", "value": 2.0}, **ENV)

    def test_remove_last_operator_is_rejected(self) -> None:
        env = dict(ENV, current_operators=["sin"])
        with self.assertRaisesRegex(ValueError, "without unary operators"):
            normalize_atomic_action({"action": "remove_operator", "operator": "sin"}, **env)


class RuleAtomicInterventionTests(unittest.TestCase):
    def test_rule_never_proposes_operator_changes(self) -> None:
        for _ in range(3):
            intent = choose_atomic_action(stagnant_complex_snapshot())
            self.assertIn(intent["action"], {"continue_warm", "adjust_parsimony"})

    def test_stagnant_complex_rule_adjusts_parsimony(self) -> None:
        intent = choose_atomic_action(stagnant_complex_snapshot())
        self.assertEqual(intent["action"], "adjust_parsimony")


class PlannerAdoptionTests(unittest.TestCase):
    def test_legal_llm_action_is_adopted(self) -> None:
        proposal = {
            "hypothesis": "residual needs tanh",
            "falsification": "tanh absent from best expression next round",
            "atomic_action": {"action": "add_operator", "operator": "tanh"},
        }
        binding = review_planner_proposal(proposal, stagnant_complex_snapshot(), **ENV)
        self.assertTrue(binding["adopted"])
        self.assertEqual(binding["source"], "llm")
        self.assertEqual(binding["action"], "restart")

    def test_illegal_llm_action_falls_back_to_rule(self) -> None:
        proposal = {
            "hypothesis": "x",
            "falsification": "y",
            "atomic_action": {"action": "add_operator", "operator": "log"},
        }
        binding = review_planner_proposal(proposal, stagnant_complex_snapshot(), **ENV)
        self.assertFalse(binding["adopted"])
        self.assertEqual(binding["source"], "rule")
        self.assertIn("reject_reason", binding)

    def test_missing_atomic_action_falls_back_to_rule(self) -> None:
        proposal = {"hypothesis": "x", "falsification": "y"}
        binding = review_planner_proposal(proposal, stagnant_complex_snapshot(), **ENV)
        self.assertFalse(binding["adopted"])
        self.assertEqual(binding["source"], "rule")


if __name__ == "__main__":
    unittest.main()
