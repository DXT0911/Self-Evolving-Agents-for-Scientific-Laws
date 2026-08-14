#!/usr/bin/env python3
"""Materialize the frozen v3 four-arm development pilot without executing it."""

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


def pilot_task(task_id: str, task: dict[str, Any], baseline: dict[str, Any]) -> str:
    frozen = json.dumps(baseline, indent=2, sort_keys=True)
    return f"""# Frozen Hamilton v3 development pilot

Task identifier: `{task_id}`. This is a development-only pilot and not confirmatory evidence.

Use only `input/data.csv` through the governed standard runner. Do not read raw rows,
identify the hidden source, use literature search, access private/OOD data, or evaluate
a candidate outside the runner.

{task_context(task)}

Run exactly three governed rounds. Each round receives 1,000 requested PySR evaluations,
for a cumulative ceiling of 3,000. All rounds must preserve the initial random seed 7101,
the same PySR worker, population, random state, operators, `search.maxsize`, and output run
directory. The only warm-compatible modification is `search.parsimony`. When residual
evidence does not justify that causal intervention, use the authorized no-op `continue`
action. Never modify a field merely to appear adaptive.

Round 1 must use the exact configuration below. Complete all three rounds unless the
controller records a deterministic failure that makes state-preserving continuation
impossible.

```json
{frozen}
```
"""


def build(output: Path = OUTPUT) -> dict[str, Any]:
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    if manifest.get("status") != "frozen_pre_execution":
        raise ValueError("pilot manifest must be frozen before materialization")
    task_id = str(manifest["task"])
    repeat = str(manifest["repeat"])
    seed = int(manifest["seed"])
    task = dict(specs["tasks"][task_id])
    task["_candidate_ranking"] = task.get(
        "candidate_ranking_override",
        specs["shared_verification"]["candidate_ranking"],
    )
    source = (V1 / task["input"]).resolve()
    if not source.is_file() or sha256(source) != task["input_sha256"]:
        raise ValueError("prepared pilot input is missing or changed")

    search = dict(specs["shared_search"])
    search["unary_operators"] = list(manifest["search"]["initial_unary_operators"])
    per_episode = int(manifest["requested_evaluations_per_episode"])
    hroot = output / "governed_hamilton" / task_id / repeat
    hworkspace = hroot / "workspaces" / "task_0"
    materialize_input(source, hworkspace / "input/data.csv", task["input_sha256"])
    baseline = runner_config(
        task_id,
        task,
        search,
        per_episode,
        seed,
        f"v3_pilot_hamilton__{task_id}__r1__round1",
        "history/round1/results/result.json",
    )
    baseline["output"]["run_directory"] = "session/pysr"
    baseline["search_session"] = {
        "mode": "warm_start",
        "session_id": f"v3-pilot-{task_id}-repeat-1",
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
    write_text(hworkspace / "task.md", pilot_task(task_id, task, baseline))

    jobs = [{
        "arm": "governed_hamilton",
        "task_id": task_id,
        "repeat_id": repeat,
        "workspace": relative(hworkspace),
        "state": "ready",
        "commands": [[
            "python", "run.py", "--agent", "hamilton", "--config",
            "configs/hamilton/config_governed_pysr_v3_pilot.yaml", "--task",
            f"Execute frozen v3 development pilot {task_id}, {repeat}.",
            "--run-dir", relative(hroot),
        ]],
    }]
    for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
        workspace = output / arm / task_id / repeat / "workspace"
        materialize_input(source, workspace / "input/data.csv", task["input_sha256"])
        jobs.append({
            "arm": arm,
            "task_id": task_id,
            "repeat_id": repeat,
            "workspace": relative(workspace),
            "state": "waiting_for_hamilton_allowance_trace",
            "commands": [],
        })
    matrix = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "execution_permitted": True,
        "execution_order": "hamilton_then_freeze_then_three_controls",
        "jobs": jobs,
    }
    write_json(output / "run_matrix.json", matrix)
    lock = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "hashes": {
            relative(HERE / "pilot_manifest.yaml"): sha256(HERE / "pilot_manifest.yaml"),
            relative(REPO / "configs/hamilton/config_governed_pysr_v3_pilot.yaml"): sha256(
                REPO / "configs/hamilton/config_governed_pysr_v3_pilot.yaml"
            ),
            relative(output / "run_matrix.json"): sha256(output / "run_matrix.json"),
            "input/data.csv": task["input_sha256"],
        },
    }
    write_json(output / "freeze_lock.json", lock)
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
