#!/usr/bin/env python3
"""Collect compact, development-only evidence from the v3 four-arm pilot."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUNDLE = HERE / "pilot_bundle"
OUTPUT = HERE / "pilot_evidence.json"
TASK = "static_s01"
REPEAT = "repeat_1"
ARMS = ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr", "governed_hamilton")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.ground_truth_equivalence import (
    verify_equivalence,
)


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths_for(arm: str) -> list[Path]:
    root = BUNDLE / arm / TASK / REPEAT
    if arm == "governed_hamilton":
        return sorted((root / "workspaces/task_0/history").glob("round*/results/result.json"))
    if arm == "ordinary_pysr":
        return [root / "workspace/results/result.json"]
    return sorted((root / "workspace/results").glob("episode_*.json"))


def selected_candidate(result: dict[str, Any]) -> dict[str, Any]:
    equation = result["selected"]["simplified_equation"]
    for candidate in result["candidates"]:
        if candidate.get("simplified_equation") == equation:
            return candidate
    raise ValueError("selected candidate is absent from candidates")


def hamilton_tokens() -> int:
    records = BUNDLE / "governed_hamilton" / TASK / REPEAT / "records"
    return sum(int(read(path).get("total_token_usage", 0)) for path in records.glob("*.json"))


def workspace_for(arm: str) -> Path:
    root = BUNDLE / arm / TASK / REPEAT
    return root / ("workspaces/task_0" if arm == "governed_hamilton" else "workspace")


def ledger_audit(arm: str) -> dict[str, Any]:
    ledger = read(workspace_for(arm) / ".hamilton_evaluation_ledger.json")
    statuses = Counter(str(item.get("status")) for item in ledger.get("attempts", []))
    return {
        "status_counts": dict(sorted(statuses.items())),
        "reserved_evaluations_by_status": {
            status: sum(
                int(item.get("requested_evals", 0))
                for item in ledger.get("attempts", [])
                if item.get("status") == status
            )
            for status in sorted(statuses)
        },
        "ledger_sha256": sha(workspace_for(arm) / ".hamilton_evaluation_ledger.json"),
    }


def hamilton_final_closure() -> dict[str, Any]:
    records = BUNDLE / "governed_hamilton" / TASK / REPEAT / "records"
    candidates = []
    for path in records.glob("*.json"):
        record = read(path)
        for item in record.get("rounds", []):
            if item.get("round") == 3:
                candidates.append((path, item))
    if not candidates:
        return {"closed": False, "finish_called": False, "record": None}
    path, item = max(candidates, key=lambda pair: pair[0].name)
    closure = item.get("signal", {}).get("closure", {})
    return {
        "closed": closure.get("closed") is True,
        "finish_called": closure.get("finish_called") is True,
        "scientific_decision_valid": (
            closure.get("scientific_decision", {}).get("valid") is True
        ),
        "record": path.name,
    }


def collect() -> dict[str, Any]:
    rows = []
    for arm in ARMS:
        paths = paths_for(arm)
        expected = 1 if arm == "ordinary_pysr" else 3
        if len(paths) != expected:
            raise ValueError(f"{arm} has {len(paths)} results; expected {expected}")
        results = [read(path) for path in paths]
        if not all(result.get("status") == "completed" for result in results):
            raise ValueError(f"{arm} contains a non-completed result")
        candidates = [selected_candidate(result) for result in results]
        winner_index = min(
            range(len(results)),
            key=lambda index: float(candidates[index]["ranking"]["scientific_score"]),
        )
        winner = results[winner_index]
        candidate = candidates[winner_index]
        requested = sum(int(result["evaluation_budget"]["requested_evals"]) for result in results)
        measured = sum(
            float(result["engine_telemetry"]["final_engine_measured_evaluations"])
            for result in results
        )
        warm_rounds = [
            result.get("engine_telemetry", {}).get("warm_start_session")
            for result in results
        ] if arm == "governed_hamilton" else []
        equivalence = verify_equivalence(
            TASK,
            winner["selected"]["simplified_equation"],
            registry_path=HERE.parent / "hamilton_vs_pysr_governed_search_v2/controller_ground_truth.yaml",
        )
        rows.append({
            "arm": arm,
            "result_count": len(results),
            "winning_result": winner_index + 1,
            "equation": winner["selected"]["simplified_equation"],
            "scientific_score": float(candidate["ranking"]["scientific_score"]),
            "validation_nrmse": float(candidate["ranking"]["validation_nrmse"]),
            "validation_r2": float(candidate["metrics"]["validation"]["r2"]),
            "ground_truth_equivalent": bool(equivalence["equivalent_ground_truth"]),
            "ground_truth_challenge_nrmse": equivalence["challenge_grid"]["normalized_rmse"],
            "requested_evaluations": requested,
            "engine_measured_evaluations": measured,
            "runtime_seconds": sum(float(result["runtime_seconds"]) for result in results),
            "llm_tokens": hamilton_tokens() if arm == "governed_hamilton" else 0,
            "warm_start_state_preserved": (
                all(item and item.get("state_preserved") is True for item in warm_rounds)
                if warm_rounds else None
            ),
            "warm_round_engine_evaluations": (
                [item["round_engine_measured_evaluations"] for item in warm_rounds]
                if warm_rounds else []
            ),
            "result_sha256": [sha(path) for path in paths],
        })
    result_gates = {
        "four_arms_present": {row["arm"] for row in rows} == set(ARMS),
        "all_requested_evaluations_equal_3000": all(
            row["requested_evaluations"] == 3000 for row in rows
        ),
        "hamilton_state_preserved": next(
            row for row in rows if row["arm"] == "governed_hamilton"
        )["warm_start_state_preserved"] is True,
        "engine_telemetry_present": all(row["engine_measured_evaluations"] > 0 for row in rows),
    }
    ledgers = {arm: ledger_audit(arm) for arm in ARMS}
    closure = hamilton_final_closure()
    audit_gates = {
        "hamilton_final_promotion_closed": closure["closed"],
        "no_orphaned_reserved_attempts": all(
            item["status_counts"].get("reserved", 0) == 0
            for item in ledgers.values()
        ),
        "no_failed_execution_attempts": all(
            item["status_counts"].get("failed", 0) == 0
            for item in ledgers.values()
        ),
    }
    ranked = sorted(rows, key=lambda row: row["scientific_score"])
    hamilton = next(row for row in rows if row["arm"] == "governed_hamilton")
    comparisons = {
        "rank_by_scientific_score": [row["arm"] for row in ranked],
        "hamilton_minus_baseline": {
            row["arm"]: {
                "scientific_score": hamilton["scientific_score"] - row["scientific_score"],
                "validation_nrmse": hamilton["validation_nrmse"] - row["validation_nrmse"],
                "engine_measured_evaluations": (
                    hamilton["engine_measured_evaluations"] - row["engine_measured_evaluations"]
                ),
            }
            for row in rows if row["arm"] != "governed_hamilton"
        },
    }
    return {
        "schema_version": 1,
        "experiment_id": "hamilton-vs-pysr-governed-search-v3-pilot-01",
        "status": (
            "passed"
            if all(result_gates.values()) and all(audit_gates.values())
            else "completed_with_operational_audit_failures"
            if all(result_gates.values())
            else "failed"
        ),
        "interpretation": "development_pilot_only_not_confirmatory",
        "scope": {"task": TASK, "repeat": REPEAT, "arms": list(ARMS)},
        "result_gates": result_gates,
        "operational_audit_gates": audit_gates,
        "hamilton_final_closure": closure,
        "attempt_ledgers": ledgers,
        "arm_results": rows,
        "comparisons": comparisons,
        "paired_budget_trace_sha256": sha(BUNDLE / "paired_budget_trace.json"),
    }


if __name__ == "__main__":
    evidence = collect()
    OUTPUT.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
