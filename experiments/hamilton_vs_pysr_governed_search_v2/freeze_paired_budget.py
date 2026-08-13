#!/usr/bin/env python3
"""Freeze Hamilton's realized schedule and materialize the three v2 controls."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import (
    runner_config,
    sha256,
    write_json,
)
from experiments.hamilton_vs_pysr_governed_search_v2.build_operational_gate import (
    DEFAULT_OUTPUT,
    V1,
    load_yaml,
    relative,
)

RUNNER = REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"


def _job(matrix: dict[str, Any], arm: str, task_id: str, repeat_id: str) -> dict[str, Any]:
    matches = [
        job for job in matrix["jobs"]
        if job["arm"] == arm and job["task_id"] == task_id
        and job["repeat_id"] == repeat_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {arm}/{task_id}/{repeat_id} job")
    return matches[0]


def freeze_paired_budget(
    task_id: str,
    repeat_id: str = "repeat_1",
    bundle: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    manifest = load_yaml(HERE / "manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    matrix_path = bundle / "run_matrix.json"
    lock_path = bundle / "freeze_lock.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))

    hjob = _job(matrix, "governed_hamilton", task_id, repeat_id)
    hworkspace = REPO / hjob["workspace"]
    ledger_path = hworkspace / ".hamilton_evaluation_ledger.json"
    seed_path = hworkspace / ".hamilton_seed_plan.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    seed_plan = json.loads(seed_path.read_text(encoding="utf-8"))
    attempts = ledger.get("attempts")
    if ledger.get("schema_version") != 1 or not isinstance(attempts, list) or not attempts:
        raise ValueError("Hamilton evaluation ledger is invalid or empty")

    expected_seeds = [int(value) for value in manifest["seed_plan"][repeat_id]["episodes"]]
    if seed_plan.get("round_seeds") != expected_seeds:
        raise ValueError("Hamilton seed plan differs from the frozen manifest")
    trace_attempts: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, start=1):
        if attempt.get("status") != "completed":
            raise ValueError(f"round {index} is not completed")
        result_file = str(attempt.get("result_file", ""))
        match = re.fullmatch(r"history/round(\d+)/results/result\.json", result_file)
        if not match or int(match.group(1)) != index:
            raise ValueError(f"round {index} result path is invalid")
        config_path = hworkspace / f"history/round{index}/experiment.json"
        result_path = hworkspace / result_file
        if sha256(config_path) != attempt.get("config_sha256"):
            raise ValueError(f"round {index} config hash differs from its ledger")
        if sha256(result_path) != attempt.get("result_sha256"):
            raise ValueError(f"round {index} result hash differs from its ledger")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        requested = attempt.get("requested_evals")
        seed = config.get("search", {}).get("random_state")
        if not isinstance(requested, int) or requested <= 0 or seed != expected_seeds[index - 1]:
            raise ValueError(f"round {index} allowance or seed is invalid")
        trace_attempts.append({
            "round": index,
            "requested_evals": requested,
            "random_state": seed,
            "config_sha256": attempt["config_sha256"],
            "result_sha256": attempt["result_sha256"],
        })

    total = sum(item["requested_evals"] for item in trace_attempts)
    ceiling = int(manifest["search"]["max_total_requested_evals_per_arm_task_repeat"])
    if total > ceiling:
        raise ValueError(f"Hamilton requested {total}, above frozen ceiling {ceiling}")

    task = dict(specs["tasks"][task_id])
    task["_candidate_ranking"] = task.get(
        "candidate_ranking_override", specs["shared_verification"]["candidate_ranking"]
    )
    initial_search = dict(specs["shared_search"])
    initial_search["unary_operators"] = list(manifest["search"]["initial_unary_operators"])
    union_search = dict(initial_search)
    union_search["unary_operators"] = list(manifest["search"]["union_unary_operators"])
    repeat_number = int(repeat_id.rsplit("_", 1)[1])

    ordinary = _job(matrix, "ordinary_pysr", task_id, repeat_id)
    ordinary_workspace = REPO / ordinary["workspace"]
    ordinary_config = runner_config(
        task_id, task, initial_search, total,
        int(manifest["seed_plan"][repeat_id]["ordinary"]),
        f"v2_ordinary__{task_id}__r{repeat_number}", "results/result.json",
    )
    write_json(ordinary_workspace / "experiment.json", ordinary_config)
    ordinary["commands"] = [["python", relative(RUNNER), "--config", "experiment.json"]]

    for arm, search in (("fixed_schedule_pysr", initial_search), ("union_schedule_pysr", union_search)):
        job = _job(matrix, arm, task_id, repeat_id)
        workspace = REPO / job["workspace"]
        commands: list[list[str]] = []
        for item in trace_attempts:
            episode = item["round"]
            config = runner_config(
                task_id, task, search, item["requested_evals"], item["random_state"],
                f"v2_{arm}__{task_id}__r{repeat_number}__e{episode}",
                f"results/episode_{episode}.json",
            )
            config_path = workspace / "episodes" / f"episode_{episode}.json"
            write_json(config_path, config)
            commands.append(["python", relative(RUNNER), "--config", f"episodes/episode_{episode}.json"])
        job["commands"] = commands

    trace = {
        "schema_version": 1,
        "task_id": task_id,
        "repeat_id": repeat_id,
        "source": "governed_hamilton_evaluation_ledger",
        "cumulative_ceiling": ceiling,
        "actual_total_requested_evals": total,
        "attempts": trace_attempts,
        "contains_scientific_outputs": False,
        "hamilton_ledger_sha256": sha256(ledger_path),
        "hamilton_seed_plan_sha256": sha256(seed_path),
    }
    trace_path = bundle / "paired_budget_traces" / task_id / f"{repeat_id}.json"
    write_json(trace_path, trace)
    trace_hash = sha256(trace_path)
    for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
        job = _job(matrix, arm, task_id, repeat_id)
        job.update({
            "state": "ready_from_frozen_hamilton_budget_trace",
            "evaluation_budget": total,
            "paired_budget_trace_sha256": trace_hash,
        })
    hjob["state"] = "completed"
    matrix["ready_job_count"] = sum(
        job.get("state") == "ready_from_frozen_hamilton_budget_trace"
        for job in matrix["jobs"]
    )
    write_json(matrix_path, matrix)
    lock["hashes"][relative(matrix_path)] = sha256(matrix_path)
    lock.setdefault("paired_budget_trace_hashes", {})[f"{task_id}/{repeat_id}"] = trace_hash
    write_json(lock_path, lock)
    return trace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("repeat_id", nargs="?", default="repeat_1")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(freeze_paired_budget(args.task_id, args.repeat_id, args.bundle.resolve()), indent=2))


if __name__ == "__main__":
    main()
