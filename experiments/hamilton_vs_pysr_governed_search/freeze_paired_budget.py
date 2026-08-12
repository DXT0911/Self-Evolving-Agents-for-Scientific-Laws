#!/usr/bin/env python3
"""Freeze one Hamilton ledger and materialize its paired PySR replay configs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .build_launch_bundle import (
        DEFAULT_OUTPUT,
        HERE,
        REPO,
        load_yaml,
        rel,
        runner_config,
        sha256,
        write_json,
    )
except ImportError:
    from build_launch_bundle import (
        DEFAULT_OUTPUT,
        HERE,
        REPO,
        load_yaml,
        rel,
        runner_config,
        sha256,
        write_json,
    )


RUNNER = REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"


def _job(matrix: dict[str, Any], arm: str, task_id: str, repeat_id: str) -> dict[str, Any]:
    matches = [
        job
        for job in matrix["jobs"]
        if job["arm"] == arm
        and job["task_id"] == task_id
        and job["repeat_id"] == repeat_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {arm}/{task_id}/{repeat_id} job")
    return matches[0]


def freeze_paired_budget(
    task_id: str,
    repeat_id: str,
    bundle: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    matrix_path = bundle / "run_matrix.json"
    lock_path = bundle / "freeze_lock.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(HERE / "task_specs.yaml")

    hamilton_job = _job(matrix, "governed_hamilton", task_id, repeat_id)
    ordinary_job = _job(matrix, "ordinary_pysr", task_id, repeat_id)
    fixed_job = _job(matrix, "fixed_schedule_pysr", task_id, repeat_id)
    hamilton_workspace = REPO / hamilton_job["workspace"]
    seed_plan_path = hamilton_workspace / ".hamilton_seed_plan.json"
    if (
        not seed_plan_path.is_file()
        or sha256(seed_plan_path) != hamilton_job.get("seed_plan_sha256")
    ):
        raise ValueError("frozen Hamilton seed plan is missing or changed")
    ledger_path = hamilton_workspace / ".hamilton_evaluation_ledger.json"
    if not ledger_path.is_file():
        raise FileNotFoundError(f"Hamilton evaluation ledger is missing: {ledger_path}")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    attempts = ledger.get("attempts")
    if (
        ledger.get("schema_version") != 1
        or not isinstance(attempts, list)
        or not 1 <= len(attempts) <= 3
    ):
        raise ValueError("Hamilton ledger must contain one to three governed attempts")

    repeat = next(
        item for item in manifest["seed_plan"]["repeats"]
        if item["repeat_id"] == repeat_id
    )
    expected_seeds = [int(value) for value in repeat["episode_seeds"]]
    trace_attempts: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, start=1):
        requested = attempt.get("requested_evals")
        if (
            not isinstance(requested, int)
            or isinstance(requested, bool)
            or requested <= 0
        ):
            raise ValueError(f"ledger attempt {index} has invalid requested_evals")
        if attempt.get("status") not in {"completed", "failed"}:
            raise ValueError(f"ledger attempt {index} is not finalized")
        result_file = str(attempt.get("result_file", ""))
        match = re.match(r"history/round(\d+)/", result_file)
        if not match or int(match.group(1)) != index:
            raise ValueError(f"ledger attempt {index} is not the expected round")
        config_path = hamilton_workspace / f"history/round{index}/experiment.json"
        if not config_path.is_file() or sha256(config_path) != attempt.get("config_sha256"):
            raise ValueError(f"round {index} config is missing or changed")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        seed = config.get("search", {}).get("random_state")
        if seed != expected_seeds[index - 1]:
            raise ValueError(
                f"round {index} seed {seed!r} does not match frozen seed "
                f"{expected_seeds[index - 1]}"
            )
        trace_attempts.append(
            {
                "round": index,
                "requested_evals": requested,
                "random_state": seed,
                "status": attempt["status"],
                "config_sha256": attempt["config_sha256"],
                "result_sha256": attempt.get("result_sha256"),
            }
        )

    actual_total = sum(item["requested_evals"] for item in trace_attempts)
    ceiling = int(manifest["budget"]["max_total_evals_per_task"])
    if actual_total > ceiling:
        raise ValueError(f"Hamilton ledger exceeds cumulative ceiling: {actual_total}")

    task = dict(specs["tasks"][task_id])
    task["_candidate_ranking"] = task.get(
        "candidate_ranking_override",
        specs["shared_verification"]["candidate_ranking"],
    )
    shared_search = dict(specs["shared_search"])
    repeat_number = int(repeat_id.rsplit("_", 1)[1])

    ordinary_workspace = REPO / ordinary_job["workspace"]
    ordinary = runner_config(
        task_id,
        task,
        shared_search,
        actual_total,
        int(repeat["ordinary_primary_seed"]),
        f"ordinary_pysr__{task_id}__r{repeat_number}",
        "results/result.json",
    )
    write_json(ordinary_workspace / "experiment.json", ordinary)
    ordinary_job.update(
        {
            "state": "ready_from_frozen_hamilton_budget_trace",
            "evaluation_budget": actual_total,
            "commands": [[
                "python", rel(RUNNER), "--config", "experiment.json",
            ]],
        }
    )

    fixed_workspace = REPO / fixed_job["workspace"]
    fixed_commands: list[list[str]] = []
    for item in trace_attempts:
        index = item["round"]
        name = f"episode_{index}"
        config = runner_config(
            task_id,
            task,
            shared_search,
            item["requested_evals"],
            item["random_state"],
            f"fixed_pysr__{task_id}__r{repeat_number}__e{index}",
            f"results/{name}.json",
        )
        write_json(fixed_workspace / "episodes" / f"{name}.json", config)
        fixed_commands.append([
            "python", rel(RUNNER), "--config", f"episodes/{name}.json",
        ])
    fixed_job.update(
        {
            "state": "ready_from_frozen_hamilton_budget_trace",
            "evaluation_budget": actual_total,
            "commands": fixed_commands,
        }
    )

    trace = {
        "schema_version": 1,
        "task_id": task_id,
        "repeat_id": repeat_id,
        "source": "governed_hamilton_evaluation_ledger",
        "cumulative_ceiling": ceiling,
        "actual_total_evals": actual_total,
        "attempts": trace_attempts,
        "contains_scientific_outputs": False,
        "hamilton_ledger_sha256": sha256(ledger_path),
    }
    trace_path = bundle / "paired_budget_traces" / task_id / f"{repeat_id}.json"
    write_json(trace_path, trace)
    trace_hash = sha256(trace_path)
    ordinary_job["paired_budget_trace_sha256"] = trace_hash
    fixed_job["paired_budget_trace_sha256"] = trace_hash
    matrix["ready_job_count"] = sum(
        job.get("state") in {
            "ready_waiting_runtime_authorizations",
            "ready_from_frozen_hamilton_budget_trace",
        }
        for job in matrix["jobs"]
    )
    write_json(matrix_path, matrix)
    lock["hashes"][rel(matrix_path)] = sha256(matrix_path)
    lock.setdefault("paired_budget_trace_hashes", {})[
        f"{task_id}/{repeat_id}"
    ] = trace_hash
    write_json(lock_path, lock)
    return trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("repeat_id")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(
        freeze_paired_budget(args.task_id, args.repeat_id, args.bundle.resolve()),
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
