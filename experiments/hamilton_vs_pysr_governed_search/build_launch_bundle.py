#!/usr/bin/env python3
"""Materialize the frozen public-pilot launch bundle without running it.

This module does not import or invoke PySR, Julia, or an LLM API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_OUTPUT = HERE / "launch_bundle"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def materialize_input(source: Path, destination: Path, expected_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(destination) != expected_hash:
            raise ValueError(f"existing generated input has wrong hash: {destination}")
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    if sha256(destination) != expected_hash:
        raise ValueError(f"generated input hash mismatch: {destination}")


def runner_config(
    task_id: str,
    task: dict[str, Any],
    search: dict[str, Any],
    max_evals: int,
    seed: int,
    experiment_id: str,
    result_file: str,
) -> dict[str, Any]:
    ranking = task.get("_candidate_ranking")
    verification: dict[str, Any] = {
        "short_ode": task["short_ode"],
        "residual_diagnostics": {
            "enabled": True,
            "max_lag": 50,
            "feature_bins": 4,
            "phase_bins": 8,
            "high_frequency_fraction": 0.25,
        },
    }
    if ranking:
        verification["candidate_ranking"] = ranking
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "data": {
            "train_file": "input/data.csv",
            "allowed_files": ["input/data.csv"],
            "time_column": task["time_column"],
            "feature_columns": task["feature_columns"],
            "target_column": task["target_column"],
            "max_rows": task["max_rows"],
            "search_stride": task["search_stride"],
            "standardize_search": task["standardize_search"],
            "validation_fraction": task["validation_fraction"],
        },
        "search": {**search, "max_evals": max_evals, "random_state": seed},
        "verification": verification,
        "output": {
            "result_file": result_file,
            "run_directory": result_file.replace(".json", "-pysr"),
        },
    }


def task_context(task: dict[str, Any]) -> str:
    if task["context"] == "public_viv":
        return (
            "The public columns retain physical semantics: x is displacement, v is "
            "velocity, a is acceleration, and t is time. Discover a=f(x,v)."
        )
    features = ", ".join(task["feature_columns"])
    if task["context"] == "blind_dynamic_derivative":
        return (
            f"The feature columns ({features}) are state variables and y is one "
            "state derivative. t preserves source-row order; it is not evidence for "
            "a physical-time rollout."
        )
    return (
        f"The feature columns ({features}) are opaque predictors and y is the target. "
        "t is a deterministic ordering index and is not a scientific input."
    )


def hamilton_task(
    task_id: str,
    task: dict[str, Any],
    baseline: dict[str, Any],
    total_budget: int,
    bounds: dict[str, int],
    episode_seeds: list[int],
) -> str:
    frozen_json = json.dumps(baseline, indent=2, sort_keys=True)
    return f"""# Frozen opaque public symbolic-regression task

Task identifier: `{task_id}`

Use only `input/data.csv` through the governed standard runner. Do not read raw
rows directly, infer a hidden source identity, use literature search, access
private/OOD data, or evaluate a candidate outside the runner.

{task_context(task)}

This run has exactly three governed Discovery rounds and cumulative PySR
evaluation ceiling `{total_budget}`. The deterministic controller, not the LLM,
assigns each effective allowance using `base={bounds["base_evals"]}`,
`min={bounds["min_evals"]}`, `max={bounds["max_evals"]}`, and
`quantum={bounds["rounding_quantum"]}`, while reserving the future-round minimum.
Use round seeds `{episode_seeds}` in order. Round 1 must use the exact runner
configuration below. In rounds 2 and 3, propose the next
configuration from machine-readable L2 memory, the preceding governed
verification result, and residual evidence. Every proposal remains subject to
controller trust-region, budget, validation, promotion, rollback, and closure.

```json
{frozen_json}
```

Do not stop early merely because a candidate improves. Search promotion and
final scientific success are distinct. Complete all three rounds unless the
controller records a deterministic execution failure that prevents continuation.
"""


def build_bundle(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    manifest_path = HERE / "pilot_manifest.yaml"
    specs_path = HERE / "task_specs.yaml"
    contracts_path = HERE / "arm_contracts.yaml"
    hamilton_config = REPO / "configs/hamilton/config_governed_pysr_public_pilot.yaml"
    manifest = load_yaml(manifest_path)
    specs = load_yaml(specs_path)

    budget = manifest["budget"]
    if budget["authorization_state"] not in {
        "frozen_pending_user_authorization",
        "authorized",
    }:
        raise ValueError("budget must be frozen or explicitly authorized")
    total_budget = int(budget["max_total_evals_per_task"])
    bounds = {
        name: int(budget["hamilton_dynamic_bounds"][name])
        for name in ("base_evals", "min_evals", "max_evals", "rounding_quantum")
    }
    if budget["episode_evals"] != "realized_from_paired_hamilton_ledger":
        raise ValueError("baseline allowances must come from the Hamilton ledger")

    task_order = [
        item["id"]
        for family in manifest["dataset_families"]
        for item in family["tasks"]
    ]
    tasks = specs["tasks"]
    if set(task_order) != set(tasks):
        raise ValueError("manifest and task-spec task sets differ")

    shared_search = dict(specs["shared_search"])
    shared_verification = specs["shared_verification"]
    jobs: list[dict[str, Any]] = []

    for task_id in task_order:
        task = tasks[task_id]
        task = dict(task)
        task["_candidate_ranking"] = task.get(
            "candidate_ranking_override",
            shared_verification["candidate_ranking"],
        )
        source = (HERE / task["input"]).resolve()
        expected_hash = task["input_sha256"]
        if not source.is_file() or sha256(source) != expected_hash:
            raise ValueError(f"missing or changed frozen public input: {source}")

        for repeat in manifest["seed_plan"]["repeats"]:
            repeat_id = repeat["repeat_id"]
            repeat_number = int(repeat_id.rsplit("_", 1)[1])
            episode_seeds = [int(value) for value in repeat["episode_seeds"]]

            ordinary_root = output / "ordinary_pysr" / task_id / repeat_id
            ordinary_workspace = ordinary_root / "workspace"
            materialize_input(
                source, ordinary_workspace / "input/data.csv", expected_hash
            )
            jobs.append(
                {
                    "arm": "ordinary_pysr",
                    "task_id": task_id,
                    "repeat_id": repeat_id,
                    "workspace": rel(ordinary_workspace),
                    "state": "waiting_for_paired_hamilton_budget_trace",
                    "evaluation_budget": "realized_from_paired_hamilton_ledger",
                    "paired_hamilton_workspace": rel(
                        output / "governed_hamilton" / task_id / repeat_id
                        / "workspaces" / "task_0"
                    ),
                    "commands": [],
                    "requires": ["pysr_julia_authorization"],
                }
            )

            fixed_root = output / "fixed_schedule_pysr" / task_id / repeat_id
            fixed_workspace = fixed_root / "workspace"
            materialize_input(source, fixed_workspace / "input/data.csv", expected_hash)
            jobs.append(
                {
                    "arm": "fixed_schedule_pysr",
                    "task_id": task_id,
                    "repeat_id": repeat_id,
                    "workspace": rel(fixed_workspace),
                    "state": "waiting_for_paired_hamilton_budget_trace",
                    "evaluation_budget": "realized_from_paired_hamilton_ledger",
                    "paired_hamilton_workspace": rel(
                        output / "governed_hamilton" / task_id / repeat_id
                        / "workspaces" / "task_0"
                    ),
                    "commands": [],
                    "requires": ["pysr_julia_authorization"],
                }
            )

            hamilton_root = output / "governed_hamilton" / task_id / repeat_id
            hamilton_workspace = hamilton_root / "workspaces" / "task_0"
            materialize_input(
                source, hamilton_workspace / "input/data.csv", expected_hash
            )
            baseline = runner_config(
                task_id,
                task,
                shared_search,
                bounds["base_evals"],
                episode_seeds[0],
                f"governed_hamilton__{task_id}__r{repeat_number}__round1",
                "history/round1/results/result.json",
            )
            write_json(hamilton_workspace / "round1_baseline.json", baseline)
            seed_plan_path = hamilton_workspace / ".hamilton_seed_plan.json"
            write_json(
                seed_plan_path,
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "repeat_id": repeat_id,
                    "round_seeds": episode_seeds,
                    "controller_owned": True,
                },
            )
            write_text(
                hamilton_workspace / "task.md",
                hamilton_task(
                    task_id,
                    task,
                    baseline,
                    total_budget,
                    bounds,
                    episode_seeds,
                ),
            )
            jobs.append(
                {
                    "arm": "governed_hamilton",
                    "task_id": task_id,
                    "repeat_id": repeat_id,
                    "workspace": rel(hamilton_workspace),
                    "state": "ready_waiting_runtime_authorizations",
                    "evaluation_budget_ceiling": total_budget,
                    "seed_plan_sha256": sha256(seed_plan_path),
                    "commands": [[
                        "python",
                        rel(REPO / "run.py"),
                        "--agent",
                        "hamilton",
                        "--config",
                        rel(hamilton_config),
                        "--task",
                        f"Execute frozen opaque public task {task_id}, {repeat_id}.",
                        "--run-dir",
                        rel(hamilton_root),
                    ]],
                    "requires": [
                        "deepseek_authorization",
                        "pysr_julia_authorization",
                    ],
                }
            )

    bundle_status = (
        "operational_gate_authorized"
        if manifest.get("status") == "frozen" and not manifest.get("launch_blocked")
        else str(manifest.get("status"))
    )
    matrix = {
        "schema_version": 1,
        "status": bundle_status,
        "execution_permitted": False,
        "private_ood_permitted": False,
        "job_count": len(jobs),
        "ready_job_count": sum(
            job.get("state") == "ready_waiting_runtime_authorizations"
            for job in jobs
        ),
        "execution_order": "hamilton_then_freeze_budget_trace_then_pysr_replay",
        "jobs": jobs,
    }
    matrix_path = output / "run_matrix.json"
    write_json(matrix_path, matrix)

    lock_sources = [
        manifest_path,
        specs_path,
        contracts_path,
        hamilton_config,
        matrix_path,
    ]
    lock = {
        "schema_version": 1,
        "status": bundle_status,
        "execution_permitted": False,
        "task_count": len(task_order),
        "repeat_count": len(manifest["seed_plan"]["repeats"]),
        "arm_count": 3,
        "job_count": len(jobs),
        "per_task_repeat_evaluation_ceiling": total_budget,
        "episode_evaluations": "realized_from_paired_hamilton_ledger",
        "dynamic_budget_bounds": bounds,
        "hashes": {rel(path): sha256(path) for path in lock_sources},
    }
    write_json(output / "freeze_lock.json", lock)
    return lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_bundle(args.output.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
