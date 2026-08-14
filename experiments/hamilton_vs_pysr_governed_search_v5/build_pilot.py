#!/usr/bin/env python3
"""Materialize the frozen v5 full-Hamilton pilot without executing it."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V1 = HERE.parent / "hamilton_vs_pysr_governed_search"
OUTPUT = HERE / "pilot_bundle"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import (
    materialize_input, runner_config, sha256, task_context, write_json, write_text,
)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def build(output: Path = OUTPUT) -> dict[str, Any]:
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    if manifest["status"] != "frozen_pre_execution":
        raise ValueError("manifest is not frozen")
    repeats = list(manifest["repeats"])
    if 4 * len(repeats) * int(manifest["requested_evaluations_per_arm_per_seed"]) != int(
        manifest["requested_evaluations_total"]
    ):
        raise ValueError("evaluation authorization does not reconcile")
    if len(repeats) * int(manifest["max_hamilton_tokens_per_seed"]) != int(
        manifest["max_hamilton_tokens_total"]
    ):
        raise ValueError("token authorization does not reconcile")

    task_id = str(manifest["task"])
    task = dict(specs["tasks"][task_id])
    task["_candidate_ranking"] = task.get(
        "candidate_ranking_override", specs["shared_verification"]["candidate_ranking"]
    )
    source = (V1 / task["input"]).resolve()
    if not source.is_file() or sha256(source) != task["input_sha256"]:
        raise ValueError("new pilot input is absent or changed")
    search = dict(specs["shared_search"])
    search["unary_operators"] = list(manifest["search"]["initial_unary_operators"])
    per_round = int(manifest["requested_evaluations_per_episode"])
    jobs = []

    for item in repeats:
        repeat, seed = str(item["repeat_id"]), int(item["seed"])
        hroot = output / "governed_hamilton" / task_id / repeat
        workspace = hroot / "workspaces/task_0"
        materialize_input(source, workspace / "input/data.csv", task["input_sha256"])
        baseline = runner_config(
            task_id, task, search, per_round, seed,
            f"v5_pilot_hamilton__{task_id}__{repeat}__round1",
            "history/round1/results/result.json",
        )
        baseline["verification"]["structural_diagnostics"] = {"enabled": True}
        baseline["output"]["run_directory"] = "session/pysr"
        baseline["search_session"] = {
            "mode": "warm_start",
            "session_id": f"v5-pilot-{task_id}-{repeat}",
            "round": 1,
            "final_round": False,
            "round_action": "initialize",
            "compatible_change_fields": ["search.parsimony"],
        }
        write_json(workspace / "round1_baseline.json", baseline)
        write_json(workspace / ".hamilton_seed_plan.json", {
            "schema_version": 1, "task_id": task_id, "repeat_id": repeat,
            "round_seeds": [seed, seed, seed], "controller_owned": True,
        })
        write_text(workspace / "task.md", f"""# Frozen full Hamilton v5 pilot

Task `{task_id}`, pair `{repeat}`, seed `{seed}`. Use only the governed runner and
`input/data.csv`; never read raw rows, hidden truth, VIV, sealed/OOD data, or identify
the source. {task_context(task)}

Run three persistent warm rounds of {per_round} requested evaluations. One compressed
DeepSeek-V4-Flash planner call follows each completed round. Its proposal is advisory;
the frozen controller owns actions, patches, budget, retention, and rollback.
""")
        jobs.append({
            "arm": "governed_hamilton", "task_id": task_id, "repeat_id": repeat,
            "workspace": relative(workspace), "state": "ready",
            "evaluation_ceiling": int(manifest["hamilton_ledger_ceiling_per_seed"]),
            "token_ceiling": int(manifest["max_hamilton_tokens_per_seed"]),
            "commands": [[
                "python",
                "experiments/hamilton_vs_pysr_governed_search_v5/execute_governed_hamilton.py",
                "--workspace", relative(workspace),
            ]],
        })
        for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
            cworkspace = output / arm / task_id / repeat / "workspace"
            materialize_input(source, cworkspace / "input/data.csv", task["input_sha256"])
            jobs.append({
                "arm": arm, "task_id": task_id, "repeat_id": repeat,
                "workspace": relative(cworkspace),
                "state": "waiting_for_hamilton_allowance_trace", "commands": [],
            })

    matrix = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "execution_permitted": True,
        "execution_order": "hamilton_serial_then_freeze_then_controls_serial",
        "jobs": jobs,
    }
    write_json(output / "run_matrix.json", matrix)
    locked = [
        HERE / "pilot_manifest.yaml", HERE / "execute_governed_hamilton.py",
        REPO / "configs/hamilton/config_governed_pysr_v5_pilot.yaml",
        REPO / "playground/hamilton/core/compressed_planner.py",
        REPO / "playground/hamilton/core/governed_policy.py",
        REPO / "playground/hamilton/core/search_control.py",
        REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py",
        output / "run_matrix.json",
    ]
    lock = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "hashes": {relative(path): sha256(path) for path in locked},
        "input/data.csv": task["input_sha256"],
    }
    write_json(output / "freeze_lock.json", lock)
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
