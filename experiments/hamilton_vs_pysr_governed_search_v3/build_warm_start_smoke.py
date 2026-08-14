#!/usr/bin/env python3
"""Materialize the v3 ordinary-vs-segmented-warm-start equivalence smoke."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / "experiments/hamilton_vs_pysr_governed_search/prepared_data/static_s01/input/data.csv"
OUTPUT = HERE / "runs/warm_start_equivalence"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def base(experiment_id: str, max_evals: int, result_file: str, run_directory: str) -> dict:
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "data": {
            "train_file": "input/data.csv", "allowed_files": ["input/data.csv"],
            "time_column": "t", "feature_columns": ["x1", "x2"], "target_column": "y",
            "max_rows": None, "search_stride": 10, "standardize_search": False,
            "validation_fraction": 0.2,
        },
        "search": {
            "engine": "pysr", "binary_operators": ["+", "-", "*", "/"],
            "unary_operators": ["sin", "cos", "exp"], "niterations": 1000,
            "max_evals": max_evals, "populations": 8, "population_size": 32,
            "tournament_selection_n": 12, "maxsize": 31, "parsimony": 0.001,
            "random_state": 6101, "top_k": 10,
        },
        "verification": {
            "short_ode": {"enabled": False},
            "candidate_ranking": {
                "enabled": True, "max_candidates": 10,
                "weights": {"validation_nrmse": 1.0, "trajectory_nrmse": 0.0, "complexity": 0.05},
                "failure_penalty": 100.0,
            },
            "residual_diagnostics": {
                "enabled": True, "max_lag": 50, "feature_bins": 4,
                "phase_bins": 8, "high_frequency_fraction": 0.25,
            },
        },
        "output": {"result_file": result_file, "run_directory": run_directory},
    }


def build() -> Path:
    for arm in ("ordinary", "warm", "warm_modify"):
        workspace = OUTPUT / arm
        (workspace / "input").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE, workspace / "input/data.csv")
    ordinary = base("v3_smoke_ordinary", 2000, "results/result.json", "results/pysr")
    write_json(OUTPUT / "ordinary/experiment.json", ordinary)
    for round_number in (1, 2):
        warm = base(
            f"v3_smoke_warm_round{round_number}", 1000,
            f"history/round{round_number}/results/result.json", "session/pysr",
        )
        warm["search_session"] = {
            "mode": "warm_start", "session_id": "static-s01-repeat-1",
            "round": round_number, "final_round": round_number == 2,
            "round_action": "initialize" if round_number == 1 else "continue",
            "compatible_change_fields": ["search.parsimony"],
        }
        write_json(OUTPUT / f"warm/history/round{round_number}/experiment.json", warm)
    write_json(OUTPUT / "warm/.hamilton_search_control.json", {
        "schema_version": 1,
        "search_advancement": {"min_score_improvement": 0.0},
        "trust_region": {
            "enabled": True, "allow_noop_continue": True,
            "max_anchor_distance": 2, "max_step_changes": 1,
            "rollback_after_stale_rounds": 2,
        },
        "dynamic_budget": {
            "enabled": False, "base_evals": 1000, "min_evals": 1000,
            "max_evals": 1000, "rounding_quantum": 1000,
        },
        "max_rounds": 2,
    })
    (OUTPUT / "warm/plan.md").write_text(
        "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
        + json.dumps({"next_strategy": {
            "action": "continue", "config_field": None, "config_patch": {}
        }})
        + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->\n",
        encoding="utf-8",
    )
    for round_number in (1, 2):
        modified = base(
            f"v3_smoke_modify_round{round_number}", 1000,
            f"history/round{round_number}/results/result.json", "session/pysr",
        )
        if round_number == 2:
            modified["search"]["parsimony"] = 0.002
        modified["search_session"] = {
            "mode": "warm_start", "session_id": "static-s01-modify-repeat-1",
            "round": round_number, "final_round": round_number == 2,
            "round_action": "initialize" if round_number == 1 else "modify",
            "compatible_change_fields": ["search.parsimony"],
        }
        write_json(
            OUTPUT / f"warm_modify/history/round{round_number}/experiment.json",
            modified,
        )
    write_json(
        OUTPUT / "warm_modify/.hamilton_search_control.json",
        json.loads(
            (OUTPUT / "warm/.hamilton_search_control.json").read_text(encoding="utf-8")
        ),
    )
    (OUTPUT / "warm_modify/plan.md").write_text(
        "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
        + json.dumps({"next_strategy": {
            "action": "modify", "config_field": "search.parsimony",
            "config_patch": {"search.parsimony": 0.002}
        }})
        + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->\n",
        encoding="utf-8",
    )
    return OUTPUT


if __name__ == "__main__":
    print(build())
