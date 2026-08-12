#!/usr/bin/env python3
"""Replay frozen public VIV candidates through the Tier-0 long-horizon verifier.

This is an offline post-hoc calibration utility. It neither imports PySR nor calls an
LLM, and its input surface is intentionally fixed to the public U248 training record
and the completed operational-gate result files.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd
import sympy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = HERE / "launch_bundle"
PUBLIC_DATA = ROOT / "playground" / "hamilton" / "workspace" / "input" / "U248_train.csv"
DEFAULT_OUTPUT = BUNDLE / "offline_analysis" / "viv_long_horizon_replay.json"
RUNNER_PATH = (
    ROOT
    / "evomaster"
    / "skills"
    / "run-sr-experiment"
    / "scripts"
    / "run_experiment.py"
)


PROFILES: dict[str, dict[str, Any]] = {
    "window_30": {"duration": 60.0, "points": 3000, "steady_state_fraction": 0.3},
    "primary_40": {"duration": 60.0, "points": 3000, "steady_state_fraction": 0.4},
    "window_50": {"duration": 60.0, "points": 3000, "steady_state_fraction": 0.5},
    "resolution_2x": {"duration": 60.0, "points": 6000, "steady_state_fraction": 0.4},
}


def load_runner():
    spec = importlib.util.spec_from_file_location("viv_replay_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen_result_paths() -> list[tuple[str, str, Path]]:
    records: list[tuple[str, str, Path]] = []
    hamilton = (
        BUNDLE
        / "governed_hamilton"
        / "viv_u248"
        / "repeat_1"
        / "workspaces"
        / "task_0"
        / "history"
    )
    for round_number in (1, 2, 3):
        records.append(
            (
                "governed_hamilton",
                f"round_{round_number}",
                hamilton / f"round{round_number}" / "results" / "result.json",
            )
        )
    records.append(
        (
            "ordinary_pysr",
            "final",
            BUNDLE
            / "ordinary_pysr"
            / "viv_u248"
            / "repeat_1"
            / "workspace"
            / "results"
            / "result.json",
        )
    )
    fixed = BUNDLE / "fixed_schedule_pysr" / "viv_u248" / "repeat_1" / "workspace" / "results"
    for episode in (1, 2, 3):
        records.append(
            ("fixed_schedule_pysr", f"episode_{episode}", fixed / f"episode_{episode}.json")
        )
    return records


def verifier_config(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": {
            "time_column": "t",
            "feature_columns": ["x", "v"],
            "target_column": "a",
        },
        "verification": {
            "candidate_ranking": {"failure_penalty": 100.0},
            "long_horizon_dynamics": {
                "enabled": True,
                "position_column": "x",
                "velocity_column": "v",
                "duration": float(profile["duration"]),
                "points": int(profile["points"]),
                "steady_state_fraction": float(profile["steady_state_fraction"]),
                "min_steady_cycles": 3.0,
                "state_limit": 1_000_000.0,
                "rtol": 1e-8,
                "atol": 1e-10,
                "large_initial_scale": 2.0,
                "stationary_amplitude_fraction": 0.001,
                "zero_initial_policy": "report_only",
                "amplitude_relative_tolerance": 0.2,
                "frequency_relative_tolerance": 0.1,
                "stationarity_relative_tolerance": 0.15,
                "attractor_relative_tolerance": 0.2,
            },
        },
    }


def compact_verdict(result: dict[str, Any]) -> dict[str, Any]:
    gates = result.get("gates", {})
    reference_match = gates.get("reference_match", {})
    attractor = gates.get("attractor_consistency", {})
    return {
        "status": result.get("status"),
        "overall_pass": gates.get("overall_pass"),
        "integration_pass": gates.get("integration"),
        "stationarity_pass": gates.get("stationarity"),
        "reference_match_pass": reference_match.get("passed"),
        "amplitude_relative_error": reference_match.get("amplitude_relative_error"),
        "frequency_relative_error": reference_match.get("frequency_relative_error"),
        "attractor_consistency_pass": attractor.get("passed"),
        "failure_classes": result.get("failure_classes", []),
        "ranking_penalty": result.get("ranking_penalty"),
        "ranking_penalty_components": result.get("ranking_penalty_components", {}),
        "rollout_behavior": {
            name: item.get("qualitative_behavior")
            for name, item in result.get("rollouts", {}).items()
        },
    }


def sensitivity_summary(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    verdicts = list(profiles.values())
    categorical_fields = (
        "overall_pass",
        "integration_pass",
        "stationarity_pass",
        "reference_match_pass",
        "attractor_consistency_pass",
    )
    categorical_stable = all(
        len({item.get(field) for item in verdicts}) == 1 for field in categorical_fields
    )
    failures_stable = len(
        {tuple(item.get("failure_classes", [])) for item in verdicts}
    ) == 1

    def finite_range(field: str) -> dict[str, float] | None:
        values = [
            float(item[field])
            for item in verdicts
            if isinstance(item.get(field), (int, float))
        ]
        if not values:
            return None
        return {"minimum": min(values), "maximum": max(values), "span": max(values) - min(values)}

    return {
        "categorical_stable": categorical_stable,
        "failure_classes_stable": failures_stable,
        "amplitude_error_range": finite_range("amplitude_relative_error"),
        "frequency_error_range": finite_range("frequency_relative_error"),
        "ranking_penalty_range": finite_range("ranking_penalty"),
    }


def replay() -> dict[str, Any]:
    runner = load_runner()
    frame = pd.read_csv(PUBLIC_DATA, usecols=["t", "x", "v", "a"])
    split = int(len(frame) * 0.8)
    train = frame.iloc[:split].copy()
    validation = frame.iloc[split:].copy()
    candidates: list[dict[str, Any]] = []
    cache: dict[tuple[str, str], dict[str, Any]] = {}

    for arm, checkpoint, result_path in frozen_result_paths():
        if not result_path.is_file():
            raise FileNotFoundError(f"completed public result missing: {result_path}")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if payload.get("status") != "completed":
            raise ValueError(f"public result is not completed: {result_path}")
        equation = payload["selected"]["simplified_equation"]
        profile_results: dict[str, dict[str, Any]] = {}
        for profile_name, profile in PROFILES.items():
            cache_key = (equation, profile_name)
            if cache_key not in cache:
                full = runner.run_long_horizon_dynamics(
                    sympy.sympify(equation),
                    verifier_config(profile),
                    train,
                    validation,
                )
                cache[cache_key] = compact_verdict(full)
            profile_results[profile_name] = cache[cache_key]
        candidates.append(
            {
                "arm_id": arm,
                "checkpoint": checkpoint,
                "source_result": str(result_path.relative_to(BUNDLE)).replace("\\", "/"),
                "equation": equation,
                "profiles": profile_results,
                "sensitivity": sensitivity_summary(profile_results),
            }
        )

    return {
        "schema_version": 1,
        "analysis_status": "post_hoc_public_tier0_calibration_not_preregistered",
        "execution": {
            "uses_llm": False,
            "uses_pysr_or_julia": False,
            "uses_private_ood": False,
        },
        "data": {
            "source": str(PUBLIC_DATA.relative_to(ROOT)).replace("\\", "/"),
            "rows": len(frame),
            "discovery_rows": len(train),
            "validation_rows": len(validation),
            "validation_time": [float(validation.iloc[0]["t"]), float(validation.iloc[-1]["t"])],
        },
        "profiles": PROFILES,
        "fixed_thresholds": verifier_config(PROFILES["primary_40"])["verification"][
            "long_horizon_dynamics"
        ],
        "candidates": candidates,
        "limitations": [
            "post-hoc calibration cannot support confirmatory claims",
            "all historical U248 candidates are near-linear and are not independent systems",
            "public Tier 0 evidence does not imply private or OOD generalization",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = replay()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "candidates": len(report["candidates"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
