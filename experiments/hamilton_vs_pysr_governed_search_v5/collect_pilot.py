#!/usr/bin/env python3
"""Collect auditable paired evidence for the Hamilton v5 development pilot."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "pilot_bundle"
TASK = "static_s02"
ARMS = ("governed_hamilton", "ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr")
REPEATS = ("repeat_1", "repeat_2", "repeat_3")


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def workspace(arm: str, repeat: str) -> Path:
    root = BUNDLE / arm / TASK / repeat
    return root / ("workspaces/task_0" if arm == "governed_hamilton" else "workspace")


def result_paths(arm: str, repeat: str) -> list[Path]:
    root = workspace(arm, repeat)
    if arm == "governed_hamilton":
        return sorted((root / "history").glob("round*/results/result.json"))
    if arm == "ordinary_pysr":
        return [root / "results/result.json"]
    return sorted((root / "results").glob("episode_*.json"))


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
    raise ValueError("selected equation is absent from candidate table")


def collect() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for repeat in REPEATS:
        for arm in ARMS:
            paths = result_paths(arm, repeat)
            results = [read(path) for path in paths]
            expected_count = 3 if arm != "ordinary_pysr" else 1
            if len(results) != expected_count or any(item.get("status") != "completed" for item in results):
                raise ValueError(f"incomplete result set: {arm}/{repeat}")
            scores = [float(item["selected"]["scientific_score"]) for item in results]
            best_index = min(range(len(scores)), key=scores.__getitem__)
            ledger = read(workspace(arm, repeat) / ".hamilton_evaluation_ledger.json")
            statuses = Counter(str(item.get("status")) for item in ledger.get("attempts", []))
            registered_requested = sum(int(item["evaluation_budget"]["requested_evals"]) for item in results)
            actual_ledger_requested = sum(
                int(item.get("requested_evals", 0))
                for item in ledger.get("attempts", [])
                if item.get("status") == "completed"
            )
            row: dict[str, Any] = {
                "repeat_id": repeat,
                "seed": 8300 + int(repeat[-1]),
                "arm": arm,
                "scientific_score": scores[best_index],
                "winning_result": best_index + 1,
                "equation": results[best_index]["selected"]["simplified_equation"],
                "validation_nrmse": float(selected_candidate(results[best_index])["ranking"]["validation_nrmse"]),
                "registered_requested_evaluations": registered_requested,
                "actual_ledger_requested_evaluations": actual_ledger_requested,
                "operational_duplicate_evaluations": actual_ledger_requested - registered_requested,
                "engine_measured_evaluations": sum(measured(item, arm) for item in results),
                "runtime_seconds": sum(float(item.get("runtime_seconds", 0)) for item in results),
                "result_count": len(results),
                "ledger_status_counts": dict(sorted(statuses.items())),
                "llm_calls": 0,
                "llm_prompt_tokens": 0,
                "llm_completion_tokens": 0,
                "llm_total_tokens": 0,
            }
            if arm == "governed_hamilton":
                planner = read(workspace(arm, repeat) / ".hamilton_planner_ledger.json")
                calls = planner["calls"]
                memory_path = workspace(arm, repeat) / ".hamilton_evidence_memory.json"
                memory = read(memory_path)
                proposal_keys = {
                    json.dumps(call["proposal"], ensure_ascii=False, sort_keys=True)
                    for call in calls
                }
                hypothesis_keys = {call["proposal"]["hypothesis"].strip() for call in calls}
                row.update({
                    "llm_calls": len(calls),
                    "llm_prompt_tokens": sum(int(call["usage"]["prompt_tokens"]) for call in calls),
                    "llm_completion_tokens": sum(int(call["usage"]["completion_tokens"]) for call in calls),
                    "llm_total_tokens": sum(int(call["usage"]["total_tokens"]) for call in calls),
                    "unique_planner_proposals": len(proposal_keys),
                    "unique_planner_hypotheses": len(hypothesis_keys),
                    "memory_updated_after_round": memory["updated_after_round"],
                    "memory_strong_outcomes": len(memory["strong"]["search_outcomes"]),
                    "memory_weak_hypotheses": len(memory["weak"]["causal_hypotheses"]),
                    "memory_bytes": memory_path.stat().st_size,
                })
            rows.append(row)

    by_arm = {arm: [row for row in rows if row["arm"] == arm] for arm in ARMS}
    summaries: dict[str, Any] = {}
    for arm, arm_rows in by_arm.items():
        values = [row["scientific_score"] for row in arm_rows]
        summaries[arm] = {
            "mean_scientific_score": statistics.mean(values),
            "median_scientific_score": statistics.median(values),
            "min_scientific_score": min(values),
            "max_scientific_score": max(values),
            "mean_engine_measured_evaluations": statistics.mean(row["engine_measured_evaluations"] for row in arm_rows),
        }

    paired: dict[str, Any] = {}
    hamilton = {row["repeat_id"]: row for row in by_arm["governed_hamilton"]}
    for control in ARMS[1:]:
        control_rows = {row["repeat_id"]: row for row in by_arm[control]}
        comparisons = []
        for repeat in REPEATS:
            h_score = hamilton[repeat]["scientific_score"]
            c_score = control_rows[repeat]["scientific_score"]
            comparisons.append({
                "repeat_id": repeat,
                "hamilton_score": h_score,
                "control_score": c_score,
                "absolute_delta_hamilton_minus_control": h_score - c_score,
                "relative_improvement": (c_score - h_score) / c_score if c_score else 0.0,
                "outcome": "win" if h_score < c_score - 1e-12 else "loss" if h_score > c_score + 1e-12 else "tie",
                "engine_eval_ratio_hamilton_over_control": hamilton[repeat]["engine_measured_evaluations"] / control_rows[repeat]["engine_measured_evaluations"],
            })
        paired[control] = {
            "pairs": comparisons,
            "wins": sum(item["outcome"] == "win" for item in comparisons),
            "ties": sum(item["outcome"] == "tie" for item in comparisons),
            "losses": sum(item["outcome"] == "loss" for item in comparisons),
            "median_relative_improvement": statistics.median(item["relative_improvement"] for item in comparisons),
            "mean_absolute_delta": statistics.mean(item["absolute_delta_hamilton_minus_control"] for item in comparisons),
        }

    hamilton_rows = by_arm["governed_hamilton"]
    prompt_tokens = sum(row["llm_prompt_tokens"] for row in hamilton_rows)
    completion_tokens = sum(row["llm_completion_tokens"] for row in hamilton_rows)
    formal_requested = sum(row["registered_requested_evaluations"] for row in rows)
    actual_requested = sum(row["actual_ledger_requested_evaluations"] for row in rows)
    summaries_data = [read(workspace("governed_hamilton", repeat) / "v5_governed_summary.json") for repeat in REPEATS]
    payload = {
        "schema_version": 1,
        "experiment_id": "hamilton-vs-pysr-governed-search-v5-pilot-01",
        "status": "completed_with_disclosed_operational_duplicate",
        "interpretation": "development_pilot_only_not_confirmatory",
        "audit": {
            "result_rows": len(rows),
            "all_registered_results_completed": len(rows) == 12,
            "formal_registered_requested_evaluations": formal_requested,
            "authorized_requested_evaluations": 54000,
            "formal_budget_reconciles": formal_requested == 54000,
            "actual_completed_ledger_requested_evaluations": actual_requested,
            "operational_duplicate_requested_evaluations": actual_requested - formal_requested,
            "failed_ledger_attempts": sum(row["ledger_status_counts"].get("failed", 0) for row in rows),
            "operator_path_errors_before_engine": 2,
            "planner_calls": sum(row["llm_calls"] for row in hamilton_rows),
            "expected_planner_calls": 9,
            "hamilton_prompt_tokens": prompt_tokens,
            "hamilton_completion_tokens": completion_tokens,
            "hamilton_total_tokens": prompt_tokens + completion_tokens,
            "authorized_hamilton_tokens": 180000,
            "token_ceiling_fraction": (prompt_tokens + completion_tokens) / 180000,
            "conservative_llm_cost_cny_cache_miss": prompt_tokens / 1_000_000 + 2 * completion_tokens / 1_000_000,
            "all_hamilton_actions_binding_continue": all(
                item["binding_action"]["action"] in {"initialize", "continue"}
                for summary in summaries_data for item in summary["rounds"]
            ),
            "all_planner_proposals_advisory_only": all(
                item["planner_proposal"]["authority"] == "advisory_only"
                for summary in summaries_data for item in summary["rounds"]
            ),
            "memory_updated_every_round": all(row["memory_updated_after_round"] == 3 for row in hamilton_rows),
            "warm_state_preserved_all_rounds": all(
                read(path).get("engine_telemetry", {}).get("warm_start_session", {}).get("state_preserved") is True
                for repeat in REPEATS for path in result_paths("governed_hamilton", repeat)
            ),
        },
        "arm_summaries": summaries,
        "paired_comparisons": paired,
        "rows": rows,
    }
    (HERE / "pilot_evidence.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
