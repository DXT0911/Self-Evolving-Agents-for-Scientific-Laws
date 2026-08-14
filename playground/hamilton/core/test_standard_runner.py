"""Contract tests for the configuration-driven SR experiment runner."""

from __future__ import annotations

import copy
import importlib.util
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import sympy

from playground.hamilton.core.exp import RoundExp
from playground.hamilton.core.promotion_exp import NEXT_ROUND_FIELDS, PromotionExp
from playground.hamilton.core.playground import HamiltonPlayground
from playground.hamilton.core.search_control import (
    initialize_control,
    meaningful_config as search_meaningful_config,
    read_evidence_memory,
    round_directive,
    update_evidence_memory,
    update_state,
)
from playground.hamilton.core.ood_evaluator import (
    OODAccessLedger,
    OODProtocolError,
    canonical_hash,
    evaluate_tier,
    finalize_tier3,
    freeze_candidate_bundle,
    load_frozen_bundle,
    release_summary,
    verify_frozen_sources,
)
from evomaster.agent.tools.builtin.editor import EditorTool, list_local_directory
from evomaster.agent.tools.builtin.literature import LiteratureSearchTool


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = (
    PROJECT_ROOT
    / "evomaster"
    / "skills"
    / "run-sr-experiment"
    / "scripts"
    / "run_experiment.py"
)
SPEC = importlib.util.spec_from_file_location("run_sr_experiment_script", RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RUNNER)


def valid_config() -> dict:
    return {
        "schema_version": 1,
        "experiment_id": "contract-test",
        "data": {
            "train_file": "input/train.csv",
            "allowed_files": ["input/train.csv"],
            "time_column": "t",
            "feature_columns": ["x", "v"],
            "target_column": "a",
            "max_rows": 10,
            "standardize_search": False,
            "validation_fraction": 0.2,
        },
        "search": {
            "engine": "pysr",
            "binary_operators": ["+", "*"],
            "unary_operators": [],
            "niterations": 1,
            "max_evals": 10,
            "populations": 1,
            "population_size": 4,
            "tournament_selection_n": 2,
            "maxsize": 5,
            "parsimony": 0.01,
            "random_state": 42,
            "top_k": 3,
        },
        "verification": {"short_ode": {"enabled": False}},
        "output": {
            "result_file": "results/result.json",
            "run_directory": "results/pysr-run",
        },
    }


class StandardRunnerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        (self.workspace / "input").mkdir()
        pd.DataFrame(
            {
                "t": range(10),
                "x": range(10),
                "v": range(10),
                "a": range(10),
            }
        ).to_csv(self.workspace / "input" / "train.csv", index=False)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_config(self, config: dict) -> Path:
        path = self.workspace / "experiment.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def test_valid_config_and_contiguous_split(self) -> None:
        config, paths = RUNNER.load_and_validate(self.write_config(valid_config()), self.workspace)
        train, validation, split = RUNNER.load_data(config, paths["train"])
        self.assertEqual(len(train), 8)
        self.assertEqual(len(validation), 2)
        self.assertEqual(split["train_time"], [0.0, 7.0])
        self.assertEqual(split["validation_time"], [8.0, 9.0])
        self.assertEqual(split["search_rows"], 8)

    def test_null_max_rows_reads_complete_file_and_stride_spans_discovery_block(self) -> None:
        config = valid_config()
        config["data"]["max_rows"] = None
        config["data"]["search_stride"] = 3
        normalized, paths = RUNNER.load_and_validate(self.write_config(config), self.workspace)
        train, validation, split = RUNNER.load_data(normalized, paths["train"])
        self.assertEqual(len(train), 8)
        self.assertEqual(len(validation), 2)
        self.assertEqual(split["search_rows"], 3)
        self.assertEqual(split["search_stride"], 3)

    def test_rejects_non_boolean_standardize_search(self) -> None:
        config = valid_config()
        config["data"]["standardize_search"] = "yes"
        with self.assertRaisesRegex(RUNNER.ConfigError, "must be boolean"):
            RUNNER.load_and_validate(self.write_config(config), self.workspace)

    def test_standardization_uses_training_block_only(self) -> None:
        config = valid_config()
        config["data"]["standardize_search"] = True
        normalized, paths = RUNNER.load_and_validate(self.write_config(config), self.workspace)
        train, validation, _ = RUNNER.load_data(normalized, paths["train"])
        validation.loc[:, ["x", "v", "a"]] = 1_000_000

        transform = RUNNER.build_search_transform(train, ["x", "v"], "a", True)

        self.assertEqual(transform["fit_source"], "training_block_only")
        self.assertAlmostEqual(transform["feature_mean"]["x"], 3.5)
        self.assertAlmostEqual(transform["target_mean"], 3.5)
        self.assertLess(transform["feature_std"]["x"], 10)

    def test_restores_search_equation_to_original_units(self) -> None:
        x, v = sympy.symbols("x v")
        transform = {
            "enabled": True,
            "feature_mean": {"x": 10.0, "v": 100.0},
            "feature_std": {"x": 2.0, "v": 10.0},
            "target_mean": 5.0,
            "target_std": 4.0,
        }
        restored = RUNNER.restore_original_units(2 * x + v**2, ["x", "v"], transform)
        expected = 5 + 4 * (2 * ((x - 10) / 2) + ((v - 100) / 10) ** 2)
        difference = sympy.lambdify((x, v), restored - expected, modules="math")
        self.assertAlmostEqual(float(difference(13.0, 117.0)), 0.0, places=12)

    def test_standardized_candidate_is_evaluated_in_original_units(self) -> None:
        config = valid_config()
        config["data"]["standardize_search"] = True
        normalized, paths = RUNNER.load_and_validate(self.write_config(config), self.workspace)
        train, validation, _ = RUNNER.load_data(normalized, paths["train"])
        transform = RUNNER.build_search_transform(train, ["x", "v"], "a", True)

        class FakeModel:
            @staticmethod
            def sympy(index: int):
                return sympy.Symbol("x")

        equations = pd.DataFrame(
            [{"equation": "x", "loss": 0.0, "complexity": 1, "score": 1.0}]
        )
        candidate = RUNNER.evaluate_candidates(
            FakeModel(),
            equations,
            normalized,
            train,
            validation,
            transform,
        )[0]
        self.assertEqual(candidate["search_space_equation"], "x")
        self.assertAlmostEqual(candidate["metrics"]["validation"]["mse"], 0.0)
        self.assertNotEqual(candidate["simplified_equation"], candidate["search_space_equation"])

    def test_rejects_training_file_outside_allowlist(self) -> None:
        config = valid_config()
        config["data"]["allowed_files"] = ["input/other.csv"]
        with self.assertRaisesRegex(RUNNER.ConfigError, "must appear exactly"):
            RUNNER.load_and_validate(self.write_config(config), self.workspace)

    def test_rejects_output_path_escape(self) -> None:
        config = valid_config()
        config["output"]["result_file"] = "../escaped.json"
        with self.assertRaisesRegex(RUNNER.ConfigError, "inside workspace"):
            RUNNER.load_and_validate(self.write_config(config), self.workspace)

    def test_rejects_cumulative_evaluation_budget_overrun(self) -> None:
        (self.workspace / ".hamilton_budget.json").write_text(
            json.dumps({"max_total_evals": 15}),
            encoding="utf-8",
        )
        previous = self.workspace / "history" / "round1" / "results"
        previous.mkdir(parents=True)
        (previous / "previous.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "config": {"search": {"max_evals": 7}},
                    "selected": {"scientific_score": 1.0},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RUNNER.ConfigError, "total PySR evaluation budget exceeded"):
            RUNNER.load_and_validate(self.write_config(valid_config()), self.workspace)

    def test_failed_and_replayed_attempts_keep_reserved_evaluation_budget(self) -> None:
        (self.workspace / ".hamilton_budget.json").write_text(
            json.dumps({"max_total_evals": 20}),
            encoding="utf-8",
        )
        config_path = self.write_config(valid_config())
        config, paths = RUNNER.load_and_validate(config_path, self.workspace)

        first = RUNNER.reserve_evaluations(self.workspace, config, paths["result"])
        RUNNER.finish_evaluation_attempt(
            self.workspace,
            first["attempt_id"],
            "failed",
        )
        second = RUNNER.reserve_evaluations(self.workspace, config, paths["result"])
        RUNNER.finish_evaluation_attempt(
            self.workspace,
            second["attempt_id"],
            "completed",
        )

        ledger = RUNNER.read_evaluation_ledger(self.workspace)
        self.assertEqual(RUNNER.evaluation_ledger_total(ledger), 20)
        self.assertEqual(
            [attempt["status"] for attempt in ledger["attempts"]],
            ["failed", "completed"],
        )
        with self.assertRaisesRegex(
            RUNNER.ConfigError,
            "total PySR evaluation budget exceeded",
        ):
            RUNNER.load_and_validate(config_path, self.workspace)

    def test_validation_does_not_reserve_evaluation_budget(self) -> None:
        (self.workspace / ".hamilton_budget.json").write_text(
            json.dumps({"max_total_evals": 10}),
            encoding="utf-8",
        )
        RUNNER.load_and_validate(self.write_config(valid_config()), self.workspace)
        self.assertFalse(
            (self.workspace / ".hamilton_evaluation_ledger.json").exists()
        )

    def test_first_reservation_imports_visible_legacy_completed_results(self) -> None:
        (self.workspace / ".hamilton_budget.json").write_text(
            json.dumps({"max_total_evals": 20}),
            encoding="utf-8",
        )
        previous = self.workspace / "history" / "round1" / "results"
        previous.mkdir(parents=True)
        (previous / "previous.json").write_text(
            json.dumps(
                {
                    "experiment_id": "legacy",
                    "status": "completed",
                    "config": {"search": {"max_evals": 7}},
                }
            ),
            encoding="utf-8",
        )
        config, paths = RUNNER.load_and_validate(
            self.write_config(valid_config()),
            self.workspace,
        )
        attempt = RUNNER.reserve_evaluations(
            self.workspace,
            config,
            paths["result"],
        )
        ledger = RUNNER.read_evaluation_ledger(self.workspace)
        self.assertEqual(RUNNER.evaluation_ledger_total(ledger), 17)
        self.assertEqual(ledger["attempts"][0]["status"], "legacy_completed")
        self.assertEqual(ledger["attempts"][1]["attempt_id"], attempt["attempt_id"])

    def test_evaluation_ledger_allows_only_an_explicit_limit_increase(self) -> None:
        budget_path = self.workspace / ".hamilton_budget.json"
        budget_path.write_text(
            json.dumps({"max_total_evals": 20}),
            encoding="utf-8",
        )
        config, paths = RUNNER.load_and_validate(
            self.write_config(valid_config()),
            self.workspace,
        )
        RUNNER.reserve_evaluations(self.workspace, config, paths["result"])

        budget_path.write_text(
            json.dumps({"max_total_evals": 30}),
            encoding="utf-8",
        )
        increased = RUNNER.read_evaluation_ledger(self.workspace)
        self.assertEqual(increased["max_total_evals"], 30)
        self.assertEqual(
            increased["budget_limit_history"][-1]["previous_max_total_evals"],
            20,
        )
        self.assertEqual(
            increased["budget_limit_history"][-1]["new_max_total_evals"],
            30,
        )

        budget_path.write_text(
            json.dumps({"max_total_evals": 15}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            RUNNER.ConfigError,
            "cannot be removed or decreased",
        ):
            RUNNER.read_evaluation_ledger(self.workspace)

    def test_dynamic_budget_uses_ledger_and_reserves_future_round_minimums(self) -> None:
        (self.workspace / ".hamilton_budget.json").write_text(
            json.dumps({"max_total_evals": 20000}),
            encoding="utf-8",
        )
        (self.workspace / ".hamilton_search_control.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "search_advancement": {"min_score_improvement": 0.0},
                    "trust_region": {
                        "enabled": True,
                        "max_anchor_distance": 2,
                        "max_step_changes": 1,
                        "rollback_after_stale_rounds": 2,
                    },
                    "dynamic_budget": {
                        "enabled": True,
                        "base_evals": 15000,
                        "min_evals": 4000,
                        "max_evals": 16000,
                        "rounding_quantum": 500,
                    },
                    "max_rounds": 3,
                }
            ),
            encoding="utf-8",
        )
        round_dir = self.workspace / "history" / "round1"
        round_dir.mkdir(parents=True)
        config = valid_config()
        config["search"]["max_evals"] = 7
        config["output"]["result_file"] = "history/round1/results/result.json"
        config["output"]["run_directory"] = "history/round1/results/pysr-run"
        config_path = round_dir / "experiment.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        normalized, paths = RUNNER.load_and_validate(config_path, self.workspace)

        self.assertEqual(normalized["search"]["max_evals"], 12000)
        allocation = normalized["_controller"]["budget_allocation"]
        self.assertEqual(allocation["proposed_evals_ignored"], 7)
        self.assertEqual(allocation["future_minimum_reserve"], 8000)
        attempt = RUNNER.reserve_evaluations(
            self.workspace,
            normalized,
            paths["result"],
        )
        self.assertEqual(attempt["requested_evals"], 12000)
        self.assertEqual(
            attempt["budget_allocation"]["mode"],
            "dynamic_cumulative_ledger",
        )

    def test_controller_seed_plan_overrides_adaptive_round_seed(self) -> None:
        (self.workspace / ".hamilton_seed_plan.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "round_seeds": [1101, 1102, 1103],
                }
            ),
            encoding="utf-8",
        )
        round_dir = self.workspace / "history" / "round1"
        round_dir.mkdir(parents=True)
        config = valid_config()
        config["search"]["random_state"] = 9999
        config["output"]["result_file"] = "history/round1/results/result.json"
        config["output"]["run_directory"] = "history/round1/results/pysr-run"
        config_path = round_dir / "experiment.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        normalized, _ = RUNNER.load_and_validate(config_path, self.workspace)

        self.assertEqual(normalized["search"]["random_state"], 1101)
        self.assertEqual(
            normalized["_controller"]["seed_assignment"],
            {
                "mode": "controller_frozen_round_seed",
                "round": 1,
                "proposed_seed_ignored": 9999,
                "assigned_seed": 1101,
            },
        )

    def test_adaptive_pre_search_audit_requires_exactly_one_leaf_change(self) -> None:
        previous_config, _ = RUNNER.load_and_validate(
            self.write_config(valid_config()),
            self.workspace,
        )
        previous_dir = self.workspace / "history" / "round1" / "results"
        previous_dir.mkdir(parents=True)
        (previous_dir / "previous.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "config": previous_config,
                }
            ),
            encoding="utf-8",
        )
        current_dir = self.workspace / "history" / "round2"
        current_dir.mkdir(parents=True)

        one_change = valid_config()
        one_change["search"]["parsimony"] = 0.02
        one_change["output"]["result_file"] = "history/round2/results/result.json"
        one_change["output"]["run_directory"] = "history/round2/results/pysr-run"
        one_change_path = current_dir / "experiment.json"
        one_change_path.write_text(json.dumps(one_change), encoding="utf-8")
        normalized, _ = RUNNER.load_and_validate(one_change_path, self.workspace)
        self.assertEqual(
            RUNNER.audit_single_field_adaptation(
                self.workspace,
                one_change_path,
                normalized,
            ),
            ["search.parsimony"],
        )

        two_changes = copy.deepcopy(one_change)
        two_changes["data"]["standardize_search"] = True
        one_change_path.write_text(json.dumps(two_changes), encoding="utf-8")
        with self.assertRaisesRegex(
            RUNNER.ConfigError,
            "change exactly one scientific config field",
        ):
            RUNNER.load_and_validate(one_change_path, self.workspace)

    def test_adaptive_pre_search_audit_enforces_governed_config_patch(self) -> None:
        previous_config, _ = RUNNER.load_and_validate(
            self.write_config(valid_config()),
            self.workspace,
        )
        previous_dir = self.workspace / "history" / "round1" / "results"
        previous_dir.mkdir(parents=True)
        (previous_dir / "previous.json").write_text(
            json.dumps({"status": "completed", "config": previous_config}),
            encoding="utf-8",
        )
        (self.workspace / "plan.md").write_text(
            "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
            + json.dumps(
                {
                    "next_strategy": {
                        "config_field": "search.populations",
                        "config_patch": {"search.populations": 16},
                    }
                }
            )
            + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->",
            encoding="utf-8",
        )
        current_dir = self.workspace / "history" / "round2"
        current_dir.mkdir(parents=True)
        current = valid_config()
        current["search"]["parsimony"] = 0.02
        current["output"]["result_file"] = "history/round2/results/result.json"
        current["output"]["run_directory"] = "history/round2/results/pysr-run"
        current_path = current_dir / "experiment.json"
        current_path.write_text(json.dumps(current), encoding="utf-8")

        with self.assertRaisesRegex(
            RUNNER.ConfigError,
            "must implement the governed next_strategy config_patch",
        ):
            RUNNER.load_and_validate(current_path, self.workspace)

    def test_rejects_invalid_pysr_population_settings(self) -> None:
        config = valid_config()
        config["search"]["tournament_selection_n"] = 4
        with self.assertRaisesRegex(RUNNER.ConfigError, "smaller than"):
            RUNNER.load_and_validate(self.write_config(config), self.workspace)

    def test_rejects_candidate_pool_larger_than_top_k(self) -> None:
        config = valid_config()
        config["verification"]["candidate_ranking"] = {
            "enabled": True,
            "max_candidates": 4,
            "weights": {
                "validation_nrmse": 1.0,
                "trajectory_nrmse": 1.0,
                "complexity": 0.1,
            },
            "failure_penalty": 100.0,
        }
        with self.assertRaisesRegex(RUNNER.ConfigError, "cannot exceed"):
            RUNNER.load_and_validate(self.write_config(config), self.workspace)

    def test_rejects_invalid_residual_diagnostic_bins(self) -> None:
        config = valid_config()
        config["verification"]["residual_diagnostics"] = {
            "enabled": True,
            "feature_bins": 1,
            "phase_bins": 8,
            "max_lag": 10,
            "high_frequency_fraction": 0.25,
        }
        with self.assertRaisesRegex(RUNNER.ConfigError, "feature_bins must be between"):
            RUNNER.load_and_validate(self.write_config(config), self.workspace)

    def test_long_horizon_contract_requires_explicit_frozen_fields(self) -> None:
        config = valid_config()
        config["verification"]["long_horizon_dynamics"] = {
            "enabled": True,
            "position_column": "x",
            "velocity_column": "v",
            "duration": 20.0,
            "points": 100,
        }
        with self.assertRaisesRegex(RUNNER.ConfigError, "state_limit"):
            RUNNER.load_and_validate(self.write_config(config), self.workspace)

    def test_steady_state_summary_extracts_robust_amplitude_and_frequency(self) -> None:
        times = np.linspace(0.0, 40.0, 4001)
        positions = 2.0 * np.sin(2.0 * np.pi * 0.5 * times)
        result = RUNNER._steady_state_summary(
            times,
            positions,
            steady_fraction=0.5,
            min_cycles=3.0,
            stationarity_tolerance=0.1,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["frequency_status"], "completed")
        self.assertAlmostEqual(result["dominant_frequency_hz"], 0.5, delta=0.01)
        self.assertAlmostEqual(result["amplitude"]["value"], 2.0, delta=0.05)
        self.assertTrue(result["stationarity"]["passed"])

    def test_long_horizon_reports_zero_and_large_initial_condition_mismatch(self) -> None:
        times = np.linspace(0.0, 50.0, 5001)
        frame = pd.DataFrame(
            {
                "t": times,
                "x": np.sin(times),
                "v": np.cos(times),
                "a": -np.sin(times),
            }
        )
        config = valid_config()
        config["verification"]["candidate_ranking"] = {
            "enabled": True,
            "max_candidates": 1,
            "weights": {
                "validation_nrmse": 1.0,
                "trajectory_nrmse": 0.0,
                "complexity": 0.0,
                "long_horizon_penalty": 1.0,
            },
            "failure_penalty": 77.0,
        }
        config["verification"]["long_horizon_dynamics"] = {
            "enabled": True,
            "position_column": "x",
            "velocity_column": "v",
            "duration": 50.0,
            "points": 2500,
            "steady_state_fraction": 0.4,
            "min_steady_cycles": 3.0,
            "state_limit": 100.0,
            "rtol": 1e-8,
            "atol": 1e-10,
            "large_initial_scale": 2.0,
            "stationary_amplitude_fraction": 0.001,
            "zero_initial_policy": "report_only",
            "amplitude_relative_tolerance": 0.1,
            "frequency_relative_tolerance": 0.1,
            "stationarity_relative_tolerance": 0.1,
            "attractor_relative_tolerance": 0.1,
        }

        result = RUNNER.run_long_horizon_dynamics(
            -sympy.Symbol("x"),
            config,
            frame.iloc[:4000].copy(),
            frame.iloc[4000:].copy(),
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["rollouts"]["zero"]["qualitative_behavior"],
            "stationary",
        )
        self.assertFalse(result["gates"]["attractor_consistency"]["passed"])
        self.assertFalse(result["gates"]["overall_pass"])
        self.assertIn("attractor_mismatch", result["failure_classes"])
        self.assertGreater(result["ranking_penalty"], 0.0)
        self.assertLess(result["ranking_penalty"], 77.0)
        self.assertIn(
            "attractor_amplitude_observed_validation_vs_large",
            result["ranking_penalty_components"],
        )
        self.assertNotIn("positions", result["rollouts"]["observed_validation"])

    @staticmethod
    def long_horizon_config(*, zero_policy: str = "report_only") -> dict:
        config = valid_config()
        config["verification"]["candidate_ranking"] = {
            "enabled": True,
            "max_candidates": 1,
            "weights": {
                "validation_nrmse": 1.0,
                "trajectory_nrmse": 0.0,
                "complexity": 0.0,
                "long_horizon_penalty": 1.0,
            },
            "failure_penalty": 91.0,
        }
        config["verification"]["long_horizon_dynamics"] = {
            "enabled": True,
            "position_column": "x",
            "velocity_column": "v",
            "duration": 60.0,
            "points": 2400,
            "steady_state_fraction": 0.4,
            "min_steady_cycles": 3.0,
            "state_limit": 100.0,
            "rtol": 1e-8,
            "atol": 1e-10,
            "large_initial_scale": 2.0,
            "stationary_amplitude_fraction": 0.001,
            "zero_initial_policy": zero_policy,
            "amplitude_relative_tolerance": 0.15,
            "frequency_relative_tolerance": 0.05,
            "stationarity_relative_tolerance": 0.1,
            "attractor_relative_tolerance": 0.15,
        }
        return config

    def test_long_horizon_accepts_damped_equilibrium_from_multiple_initial_states(self) -> None:
        times = np.linspace(0.0, 100.0, 5001)
        decay = np.exp(-0.2 * times)
        frame = pd.DataFrame(
            {
                "t": times,
                "x": decay * np.cos(times),
                "v": decay * (-0.2 * np.cos(times) - np.sin(times)),
            }
        )
        frame["a"] = -0.4 * frame["v"] - 1.04 * frame["x"]
        result = RUNNER.run_long_horizon_dynamics(
            -0.4 * sympy.Symbol("v") - 1.04 * sympy.Symbol("x"),
            self.long_horizon_config(),
            frame.iloc[:4000].copy(),
            frame.iloc[4000:].copy(),
        )
        self.assertTrue(result["gates"]["overall_pass"])
        self.assertEqual(
            result["gates"]["reference_match"]["frequency_comparison"],
            "both_stationary",
        )
        self.assertTrue(result["gates"]["attractor_consistency"]["passed"])

    def test_long_horizon_accepts_van_der_pol_limit_cycle_for_nonzero_states(self) -> None:
        from scipy.integrate import solve_ivp

        times = np.linspace(0.0, 100.0, 5001)

        def rhs(_time, state):
            return [state[1], (1.0 - state[0] ** 2) * state[1] - state[0]]

        solution = solve_ivp(
            rhs,
            (0.0, 100.0),
            [0.1, 0.0],
            t_eval=times,
            method="DOP853",
            rtol=1e-10,
            atol=1e-12,
        )
        frame = pd.DataFrame(
            {"t": times, "x": solution.y[0], "v": solution.y[1]}
        )
        frame["a"] = (1.0 - frame["x"] ** 2) * frame["v"] - frame["x"]
        x, v = sympy.symbols("x v")
        result = RUNNER.run_long_horizon_dynamics(
            (1 - x**2) * v - x,
            self.long_horizon_config(),
            frame.iloc[:2000].copy(),
            frame.iloc[2000:].copy(),
        )
        self.assertTrue(result["gates"]["overall_pass"])
        self.assertEqual(result["rollouts"]["zero"]["qualitative_behavior"], "stationary")

    def test_long_horizon_classifies_unstable_candidate(self) -> None:
        times = np.linspace(0.0, 80.0, 4001)
        frame = pd.DataFrame(
            {"t": times, "x": np.sin(times), "v": np.cos(times), "a": -np.sin(times)}
        )
        config = self.long_horizon_config()
        config["verification"]["long_horizon_dynamics"]["state_limit"] = 10.0
        result = RUNNER.run_long_horizon_dynamics(
            sympy.Symbol("v") - sympy.Symbol("x"),
            config,
            frame.iloc[:3200].copy(),
            frame.iloc[3200:].copy(),
        )
        self.assertFalse(result["gates"]["overall_pass"])
        self.assertTrue(
            {"state_limit_exceeded", "solver_failed"}.intersection(result["failure_classes"])
        )

    def test_steady_state_summary_rejects_drift_and_insufficient_cycles(self) -> None:
        times = np.linspace(0.0, 40.0, 4001)
        drift = np.sin(2.0 * np.pi * 0.5 * times) + 0.08 * times
        drifting = RUNNER._steady_state_summary(times, drift, 0.5, 3.0, 0.1)
        self.assertFalse(drifting["stationarity"]["passed"])

        slow = np.sin(2.0 * np.pi * 0.02 * times)
        unresolved = RUNNER._steady_state_summary(times, slow, 0.5, 3.0, 0.1)
        self.assertEqual(unresolved["frequency_status"], "insufficient_cycles")
        self.assertFalse(unresolved["stationarity"]["passed"])

    def test_steady_state_summary_handles_nonuniform_time_grid(self) -> None:
        increments = 0.01 * (1.0 + 0.1 * np.sin(np.arange(4000)))
        times = np.concatenate([[0.0], np.cumsum(increments)])
        positions = 1.5 * np.sin(2.0 * np.pi * 0.4 * times)
        result = RUNNER._steady_state_summary(times, positions, 0.5, 3.0, 0.15)
        self.assertEqual(result["frequency_status"], "completed")
        self.assertAlmostEqual(result["dominant_frequency_hz"], 0.4, delta=0.02)

    def test_structured_residual_diagnostics_find_state_and_time_patterns(self) -> None:
        config = valid_config()
        config["verification"]["residual_diagnostics"] = {
            "enabled": True,
            "feature_bins": 4,
            "phase_bins": 8,
            "max_lag": 20,
            "high_frequency_fraction": 0.25,
        }
        config["verification"]["short_ode"] = {
            "enabled": False,
            "position_column": "x",
            "velocity_column": "v",
        }
        time_values = np.arange(100, dtype=float) * 0.05
        frame = pd.DataFrame(
            {
                "t": time_values,
                "x": np.linspace(-2.0, 2.0, len(time_values)),
                "v": np.sin(2 * np.pi * time_values),
            }
        )
        frame["a"] = 1.5 * frame["x"] + 0.2 * np.sin(4 * np.pi * time_values)
        train = frame.iloc[:80].copy()
        validation = frame.iloc[80:].copy()
        train_prediction = np.zeros(len(train))
        validation_prediction = np.zeros(len(validation))

        result = RUNNER.residual_diagnostics(
            train,
            validation,
            train_prediction,
            validation_prediction,
            config,
        )

        self.assertEqual(result["definition"], "target_minus_prediction_in_original_units")
        self.assertEqual(result["role"], "diagnostic_only_not_in_scientific_score")
        state = result["train"]["state_dependence"]
        self.assertGreater(abs(state["pearson_correlation"]["x"]), 0.9)
        self.assertEqual(
            sum(item["count"] for item in state["feature_quantile_bins"]["x"]),
            len(train),
        )
        temporal = result["train"]["temporal_structure"]
        self.assertIsNotNone(temporal["strongest_reported_autocorrelation"]["value"])
        self.assertEqual(temporal["spectrum"]["status"], "completed")
        self.assertIn("oscillator_state", result["train"])
        self.assertNotIn("residual_values", result["train"])
        json.dumps(result, allow_nan=False)

    def test_candidate_scoring_uses_validation_and_complexity(self) -> None:
        config = valid_config()
        config["verification"]["candidate_ranking"] = {
            "enabled": True,
            "max_candidates": 2,
            "weights": {
                "validation_nrmse": 1.0,
                "trajectory_nrmse": 0.0,
                "complexity": 0.1,
            },
            "failure_penalty": 100.0,
        }
        config["verification"]["short_ode"] = {"enabled": False}
        config, paths = RUNNER.load_and_validate(self.write_config(config), self.workspace)
        train, validation, _ = RUNNER.load_data(config, paths["train"])

        class FakeModel:
            @staticmethod
            def sympy(index: int):
                x = sympy.Symbol("x")
                return x if index == 0 else 0 * x

        equations = pd.DataFrame(
            [
                {"equation": "x", "loss": 0.1, "complexity": 1, "score": 1.0},
                {"equation": "0", "loss": 0.2, "complexity": 1, "score": 0.5},
            ]
        )
        candidates = RUNNER.evaluate_candidates(FakeModel(), equations, config, train, validation)
        self.assertEqual(len(candidates), 2)
        self.assertIn("scientific_score", candidates[0]["ranking"])
        self.assertLess(
            candidates[0]["ranking"]["scientific_score"],
            candidates[1]["ranking"]["scientific_score"],
        )

    def test_linear_diagnostic_reports_scale_aware_effects(self) -> None:
        config, paths = RUNNER.load_and_validate(self.write_config(valid_config()), self.workspace)
        train, validation, _ = RUNNER.load_data(config, paths["train"])
        diagnostic = RUNNER.linear_diagnostic(train, validation, ["x", "v"], "a")
        self.assertEqual(
            diagnostic["scale_aware"]["method"],
            "coefficient_times_train_std_over_target_std",
        )
        self.assertEqual(set(diagnostic["scale_aware"]["standardized_effect"]), {"x", "v"})


class HamiltonSearchControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        (self.workspace / "input").mkdir()
        pd.DataFrame(
            {
                "t": range(10),
                "x": range(10),
                "v": range(10),
                "a": range(10),
            }
        ).to_csv(self.workspace / "input" / "train.csv", index=False)
        self.experiment = {
            "max_rounds": 5,
            "max_total_evals": 50000,
            "search_control": {
                "trust_region": {
                    "rollback_after_stale_rounds": 2,
                    "max_anchor_distance": 2,
                    "max_step_changes": 1,
                },
                "dynamic_budget": {"enabled": False},
            },
        }
        initialize_control(self.workspace, self.experiment)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def config(parsimony: float = 0.01) -> dict:
        config = valid_config()
        config["search"]["parsimony"] = parsimony
        return config

    def test_incumbent_config_is_saved_and_two_stale_rounds_trigger_rollback(self) -> None:
        incumbent_config = self.config()
        state1 = update_state(
            self.workspace,
            round_num=1,
            current_result_file="history/round1/results/r1.json",
            incumbent_result_file="history/round1/results/r1.json",
            incumbent_action="initialize",
            incumbent_score=0.8,
            incumbent_equation="x",
            incumbent_config=incumbent_config,
        )
        self.assertEqual(state1["stale_rounds"], 0)
        self.assertFalse(state1["rollback_required"])
        self.assertEqual(
            state1["incumbent"]["config"],
            search_meaningful_config(incumbent_config),
        )

        state2 = update_state(
            self.workspace,
            round_num=2,
            current_result_file="history/round2/results/r2.json",
            incumbent_result_file="history/round1/results/r1.json",
            incumbent_action="retain",
            incumbent_score=0.8,
            incumbent_equation="x",
            incumbent_config=incumbent_config,
        )
        self.assertEqual(
            state2["next_round"]["baseline_result_file"],
            "history/round2/results/r2.json",
        )
        state3 = update_state(
            self.workspace,
            round_num=3,
            current_result_file="history/round3/results/r3.json",
            incumbent_result_file="history/round1/results/r1.json",
            incumbent_action="retain",
            incumbent_score=0.8,
            incumbent_equation="x",
            incumbent_config=incumbent_config,
        )
        self.assertTrue(state3["rollback_required"])
        self.assertEqual(
            state3["next_round"]["baseline_result_file"],
            "history/round1/results/r1.json",
        )
        directive = round_directive(self.workspace, 4)
        self.assertTrue(directive["rollback_required"])
        self.assertEqual(directive["baseline_mode"], "rollback_to_incumbent")

    def test_binding_policy_is_persisted_from_frozen_result_diagnostics(self) -> None:
        controlled = copy.deepcopy(self.experiment)
        controlled["search_control"]["deterministic_policy"] = {
            "enabled": True,
            "binding": True,
            "warm_compatible_fields": ["search.parsimony"],
            "thresholds": {
                "min_score_improvement": 0.0001,
                "stale_rounds_before_intervention": 2,
                "high_complexity_fraction": 0.8,
                "low_complexity_fraction": 0.25,
                "material_residual_correlation": 0.3,
                "parsimony_multiplier": 2.0,
                "min_parsimony": 1e-8,
                "max_parsimony": 1.0,
            },
        }
        (self.workspace / ".hamilton_search_control.json").unlink()
        initialize_control(self.workspace, controlled)
        result_path = self.workspace / "history/round1/results/r1.json"
        result_path.parent.mkdir(parents=True)
        config = self.config(parsimony=0.01)
        result_path.write_text(
            json.dumps({
                "status": "completed",
                "config": config,
                "selected": {"scientific_score": 0.4, "complexity": 10},
                "verification": {"residual_diagnostics": {"validation": {}}},
            }),
            encoding="utf-8",
        )
        state = update_state(
            self.workspace,
            round_num=1,
            current_result_file="history/round1/results/r1.json",
            incumbent_result_file="history/round1/results/r1.json",
            incumbent_action="initialize",
            incumbent_score=0.4,
            incumbent_equation="x",
            incumbent_config=config,
        )
        policy = state["next_round"]["controller_policy"]
        self.assertTrue(policy["binding"])
        self.assertEqual(policy["action"]["action"], "continue")
        self.assertEqual(RUNNER.expected_adaptive_config_patch(self.workspace), {})
        self.assertTrue(round_directive(self.workspace, 2)["controller_policy"]["binding"])

    def test_runner_enforces_rollback_baseline_instead_of_latest_failed_config(self) -> None:
        baseline_path = self.workspace / "baseline.json"
        baseline_path.write_text(
            json.dumps(self.config()),
            encoding="utf-8",
        )
        incumbent_config, _ = RUNNER.load_and_validate(
            baseline_path,
            self.workspace,
        )
        result_dir = self.workspace / "history" / "round1" / "results"
        result_dir.mkdir(parents=True)
        (result_dir / "r1.json").write_text(
            json.dumps(
                {"status": "completed", "config": incumbent_config}
            ),
            encoding="utf-8",
        )
        update_state(
            self.workspace,
            round_num=3,
            current_result_file="history/round3/results/r3.json",
            incumbent_result_file="history/round1/results/r1.json",
            incumbent_action="retain",
            incumbent_score=0.8,
            incumbent_equation="x",
            incumbent_config=incumbent_config,
        )
        # A second retained update crosses the rollback threshold.
        update_state(
            self.workspace,
            round_num=4,
            current_result_file="history/round4/results/r4.json",
            incumbent_result_file="history/round1/results/r1.json",
            incumbent_action="retain",
            incumbent_score=0.8,
            incumbent_equation="x",
            incumbent_config=incumbent_config,
        )
        (self.workspace / "plan.md").write_text(
            "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
            + json.dumps(
                {
                    "next_strategy": {
                        "config_field": "search.parsimony",
                        "config_patch": {"search.parsimony": 0.02},
                    }
                }
            )
            + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->",
            encoding="utf-8",
        )
        round_dir = self.workspace / "history" / "round5"
        round_dir.mkdir(parents=True)
        current = self.config(parsimony=0.02)
        current["output"]["result_file"] = "history/round5/results/r5.json"
        current["output"]["run_directory"] = "history/round5/results/pysr-run"
        config_path = round_dir / "experiment.json"
        config_path.write_text(json.dumps(current), encoding="utf-8")

        normalized, _ = RUNNER.load_and_validate(config_path, self.workspace)
        self.assertEqual(
            RUNNER.audit_single_field_adaptation(
                self.workspace,
                config_path,
                normalized,
            ),
            ["search.parsimony"],
        )

    def test_controller_builds_deduplicated_strong_and_weak_evidence_memory(self) -> None:
        result_dir = self.workspace / "history" / "round1" / "results"
        result_dir.mkdir(parents=True)
        result_file = "history/round1/results/r1.json"
        result_path = self.workspace / result_file
        result_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "config": self.config(),
                    "selected": {
                        "scientific_score": 0.8,
                        "simplified_equation": "x",
                    },
                    "verification": {
                        "residual_diagnostics": {
                            "validation": {
                                "state_dependence": {
                                    "strongest_absolute_correlation": {
                                        "signal": "v",
                                        "value": 0.2,
                                    }
                                },
                                "temporal_structure": {
                                    "strongest_reported_autocorrelation": {
                                        "lag": 5,
                                        "value": 0.4,
                                    }
                                },
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.workspace / "plan.md").write_text(
            "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
            + json.dumps(
                {
                    "search_advancement_gates": [
                        {
                            "name": "candidate validity",
                            "passed": True,
                            "evidence": "finite validation predictions",
                        }
                    ],
                    "next_strategy": {
                        "diagnosed_failure": "residual autocorrelation remains",
                        "config_field": "search.maxsize",
                        "config_patch": {"search.maxsize": 7},
                        "alternative_explanation": "derivative noise",
                        "expected_effect": "lower score",
                        "expected_residual_change": "lag-5 decreases",
                        "falsification": "score does not improve",
                    },
                }
            )
            + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->",
            encoding="utf-8",
        )
        audit = {
            "incumbent_valid": True,
            "search_advancement_gates_valid": True,
            "protocol_evidence_valid": True,
            "residual_feedback_valid": True,
        }

        for _ in range(2):
            update_evidence_memory(
                self.workspace,
                round_num=1,
                current_result_file=result_file,
                incumbent_result_file=result_file,
                incumbent_action="initialize",
                incumbent_score=0.8,
                changed_fields=[],
                governance_audit=audit,
            )

        memory = read_evidence_memory(self.workspace)
        self.assertEqual(len(memory["strong"]["search_outcomes"]), 1)
        self.assertEqual(len(memory["strong"]["residual_observations"]), 1)
        self.assertEqual(len(memory["strong"]["incumbent_history"]), 1)
        self.assertEqual(len(memory["weak"]["causal_hypotheses"]), 1)
        self.assertEqual(len(memory["weak"]["near_miss_candidates"]), 0)
        self.assertEqual(
            memory["strong"]["residual_observations"][0][
                "temporal_dependence"
            ]["value"],
            0.4,
        )

        update_state(
            self.workspace,
            round_num=1,
            current_result_file=result_file,
            incumbent_result_file=result_file,
            incumbent_action="initialize",
            incumbent_score=0.8,
            incumbent_equation="x",
            incumbent_config=self.config(),
        )
        directive = round_directive(self.workspace, 2)
        self.assertEqual(
            directive["evidence_memory"]["updated_after_round"],
            1,
        )

    def test_evidence_memory_rejects_failed_governance_audit(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requires valid incumbent",
        ):
            update_evidence_memory(
                self.workspace,
                round_num=1,
                current_result_file="history/round1/results/invalid.json",
                incumbent_result_file="history/round1/results/invalid.json",
                incumbent_action="retain",
                incumbent_score=1.0,
                changed_fields=[],
                governance_audit={
                    "incumbent_valid": False,
                    "search_advancement_gates_valid": True,
                    "protocol_evidence_valid": True,
                    "residual_feedback_valid": True,
                },
            )
        self.assertFalse(
            (self.workspace / ".hamilton_evidence_memory.json").exists()
        )


class RoundAndPromotionPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.round_dir = self.workspace / "history" / "round1"
        (self.round_dir / "results").mkdir(parents=True)
        (self.workspace / "findings.md").write_text("findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text("plan", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_round_exp_produces_evidence_without_promotion(self) -> None:
        workspace = self.workspace

        class FakeAgent:
            task = None

            def run(self, task):
                self.task = task
                result = workspace / "history" / "round1" / "results" / "result.json"
                result.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
                return SimpleNamespace(status="completed", steps=[], dialogs=[])

        agent = FakeAgent()
        exp = RoundExp(agent, SimpleNamespace(experiment={}), 1)
        exp.set_run_dir(self.workspace)
        result = exp.run("discover")
        self.assertEqual(agent.task.task_type, "hamilton_round")
        self.assertTrue(result["ready_for_promotion"])
        self.assertEqual(
            result["completed_result_files"],
            ["history/round1/results/result.json"],
        )
        self.assertFalse((self.round_dir / "promotion_input.json").exists())

    def test_promotion_input_is_stable_and_detects_mutation(self) -> None:
        result_path = self.round_dir / "results" / "result.json"
        result_path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        exp = PromotionExp(
            SimpleNamespace(),
            SimpleNamespace(experiment={}),
            1,
            result_files=["history/round1/results/result.json"],
        )
        exp.set_run_dir(self.workspace)
        first = exp._load_or_create_promotion_input()
        second = exp._load_or_create_promotion_input()
        self.assertEqual(first, second)
        result_path.write_text(json.dumps({"status": "completed", "changed": True}), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "changed after preparation"):
            exp._load_or_create_promotion_input()

    def test_promotion_evidence_is_compact_controller_projection(self) -> None:
        result_path = self.round_dir / "results" / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "experiment_id": "compact-evidence",
                    "config": {
                        "search": {"maxsize": 31},
                        "data": {"feature_columns": ["x1", "x2"]},
                        "verification": {"residual_diagnostics": {"enabled": True}},
                    },
                    "selected": {
                        "simplified_equation": "x1 + x2",
                        "scientific_score": 0.25,
                    },
                    "metrics": {"validation": {"r2": 0.9}},
                    "diagnostics": {
                        "linear_raw_features": {
                            "scale_aware": {
                                "standardized_effect": {"x1": 0.5, "x2": 0.25}
                            }
                        }
                    },
                    "verification": {
                        "short_ode": {"enabled": False},
                        "residual_diagnostics": {
                            "enabled": True,
                            "status": "completed",
                            "validation": {
                                "state_dependence": {
                                    "strongest_absolute_correlation": {
                                        "signal": "x2",
                                        "value": 0.2,
                                    }
                                },
                                "temporal_structure": {
                                    "strongest_reported_autocorrelation": {
                                        "lag": 1,
                                        "value": 0.1,
                                    },
                                    "durbin_watson": 1.8,
                                },
                            },
                        },
                    },
                    "candidates": [{"large": "must not be copied"}] * 100,
                }
            ),
            encoding="utf-8",
        )
        exp = PromotionExp(
            SimpleNamespace(),
            SimpleNamespace(experiment={}),
            1,
            result_files=["history/round1/results/result.json"],
        )
        exp.set_run_dir(self.workspace)
        promotion_input = exp._load_or_create_promotion_input()
        evidence = exp._write_promotion_evidence(promotion_input)
        compact_result = evidence["results"][0]
        self.assertFalse(evidence["full_result_read_required"])
        self.assertNotIn("candidates", compact_result)
        self.assertEqual(
            compact_result["residual_diagnostics"]["strongest_state_dependence"],
            {"signal": "x2", "value": 0.2},
        )
        self.assertEqual(
            evidence["required_protocol_valid_result_files"],
            ["history/round1/results/result.json"],
        )

    def test_promotion_attempt_limit_does_not_call_agent(self) -> None:
        result_path = self.round_dir / "results" / "result.json"
        result_path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")

        class FailingAgent:
            def run(self, _task):
                raise AssertionError("agent must not run after attempt exhaustion")

        exp = PromotionExp(
            FailingAgent(),
            SimpleNamespace(experiment={}),
            1,
            result_files=["history/round1/results/result.json"],
            max_attempts=2,
        )
        exp.set_run_dir(self.workspace)
        exp._load_or_create_promotion_input()
        exp._write_promotion_state({"status": "pending", "attempts": 2})
        result = exp.run("promote")
        self.assertTrue(result["signal"]["promotion_attempts_exhausted"])
        self.assertFalse(result["signal"]["closed"])

    def test_promotion_state_is_bound_to_frozen_input(self) -> None:
        result_path = self.round_dir / "results" / "result.json"
        result_path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        exp = PromotionExp(
            SimpleNamespace(),
            SimpleNamespace(experiment={}),
            1,
            result_files=["history/round1/results/result.json"],
        )
        exp.set_run_dir(self.workspace)
        exp._load_or_create_promotion_input()
        exp._write_promotion_state(
            {"status": "completed", "attempts": 1, "input_sha256": "wrong"}
        )
        with self.assertRaisesRegex(RuntimeError, "does not match the frozen input"):
            exp.run("promote")

    def test_promotion_recovery_feedback_includes_closure_errors(self) -> None:
        feedback = PromotionExp._recovery_feedback(
            attempts=2,
            prior_closure_errors=[
                "claims lack evidence or overstate confirmation",
                "residual feedback is stale",
            ],
        )
        self.assertIn("controller-approved Promotion recovery", feedback)
        self.assertIn("claims lack evidence or overstate confirmation", feedback)
        self.assertIn("residual feedback is stale", feedback)
        self.assertIn("do not repeat the rejected claim strength", feedback)
        self.assertEqual(
            PromotionExp._recovery_feedback(
                attempts=0,
                prior_closure_errors=["ignored"],
            ),
            "",
        )

    def test_fast_finish_feedback_uses_current_round_and_attempt(self) -> None:
        feedback = PromotionExp._fast_finish_feedback(
            round_num=1,
            attempt_num=3,
        )
        self.assertIn("history/round1/trace.md", feedback)
        self.assertIn("# Round 1 工作记录", feedback)
        self.assertIn("EVO_FAST_FINISH_RECOVERY_ATTEMPT_3", feedback)
        self.assertNotIn("history/round3/trace.md", feedback)

    def test_fast_finish_requires_explicit_successful_scientific_audit(self) -> None:
        exp = PromotionExp(
            SimpleNamespace(),
            SimpleNamespace(experiment={}),
            3,
        )
        valid = {
            "closed": False,
            "completed_result_files": ["history/round3/results/result.json"],
            "continuation_contract_valid": None,
            "meaningful_config_change": True,
            "single_config_change": True,
            "initial_priors": {"valid": True},
            "scientific_decision": {"valid": True},
        }
        self.assertTrue(exp._fast_finish_eligible(valid))

        invalid = dict(valid)
        invalid["scientific_decision"] = {"valid": False}
        self.assertFalse(exp._fast_finish_eligible(invalid))
        self.assertFalse(exp._fast_finish_eligible({}))

    def test_repaired_artifacts_can_authorize_fast_finish(self) -> None:
        exp = PromotionExp(
            SimpleNamespace(),
            SimpleNamespace(experiment={"scientific_governance": True, "max_rounds": 3}),
            1,
        )
        with (
            patch.object(exp, "_continuation_contract_valid", return_value=True),
            patch.object(exp, "_meaningful_config_changed", return_value=None),
            patch.object(exp, "_single_config_change", return_value=(None, [])),
            patch.object(exp, "_audit_scientific_decision", return_value={"valid": True}),
        ):
            self.assertTrue(
                exp._existing_artifacts_fast_finish_eligible(
                    ["history/round1/results/result.json"]
                )
            )

    def test_audited_recovery_closes_without_another_agent_call(self) -> None:
        result_path = self.round_dir / "results" / "result.json"
        result_path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        (self.round_dir / "trace.md").write_text("# trace\n", encoding="utf-8")

        class FailingAgent:
            def run(self, _task):
                raise AssertionError("audited deterministic recovery must not call the agent")

        exp = PromotionExp(
            FailingAgent(),
            SimpleNamespace(experiment={"max_rounds": 1}),
            1,
            result_files=["history/round1/results/result.json"],
        )
        exp.set_run_dir(self.workspace)
        exp._load_or_create_promotion_input()
        exp._write_promotion_state(
            {
                "status": "pending",
                "attempts": 1,
                "input_sha256": exp._file_digest(exp._promotion_input_path()),
                "fast_finish_eligible": True,
            }
        )

        with patch.object(
            exp,
            "_audit_scientific_decision",
            return_value={"valid": True, "errors": []},
        ):
            result = exp.run("promote")
        self.assertTrue(result["signal"]["closed"])
        self.assertTrue(result["signal"]["deterministic_finish_recovery"])
        self.assertIsNone(result["trajectory"])
        state = exp._load_promotion_state()
        self.assertEqual(state["status"], "completed")
        self.assertTrue(state["deterministic_finish_recovery"])


class HamiltonPromotionOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.agent = SimpleNamespace(config=SimpleNamespace(max_total_tokens=999))
        self.playground = object.__new__(HamiltonPlayground)
        self.playground.agent = self.agent
        self.playground.config = SimpleNamespace(experiment={})
        self.playground.logger = logging.getLogger("promotion-orchestration-test")
        self.playground.workspace_dir = self.workspace
        self.playground.run_dir = self.workspace
        self.playground.experiment_record = {
            "task": "",
            "rounds": [],
            "start_time": "test",
        }
        self.playground.setup = lambda: None
        self.playground.cleanup = lambda: None
        self.playground._setup_trajectory_file = lambda _output=None: None
        self.playground._init_workspace = lambda: None
        self.playground._save_experiment_record = lambda: None

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def completed_promotion_result() -> dict:
        return {
            "round": 1,
            "agent_result": "promoted",
            "findings": "findings",
            "signal": {
                "closed": True,
                "satisfied": True,
                "closure": {"scientific_decision": {}},
            },
            "trajectory": SimpleNamespace(status="completed", steps=[]),
        }

    def test_promotion_resume_skips_discovery_and_preflight(self) -> None:
        round_dir = self.workspace / "history" / "round1"
        round_dir.mkdir(parents=True)
        (round_dir / "promotion_input.json").write_text(
            json.dumps({"schema_version": 1, "round": 1, "results": [{}]}),
            encoding="utf-8",
        )
        (round_dir / "promotion_state.json").write_text(
            json.dumps({"status": "pending", "attempts": 1}),
            encoding="utf-8",
        )
        self.playground.config = SimpleNamespace(
            experiment={
                "max_rounds": 1,
                "promotion": {"max_tokens": 1234, "max_attempts": 2},
            }
        )
        self.playground._ensure_pysr_preflight = lambda _cfg: self.fail(
            "Promotion-only recovery must not run PySR preflight"
        )
        seen = {}

        class FakePromotionExp:
            def __init__(_self, agent, _config, _round, result_files, max_attempts):
                seen["agent"] = agent
                seen["result_files"] = result_files
                seen["max_attempts"] = max_attempts

            def set_run_dir(_self, _run_dir):
                pass

            def run(_self, _task):
                seen["budget"] = self.agent.config.max_total_tokens
                return HamiltonPromotionOrchestrationTests.completed_promotion_result()

        with patch("playground.hamilton.core.playground.RoundExp") as round_mock, patch(
            "playground.hamilton.core.playground.PromotionExp", FakePromotionExp
        ):
            result = self.playground.run("task")
        round_mock.assert_not_called()
        self.assertIs(seen["agent"], self.agent)
        self.assertIsNone(seen["result_files"])
        self.assertEqual(seen["budget"], 1234)
        self.assertEqual(result["termination_reason"], "scientific_success")
        self.assertEqual(self.agent.config.max_total_tokens, 999)

    def test_completed_result_recovers_before_promotion_input_is_written(self) -> None:
        results_dir = self.workspace / "history" / "round1" / "results"
        results_dir.mkdir(parents=True)
        result_path = results_dir / "result.json"
        result_path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        self.playground.config = SimpleNamespace(
            experiment={
                "max_rounds": 1,
                "promotion": {"max_tokens": 1234, "max_attempts": 2},
            }
        )
        self.playground._ensure_pysr_preflight = lambda _cfg: self.fail(
            "Recovery from a completed result must not rerun PySR preflight"
        )
        seen = {}

        class FakePromotionExp:
            def __init__(_self, _agent, _config, _round, result_files, max_attempts):
                seen["result_files"] = result_files

            def set_run_dir(_self, _run_dir):
                pass

            def run(_self, _task):
                return HamiltonPromotionOrchestrationTests.completed_promotion_result()

        with patch("playground.hamilton.core.playground.RoundExp") as round_mock, patch(
            "playground.hamilton.core.playground.PromotionExp", FakePromotionExp
        ):
            result = self.playground.run("task")
        round_mock.assert_not_called()
        self.assertEqual(
            seen["result_files"], ["history/round1/results/result.json"]
        )
        self.assertEqual(result["termination_reason"], "scientific_success")

    def test_completed_promotion_state_is_replayed_without_discovery(self) -> None:
        round_dir = self.workspace / "history" / "round1"
        round_dir.mkdir(parents=True)
        (round_dir / "promotion_input.json").write_text(
            json.dumps({"schema_version": 1, "round": 1, "results": [{}]}),
            encoding="utf-8",
        )
        (round_dir / "promotion_state.json").write_text(
            json.dumps({"status": "completed", "attempts": 1}),
            encoding="utf-8",
        )
        self.playground.config = SimpleNamespace(
            experiment={"max_rounds": 1, "promotion": {"max_tokens": 1234}}
        )
        self.playground._ensure_pysr_preflight = lambda _cfg: self.fail(
            "Completed Promotion replay must not run PySR preflight"
        )

        class FakePromotionExp:
            def __init__(_self, _agent, _config, _round, result_files, max_attempts):
                self.assertIsNone(result_files)

            def set_run_dir(_self, _run_dir):
                pass

            def run(_self, _task):
                return HamiltonPromotionOrchestrationTests.completed_promotion_result()

        with patch("playground.hamilton.core.playground.RoundExp") as round_mock, patch(
            "playground.hamilton.core.playground.PromotionExp", FakePromotionExp
        ):
            result = self.playground.run("task")
        round_mock.assert_not_called()
        self.assertEqual(result["termination_reason"], "scientific_success")

    def test_global_budget_reserves_promotion_before_discovery(self) -> None:
        self.playground.config = SimpleNamespace(
            experiment={
                "max_rounds": 1,
                "max_total_tokens": 100,
                "max_tokens_per_round": 90,
                "pysr_preflight": {"enabled": False},
                "promotion": {"max_tokens": 30, "max_attempts": 2},
            }
        )
        self.playground._ensure_pysr_preflight = lambda _cfg: None
        seen = {}

        class FakeRoundExp:
            def __init__(_self, agent, _config, _round):
                seen["same_round_agent"] = agent is self.agent

            def set_run_dir(_self, _run_dir):
                pass

            def run(_self, _task):
                seen["round_budget"] = self.agent.config.max_total_tokens
                return {
                    "round": 1,
                    "completed_result_files": ["history/round1/results/result.json"],
                    "trajectory": SimpleNamespace(status="completed", steps=[]),
                }

        class FakePromotionExp:
            def __init__(_self, agent, _config, _round, result_files, max_attempts):
                seen["same_promotion_agent"] = agent is self.agent
                seen["result_files"] = result_files

            def set_run_dir(_self, _run_dir):
                pass

            def run(_self, _task):
                seen["promotion_budget"] = self.agent.config.max_total_tokens
                return HamiltonPromotionOrchestrationTests.completed_promotion_result()

        with patch("playground.hamilton.core.playground.RoundExp", FakeRoundExp), patch(
            "playground.hamilton.core.playground.PromotionExp", FakePromotionExp
        ):
            self.playground.run("task")
        self.assertTrue(seen["same_round_agent"])
        self.assertTrue(seen["same_promotion_agent"])
        self.assertEqual(seen["round_budget"], 70)
        self.assertEqual(seen["promotion_budget"], 30)
        self.assertEqual(self.agent.config.max_total_tokens, 999)


class HamiltonWorkspaceTemplateTests(unittest.TestCase):
    def test_custom_task_template_seeds_blind_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            custom_task = root / "docs" / "blind_task.md"
            custom_task.parent.mkdir(parents=True)
            custom_task.write_text("# Blind task\nNo prior result.", encoding="utf-8")
            default_input = root / "playground" / "hamilton" / "workspace" / "input"
            default_input.mkdir(parents=True)
            (default_input / "train.txt").write_text("public", encoding="utf-8")

            playground = object.__new__(HamiltonPlayground)
            playground.workspace_dir = root / "run" / "workspace"
            playground._project_root = root
            playground.config = SimpleNamespace(
                experiment={
                    "task_template": "docs/blind_task.md",
                    "max_total_evals": 100,
                }
            )
            playground.logger = logging.getLogger("workspace-template-test")
            playground._init_workspace()

            self.assertEqual(
                (playground.workspace_dir / "task.md").read_text(encoding="utf-8"),
                "# Blind task\nNo prior result.",
            )
            self.assertTrue((playground.workspace_dir / "input" / "train.txt").is_file())
            self.assertEqual(
                json.loads(
                    (playground.workspace_dir / ".hamilton_budget.json").read_text(
                        encoding="utf-8"
                    )
                )["max_total_evals"],
                100,
            )


class RoundClosureContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.round_dir = self.workspace / "history" / "round1"
        (self.round_dir / "results").mkdir(parents=True)
        (self.round_dir / "trace.md").write_text("initial trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("initial findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text("initial plan", encoding="utf-8")
        self.exp = object.__new__(PromotionExp)
        self.exp.run_dir = self.workspace
        self.exp.round_num = 1
        self.exp.logger = logging.getLogger("round-closure-test")

    def test_disabled_new_schema_fields_match_legacy_absence(self) -> None:
        legacy = {
            "data": {"train_file": "input/train.csv"},
            "search": {"niterations": 500},
            "verification": {"short_ode": {"enabled": True}},
        }
        expanded = copy.deepcopy(legacy)
        expanded["data"]["standardize_search"] = False
        expanded["verification"]["residual_diagnostics"] = {"enabled": False}
        self.assertEqual(
            PromotionExp._meaningful_config(legacy),
            PromotionExp._meaningful_config(expanded),
        )

    def test_controller_seed_is_not_a_scientific_config_change(self) -> None:
        first = {
            "data": {"train_file": "input/train.csv"},
            "search": {"maxsize": 31, "random_state": 1101},
            "verification": {},
        }
        second = copy.deepcopy(first)
        second["search"]["random_state"] = 1102
        self.assertEqual(
            search_meaningful_config(first),
            search_meaningful_config(second),
        )
        self.assertEqual(
            PromotionExp._meaningful_config(first),
            PromotionExp._meaningful_config(second),
        )
    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def finish_trajectory(task_completed: str = "true") -> SimpleNamespace:
        function = SimpleNamespace(
            name="finish",
            arguments=json.dumps({"message": "closed", "task_completed": task_completed}),
        )
        call = SimpleNamespace(function=function)
        assistant = SimpleNamespace(tool_calls=[call])
        return SimpleNamespace(steps=[SimpleNamespace(assistant_message=assistant)])

    def test_accepts_complete_round_closure(self) -> None:
        before = self.exp._snapshot_closure_artifacts()
        (self.round_dir / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("updated findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text("updated plan", encoding="utf-8")
        (self.round_dir / "results" / "result.json").write_text(
            json.dumps({"status": "completed"}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(before, self.finish_trajectory())
        self.assertTrue(closure["closed"])
        self.assertEqual(closure["completed_result_files"], ["history\\round1\\results\\result.json"])

    def test_accepts_controller_declared_completed_result_on_promotion_resume(self) -> None:
        result = self.round_dir / "results" / "result.json"
        result.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        self.exp.config = SimpleNamespace(
            experiment={
                "resume_completed_result": "history/round1/results/result.json",
            }
        )
        before = self.exp._snapshot_closure_artifacts()
        (self.round_dir / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("updated findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text("updated plan", encoding="utf-8")
        closure = self.exp._check_round_closure(
            before,
            self.finish_trajectory(task_completed="true"),
        )
        self.assertTrue(closure["closed"])
        self.assertEqual(
            closure["completed_result_files"],
            ["history\\round1\\results\\result.json"],
        )

    def test_rejects_round_one_without_required_literature_grounding(self) -> None:
        self.exp.config = SimpleNamespace(
            experiment={"require_literature_grounding": True}
        )
        before = self.exp._snapshot_closure_artifacts()
        (self.round_dir / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("updated findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text("updated plan without priors", encoding="utf-8")
        (self.round_dir / "results" / "result.json").write_text(
            json.dumps({"status": "completed"}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(before, self.finish_trajectory())
        self.assertFalse(closure["closed"])
        self.assertFalse(closure["initial_priors"]["valid"])

    def test_rejects_missing_promotion_and_finish(self) -> None:
        before = self.exp._snapshot_closure_artifacts()
        (self.round_dir / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.round_dir / "results" / "result.json").write_text(
            json.dumps({"status": "completed"}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(before, SimpleNamespace(steps=[]))
        self.assertFalse(closure["closed"])
        self.assertFalse(closure["finish_called"])
        self.assertFalse(closure["findings_updated"])
        self.assertFalse(closure["plan_updated"])

    @staticmethod
    def continuation_contract() -> str:
        return """<!-- EVO_NEXT_ROUND_BEGIN -->
## 下一轮实验契约
- 上轮失败：candidate failed
- 原因假设：verification was too short
- 残差证据：validation residual autocorrelation remained high
- 替代解释：derivative noise may create the same autocorrelation
- 下一轮主变量：verification duration
- 保持不变：data and search
- 预期证据：ranking changes
- 预期残差变化：validation residual autocorrelation decreases
- 成功标准：long rollout passes
- 证伪条件：residual autocorrelation does not decrease
- 失败后的策略：change search
<!-- EVO_NEXT_ROUND_END -->"""

    def test_continuing_round_requires_next_round_contract(self) -> None:
        before = self.exp._snapshot_closure_artifacts()
        (self.round_dir / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("updated findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text("updated plan without contract", encoding="utf-8")
        (self.round_dir / "results" / "result.json").write_text(
            json.dumps({"status": "completed", "config": {"search": {"niterations": 1}}}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(before, self.finish_trajectory("false"))
        self.assertFalse(closure["closed"])
        self.assertFalse(closure["continuation_contract_valid"])

    def test_next_round_contract_rejects_empty_residual_falsification(self) -> None:
        contract = self.continuation_contract().replace(
            "- 证伪条件：residual autocorrelation does not decrease",
            "- 证伪条件：",
        )
        (self.workspace / "plan.md").write_text(contract, encoding="utf-8")
        self.assertFalse(self.exp._continuation_contract_valid())

    def test_next_round_contract_accepts_utf8_chinese_field_labels(self) -> None:
        contract = """<!-- EVO_NEXT_ROUND_BEGIN -->
- 上轮失败：candidate failed
- 原因假设：operator family is incomplete
- 残差证据（来源：current frozen result）：lag correlation remains high
- 替代解释：derivative noise may cause the pattern
- 下一轮主变量：search.unary_operators
- 保持不变：all other normalized leaves
- 预期证据：candidate contains a new operator
- 预期残差变化：lag correlation decreases
- 成功标准：score improves
- 证伪条件：score does not improve
- 失败后的策略：test a different single field
<!-- EVO_NEXT_ROUND_END -->"""
        (self.workspace / "plan.md").write_text(contract, encoding="utf-8")
        self.assertTrue(self.exp._continuation_contract_valid())

    def test_next_round_contract_accepts_ascii_parenthesized_label_annotation(self) -> None:
        contract = self.continuation_contract().replace(
            NEXT_ROUND_FIELDS[0],
            f"{NEXT_ROUND_FIELDS[0]}(Round 6)",
            1,
        )
        (self.workspace / "plan.md").write_text(contract, encoding="utf-8")
        self.assertTrue(self.exp._continuation_contract_valid())

    def test_final_round_does_not_require_next_round_contract(self) -> None:
        self.exp.config = SimpleNamespace(experiment={"max_rounds": 1})
        before = self.exp._snapshot_closure_artifacts()
        (self.round_dir / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("updated findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text("updated final plan", encoding="utf-8")
        (self.round_dir / "results" / "result.json").write_text(
            json.dumps({"status": "completed"}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(
            before,
            self.finish_trajectory("false"),
        )
        self.assertTrue(closure["closed"])
        self.assertIsNone(closure["continuation_contract_valid"])

    def test_round_two_requires_meaningful_config_change(self) -> None:
        previous_config = {
            "data": {"train_file": "input/train.csv"},
            "search": {"niterations": 10},
            "verification": {"short_ode": {"duration": 1.0}},
            "output": {"result_file": "old.json"},
        }
        (self.round_dir / "results" / "previous.json").write_text(
            json.dumps({"status": "completed", "config": previous_config}),
            encoding="utf-8",
        )
        self.exp.round_num = 2
        round_two = self.workspace / "history" / "round2"
        (round_two / "results").mkdir(parents=True)
        (round_two / "trace.md").write_text("initial trace", encoding="utf-8")
        before = self.exp._snapshot_closure_artifacts()

        (round_two / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("updated findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text(self.continuation_contract(), encoding="utf-8")
        (round_two / "results" / "same.json").write_text(
            json.dumps({"status": "completed", "config": previous_config}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(before, self.finish_trajectory("false"))
        self.assertFalse(closure["closed"])
        self.assertFalse(closure["meaningful_config_change"])

        changed_config = json.loads(json.dumps(previous_config))
        changed_config["verification"]["short_ode"]["duration"] = 5.0
        (round_two / "results" / "same.json").unlink()
        (round_two / "results" / "changed.json").write_text(
            json.dumps({"status": "completed", "config": changed_config}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(before, self.finish_trajectory("false"))
        self.assertTrue(closure["closed"])
        self.assertTrue(closure["meaningful_config_change"])
        self.assertEqual(
            closure["changed_config_fields"],
            ["verification.short_ode.duration"],
        )

    def test_round_two_accepts_authorized_warm_start_noop_continue(self) -> None:
        previous_config = {
            "data": {"train_file": "input/train.csv"},
            "search": {"niterations": 10, "parsimony": 0.001},
            "verification": {"short_ode": {"duration": 1.0}},
        }
        (self.round_dir / "results" / "previous.json").write_text(
            json.dumps({"status": "completed", "config": previous_config}),
            encoding="utf-8",
        )
        (self.workspace / ".hamilton_search_control.json").write_text(
            json.dumps({
                "schema_version": 1,
                "search_advancement": {"min_score_improvement": 0.0},
                "trust_region": {
                    "allow_noop_continue": True,
                    "max_anchor_distance": 2,
                    "max_step_changes": 1,
                    "rollback_after_stale_rounds": 2,
                },
                "dynamic_budget": {
                    "enabled": False,
                    "base_evals": 100,
                    "min_evals": 100,
                    "max_evals": 100,
                    "rounding_quantum": 100,
                },
                "max_rounds": 3,
            }),
            encoding="utf-8",
        )
        self.exp.round_num = 2
        round_two = self.workspace / "history" / "round2"
        (round_two / "results").mkdir(parents=True)
        (round_two / "trace.md").write_text("initial trace", encoding="utf-8")
        before = self.exp._snapshot_closure_artifacts()
        (round_two / "trace.md").write_text("updated trace", encoding="utf-8")
        (self.workspace / "findings.md").write_text("updated findings", encoding="utf-8")
        (self.workspace / "plan.md").write_text(
            self.continuation_contract(), encoding="utf-8"
        )
        current_config = copy.deepcopy(previous_config)
        current_config["search_session"] = {
            "mode": "warm_start",
            "round": 2,
            "round_action": "continue",
        }
        (round_two / "results" / "continued.json").write_text(
            json.dumps({"status": "completed", "config": current_config}),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(
            before, self.finish_trajectory("false")
        )
        self.assertTrue(closure["closed"])
        self.assertTrue(closure["meaningful_config_change"])
        self.assertTrue(closure["single_config_change"])
        self.assertEqual(closure["changed_config_fields"], [])

    def test_round_two_rejects_multiple_config_changes(self) -> None:
        previous_config = {
            "data": {"train_file": "input/train.csv"},
            "search": {"niterations": 10, "parsimony": 0.1},
            "verification": {"short_ode": {"duration": 1.0}},
        }
        (self.round_dir / "results" / "previous.json").write_text(
            json.dumps({"status": "completed", "config": previous_config}),
            encoding="utf-8",
        )
        self.exp.round_num = 2
        round_two = self.workspace / "history" / "round2"
        (round_two / "results").mkdir(parents=True)
        (round_two / "trace.md").write_text("initial trace", encoding="utf-8")
        changed = json.loads(json.dumps(previous_config))
        changed["search"]["niterations"] = 20
        changed["search"]["parsimony"] = 0.01
        (round_two / "results" / "changed.json").write_text(
            json.dumps({"status": "completed", "config": changed}),
            encoding="utf-8",
        )
        valid, fields = self.exp._single_config_change(
            ["history/round2/results/changed.json"]
        )
        self.assertFalse(valid)
        self.assertEqual(fields, ["search.niterations", "search.parsimony"])


class ScientificGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.exp = object.__new__(PromotionExp)
        self.exp.run_dir = self.workspace
        self.exp.round_num = 2
        self.exp.config = SimpleNamespace(experiment={"scientific_governance": True})
        self.exp.logger = __import__("logging").getLogger("scientific-governance-test")
        for round_num, score in ((1, 0.8), (2, 0.9)):
            results = self.workspace / "history" / f"round{round_num}" / "results"
            results.mkdir(parents=True)
            (results / f"r{round_num}.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "config": {
                            "data": {"train_file": "input/train.csv"},
                            "search": {"max_evals": 10 * round_num},
                            "verification": {
                                "residual_diagnostics": {"enabled": True}
                            },
                        },
                        "selected": {
                            "scientific_score": score,
                            "simplified_equation": f"eq{round_num}",
                        },
                        "verification": {
                            "residual_diagnostics": {
                                "enabled": True,
                                "status": "completed",
                                "validation": {
                                    "state_dependence": {
                                        "strongest_absolute_correlation": {
                                            "signal": "v",
                                            "value": 0.25 + 0.01 * round_num,
                                        }
                                    },
                                    "temporal_structure": {
                                        "strongest_reported_autocorrelation": {
                                            "lag": 5,
                                            "value": 0.4 + 0.01 * round_num,
                                        }
                                    },
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
        self.write_residual_feedback()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_residual_feedback(
        self,
        *,
        state_value: float = 0.27,
        temporal_value: float = 0.42,
        alternatives: list[str] | None = None,
    ) -> None:
        feedback = {
            "round": 2,
            "result_file": "history/round2/results/r2.json",
            "strongest_state_dependence": {"signal": "v", "value": state_value},
            "strongest_temporal_dependence": {"lag": 5, "value": temporal_value},
            "interpretation": "validation residual retains state and temporal structure",
            "alternative_explanations": alternatives or ["derivative estimation bias"],
            "limitations": ["the pattern does not identify a unique missing term"],
            "next_testable_question": "does one controlled intervention reduce the pattern",
        }
        (self.workspace / "findings.md").write_text(
            "<!-- EVO_RESIDUAL_FEEDBACK_BEGIN -->\n"
            + json.dumps(feedback, ensure_ascii=False)
            + "\n<!-- EVO_RESIDUAL_FEEDBACK_END -->",
            encoding="utf-8",
        )

    def write_decision(
        self,
        *,
        incumbent: str = "history/round1/results/r1.json",
        incumbent_action: str = "retain",
        claim_strength: str = "supported",
        evidence: list[str] | None = None,
        alternatives_tested: int = 0,
        promotion_gate_passed: bool = False,
        gate_passed: bool = False,
        solver_completion_only: bool = False,
    ) -> None:
        decision = {
            "incumbent": {"result_file": incumbent, "action": incumbent_action},
            "claims": [
                {
                    "statement": "intervention changed the measured outcome",
                    "strength": claim_strength,
                    "evidence": evidence or ["history/round2/results/r2.json: scientific_score=0.9"],
                    "alternatives_tested": alternatives_tested,
                }
            ],
            "protocol_evidence": {
                "valid_result_files": [
                    "history/round1/results/r1.json",
                    "history/round2/results/r2.json",
                ],
                "invalid_attempts_used_as_scientific_evidence": False,
            },
            "scale_diagnostics": {
                "method": "standardized_feature_effect",
                "raw_coefficient_comparison": False,
                "evidence": "diagnostics.linear_raw_features.scale_aware.standardized_effect",
            },
            "search_advancement_gates": [
                {
                    "name": "candidate validity",
                    "passed": promotion_gate_passed,
                    "evidence": "validation and rollout thresholds",
                }
            ],
            "scientific_gates": [
                {
                    "name": "held-out validation",
                    "passed": gate_passed,
                    "evidence": "validation R2 threshold comparison",
                }
            ],
            "solver_completion_only": solver_completion_only,
            "next_strategy": {
                "diagnosed_failure": "held-out validation did not improve",
                "evidence": "round2 score 0.9 is worse than 0.8",
                "residual_evidence": {
                    "result_file": "history/round2/results/r2.json",
                    "finding": "both",
                    "observed": "state correlation=0.27 and lag-5 autocorrelation=0.42",
                },
                "config_field": "search.max_evals",
                "config_patch": {"search.max_evals": 30},
                "expected_effect": "lower held-out scientific score",
                "alternative_explanation": "derivative estimation bias may create the pattern",
                "expected_residual_change": "state and temporal dependence decrease",
                "risks": ["more compute may not diversify structures"],
                "falsification": "score remains greater than or equal to 0.8",
            },
        }
        (self.workspace / "plan.md").write_text(
            "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
            + json.dumps(decision, ensure_ascii=False)
            + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->",
            encoding="utf-8",
        )

    def test_retains_lower_scoring_historical_incumbent(self) -> None:
        self.write_decision()
        audit = self.exp._audit_scientific_decision("false")
        self.assertTrue(audit["valid"])
        self.assertEqual(
            audit["incumbent_expected"]["path"],
            "history/round1/results/r1.json",
        )

    def test_rejects_latest_result_when_its_score_is_worse(self) -> None:
        self.write_decision(
            incumbent="history/round2/results/r2.json",
            incumbent_action="promote",
            promotion_gate_passed=True,
        )
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["valid"])
        self.assertFalse(audit["incumbent_valid"])

    def test_lower_score_requires_promotion_gate(self) -> None:
        result = self.workspace / "history" / "round2" / "results" / "r2.json"
        payload = json.loads(result.read_text(encoding="utf-8"))
        payload["selected"]["scientific_score"] = 0.7
        result.write_text(json.dumps(payload), encoding="utf-8")

        self.write_decision(promotion_gate_passed=False)
        retained = self.exp._audit_scientific_decision("false")
        self.assertTrue(retained["incumbent_valid"])

        self.write_decision(
            incumbent="history/round2/results/r2.json",
            incumbent_action="promote",
            promotion_gate_passed=True,
        )
        promoted = self.exp._audit_scientific_decision("false")
        self.assertTrue(promoted["incumbent_valid"])

    def test_legacy_promotion_gate_name_remains_recoverable(self) -> None:
        self.write_decision()
        plan = self.workspace / "plan.md"
        plan.write_text(
            plan.read_text(encoding="utf-8").replace(
                '"search_advancement_gates"',
                '"promotion_gates"',
            ),
            encoding="utf-8",
        )
        audit = self.exp._audit_scientific_decision("false")
        self.assertTrue(audit["search_advancement_gates_valid"])

    def test_rejects_confirmation_without_alternative_test(self) -> None:
        self.write_decision(
            claim_strength="confirmed",
            evidence=["experiment one", "experiment two"],
            alternatives_tested=0,
        )
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["claims_valid"])

    def test_rejects_solver_only_success(self) -> None:
        self.write_decision(gate_passed=True, solver_completion_only=True)
        audit = self.exp._audit_scientific_decision("true")
        self.assertFalse(audit["success_gates_valid"])

    def test_rejects_multiple_next_strategy_fields(self) -> None:
        self.write_decision()
        plan = self.workspace / "plan.md"
        content = plan.read_text(encoding="utf-8")
        content = content.replace(
            '"config_field": "search.max_evals"',
            '"config_field": "search.max_evals, search.niterations"',
        )
        plan.write_text(content, encoding="utf-8")
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["plan_quality_valid"])

    def test_rejects_next_strategy_patch_with_multiple_fields(self) -> None:
        self.write_decision()
        plan = self.workspace / "plan.md"
        content = plan.read_text(encoding="utf-8")
        content = content.replace(
            '"config_patch": {"search.max_evals": 30}',
            '"config_patch": {"search.max_evals": 30, "search.niterations": 20}',
        )
        plan.write_text(content, encoding="utf-8")
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["plan_quality_valid"])

    def test_rejects_protocol_evidence_that_includes_invalid_attempt(self) -> None:
        self.write_decision()
        plan = self.workspace / "plan.md"
        content = plan.read_text(encoding="utf-8")
        content = content.replace(
            '"history/round2/results/r2.json"]',
            '"history/round2/results/r2.json", '
            '"history/protocol_invalid/round2_attempt/results/invalid.json"]',
        )
        plan.write_text(content, encoding="utf-8")
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["protocol_evidence_valid"])
        self.assertFalse(audit["valid"])

    def test_rejects_protocol_evidence_without_explicit_exclusion(self) -> None:
        self.write_decision()
        plan = self.workspace / "plan.md"
        content = plan.read_text(encoding="utf-8").replace(
            '"invalid_attempts_used_as_scientific_evidence": false',
            '"invalid_attempts_used_as_scientific_evidence": true',
        )
        plan.write_text(content, encoding="utf-8")
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["protocol_evidence_valid"])

    def test_rejects_missing_residual_feedback_block(self) -> None:
        (self.workspace / "findings.md").write_text("narrative only", encoding="utf-8")
        self.write_decision()
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["residual_feedback_valid"])
        self.assertFalse(audit["valid"])

    def test_rejects_disabled_residual_diagnostics(self) -> None:
        result = self.workspace / "history" / "round2" / "results" / "r2.json"
        payload = json.loads(result.read_text(encoding="utf-8"))
        payload["verification"]["residual_diagnostics"] = {
            "enabled": False,
            "status": "disabled",
        }
        result.write_text(json.dumps(payload), encoding="utf-8")
        self.write_decision()
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["residual_feedback_valid"])

    def test_rejects_residual_values_not_matching_result(self) -> None:
        self.write_residual_feedback(state_value=0.99)
        self.write_decision()
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["residual_feedback_valid"])

    def test_rejects_residual_finding_without_alternative_explanation(self) -> None:
        self.write_residual_feedback(alternatives=[])
        findings = self.workspace / "findings.md"
        content = findings.read_text(encoding="utf-8").replace(
            '["derivative estimation bias"]',
            "[]",
        )
        findings.write_text(content, encoding="utf-8")
        self.write_decision()
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["residual_feedback_valid"])

    def test_rejects_next_strategy_without_expected_residual_change(self) -> None:
        self.write_decision()
        plan = self.workspace / "plan.md"
        content = plan.read_text(encoding="utf-8")
        content = content.replace(
            '"expected_residual_change": "state and temporal dependence decrease",',
            "",
        )
        plan.write_text(content, encoding="utf-8")
        audit = self.exp._audit_scientific_decision("false")
        self.assertFalse(audit["plan_quality_valid"])

    def test_round_closure_requires_and_accepts_linked_residual_feedback(self) -> None:
        trace = self.workspace / "history" / "round2" / "trace.md"
        trace.write_text("initial trace", encoding="utf-8")
        (self.workspace / "plan.md").write_text("initial plan", encoding="utf-8")
        before = self.exp._snapshot_closure_artifacts()

        trace.write_text("updated trace", encoding="utf-8")
        findings = self.workspace / "findings.md"
        findings.write_text(
            findings.read_text(encoding="utf-8") + "\nround 2 promoted",
            encoding="utf-8",
        )
        self.write_decision()
        plan = self.workspace / "plan.md"
        plan.write_text(
            plan.read_text(encoding="utf-8")
            + "\n"
            + RoundClosureContractTests.continuation_contract(),
            encoding="utf-8",
        )
        closure = self.exp._check_round_closure(
            before,
            RoundClosureContractTests.finish_trajectory("false"),
            completed_results=["history/round2/results/r2.json"],
        )
        self.assertTrue(closure["scientific_decision"]["residual_feedback_valid"])
        self.assertTrue(closure["closed"])


class ProtectedDataToolTests(unittest.TestCase):
    def test_editor_refuses_protected_tabular_file(self) -> None:
        session = SimpleNamespace(
            config=SimpleNamespace(blocked_read_extensions=[".csv"])
        )
        output, info = EditorTool().execute(
            session,
            json.dumps({"command": "view", "path": "C:\\workspace\\input\\secret.csv"}),
        )
        self.assertIn("Access denied", output)
        self.assertIn("error", info)

    def test_directory_listing_hides_protected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "secret.csv").write_text("private", encoding="utf-8")
            (root / "summary.json").write_text("{}", encoding="utf-8")
            output = list_local_directory(str(root), blocked_extensions={".csv"})
            self.assertNotIn("secret.csv", output)
            self.assertIn("summary.json", output)

    def test_editor_refuses_path_outside_active_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            outside = Path(temporary) / "private" / "benchmark.json"
            outside.parent.mkdir()
            outside.write_text('{"answer": "hidden"}', encoding="utf-8")
            session = SimpleNamespace(
                config=SimpleNamespace(
                    blocked_read_extensions=[],
                    workspace_path=str(workspace),
                )
            )
            output, info = EditorTool().execute(
                session,
                json.dumps({"command": "view", "path": str(outside.resolve())}),
            )
            self.assertIn("restricted to the active workspace", output)
            self.assertIn("error", info)


class LiteratureGroundingTests(unittest.TestCase):
    def test_literature_tool_returns_structured_citations(self) -> None:
        payload = {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/example",
                        "title": ["General oscillator energy balance"],
                        "author": [{"given": "Ada", "family": "Researcher"}],
                        "published-online": {"date-parts": [[2025, 1, 2]]},
                        "container-title": ["Journal of Dynamics"],
                        "abstract": "<jats:p>Broad qualitative mechanism.</jats:p>",
                        "type": "journal-article",
                    }
                ]
            }
        }

        with patch.object(LiteratureSearchTool, "_request", return_value=payload):
            output, info = LiteratureSearchTool().execute(
                None,
                json.dumps(
                    {
                        "query": "nonlinear oscillator energy balance",
                        "max_results": 3,
                    }
                ),
            )

        result = json.loads(output)
        self.assertEqual(info["result_count"], 1)
        self.assertEqual(result["results"][0]["year"], 2025)
        self.assertEqual(result["results"][0]["url"], "https://doi.org/10.1234/example")
        self.assertNotIn("<jats", result["results"][0]["abstract"])

    def test_initial_priors_require_citations_and_no_equation_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            plan = {
                "status": "completed",
                "queries": ["restoring mechanisms", "oscillator energy balance"],
                "sources": [
                    {"id": "S1", "title": "Paper one", "year": 2024, "url": "https://doi.org/1"},
                    {"id": "S2", "title": "Paper two", "year": 2025, "url": "https://doi.org/2"},
                ],
                "priors": [
                    {
                        "statement": "Elastic support can provide restoring behavior.",
                        "evidence_sources": ["S1"],
                        "scope": "elastic oscillators",
                        "strength": "hypothesis",
                    },
                    {
                        "statement": "Energy input and dissipation can coexist.",
                        "evidence_sources": ["S1", "S2"],
                        "scope": "flow-coupled oscillators",
                        "strength": "hypothesis",
                    },
                    {
                        "statement": "Operating conditions may share qualitative structure.",
                        "evidence_sources": ["S2"],
                        "scope": "one specimen",
                        "strength": "hypothesis",
                    },
                ],
                "candidate_template_proposed": False,
            }
            (workspace / "plan.md").write_text(
                "<!-- EVO_INITIAL_PRIORS_BEGIN -->\n"
                + json.dumps(plan)
                + "\n<!-- EVO_INITIAL_PRIORS_END -->",
                encoding="utf-8",
            )
            exp = object.__new__(PromotionExp)
            exp.run_dir = workspace
            self.assertTrue(exp._audit_initial_priors()["valid"])

            plan["priors"][0]["statement"] = "a = c1*x"
            (workspace / "plan.md").write_text(
                "<!-- EVO_INITIAL_PRIORS_BEGIN -->\n"
                + json.dumps(plan)
                + "\n<!-- EVO_INITIAL_PRIORS_END -->",
                encoding="utf-8",
            )
            self.assertFalse(exp._audit_initial_priors()["valid"])

    def test_public_task_contains_no_reference_equation(self) -> None:
        content = (
            PROJECT_ROOT / "playground" / "hamilton" / "workspace" / "task.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("EvLOWN", content)
        self.assertNotIn("v^3", content)
        self.assertNotIn("omega^2", content)

    def test_public_workspace_contains_training_data_only(self) -> None:
        input_dir = PROJECT_ROOT / "playground" / "hamilton" / "workspace" / "input"
        names = {path.name for path in input_dir.glob("*.csv")}
        self.assertEqual(
            names,
            {
                "U248_train.csv",
                "U254_train.csv",
                "U260_train.csv",
                "U273_train.csv",
                "U282_train.csv",
            },
        )


class TieredOODTests(unittest.TestCase):
    def test_freeze_bundle_detects_result_or_bundle_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            result_dir = workspace / "history" / "round1" / "results"
            result_dir.mkdir(parents=True)
            result_path = result_dir / "candidate.json"
            result_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "config": {
                            "data": {
                                "train_file": "input/U248_train.csv",
                                "feature_columns": ["x", "v"],
                                "target_column": "a",
                                "time_column": "t",
                            },
                            "verification": {
                                "short_ode": {
                                    "position_column": "x",
                                    "velocity_column": "v",
                                }
                            },
                        },
                        "selected": {"simplified_equation": "-x - v"},
                        "data": {},
                    }
                ),
                encoding="utf-8",
            )
            frozen_path = Path(temporary) / "private" / "frozen.json"
            bundle = freeze_candidate_bundle(
                workspace,
                ["history/round1/results/candidate.json"],
                frozen_path,
            )
            self.assertEqual(
                bundle["exact_condition_models"]["2.48"]["source_sha256"],
                __import__("hashlib").sha256(result_path.read_bytes()).hexdigest(),
            )
            load_frozen_bundle(frozen_path)

            result_path.write_text(
                result_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OODProtocolError, "source result changed"):
                verify_frozen_sources(bundle, workspace)

            tampered = json.loads(frozen_path.read_text(encoding="utf-8"))
            tampered["exact_condition_models"]["2.48"]["equation"] = "0"
            frozen_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(OODProtocolError, "hash mismatch"):
                load_frozen_bundle(frozen_path)

    def test_tier1_evaluates_same_condition_different_initial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private"
            workspace = root / "workspace"
            private.mkdir()
            workspace.mkdir()
            t = np.linspace(0.0, 2.0 * np.pi, 300)
            pd.DataFrame(
                {
                    "t": t,
                    "x": np.cos(t),
                    "v": -np.sin(t),
                    "a": -np.cos(t),
                }
            ).to_csv(private / "paired.csv", index=False)
            model = {
                "equation": "-x",
                "feature_columns": ["x", "v"],
                "target_column": "a",
                "time_column": "t",
                "position_column": "x",
                "velocity_column": "v",
                "training_conditions": ["2.48"],
                "condition": "2.48",
            }
            core = {"2.48": model}
            bundle = {
                "schema_version": 1,
                "status": "frozen",
                "exact_condition_models": core,
                "global_model": None,
            }
            bundle["freeze_id"] = canonical_hash(
                {
                    "exact_condition_models": core,
                    "global_model": None,
                }
            )
            manifest = {
                "conditions": {
                    "2.48": {
                        "public_training_file": "input/U248_train.csv",
                        "paired_initial_condition_file": "paired.csv",
                    }
                },
                "tier_policy": {
                    "tier1": {
                        "feedback_policy": "development_summary",
                        "trajectory_duration": 2.0 * np.pi,
                        "trajectory_points": 300,
                        "state_limit": 1000,
                    }
                },
            }
            result = evaluate_tier("tier1", bundle, manifest, workspace, private)
            evaluation = result["evaluations"][0]
            self.assertAlmostEqual(evaluation["pointwise"]["r2"], 1.0, places=12)
            self.assertEqual(evaluation["trajectory"]["status"], "completed")
            self.assertLess(evaluation["trajectory"]["position_rmse"], 1e-4)
            summary = release_summary(result)
            self.assertNotIn("paired.csv", json.dumps(summary))

    def test_tier2_rejects_condition_specific_model(self) -> None:
        bundle = {
            "freeze_id": "frozen",
            "exact_condition_models": {"2.48": {}},
            "global_model": None,
        }
        manifest = {
            "tier_policy": {"tier2": {"feedback_policy": "promotion_summary"}},
            "conditions": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(OODProtocolError, "requires a frozen global"):
                evaluate_tier("tier2", bundle, manifest, root, root)

    def test_private_ledger_enforces_total_access_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = OODAccessLedger(
                Path(temporary) / "ledger.json",
                {"tier1": {"max_total_evaluations": 1}},
            )
            index = ledger.begin("tier1", "freeze-a")
            ledger.finish(index, "completed")
            with self.assertRaisesRegex(OODProtocolError, "budget exhausted"):
                ledger.begin("tier1", "freeze-b")

    def test_final_tier3_attestation_locks_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private"
            workspace = root / "workspace"
            private.mkdir()
            workspace.mkdir()
            result_path = private / "tier3-result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tier": "tier3",
                        "status": "completed",
                        "freeze_id": "freeze-final",
                        "feedback_policy": "final_only",
                        "evaluations": [],
                    }
                ),
                encoding="utf-8",
            )
            (private / "ood_access_ledger.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "accesses": [
                            {
                                "tier": "tier3",
                                "freeze_id": "freeze-final",
                                "status": "completed",
                                "result_file": str(result_path),
                                "result_sha256": __import__("hashlib").sha256(
                                    result_path.read_bytes()
                                ).hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = workspace / "final_ood_attestation.json"
            attestation = finalize_tier3(private, result_path, workspace, output)
            self.assertTrue(attestation["no_further_adaptation_allowed"])
            self.assertTrue(output.is_file())
            self.assertTrue((workspace / ".hamilton_final_ood.lock").is_file())


if __name__ == "__main__":
    unittest.main()
