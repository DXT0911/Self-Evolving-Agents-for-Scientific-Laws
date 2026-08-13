#!/usr/bin/env python3
"""Materialize the authorized v2 operational gate without executing it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import (
    hamilton_task,
    materialize_input,
    runner_config,
    sha256,
    write_json,
    write_text,
)

V1 = HERE.parent / "hamilton_vs_pysr_governed_search"
DEFAULT_OUTPUT = HERE / "launch_bundle" / "operational_gate"
TASKS = ("static_s02", "dynamic_d02")
REPEAT = "repeat_1"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    manifest = load_yaml(HERE / "manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    config_path = REPO / "configs/hamilton/config_governed_pysr_v2.yaml"
    if manifest["status"] != "frozen_pre_execution":
        raise ValueError("v2 protocol must remain frozen before operational execution")
    wave = next(item for item in manifest["waves"] if item["id"] == "operational_gate")
    if tuple(wave["tasks"]) != TASKS or wave["repeats"] != [REPEAT]:
        raise ValueError("operational wave differs from the frozen task/repeat set")

    search = manifest["search"]
    bounds = {
        "base_evals": int(search["dynamic_budget"]["base"]),
        "min_evals": int(search["dynamic_budget"]["min"]),
        "max_evals": int(search["dynamic_budget"]["max"]),
        "rounding_quantum": int(search["dynamic_budget"]["quantum"]),
    }
    seeds = [int(value) for value in manifest["seed_plan"][REPEAT]["episodes"]]
    shared_search = dict(specs["shared_search"])
    shared_search["unary_operators"] = list(search["initial_unary_operators"])
    jobs: list[dict[str, Any]] = []

    for task_id in TASKS:
        task = dict(specs["tasks"][task_id])
        task["_candidate_ranking"] = task.get(
            "candidate_ranking_override", specs["shared_verification"]["candidate_ranking"]
        )
        source = (V1 / task["input"]).resolve()
        if not source.is_file() or sha256(source) != task["input_sha256"]:
            raise ValueError(f"missing or changed prepared input: {source}")

        hroot = output / "governed_hamilton" / task_id / REPEAT
        workspace = hroot / "workspaces" / "task_0"
        materialize_input(source, workspace / "input/data.csv", task["input_sha256"])
        baseline = runner_config(
            task_id, task, shared_search, bounds["base_evals"], seeds[0],
            f"v2_hamilton__{task_id}__r1__round1", "history/round1/results/result.json",
        )
        write_json(workspace / "round1_baseline.json", baseline)
        write_json(workspace / ".hamilton_seed_plan.json", {
            "schema_version": 1, "task_id": task_id, "repeat_id": REPEAT,
            "round_seeds": seeds, "controller_owned": True,
        })
        write_text(workspace / "task.md", hamilton_task(
            task_id, task, baseline,
            int(search["max_total_requested_evals_per_arm_task_repeat"]), bounds, seeds,
        ))
        jobs.append({
            "arm": "governed_hamilton", "task_id": task_id, "repeat_id": REPEAT,
            "workspace": relative(workspace), "state": "ready",
            "commands": [["python", relative(REPO / "run.py"), "--agent", "hamilton",
                "--config", relative(config_path), "--task",
                f"Execute frozen v2 task {task_id}, {REPEAT}.", "--run-dir", relative(hroot)]],
        })

        for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
            bworkspace = output / arm / task_id / REPEAT / "workspace"
            materialize_input(source, bworkspace / "input/data.csv", task["input_sha256"])
            jobs.append({
                "arm": arm, "task_id": task_id, "repeat_id": REPEAT,
                "workspace": relative(bworkspace),
                "state": "waiting_for_hamilton_allowance_trace", "commands": [],
            })

    matrix = {
        "schema_version": 1, "wave": "operational_gate", "execution_permitted": True,
        "execution_order": "hamilton_then_freeze_then_three_pysr_controls",
        "jobs": jobs,
    }
    write_json(output / "run_matrix.json", matrix)
    lock = {
        "schema_version": 1, "wave": "operational_gate", "job_count": len(jobs),
        "task_count": len(TASKS), "arm_count": 4,
        "hashes": {
            relative(HERE / "manifest.yaml"): sha256(HERE / "manifest.yaml"),
            relative(HERE / "dataset_split.yaml"): sha256(HERE / "dataset_split.yaml"),
            relative(config_path): sha256(config_path),
            relative(output / "run_matrix.json"): sha256(output / "run_matrix.json"),
        },
    }
    write_json(output / "freeze_lock.json", lock)
    return lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == "__main__":
    main()
