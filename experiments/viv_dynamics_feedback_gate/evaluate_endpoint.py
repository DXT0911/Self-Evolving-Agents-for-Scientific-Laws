#!/usr/bin/env python3
"""Evaluate a frozen public-U248 endpoint without PySR, Julia, or an LLM."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import sympy

from .build_launch_bundle import DATA, ROOT, RUNNER, long_horizon


def load_runner():
    spec = importlib.util.spec_from_file_location("viv_gate_runner", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load deterministic runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def incumbent_result(workspace: Path) -> Path:
    state = json.loads((workspace / ".hamilton_search_state.json").read_text(encoding="utf-8"))
    relative = state["incumbent"]["result_file"]
    path = (workspace / relative).resolve()
    path.relative_to(workspace.resolve())
    return path


def evaluate(source_result: Path) -> dict:
    payload = json.loads(source_result.read_text(encoding="utf-8"))
    if payload.get("status") != "completed":
        raise ValueError("endpoint source is not completed")
    equation = payload["selected"]["simplified_equation"]
    expression = sympy.sympify(equation)
    frame = pd.read_csv(DATA, usecols=["t", "x", "v", "a"])
    split = int(len(frame) * 0.8)
    train, validation = frame.iloc[:split].copy(), frame.iloc[split:].copy()
    config = {
        "data": {"time_column": "t", "feature_columns": ["x", "v"], "target_column": "a"},
        "verification": {
            "candidate_ranking": {"failure_penalty": 100.0},
            "short_ode": {"enabled": True, "position_column": "x", "velocity_column": "v",
                          "duration": 10.0, "points": 1000, "state_limit": 1_000_000.0},
            "long_horizon_dynamics": long_horizon(),
        },
    }
    runner = load_runner()
    return {
        "schema_version": 1,
        "status": "completed",
        "source_result": str(source_result),
        "source_sha256": digest(source_result),
        "equation": equation,
        "public_validation_metrics": payload.get("metrics"),
        "short_ode": runner.run_short_ode(expression, config, validation),
        "long_horizon_dynamics": runner.run_long_horizon_dynamics(
            expression, config, train, validation
        ),
        "execution": {"uses_llm": False, "uses_pysr_or_julia": False,
                      "uses_private_ood": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--source-result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.workspace) == bool(args.source_result):
        parser.error("provide exactly one of --workspace or --source-result")
    source = incumbent_result(args.workspace.resolve()) if args.workspace else args.source_result.resolve()
    report = evaluate(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

