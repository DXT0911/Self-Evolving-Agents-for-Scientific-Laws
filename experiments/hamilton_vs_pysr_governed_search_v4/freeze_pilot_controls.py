#!/usr/bin/env python3
"""Freeze Hamilton ledgers and materialize all paired v4 control jobs."""

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
    runner_config, sha256, write_json,
)
from experiments.hamilton_vs_pysr_governed_search_v4.build_pilot import load_yaml, relative


def _job(matrix: dict[str, Any], arm: str, repeat: str) -> dict[str, Any]:
    matches = [j for j in matrix["jobs"] if j["arm"] == arm and j["repeat_id"] == repeat]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {arm}/{repeat} job")
    return matches[0]


def freeze(bundle: Path = BUNDLE) -> dict[str, Any]:
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    matrix_path = bundle / "run_matrix.json"
    lock_path = bundle / "freeze_lock.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    task_id = str(manifest["task"])
    task = dict(specs["tasks"][task_id])
    task["_candidate_ranking"] = task.get(
        "candidate_ranking_override", specs["shared_verification"]["candidate_ranking"]
    )
    initial = dict(specs["shared_search"])
    initial["unary_operators"] = list(manifest["search"]["initial_unary_operators"])
    union = dict(initial)
    union["unary_operators"] = list(manifest["search"]["union_unary_operators"])
    traces: list[dict[str, Any]] = []

    for repeat_item in manifest["repeats"]:
        repeat = str(repeat_item["repeat_id"])
        seed = int(repeat_item["seed"])
        hjob = _job(matrix, "governed_hamilton", repeat)
        hworkspace = REPO / hjob["workspace"]
        ledger_path = hworkspace / ".hamilton_evaluation_ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        attempts = ledger.get("attempts")
        if not isinstance(attempts, list):
            raise ValueError(f"invalid Hamilton ledger for {repeat}")
        completed = [a for a in attempts if a.get("status") == "completed"]
        failed = [a for a in attempts if a.get("status") == "failed"]
        if len(completed) != int(manifest["episodes"]):
            raise ValueError(f"Hamilton {repeat} did not complete three rounds")
        if len(failed) > int(manifest["retry_policy"]["maximum_retries_per_arm_seed"]):
            raise ValueError(f"Hamilton {repeat} exceeded retry allowance")
        attempt_trace = []
        for index, attempt in enumerate(completed, start=1):
            result_file = str(attempt.get("result_file", ""))
            if not re.fullmatch(fr"history/round{index}/results/result\.json", result_file):
                raise ValueError(f"Hamilton {repeat} round {index} result path invalid")
            config_path = hworkspace / f"history/round{index}/experiment.json"
            result_path = hworkspace / result_file
            config = json.loads(config_path.read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            warm = result.get("engine_telemetry", {}).get("warm_start_session", {})
            policy = json.loads((hworkspace / ".hamilton_search_state.json").read_text(encoding="utf-8")) if index == 3 else None
            if config.get("search", {}).get("random_state") != seed:
                raise ValueError(f"Hamilton {repeat} changed the seed")
            if warm.get("state_preserved") is not True:
                raise ValueError(f"Hamilton {repeat} round {index} lost warm state")
            requested = int(attempt.get("requested_evals", 0))
            if requested != int(manifest["requested_evaluations_per_episode"]):
                raise ValueError(f"Hamilton {repeat} round allowance mismatch")
            attempt_trace.append({
                "round": index, "requested_evals": requested,
                "round_action": config.get("search_session", {}).get("round_action"),
                "engine_measured_evaluations": warm.get("round_engine_measured_evaluations"),
                "config_sha256": sha256(config_path), "result_sha256": sha256(result_path),
            })
        for failure in failed:
            if float(failure.get("engine_measured_evaluations", 0) or 0) != 0:
                raise ValueError(f"Hamilton {repeat} retried after engine consumption")
        total = sum(a["requested_evals"] for a in attempt_trace)
        if total != int(manifest["requested_evaluations_per_arm_per_seed"]):
            raise ValueError(f"Hamilton {repeat} budget mismatch")

        ordinary = _job(matrix, "ordinary_pysr", repeat)
        ordinary_workspace = REPO / ordinary["workspace"]
        config = runner_config(
            task_id, task, initial, total, seed,
            f"v4_pilot_ordinary__{task_id}__{repeat}", "results/result.json",
        )
        config["verification"]["structural_diagnostics"] = {"enabled": True}
        write_json(ordinary_workspace / "experiment.json", config)
        ordinary["commands"] = [["python", relative(RUNNER), "--config", "experiment.json"]]

        for arm, search in (("fixed_schedule_pysr", initial), ("union_schedule_pysr", union)):
            job = _job(matrix, arm, repeat)
            workspace = REPO / job["workspace"]
            commands = []
            for episode in range(1, 4):
                config = runner_config(
                    task_id, task, search, int(attempt_trace[episode - 1]["requested_evals"]), seed,
                    f"v4_pilot_{arm}__{task_id}__{repeat}__e{episode}",
                    f"results/episode_{episode}.json",
                )
                config["verification"]["structural_diagnostics"] = {"enabled": True}
                write_json(workspace / "episodes" / f"episode_{episode}.json", config)
                commands.append(["python", relative(RUNNER), "--config", f"episodes/episode_{episode}.json"])
            job["commands"] = commands

        trace = {
            "repeat_id": repeat, "seed": seed, "attempts": attempt_trace,
            "failed_attempts": len(failed), "actual_total_requested_evals": total,
            "hamilton_ledger_sha256": sha256(ledger_path),
        }
        traces.append(trace)
        hjob["state"] = "completed"
        for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
            job = _job(matrix, arm, repeat)
            job["state"] = "ready_from_frozen_hamilton_trace"
            job["evaluation_budget"] = total

    payload = {"schema_version": 1, "experiment_id": manifest["experiment_id"], "pairs": traces}
    trace_path = bundle / "paired_budget_trace.json"
    write_json(trace_path, payload)
    trace_hash = sha256(trace_path)
    for job in matrix["jobs"]:
        if job["arm"] != "governed_hamilton":
            job["paired_budget_trace_sha256"] = trace_hash
    write_json(matrix_path, matrix)
    lock["hashes"][relative(matrix_path)] = sha256(matrix_path)
    lock["hashes"][relative(trace_path)] = trace_hash
    write_json(lock_path, lock)
    return payload


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
