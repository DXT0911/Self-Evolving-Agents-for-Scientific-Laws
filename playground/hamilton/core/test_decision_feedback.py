from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from playground.hamilton.core.decision_feedback import (
    evaluate_decision_feedback,
    record_decision_feedback,
)


def previous_round() -> dict:
    return {
        "round": 1,
        "incumbent_score": 0.5,
        "diagnostic_snapshot": {"material_residual_correlation": 0.5},
        "llm_decision": {
            "selected_candidate_id": "decrease_parsimony",
            "selected_action": {"action": "modify"},
        },
    }


class DecisionFeedbackTests(unittest.TestCase):
    def test_next_round_improvement_supports_prior_decision(self) -> None:
        feedback = evaluate_decision_feedback(
            previous_round=previous_round(),
            current_round_num=2,
            current_incumbent_score=0.4,
            current_snapshot={"material_residual_correlation": 0.48},
            min_score_improvement=0.001,
        )
        self.assertEqual(feedback["status"], "supported_by_next_round")
        self.assertAlmostEqual(feedback["score_improvement"], 0.1)

    def test_feedback_updates_prior_hypothesis_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            memory = {
                "schema_version": 1,
                "updated_after_round": 1,
                "strong": {"search_outcomes": [], "residual_observations": [], "incumbent_history": []},
                "weak": {
                    "causal_hypotheses": [{
                        "memory_id": "round:1:next_hypothesis",
                        "status": "untested",
                    }],
                    "near_miss_candidates": [],
                },
                "invalidated": [],
                "routed": {"elite": [], "motifs": [], "failures": [], "diagnostics": []},
            }
            (workspace / ".hamilton_evidence_memory.json").write_text(
                json.dumps(memory), encoding="utf-8"
            )
            record_decision_feedback(
                workspace,
                previous_round=previous_round(),
                current_round_num=2,
                current_incumbent_score=0.6,
                current_snapshot={"material_residual_correlation": 0.55},
                min_score_improvement=0.001,
            )
            updated = json.loads(
                (workspace / ".hamilton_evidence_memory.json").read_text(encoding="utf-8")
            )
            hypothesis = updated["weak"]["causal_hypotheses"][0]
            self.assertEqual(hypothesis["status"], "not_supported_by_next_round")
            self.assertEqual(hypothesis["tested_by_round"], 2)


if __name__ == "__main__":
    unittest.main()
