#!/usr/bin/env python3
"""Freeze the realized Hamilton schedule and materialize the v3 pilot controls."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V1 = HERE.parent / "hamilton_vs_pysr_governed_search"
BUNDLE = HERE / "pilot_bundle"
RUNNER = REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import (
    runner_config,
    sha256,
    write_json,
)
from experiments.hamilton_vs_pysr_governed_search_v3.build_pilot import (
    load_yaml,
    relative,
)


def _job(matrix: dict[str, Any], arm: str) -> dict[str, Any]:
    matches = [job for job in matrix["jobs"] if job["arm"] == arm]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {arm} job")
    return matches[0]


def freeze(bundle: Path = BUNDLE) -> dict[str, Any]:
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    matrix_path = bundle / "run_matrix.json"
    lock_path = bundle / "freeze_lock.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    hjob = _job(matrix, "governed_hamilton")
    hworkspace = REPO / hjob["workspace"]
    ledger_path = hworkspace / ".hamilton_evaluation_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    attempts = ledger.get("attempts")
    episodes = int(manifest["episodes"])
    seed = int(manifest["seed"])
    if not isinstance(attempts, list):
        raise ValueError("Hamilton evaluation ledger is invalid")
    completed_attempts = [item for item in attempts if item.get("status") == "completed"]
    failed_attempts = [item for item in attempts if item.get("status") == "failed"]
    if len(completed_attempts) != episodes:
        raise ValueError("Hamilton did not complete the frozen number of rounds")

    trace_attempts: list[dict[str, Any]] = []
    for index, attempt in enumerate(completed_attempts, start=1):
        result_file = str(attempt.get("result_file", ""))
        match = re.fullmatch(r"history/round(\d+)/results/result\.json", result_file)
        if not match or int(match.group(1)) != index:
            raise ValueError(f"Hamilton round {index} result path is invalid")
        config_path = hworkspace / f"history/round{index}/experiment.json"
        result_path = hworkspace / result_file
        config = json.loads(config_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        session = config.get("search_session", {})
        warm = result.get("engine_telemetry", {}).get("warm_start_session", {})
        if config.get("search", {}).get("random_state") != seed:
            raise ValueError(f"Hamilton round {index} changed the frozen seed")
        if session.get("round") != index or session.get("mode") != "warm_start":
            raise ValueError(f"Hamilton round {index} lacks the warm-start session")
        if warm.get("state_preserved") is not True:
            raise ValueError(f"Hamilton round {index} did not preserve search state")
        requested = int(attempt.get("requested_evals", 0))
        if requested != int(manifest["requested_evaluations_per_episode"]):
            raise ValueError(f"Hamilton round {index} allowance differs from the pilot")
        trace_attempts.append({
            "round": index,
            "requested_evals": requested,
            "random_state": seed,
            "round_action": session.get("round_action"),
            "config_sha256": sha256(config_path),
            "result_sha256": sha256(result_path),
            "engine_measured_evaluations": warm.get("round_engine_measured_evaluations"),
        })
    total = sum(item["requested_evals"] for item in trace_attempts)
    if total != int(manifest["requested_evaluations_per_arm"]):
        raise ValueError("Hamilton total requested evaluations do not reconcile")

    task_id = str(manifest["task"])
    task = dict(specs["tasks"][task_id])
    task["_candidate_ranking"] = task.get(
        "candidate_ranking_override",
        specs["shared_verification"]["candidate_ranking"],
    )
    initial_search = dict(specs["shared_search"])
    initial_search["unary_operators"] = list(manifest["search"]["initial_unary_operators"])
    union_search = dict(initial_search)
    union_search["unary_operators"] = list(manifest["search"]["union_unary_operators"])

    ordinary = _job(matrix, "ordinary_pysr")
    ordinary_workspace = REPO / ordinary["workspace"]
    write_json(ordinary_workspace / "experiment.json", runner_config(
        task_id, task, initial_search, total, seed,
        f"v3_pilot_ordinary__{task_id}__r1", "results/result.json",
    ))
    ordinary["commands"] = [["python", relative(RUNNER), "--config", "experiment.json"]]

    for arm, search in (
        ("fixed_schedule_pysr", initial_search),
        ("union_schedule_pysr", union_search),
    ):
        job = _job(matrix, arm)
        workspace = REPO / job["workspace"]
        commands = []
        for item in trace_attempts:
            episode = item["round"]
            config = runner_config(
                task_id, task, search, item["requested_evals"], seed,
                f"v3_pilot_{arm}__{task_id}__r1__e{episode}",
                f"results/episode_{episode}.json",
            )
            write_json(workspace / "episodes" / f"episode_{episode}.json", config)
            commands.append([
                "python", relative(RUNNER), "--config", f"episodes/episode_{episode}.json"
            ])
        job["commands"] = commands

    trace = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "source": "governed_hamilton_evaluation_ledger",
        "actual_total_requested_evals": total,
        "total_reserved_evals_including_pre_search_failures": sum(
            int(item["requested_evals"]) for item in attempts
        ),
        "failed_attempts": [
            {
                "experiment_id": item.get("experiment_id"),
                "requested_evals": item.get("requested_evals"),
                "result_sha256": item.get("result_sha256"),
                "scientific_evidence": False,
                "engine_evaluations": 0,
            }
            for item in failed_attempts
        ],
        "same_seed_restart_policy": True,
        "attempts": trace_attempts,
        "hamilton_ledger_sha256": sha256(ledger_path),
    }
    trace_path = bundle / "paired_budget_trace.json"
    write_json(trace_path, trace)
    trace_hash = sha256(trace_path)
    hjob["state"] = "completed"
    for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
        job = _job(matrix, arm)
        job["state"] = "ready_from_frozen_hamilton_trace"
        job["evaluation_budget"] = total
        job["paired_budget_trace_sha256"] = trace_hash
    write_json(matrix_path, matrix)
    lock["hashes"][relative(matrix_path)] = sha256(matrix_path)
    lock["hashes"][relative(trace_path)] = trace_hash
    write_json(lock_path, lock)
    return trace


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
