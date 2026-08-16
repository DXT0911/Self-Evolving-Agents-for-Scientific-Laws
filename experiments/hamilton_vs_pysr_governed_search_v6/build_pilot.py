#!/usr/bin/env python3
"""Materialize the frozen v6 three-arm ablation pilot without executing it."""

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
    materialize_input,
    runner_config,
    sha256,
    task_context,
    write_json,
    write_text,
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
    tasks = list(manifest["tasks"])
    seeds = list(manifest["seeds"])
    arms = list(manifest["arms"]["ids"])
    per_round = int(manifest["requested_evaluations_per_round"])
    rounds = int(manifest["rounds"])
    per_seed = int(manifest["requested_evaluations_per_arm_per_seed"])
    if per_round * rounds != per_seed:
        raise ValueError("per-round and per-seed evaluation authorization do not reconcile")
    if len(arms) * len(tasks) * len(seeds) * per_seed != int(
        manifest["requested_evaluations_total"]
    ):
        raise ValueError("evaluation authorization does not reconcile")
    if int(manifest["arm_c_run_count"]) * int(manifest["max_hamilton_tokens_per_run"]) != int(
        manifest["max_hamilton_tokens_total"]
    ):
        raise ValueError("token authorization does not reconcile")
    if int(manifest["arm_c_run_count"]) != len(tasks) * len(seeds):
        raise ValueError("arm C run count must equal tasks x seeds")

    initial_operators = list(manifest["search"]["initial_unary_operators"])
    allowed_operators = list(manifest["search"]["allowed_unary_operators"])
    if any(op not in allowed_operators for op in initial_operators):
        raise ValueError("initial operators must be a subset of the allowed envelope")

    jobs: list[dict[str, Any]] = []
    for task_id in tasks:
        task = dict(specs["tasks"][task_id])
        task["_candidate_ranking"] = task.get(
            "candidate_ranking_override", specs["shared_verification"]["candidate_ranking"]
        )
        source = (V1 / task["input"]).resolve()
        if not source.is_file() or sha256(source) != task["input_sha256"]:
            raise ValueError(f"new pilot input is absent or changed: {source}")
        search = dict(specs["shared_search"])
        search["unary_operators"] = list(initial_operators)

        for index, seed in enumerate(seeds):
            repeat = f"repeat_{index + 1}"
            for arm in arms:
                root = output / arm / task_id / repeat
                workspace = root / "workspace"
                materialize_input(source, workspace / "input/data.csv", task["input_sha256"])
                baseline = runner_config(
                    task_id, task, search, per_round, seed,
                    f"v6_pilot_{arm}__{task_id}__{repeat}__round1",
                    "history/round1/results/result.json",
                )
                baseline["verification"]["structural_diagnostics"] = {"enabled": True}
                baseline["output"]["run_directory"] = "session/pysr"
                baseline["search_session"] = {
                    "mode": "warm_start",
                    "session_id": f"v6-pilot-{task_id}-{repeat}-{arm}",
                    "round": 1,
                    "final_round": False,
                    "round_action": "initialize",
                    "compatible_change_fields": ["search.parsimony"],
                }
                write_json(workspace / "round1_baseline.json", baseline)
                write_json(workspace / ".hamilton_seed_plan.json", {
                    "schema_version": 1, "task_id": task_id, "repeat_id": repeat,
                    "round_seeds": [seed] * rounds, "controller_owned": True,
                })
                write_json(workspace / ".hamilton_budget.json", {
                    "schema_version": 1,
                    "max_total_evals": int(manifest["hamilton_ledger_ceiling_per_seed"]),
                    "retry_policy": "one_retry_only_when_engine_evaluations_zero",
                })
                write_text(workspace / "task.md", f"""# Frozen v6 three-arm ablation pilot

Task `{task_id}`, pair `{repeat}`, seed `{seed}`, arm `{arm}`. Use only the governed
runner and `input/data.csv`; never read raw rows, hidden truth, VIV, sealed/OOD data,
or identify the source. {task_context(task)}

Run {rounds} persistent warm rounds of {per_round} requested evaluations. The frozen
controller owns budgets, retention, and rollback. Arm A always continues; arm B uses a
deterministic rule intervention; arm C calls exactly one compressed planner per
intervention round and the controller adopts or rejects its atomic action.
""")
                jobs.append({
                    "arm": arm,
                    "task_id": task_id,
                    "repeat_id": repeat,
                    "workspace": relative(workspace),
                    "state": "ready_waiting_runtime_authorizations",
                    "evaluation_ceiling": int(manifest["hamilton_ledger_ceiling_per_seed"]),
                    "token_ceiling": (
                        int(manifest["max_hamilton_tokens_per_run"])
                        if arm == "arm_c_llm_hamilton"
                        else 0
                    ),
                    "commands": [[
                        "python",
                        "experiments/hamilton_vs_pysr_governed_search_v6/execute_governed_hamilton.py",
                        "--workspace", relative(workspace),
                        "--arm", arm,
                    ]],
                    "requires": (
                        ["deepseek_authorization", "pysr_julia_authorization"]
                        if arm == "arm_c_llm_hamilton"
                        else ["pysr_julia_authorization"]
                    ),
                })

    matrix = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "execution_permitted": False,
        "execution_order": "arms_independent",
        "jobs": jobs,
    }
    write_json(output / "run_matrix.json", matrix)
    locked = [
        HERE / "pilot_manifest.yaml",
        HERE / "execute_governed_hamilton.py",
        REPO / "configs/hamilton/config_governed_pysr_v6_pilot.yaml",
        REPO / "playground/hamilton/core/compressed_planner.py",
        REPO / "playground/hamilton/core/governed_policy.py",
        REPO / "playground/hamilton/core/search_control.py",
        REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py",
        REPO / "evomaster/skills/run-sr-experiment/scripts/warm_start_worker.py",
        output / "run_matrix.json",
    ]
    lock = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "execution_permitted": False,
        "hashes": {relative(path): sha256(path) for path in locked},
        "inputs": {task_id: specs["tasks"][task_id]["input_sha256"] for task_id in tasks},
    }
    write_json(output / "freeze_lock.json", lock)
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
