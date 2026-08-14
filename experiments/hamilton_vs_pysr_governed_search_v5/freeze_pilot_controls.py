#!/usr/bin/env python3
"""Audit full Hamilton traces and materialize paired v5 controls."""

from __future__ import annotations

import json
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

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import runner_config, sha256, write_json
from experiments.hamilton_vs_pysr_governed_search_v5.build_pilot import load_yaml, relative


def job(matrix: dict[str, Any], arm: str, repeat: str) -> dict[str, Any]:
    found = [item for item in matrix["jobs"] if item["arm"] == arm and item["repeat_id"] == repeat]
    if len(found) != 1:
        raise ValueError(f"expected one {arm}/{repeat}")
    return found[0]


def freeze(bundle: Path = BUNDLE) -> dict[str, Any]:
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    specs = load_yaml(V1 / "task_specs.yaml")
    matrix_path, lock_path = bundle / "run_matrix.json", bundle / "freeze_lock.json"
    matrix, lock = json.loads(matrix_path.read_text()), json.loads(lock_path.read_text())
    task_id = str(manifest["task"])
    task = dict(specs["tasks"][task_id])
    task["_candidate_ranking"] = task.get(
        "candidate_ranking_override", specs["shared_verification"]["candidate_ranking"]
    )
    initial = dict(specs["shared_search"])
    initial["unary_operators"] = list(manifest["search"]["initial_unary_operators"])
    union = dict(initial)
    union["unary_operators"] = list(manifest["search"]["union_unary_operators"])
    traces = []

    for repeat_item in manifest["repeats"]:
        repeat, seed = str(repeat_item["repeat_id"]), int(repeat_item["seed"])
        hjob = job(matrix, "governed_hamilton", repeat)
        hworkspace = REPO / hjob["workspace"]
        summary = json.loads((hworkspace / "v5_governed_summary.json").read_text(encoding="utf-8"))
        planner = json.loads((hworkspace / ".hamilton_planner_ledger.json").read_text(encoding="utf-8"))
        memory = json.loads((hworkspace / ".hamilton_evidence_memory.json").read_text(encoding="utf-8"))
        ledger_path = hworkspace / ".hamilton_evaluation_ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        completed = [item for item in ledger["attempts"] if item.get("status") == "completed"]
        failed = [item for item in ledger["attempts"] if item.get("status") == "failed"]
        if len(completed) != 3 or failed:
            raise ValueError(f"Hamilton {repeat} result ledger is not clean")
        if len(planner["calls"]) != 3 or [item["round"] for item in planner["calls"]] != [1, 2, 3]:
            raise ValueError(f"Hamilton {repeat} planner calls are not one per round")
        if int(planner["total_token_usage"]) > int(manifest["max_hamilton_tokens_per_seed"]):
            raise ValueError(f"Hamilton {repeat} exceeded token authorization")
        if memory.get("updated_after_round") != 3:
            raise ValueError(f"Hamilton {repeat} evidence memory is incomplete")
        if any(row.get("memory_updated_after_round") != row["round"] for row in summary["rounds"]):
            raise ValueError(f"Hamilton {repeat} memory progression is invalid")
        total = sum(int(item["requested_evals"]) for item in completed)
        if total != int(manifest["requested_evaluations_per_arm_per_seed"]):
            raise ValueError(f"Hamilton {repeat} evaluation total differs")

        ordinary = job(matrix, "ordinary_pysr", repeat)
        oworkspace = REPO / ordinary["workspace"]
        config = runner_config(
            task_id, task, initial, total, seed,
            f"v5_pilot_ordinary__{task_id}__{repeat}", "results/result.json",
        )
        config["verification"]["structural_diagnostics"] = {"enabled": True}
        write_json(oworkspace / "experiment.json", config)
        ordinary["commands"] = [["python", relative(RUNNER), "--config", "experiment.json"]]

        for arm, search in (("fixed_schedule_pysr", initial), ("union_schedule_pysr", union)):
            cjob, commands = job(matrix, arm, repeat), []
            cworkspace = REPO / cjob["workspace"]
            for episode in range(1, 4):
                config = runner_config(
                    task_id, task, search, int(manifest["requested_evaluations_per_episode"]), seed,
                    f"v5_pilot_{arm}__{task_id}__{repeat}__e{episode}",
                    f"results/episode_{episode}.json",
                )
                config["verification"]["structural_diagnostics"] = {"enabled": True}
                write_json(cworkspace / "episodes" / f"episode_{episode}.json", config)
                commands.append(["python", relative(RUNNER), "--config", f"episodes/episode_{episode}.json"])
            cjob["commands"] = commands

        traces.append({
            "repeat_id": repeat, "seed": seed, "requested_evals": total,
            "planner_calls": len(planner["calls"]),
            "planner_tokens": planner["total_token_usage"],
            "memory_updated_after_round": memory["updated_after_round"],
            "hamilton_ledger_sha256": sha256(ledger_path),
        })
        hjob["state"] = "completed"
        for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
            job(matrix, arm, repeat)["state"] = "ready_from_frozen_hamilton_trace"

    payload = {"schema_version": 1, "experiment_id": manifest["experiment_id"], "pairs": traces}
    trace_path = bundle / "paired_budget_trace.json"
    write_json(trace_path, payload)
    write_json(matrix_path, matrix)
    lock["hashes"][relative(matrix_path)] = sha256(matrix_path)
    lock["hashes"][relative(trace_path)] = sha256(trace_path)
    write_json(lock_path, lock)
    return payload


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
