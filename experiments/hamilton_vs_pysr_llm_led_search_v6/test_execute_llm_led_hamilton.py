from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from experiments.hamilton_vs_pysr_llm_led_search_v6 import execute_llm_led_hamilton as v6
from experiments.hamilton_vs_pysr_llm_led_search_v6 import prepare_workspace
from playground.hamilton.core.governed_policy import validate_planner_decision


def baseline_config() -> dict:
    return {
        "schema_version": 1,
        "experiment_id": "v6-test__round1",
        "data": {
            "train_file": "input/data.csv",
            "allowed_files": ["input/data.csv"],
            "time_column": "t",
            "feature_columns": ["x"],
            "target_column": "y",
            "validation_fraction": 0.2,
        },
        "search": {
            "engine": "pysr",
            "binary_operators": ["+", "*"],
            "unary_operators": ["sin"],
            "max_evals": 100,
            "maxsize": 20,
            "parsimony": 0.01,
            "random_state": 7,
        },
        "search_session": {
            "mode": "warm_start",
            "session_id": "v6-unit-session",
            "round": 1,
            "final_round": False,
            "round_action": "initialize",
            "compatible_change_fields": ["search.parsimony"],
        },
        "verification": {"residual_diagnostics": {"enabled": True}},
        "output": {
            "result_file": "history/round1/results/result.json",
            "run_directory": "session/pysr",
        },
    }


def completed_result(config: dict, round_num: int) -> dict:
    equation = "x" if round_num == 1 else "x**2"
    score = 0.5 if round_num == 1 else 0.4
    return {
        "status": "completed",
        "experiment_id": config["experiment_id"],
        "config": config,
        "selected": {
            "scientific_score": score,
            "complexity": 4,
            "simplified_equation": equation,
        },
        "candidates": [{
            "simplified_equation": equation,
            "ranking": {"validation_nrmse": 0.1},
        }],
        "verification": {
            "residual_diagnostics": {
                "validation": {
                    "state_dependence": {
                        "strongest_absolute_correlation": {"signal": "x", "value": 0.2}
                    },
                    "temporal_structure": {
                        "strongest_reported_autocorrelation": {"lag": 1, "value": 0.1}
                    },
                }
            }
        },
        "engine_telemetry": {
            "warm_start_session": {"round_engine_measured_evaluations": 100}
        },
    }


class LLMExecutorIntegrationTests(unittest.TestCase):
    def test_prepare_workspace_does_not_copy_old_control_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            source.joinpath("input").mkdir(parents=True)
            source.joinpath("input/data.csv").write_text("x,y\n1,1\n", encoding="utf-8")
            source.joinpath("round1_baseline.json").write_text(
                json.dumps(baseline_config()), encoding="utf-8"
            )
            source.joinpath(".hamilton_search_control.json").write_text(
                "{}", encoding="utf-8"
            )
            output = root / "output"
            prepare_workspace.prepare(source, output)
            prepared = json.loads(
                output.joinpath("round1_baseline.json").read_text(encoding="utf-8")
            )
            self.assertTrue(output.joinpath("input/data.csv").is_file())
            self.assertFalse(output.joinpath(".hamilton_search_control.json").exists())
            self.assertTrue(prepared["experiment_id"].startswith("hamilton-v6-"))

    def test_two_round_closed_loop_updates_findings_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = root / "workspace"
            workspace.mkdir()
            baseline = baseline_config()
            (workspace / "round1_baseline.json").write_text(
                json.dumps(baseline), encoding="utf-8"
            )
            config = yaml.safe_load(v6.DEFAULT_CONFIG.read_text(encoding="utf-8"))
            config = copy.deepcopy(config)
            config["experiment"].update({
                "min_rounds": 1,
                "max_rounds": 2,
                "evals_per_round": 100,
                "max_total_evals": 200,
                "early_stop_patience": 99,
            })
            config["experiment"]["search_control"]["dynamic_budget"].update({
                "base_evals": 100,
                "min_evals": 100,
                "max_evals": 100,
                "rounding_quantum": 100,
            })
            config_path = root / "v6-test.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

            run_count = 0

            def fake_run(args, *, cwd, **kwargs):
                nonlocal run_count
                run_count += 1
                config_file = Path(cwd) / args[-1]
                round_config = json.loads(config_file.read_text(encoding="utf-8"))
                round_num = int(round_config["search_session"]["round"])
                result = completed_result(round_config, round_num)
                result_path = Path(cwd) / round_config["output"]["result_file"]
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(json.dumps(result), encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

            def fake_planner(workspace_arg, **kwargs):
                self.assertEqual(Path(workspace_arg), workspace)
                return validate_planner_decision(
                    {
                        "hypothesis": "one more unchanged round should test continued improvement",
                        "candidate_variables": ["x"],
                        "candidate_operators": ["*"],
                        "selected_candidate_id": "continue",
                        "rationale": "the first score is only a baseline",
                        "expected_effect": "the score should decrease",
                        "falsification": "the second score does not decrease",
                    },
                    action_candidates=kwargs["action_envelope"]["candidates"],
                    allowed_variables=kwargs["allowed_variables"],
                    allowed_operators=kwargs["allowed_operators"],
                )

            with mock.patch.object(v6.subprocess, "run", side_effect=fake_run), mock.patch.object(
                v6, "call_llm_decision_planner", side_effect=fake_planner
            ):
                summary = v6.execute(workspace, config_path)

            self.assertEqual(run_count, 2)
            self.assertEqual(summary["completed_rounds"], 2)
            self.assertEqual(summary["incumbent"]["equation"], "x**2")
            self.assertEqual(summary["rounds"][1]["binding_action"]["authority"], "llm_selected_controller_validated")
            self.assertEqual(
                summary["rounds"][0]["llm_feedback"]["status"],
                "supported_by_next_round",
            )
            findings = (workspace / "findings.md").read_text(encoding="utf-8")
            self.assertIn("Round 2", findings)
            self.assertIn("x**2", findings)
            self.assertIn("supported_by_next_round", findings)
            self.assertNotIn("template", findings)


if __name__ == "__main__":
    unittest.main()
