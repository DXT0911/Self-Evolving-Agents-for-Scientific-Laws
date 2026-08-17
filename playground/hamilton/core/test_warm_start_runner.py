from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "evomaster/skills/run-sr-experiment/scripts"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _module("warm_runner_test", SCRIPTS / "run_experiment.py")
WORKER = _module("warm_worker_test", SCRIPTS / "warm_start_worker.py")
PREPARE = _module("warm_prepare_test", SCRIPTS / "prepare_adaptive_config.py")


def config(round_number: int = 1) -> dict:
    return {
        "schema_version": 1,
        "experiment_id": f"warm-round-{round_number}",
        "data": {
            "train_file": "input/data.csv",
            "allowed_files": ["input/data.csv"],
            "time_column": "t",
            "feature_columns": ["x"],
            "target_column": "y",
            "max_rows": None,
            "search_stride": 1,
            "standardize_search": False,
            "validation_fraction": 0.2,
        },
        "search": {
            "engine": "pysr", "binary_operators": ["+", "*"],
            "unary_operators": ["sin"], "niterations": 10, "max_evals": 100,
            "populations": 1, "population_size": 4, "tournament_selection_n": 2,
            "maxsize": 10, "parsimony": 0.001, "random_state": 7, "top_k": 3,
        },
        "search_session": {
            "mode": "warm_start", "session_id": "unit-session",
            "round": round_number, "final_round": round_number == 3,
            "round_action": "initialize" if round_number == 1 else "continue",
            "compatible_change_fields": ["search.parsimony"],
        },
        "verification": {"short_ode": {"enabled": False}},
        "output": {
            "result_file": f"history/round{round_number}/results/result.json",
            "run_directory": "warm_start_session/pysr",
        },
    }


class WarmStartRunnerTests(unittest.TestCase):
    def test_atomic_request_write_tolerates_concurrent_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "requests" / "same.json"
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda value: RUNNER._atomic_json(target, {"value": value}), range(64)))
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn(payload["value"], range(64))
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_warm_start_ipc_uses_short_hashed_paths(self) -> None:
        workspace = Path("C:/") / ("long-workspace-segment-" * 7)
        state = RUNNER.warm_start_state_dir(workspace, "descriptive-session-name")
        request = state / "q" / "0123456789abcdef.json"
        self.assertEqual(state.parent.name, ".hws")
        self.assertEqual(len(state.name), 12)
        self.assertLess(len(str(request)), 260)

    def test_session_validation_and_transition(self) -> None:
        first = config(1)
        second = config(2)
        session = RUNNER.warm_start_session(first)
        self.assertEqual(session["round_action"], "initialize")
        self.assertEqual(
            WORKER._validate_transition(first, second, session["compatible_change_fields"]),
            [],
        )

    def test_transition_allows_parsimony_but_rejects_maxsize_and_seed_change(self) -> None:
        first = config(1)
        adjusted = config(2)
        adjusted["search"]["parsimony"] = 0.002
        self.assertEqual(
            WORKER._validate_transition(first, adjusted, ["search.parsimony"]),
            ["search.parsimony"],
        )
        changed_maxsize = config(2)
        changed_maxsize["search"]["maxsize"] = 12
        with self.assertRaisesRegex(ValueError, "incompatible fields"):
            WORKER._validate_transition(first, changed_maxsize, ["search.parsimony"])
        changed_seed = config(2)
        changed_seed["search"]["random_state"] = 8
        with self.assertRaisesRegex(ValueError, "random_state"):
            WORKER._validate_transition(first, changed_seed, [])

    def test_restart_transition_ignores_compatible_change_fields_switch(self) -> None:
        first = config(1)
        restart = config(2)
        restart["search"]["unary_operators"] = ["sin", "cos"]
        restart["search_session"]["round_action"] = "restart"
        restart["search_session"]["compatible_change_fields"] = ["search.unary_operators"]
        # The compatible_change_fields directive flips on a restart round; only the
        # operator change itself should be reported, not the directive switch.
        self.assertEqual(
            WORKER._validate_transition(first, restart, ["search.unary_operators"]),
            ["search.unary_operators"],
        )

    def test_noop_materialization_retains_seed_and_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            baseline = config(1)
            result = {"status": "completed", "experiment_id": baseline["experiment_id"], "config": baseline}
            result_path = workspace / "history/round1/results/result.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text(json.dumps(result), encoding="utf-8")
            (workspace / ".hamilton_search_state.json").write_text(json.dumps({
                "next_round": {"baseline_result_file": "history/round1/results/result.json"}
            }), encoding="utf-8")
            (workspace / ".hamilton_seed_plan.json").write_text(json.dumps({
                "round_seeds": [7, 8, 9]
            }), encoding="utf-8")
            (workspace / "plan.md").write_text(
                "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
                + json.dumps({"next_strategy": {
                    "action": "continue", "config_field": None, "config_patch": {}
                }})
                + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->\n",
                encoding="utf-8",
            )
            output, summary = PREPARE.materialize(workspace, 2)
            materialized = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["action"], "continue")
            self.assertEqual(materialized["search"]["random_state"], 7)
            self.assertEqual(materialized["output"]["run_directory"], "warm_start_session/pysr")
            self.assertEqual(materialized["search_session"]["round_action"], "continue")

    def test_restart_materialization_marks_cold_restart_and_single_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "history" / "round1" / "results").mkdir(parents=True)
            baseline = config(1)
            (workspace / "history" / "round1" / "results" / "result.json").write_text(
                json.dumps({"status": "completed", "experiment_id": "unit__round1", "config": baseline}),
                encoding="utf-8",
            )
            (workspace / ".hamilton_search_state.json").write_text(json.dumps({
                "next_round": {"baseline_result_file": "history/round1/results/result.json"}
            }), encoding="utf-8")
            (workspace / ".hamilton_seed_plan.json").write_text(json.dumps({
                "round_seeds": [7, 7, 7]
            }), encoding="utf-8")
            (workspace / "plan.md").write_text(
                "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
                + json.dumps({"next_strategy": {
                    "action": "restart",
                    "config_field": "search.maxsize",
                    "config_patch": {"search.maxsize": 12},
                }})
                + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->\n",
                encoding="utf-8",
            )
            output, summary = PREPARE.materialize(workspace, 2)
            materialized = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["action"], "restart")
            self.assertEqual(materialized["search"]["maxsize"], 12)
            self.assertEqual(materialized["search_session"]["round_action"], "restart")
            self.assertEqual(
                materialized["search_session"]["compatible_change_fields"],
                ["search.maxsize"],
            )


if __name__ == "__main__":
    unittest.main()
