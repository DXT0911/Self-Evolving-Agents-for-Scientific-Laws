from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from playground.hamilton.core.compressed_planner import call_llm_decision_planner
from playground.hamilton.core.governed_policy import build_llm_action_candidates


def result_payload() -> dict:
    return {
        "selected": {
            "scientific_score": 0.2,
            "complexity": 4,
            "simplified_equation": "x**2",
        }
    }


class LLMDecisionPlannerTests(unittest.TestCase):
    def inputs(self, workspace: Path) -> dict:
        snapshot = {
            "scientific_score": 0.2,
            "score_improvement": 0.01,
            "parsimony": 0.01,
            "complexity_fraction": 0.2,
            "material_residual_correlation": 0.4,
        }
        return {
            "workspace": workspace,
            "round_num": 1,
            "result": result_payload(),
            "controller_policy": {"snapshot": snapshot},
            "action_envelope": build_llm_action_candidates(snapshot),
            "allowed_variables": ["x"],
            "allowed_operators": ["+", "*"],
        }

    def test_missing_api_key_is_recorded_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw, mock.patch.dict(os.environ, {}, clear=True):
            workspace = Path(raw)
            decision = call_llm_decision_planner(**self.inputs(workspace))
            self.assertEqual(decision["planner_status"], "fallback")
            ledger = json.loads(
                (workspace / ".hamilton_llm_decision_ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ledger["calls"][0]["status"], "fallback")
            self.assertNotIn("api_key", json.dumps(ledger))

    def test_valid_llm_choice_becomes_binding_and_is_idempotent(self) -> None:
        calls = []

        class Completions:
            def create(self, **kwargs):
                calls.append(kwargs)
                content = json.dumps({
                    "hypothesis": "the search should continue before changing sparsity",
                    "candidate_variables": ["x"],
                    "candidate_operators": ["*"],
                    "selected_candidate_id": "continue",
                    "rationale": "the incumbent is still improving",
                    "expected_effect": "another round should reduce the score",
                    "falsification": "the incumbent does not improve",
                })
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(
                        message=types.SimpleNamespace(content=content)
                    )],
                    usage=types.SimpleNamespace(
                        prompt_tokens=100,
                        completion_tokens=40,
                        total_tokens=140,
                    ),
                )

        class Client:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=Completions())

        fake_openai = types.SimpleNamespace(OpenAI=Client)
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            with mock.patch.dict(os.environ, {"HAMILTON_API_KEY": "test-key"}), mock.patch.dict(
                sys.modules, {"openai": fake_openai}
            ):
                first = call_llm_decision_planner(**self.inputs(workspace))
                second = call_llm_decision_planner(**self.inputs(workspace))
        self.assertEqual(first["planner_status"], "accepted")
        self.assertEqual(first["selected_action"]["authority"], "llm_selected_controller_validated")
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
