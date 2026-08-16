#!/usr/bin/env python3
"""Collect v6 three-arm ablation results into a machine-readable evidence bundle."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUNDLE = HERE / "pilot_bundle"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import write_json


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def collect(bundle: Path = BUNDLE) -> dict[str, Any]:
    matrix = read(bundle / "run_matrix.json")
    manifest_path = HERE / "pilot_manifest.yaml"
    rows: list[dict[str, Any]] = []
    for job in matrix["jobs"]:
        workspace = REPO / job["workspace"]
        summary_path = workspace / "v6_governed_summary.json"
        if not summary_path.is_file():
            rows.append({
                "arm": job["arm"], "task_id": job["task_id"],
                "repeat_id": job["repeat_id"], "status": "missing_summary",
            })
            continue
        summary = read(summary_path)
        rounds = summary.get("rounds", [])
        engine_total = sum(
            float(round_["engine_measured_evaluations"] or 0) for round_ in rounds
        )
        adopted = sum(
            1 for round_ in rounds
            if (round_.get("next_binding_action") or {}).get("adopted") is True
        )
        rejected = sum(
            1 for round_ in rounds
            if (round_.get("next_binding_action") or {}).get("adopted") is False
        )
        action_counts: dict[str, int] = {}
        for round_ in rounds:
            binding = round_.get("binding_action") or {}
            action_counts[binding.get("action", "unknown")] = (
                action_counts.get(binding.get("action", "unknown"), 0) + 1
            )
        rows.append({
            "arm": job["arm"], "task_id": job["task_id"], "repeat_id": job["repeat_id"],
            "seed": rounds[0].get("seed") if rounds else None,
            "status": summary.get("status"),
            "final_scientific_score": (summary.get("incumbent") or {}).get("score"),
            "engine_measured_evaluations_total": engine_total,
            "llm_tokens": summary.get("llm_tokens", 0),
            "planner_calls": summary.get("planner_calls", 0),
            "llm_adopted": adopted,
            "llm_rejected": rejected,
            "binding_action_counts": action_counts,
        })

    arm_summaries: dict[str, dict[str, Any]] = {}
    for arm in ("arm_a_persistent_pysr", "arm_b_rule_hamilton", "arm_c_llm_hamilton"):
        arm_rows = [row for row in rows if row["arm"] == arm and row.get("status") == "completed"]
        scores = [row["final_scientific_score"] for row in arm_rows if row["final_scientific_score"] is not None]
        arm_summaries[arm] = {
            "completed_runs": len(arm_rows),
            "median_scientific_score": (
                sorted(scores)[len(scores) // 2] if scores else None
            ),
        }

    paired: list[dict[str, Any]] = []
    for task_id in sorted({row["task_id"] for row in rows}):
        for repeat_id in sorted({row["repeat_id"] for row in rows if row["task_id"] == task_id}):
            by_arm = {
                row["arm"]: row
                for row in rows
                if row["task_id"] == task_id and row["repeat_id"] == repeat_id
            }
            a = by_arm.get("arm_a_persistent_pysr", {})
            b = by_arm.get("arm_b_rule_hamilton", {})
            c = by_arm.get("arm_c_llm_hamilton", {})
            paired.append({
                "task_id": task_id,
                "repeat_id": repeat_id,
                "arm_a_score": a.get("final_scientific_score"),
                "arm_b_score": b.get("final_scientific_score"),
                "arm_c_score": c.get("final_scientific_score"),
                "arm_a_engine_evals": a.get("engine_measured_evaluations_total"),
                "arm_b_engine_evals": b.get("engine_measured_evaluations_total"),
                "arm_c_engine_evals": c.get("engine_measured_evaluations_total"),
            })

    def compare(left_key: str, right_key: str) -> dict[str, int]:
        wins = losses = ties = 0
        for pair in paired:
            left = pair[left_key]
            right = pair[right_key]
            if left is None or right is None:
                continue
            if left < right - 1e-12:
                wins += 1
            elif right < left - 1e-12:
                losses += 1
            else:
                ties += 1
        return {"wins": wins, "losses": losses, "ties": ties}

    evidence = {
        "schema_version": 1,
        "experiment_id": matrix["experiment_id"],
        "status": "collected",
        "interpretation": "development_pilot_only_not_confirmatory",
        "arm_summaries": arm_summaries,
        "paired_comparisons": paired,
        "head_to_head": {
            "c_vs_a": compare("arm_c_score", "arm_a_score"),
            "c_vs_b": compare("arm_c_score", "arm_b_score"),
            "b_vs_a": compare("arm_b_score", "arm_a_score"),
        },
        "rows": rows,
    }
    write_json(bundle / "pilot_evidence.json", evidence)
    return evidence


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
