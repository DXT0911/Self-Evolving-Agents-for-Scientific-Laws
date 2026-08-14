#!/usr/bin/env python3
"""Materialize the frozen v4 three-seed pilot without executing it."""

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
from playground.hamilton.core.governed_policy import policy_manifest


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def pilot_task(
    task_id: str, task: dict[str, Any], baseline: dict[str, Any], repeat: str, seed: int
) -> str:
    frozen = json.dumps(baseline, indent=2, sort_keys=True)
    return f"""# Frozen Hamilton v4 development pilot

Task `{task_id}`, pair `{repeat}`, seed `{seed}`. Development-only evidence.

Use only `input/data.csv` through the governed standard runner. Do not read raw rows,
identify the hidden source, search literature, access private/OOD data, or evaluate a
candidate outside the runner.

{task_context(task)}

Run exactly three governed rounds of 1,000 requested evaluations. Preserve the seed,
worker, population, operators, maxsize, run directory, and warm PySR state. The frozen
deterministic binding policy owns action selection. The LLM may state a structural
hypothesis but may not override its action, patch, candidate retention, rollback, or
budget. A binding `continue` is an authorized no-op continuation.

Round 1 must use this exact configuration:

```json
{frozen}
```
"""


def build(output: Path = OUTPUT) -> dict[str, Any]:
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    if manifest.get("status") != "frozen_pre_execution":
        raise ValueError("pilot manifest must be frozen before materialization")
    repeats = list(manifest["repeats"])
    if len(repeats) != 3 or len({int(item["seed"]) for item in repeats}) != 3:
        raise ValueError("pilot requires exactly three distinct frozen seeds")
    if 4 * len(repeats) * int(manifest["requested_evaluations_per_arm_per_seed"]) != int(
        manifest["requested_evaluations_total"]
    ):
        raise ValueError("requested evaluation authorization does not reconcile")
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
        raise ValueError("prepared pilot input is missing or changed")

    search = dict(specs["shared_search"])
    search["unary_operators"] = list(manifest["search"]["initial_unary_operators"])
    per_episode = int(manifest["requested_evaluations_per_episode"])
    jobs: list[dict[str, Any]] = []
    for item in repeats:
        repeat = str(item["repeat_id"])
        seed = int(item["seed"])
        hroot = output / "governed_hamilton" / task_id / repeat
        hworkspace = hroot / "workspaces" / "task_0"
        materialize_input(source, hworkspace / "input/data.csv", task["input_sha256"])
        baseline = runner_config(
            task_id, task, search, per_episode, seed,
            f"v4_pilot_hamilton__{task_id}__{repeat}__round1",
            "history/round1/results/result.json",
        )
        baseline["verification"]["structural_diagnostics"] = {"enabled": True}
        baseline["output"]["run_directory"] = "session/pysr"
        baseline["search_session"] = {
            "mode": "warm_start",
            "session_id": f"v4-pilot-{task_id}-{repeat}",
            "round": 1,
            "final_round": False,
            "round_action": "initialize",
            "compatible_change_fields": ["search.parsimony"],
        }
        write_json(hworkspace / "round1_baseline.json", baseline)
        write_json(hworkspace / ".hamilton_seed_plan.json", {
            "schema_version": 1,
            "task_id": task_id,
            "repeat_id": repeat,
            "round_seeds": [seed, seed, seed],
            "controller_owned": True,
            "warm_start_seed_policy": "retain_initial_seed",
        })
        write_text(hworkspace / "task.md", pilot_task(task_id, task, baseline, repeat, seed))
        jobs.append({
            "arm": "governed_hamilton", "task_id": task_id, "repeat_id": repeat,
            "workspace": relative(hworkspace), "state": "ready",
            "requested_evaluation_ceiling": int(manifest["hamilton_ledger_ceiling_per_seed"]),
            "llm_token_ceiling": int(manifest["max_hamilton_tokens_per_seed"]),
            "commands": [[
                "python",
                "experiments/hamilton_vs_pysr_governed_search_v4/execute_governed_hamilton.py",
                "--workspace", relative(hworkspace),
            ]],
        })
        for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
            workspace = output / arm / task_id / repeat / "workspace"
            materialize_input(source, workspace / "input/data.csv", task["input_sha256"])
            jobs.append({
                "arm": arm, "task_id": task_id, "repeat_id": repeat,
                "workspace": relative(workspace),
                "state": "waiting_for_hamilton_allowance_trace", "commands": [],
            })

    matrix = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "execution_permitted": True,
        "execution_order": "three_hamilton_serial_then_freeze_then_controls_serial",
        "jobs": jobs,
    }
    write_json(output / "run_matrix.json", matrix)
    write_json(output / "binding_policy.json", policy_manifest())
    locked = [
        HERE / "pilot_manifest.yaml",
        REPO / "configs/hamilton/config_governed_pysr_v4_pilot.yaml",
        REPO / "playground/hamilton/prompts/hamilton_v4_pilot_system.txt",
        REPO / "playground/hamilton/core/governed_policy.py",
        REPO / "playground/hamilton/core/search_control.py",
        REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py",
        HERE / "execute_governed_hamilton.py",
        output / "run_matrix.json",
        output / "binding_policy.json",
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
