"""Cross-round feedback for LLM-selected Hamilton actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .search_control import EVIDENCE_FILE, atomic_write_json, read_evidence_memory


FEEDBACK_FILE = ".hamilton_decision_feedback.json"


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def evaluate_decision_feedback(
    *,
    previous_round: dict[str, Any],
    current_round_num: int,
    current_incumbent_score: float,
    current_snapshot: dict[str, Any],
    min_score_improvement: float,
) -> dict[str, Any]:
    """Test a prior LLM decision against the next completed round."""
    previous_number = int(previous_round["round"])
    previous_score = _number(previous_round.get("incumbent_score"), float("inf"))
    score_improvement = previous_score - float(current_incumbent_score)
    previous_snapshot = previous_round.get("diagnostic_snapshot")
    previous_snapshot = previous_snapshot if isinstance(previous_snapshot, dict) else {}
    residual_before = _number(previous_snapshot.get("material_residual_correlation"))
    residual_after = _number(current_snapshot.get("material_residual_correlation"))
    residual_reduction = residual_before - residual_after
    supported = (
        score_improvement >= float(min_score_improvement)
        or residual_reduction >= 0.05
    )
    decision = previous_round.get("llm_decision")
    decision = decision if isinstance(decision, dict) else {}
    return {
        "schema_version": 1,
        "decision_after_round": previous_number,
        "tested_by_round": int(current_round_num),
        "selected_candidate_id": decision.get("selected_candidate_id"),
        "selected_action": decision.get("selected_action", {}).get("action")
        if isinstance(decision.get("selected_action"), dict)
        else None,
        "status": "supported_by_next_round" if supported else "not_supported_by_next_round",
        "score_improvement": score_improvement,
        "required_score_improvement": float(min_score_improvement),
        "residual_correlation_before": residual_before,
        "residual_correlation_after": residual_after,
        "residual_correlation_reduction": residual_reduction,
        "interpretation_boundary": (
            "A one-round association supports or fails to support this local search "
            "decision; it does not establish a general causal effect."
        ),
    }


def record_decision_feedback(
    workspace: Path,
    *,
    previous_round: dict[str, Any],
    current_round_num: int,
    current_incumbent_score: float,
    current_snapshot: dict[str, Any],
    min_score_improvement: float,
) -> dict[str, Any]:
    """Persist feedback and update the corresponding weak-memory hypothesis."""
    feedback = evaluate_decision_feedback(
        previous_round=previous_round,
        current_round_num=current_round_num,
        current_incumbent_score=current_incumbent_score,
        current_snapshot=current_snapshot,
        min_score_improvement=min_score_improvement,
    )
    path = workspace / FEEDBACK_FILE
    ledger = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.is_file()
        else {"schema_version": 1, "feedback": []}
    )
    prior_round = feedback["decision_after_round"]
    ledger["feedback"] = [
        item
        for item in ledger.get("feedback", [])
        if item.get("decision_after_round") != prior_round
    ]
    ledger["feedback"].append(feedback)
    atomic_write_json(path, ledger)

    memory = read_evidence_memory(workspace)
    memory_id = f"round:{prior_round}:next_hypothesis"
    for item in memory.get("weak", {}).get("causal_hypotheses", []):
        if isinstance(item, dict) and item.get("memory_id") == memory_id:
            item["status"] = feedback["status"]
            item["tested_by_round"] = feedback["tested_by_round"]
            item["feedback"] = {
                "score_improvement": feedback["score_improvement"],
                "residual_correlation_reduction": feedback[
                    "residual_correlation_reduction"
                ],
            }
            break
    atomic_write_json(workspace / EVIDENCE_FILE, memory)
    return feedback
