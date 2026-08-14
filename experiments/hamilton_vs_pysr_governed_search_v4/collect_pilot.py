#!/usr/bin/env python3
"""Collect paired development evidence for the v4 three-seed pilot."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "pilot_bundle"
ARMS = ("governed_hamilton", "ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr")
REPEATS = ("repeat_1", "repeat_2", "repeat_3")


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def result_paths(arm: str, repeat: str) -> list[Path]:
    root = BUNDLE / arm / "static_s01" / repeat
    if arm == "governed_hamilton":
        return sorted((root / "workspaces/task_0/history").glob("round*/results/result.json"))
    if arm == "ordinary_pysr":
        return [root / "workspace/results/result.json"]
    return sorted((root / "workspace/results").glob("episode_*.json"))


def workspace(arm: str, repeat: str) -> Path:
    root = BUNDLE / arm / "static_s01" / repeat
    return root / ("workspaces/task_0" if arm == "governed_hamilton" else "workspace")


def measured(result: dict[str, Any], arm: str) -> float:
    telemetry = result.get("engine_telemetry", {})
    if arm == "governed_hamilton":
        return float(telemetry.get("warm_start_session", {}).get("round_engine_measured_evaluations", 0))
    return float(telemetry.get("final_engine_measured_evaluations", 0))


def selected_candidate(result: dict[str, Any]) -> dict[str, Any]:
    equation = result["selected"]["simplified_equation"]
    for candidate in result.get("candidates", []):
        if candidate.get("simplified_equation") == equation:
            return candidate
    raise ValueError("selected equation is absent from the candidate table")


def collect() -> dict[str, Any]:
    rows = []
    for repeat in REPEATS:
        for arm in ARMS:
            paths = result_paths(arm, repeat)
            results = [read(path) for path in paths]
            if not results or any(item.get("status") != "completed" for item in results):
                raise ValueError(f"incomplete result set: {arm}/{repeat}")
            scores = [float(item["selected"]["scientific_score"]) for item in results]
            best_index = min(range(len(scores)), key=scores.__getitem__)
            ledger = read(workspace(arm, repeat) / ".hamilton_evaluation_ledger.json")
            statuses = Counter(str(item.get("status")) for item in ledger.get("attempts", []))
            requested = sum(
                int(item.get("requested_evals", 0))
                for item in ledger.get("attempts", [])
                if item.get("status") == "completed"
            )
            rows.append({
                "repeat_id": repeat,
                "seed": 8200 + int(repeat[-1]),
                "arm": arm,
                "scientific_score": scores[best_index],
                "winning_result": best_index + 1,
                "equation": results[best_index]["selected"]["simplified_equation"],
                "validation_nrmse": float(
                    selected_candidate(results[best_index])["ranking"]["validation_nrmse"]
                ),
                "requested_evaluations": requested,
                "engine_measured_evaluations": sum(measured(item, arm) for item in results),
                "runtime_seconds": sum(float(item.get("runtime_seconds", 0)) for item in results),
                "result_count": len(results),
                "ledger_status_counts": dict(sorted(statuses.items())),
                "llm_tokens": 0,
            })

    by_arm = {arm: [row for row in rows if row["arm"] == arm] for arm in ARMS}
    summaries = {}
    for arm, arm_rows in by_arm.items():
        values = [row["scientific_score"] for row in arm_rows]
        summaries[arm] = {
            "mean_scientific_score": statistics.mean(values),
            "median_scientific_score": statistics.median(values),
            "min_scientific_score": min(values),
            "max_scientific_score": max(values),
            "mean_engine_measured_evaluations": statistics.mean(
                row["engine_measured_evaluations"] for row in arm_rows
            ),
        }

    paired = {}
    h = {row["repeat_id"]: row for row in by_arm["governed_hamilton"]}
    for control in ARMS[1:]:
        c = {row["repeat_id"]: row for row in by_arm[control]}
        comparisons = []
        for repeat in REPEATS:
            hs, cs = h[repeat]["scientific_score"], c[repeat]["scientific_score"]
            comparisons.append({
                "repeat_id": repeat,
                "hamilton_score": hs,
                "control_score": cs,
                "absolute_delta_hamilton_minus_control": hs - cs,
                "relative_improvement": (cs - hs) / cs if cs else 0.0,
                "outcome": "win" if hs < cs - 1e-12 else "loss" if hs > cs + 1e-12 else "tie",
                "engine_eval_ratio_hamilton_over_control": (
                    h[repeat]["engine_measured_evaluations"] / c[repeat]["engine_measured_evaluations"]
                ),
            })
        paired[control] = {
            "pairs": comparisons,
            "wins": sum(item["outcome"] == "win" for item in comparisons),
            "ties": sum(item["outcome"] == "tie" for item in comparisons),
            "losses": sum(item["outcome"] == "loss" for item in comparisons),
            "median_relative_improvement": statistics.median(
                item["relative_improvement"] for item in comparisons
            ),
            "mean_absolute_delta": statistics.mean(
                item["absolute_delta_hamilton_minus_control"] for item in comparisons
            ),
        }

    requested_total = sum(row["requested_evaluations"] for row in rows)
    payload = {
        "schema_version": 1,
        "experiment_id": "hamilton-vs-pysr-governed-search-v4-pilot-01",
        "status": "completed",
        "interpretation": "development_pilot_only_not_confirmatory",
        "audit": {
            "result_rows": len(rows),
            "all_results_completed": len(rows) == 12,
            "successful_requested_evaluations": requested_total,
            "authorized_requested_evaluations": 36000,
            "requested_budget_reconciles": requested_total == 36000,
            "failed_attempts": sum(
                row["ledger_status_counts"].get("failed", 0) for row in rows
            ),
            "hamilton_llm_tokens": 0,
            "authorized_hamilton_llm_tokens": 90000,
            "all_hamilton_actions_binding_continue": all(
                item["binding_action"]["action"] in {"initialize", "continue"}
                for repeat in REPEATS
                for item in read(workspace("governed_hamilton", repeat) / "v4_governed_summary.json")["rounds"]
            ),
            "warm_state_preserved_all_rounds": all(
                read(path).get("engine_telemetry", {}).get("warm_start_session", {}).get("state_preserved") is True
                for repeat in REPEATS for path in result_paths("governed_hamilton", repeat)
            ),
        },
        "arm_summaries": summaries,
        "paired_comparisons": paired,
        "rows": rows,
    }
    (HERE / "pilot_evidence.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
