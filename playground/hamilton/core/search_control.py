"""Deterministic search-control state for Hamilton.

The LLM proposes scientific search changes, while this module persists the
numerical search incumbent and decides whether the next round should continue
locally or roll back to the incumbent configuration.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTROL_FILE = ".hamilton_search_control.json"
STATE_FILE = ".hamilton_search_state.json"
EVIDENCE_FILE = ".hamilton_evidence_memory.json"
SCIENTIFIC_DECISION_BEGIN = "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->"
SCIENTIFIC_DECISION_END = "<!-- EVO_SCIENTIFIC_DECISION_END -->"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def meaningful_config(
    config: dict[str, Any],
    *,
    controller_owns_budget: bool = False,
) -> dict[str, Any]:
    """Project a result config onto fields that define the scientific search."""
    if not isinstance(config, dict):
        return {}
    projected = copy.deepcopy(
        {
            "data": config.get("data") or {},
            "search": config.get("search") or {},
            "verification": config.get("verification") or {},
        }
    )
    if projected["data"].get("standardize_search") is False:
        projected["data"].pop("standardize_search")
    residual = projected["verification"].get("residual_diagnostics")
    if isinstance(residual, dict) and residual.get("enabled") is False:
        projected["verification"].pop("residual_diagnostics")
    long_horizon = projected["verification"].get("long_horizon_dynamics")
    if isinstance(long_horizon, dict) and long_horizon.get("enabled") is False:
        projected["verification"].pop("long_horizon_dynamics")
    weights = (
        projected["verification"]
        .get("candidate_ranking", {})
        .get("weights")
    )
    if isinstance(weights, dict) and weights.get("long_horizon_penalty") == 0.0:
        weights.pop("long_horizon_penalty")
    if controller_owns_budget:
        projected["search"].pop("max_evals", None)
    # Seeds are frozen by the controller for reproducibility and paired replay.
    # They are not an LLM-authored scientific search intervention.
    projected["search"].pop("random_state", None)
    return projected


def changed_config_fields(
    previous: object,
    current: object,
    prefix: str = "",
) -> list[str]:
    if isinstance(previous, dict) and isinstance(current, dict):
        fields: list[str] = []
        for key in sorted(set(previous) | set(current)):
            child = f"{prefix}.{key}" if prefix else str(key)
            fields.extend(
                changed_config_fields(previous.get(key), current.get(key), child)
            )
        return fields
    return [] if previous == current else [prefix]


def default_control_config(experiment: dict[str, Any]) -> dict[str, Any]:
    raw = experiment.get("search_control")
    raw = raw if isinstance(raw, dict) else {}
    trust = raw.get("trust_region")
    trust = trust if isinstance(trust, dict) else {}
    budget = raw.get("dynamic_budget")
    budget = budget if isinstance(budget, dict) else {}
    max_rounds = int(experiment.get("max_rounds", 1) or 1)
    max_total_evals = experiment.get("max_total_evals")
    return {
        "schema_version": 1,
        "search_advancement": {
            "min_score_improvement": float(
                (raw.get("search_advancement") or {}).get(
                    "min_score_improvement", 0.0
                )
                if isinstance(raw.get("search_advancement"), dict)
                else 0.0
            ),
        },
        "trust_region": {
            "enabled": bool(trust.get("enabled", True)),
            "max_anchor_distance": int(trust.get("max_anchor_distance", 2) or 2),
            "max_step_changes": int(trust.get("max_step_changes", 1) or 1),
            "rollback_after_stale_rounds": int(
                trust.get("rollback_after_stale_rounds", 2) or 2
            ),
        },
        "dynamic_budget": {
            "enabled": bool(
                budget.get("enabled", max_total_evals is not None)
            ),
            "base_evals": int(budget.get("base_evals", 12000) or 12000),
            "min_evals": int(budget.get("min_evals", 4000) or 4000),
            "max_evals": int(budget.get("max_evals", 20000) or 20000),
            "rounding_quantum": int(
                budget.get("rounding_quantum", 500) or 500
            ),
        },
        "max_rounds": max_rounds,
    }


def validate_control_config(control: dict[str, Any]) -> None:
    if control.get("schema_version") != 1:
        raise ValueError("Hamilton search-control schema_version must be 1")
    trust = control.get("trust_region")
    budget = control.get("dynamic_budget")
    advancement = control.get("search_advancement")
    if not isinstance(trust, dict) or not isinstance(budget, dict):
        raise ValueError("Hamilton search-control sections must be objects")
    if not isinstance(advancement, dict):
        raise ValueError("Hamilton search advancement section must be an object")
    if float(advancement.get("min_score_improvement", -1)) < 0:
        raise ValueError("min_score_improvement must be non-negative")
    for name in (
        "max_anchor_distance",
        "max_step_changes",
        "rollback_after_stale_rounds",
    ):
        if int(trust.get(name, 0) or 0) <= 0:
            raise ValueError(f"trust_region.{name} must be positive")
    for name in ("base_evals", "min_evals", "max_evals", "rounding_quantum"):
        if int(budget.get(name, 0) or 0) <= 0:
            raise ValueError(f"dynamic_budget.{name} must be positive")
    if int(budget["min_evals"]) > int(budget["base_evals"]):
        raise ValueError("dynamic_budget.min_evals cannot exceed base_evals")
    if int(budget["base_evals"]) > int(budget["max_evals"]):
        raise ValueError("dynamic_budget.base_evals cannot exceed max_evals")
    if int(control.get("max_rounds", 0) or 0) <= 0:
        raise ValueError("search-control max_rounds must be positive")


def initialize_control(workspace: Path, experiment: dict[str, Any]) -> dict[str, Any]:
    path = workspace / CONTROL_FILE
    if path.is_file():
        control = json.loads(path.read_text(encoding="utf-8"))
    else:
        control = default_control_config(experiment)
        atomic_write_json(path, control)
    validate_control_config(control)
    return control


def read_control(workspace: Path) -> dict[str, Any] | None:
    path = workspace / CONTROL_FILE
    if not path.is_file():
        return None
    control = json.loads(path.read_text(encoding="utf-8"))
    validate_control_config(control)
    return control


def read_state(workspace: Path) -> dict[str, Any]:
    path = workspace / STATE_FILE
    if not path.is_file():
        return {"schema_version": 1, "stale_rounds": 0}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != 1:
        raise ValueError("Hamilton search-state schema_version must be 1")
    return state


def read_evidence_memory(workspace: Path) -> dict[str, Any]:
    path = workspace / EVIDENCE_FILE
    if not path.is_file():
        return {
            "schema_version": 1,
            "updated_after_round": 0,
            "strong": {
                "search_outcomes": [],
                "residual_observations": [],
                "incumbent_history": [],
            },
            "weak": {
                "causal_hypotheses": [],
                "near_miss_candidates": [],
            },
            "invalidated": [],
        }
    memory = json.loads(path.read_text(encoding="utf-8"))
    if memory.get("schema_version") != 1:
        raise ValueError("Hamilton evidence-memory schema_version must be 1")
    return memory


def _read_latest_scientific_decision(workspace: Path) -> dict[str, Any]:
    path = workspace / "plan.md"
    if not path.is_file():
        return {}
    content = path.read_text(encoding="utf-8")
    start = content.rfind(SCIENTIFIC_DECISION_BEGIN)
    if start < 0:
        return {}
    start += len(SCIENTIFIC_DECISION_BEGIN)
    end = content.find(SCIENTIFIC_DECISION_END, start)
    if end < 0:
        return {}
    raw = content[start:end].strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1]).strip()
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _result_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _upsert_evidence(
    memory: dict[str, Any],
    section: str,
    category: str,
    record: dict[str, Any],
) -> None:
    entries = memory[section][category]
    existing = next(
        (
            item
            for item in entries
            if item.get("memory_id") == record["memory_id"]
        ),
        None,
    )
    if existing is not None:
        if existing.get("result_sha256") == record.get("result_sha256"):
            existing.clear()
            existing.update(record)
            return
        invalidated = dict(existing)
        invalidated["invalidated_at"] = utc_now()
        invalidated["invalidation_reason"] = "superseded_by_new_frozen_result"
        memory["invalidated"].append(invalidated)
        entries.remove(existing)
    entries.append(record)


def update_evidence_memory(
    workspace: Path,
    *,
    round_num: int,
    current_result_file: str,
    incumbent_result_file: str,
    incumbent_action: str,
    incumbent_score: float,
    changed_fields: list[str],
    governance_audit: dict[str, Any],
) -> dict[str, Any]:
    """Build strong/weak evidence only after deterministic closure audits pass."""
    required_audits = (
        "incumbent_valid",
        "search_advancement_gates_valid",
        "protocol_evidence_valid",
        "residual_feedback_valid",
    )
    if not all(governance_audit.get(name) is True for name in required_audits):
        raise ValueError(
            "evidence memory requires valid incumbent, advancement, protocol, "
            "and residual audits"
        )
    result_path = (workspace / current_result_file).resolve()
    result_path.relative_to(workspace.resolve())
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "completed":
        raise ValueError("evidence memory requires a completed result")
    result_sha256 = _result_sha256(result_path)
    score = float(result["selected"]["scientific_score"])
    equation = result["selected"].get("simplified_equation")
    decision = _read_latest_scientific_decision(workspace)
    search_gates = decision.get("search_advancement_gates")
    if search_gates is None:
        search_gates = decision.get("promotion_gates")
    if not isinstance(search_gates, list):
        search_gates = []

    memory = read_evidence_memory(workspace)
    common = {
        "round": int(round_num),
        "result_file": current_result_file.replace("\\", "/"),
        "result_sha256": result_sha256,
        "recorded_at": utc_now(),
    }
    _upsert_evidence(
        memory,
        "strong",
        "search_outcomes",
        {
            **common,
            "memory_id": f"round:{round_num}:search_outcome",
            "strength": "strong_observation",
            "scope": {
                "changed_fields": list(changed_fields),
                "config": meaningful_config(
                    result.get("config", {}),
                    controller_owns_budget=bool(
                        (read_control(workspace) or {})
                        .get("dynamic_budget", {})
                        .get("enabled")
                    ),
                ),
            },
            "outcome": {
                "incumbent_action": incumbent_action,
                "scientific_score": score,
                "equation": equation,
                "search_advancement_gates": search_gates,
            },
            "interpretation_boundary": (
                "This records the controlled numerical outcome only; it does "
                "not establish that the changed field is universally good or bad."
            ),
        },
    )

    residual = (
        result.get("verification", {})
        .get("residual_diagnostics", {})
        .get("validation", {})
    )
    state_dependence = (
        residual.get("state_dependence", {})
        .get("strongest_absolute_correlation")
    )
    temporal_dependence = (
        residual.get("temporal_structure", {})
        .get("strongest_reported_autocorrelation")
    )
    _upsert_evidence(
        memory,
        "strong",
        "residual_observations",
        {
            **common,
            "memory_id": f"round:{round_num}:residual_observation",
            "strength": "strong_observation",
            "state_dependence": state_dependence,
            "temporal_dependence": temporal_dependence,
            "interpretation_boundary": (
                "The residual structure is measured evidence, but its physical "
                "or algebraic cause remains non-unique."
            ),
        },
    )

    if incumbent_action in {"initialize", "promote"}:
        incumbent_path = (workspace / incumbent_result_file).resolve()
        incumbent_path.relative_to(workspace.resolve())
        incumbent_payload = json.loads(
            incumbent_path.read_text(encoding="utf-8")
        )
        _upsert_evidence(
            memory,
            "strong",
            "incumbent_history",
            {
                "memory_id": f"round:{round_num}:incumbent",
                "round": int(round_num),
                "result_file": incumbent_result_file.replace("\\", "/"),
                "result_sha256": _result_sha256(incumbent_path),
                "recorded_at": utc_now(),
                "strength": "strong_search_evidence",
                "action": incumbent_action,
                "scientific_score": float(incumbent_score),
                "equation": incumbent_payload.get("selected", {}).get(
                    "simplified_equation"
                ),
            },
        )

    strategy = decision.get("next_strategy")
    if isinstance(strategy, dict):
        _upsert_evidence(
            memory,
            "weak",
            "causal_hypotheses",
            {
                **common,
                "memory_id": f"round:{round_num}:next_hypothesis",
                "strength": "weak_hypothesis",
                "diagnosed_failure": strategy.get("diagnosed_failure"),
                "proposed_config_field": strategy.get("config_field"),
                "proposed_config_patch": strategy.get("config_patch"),
                "alternative_explanation": strategy.get(
                    "alternative_explanation"
                ),
                "expected_effect": strategy.get("expected_effect"),
                "expected_residual_change": strategy.get(
                    "expected_residual_change"
                ),
                "falsification": strategy.get("falsification"),
                "status": "untested",
            },
        )

    near_miss_tolerance = max(0.05, 0.10 * abs(float(incumbent_score)))
    if (
        incumbent_action == "retain"
        and score <= float(incumbent_score) + near_miss_tolerance
    ):
        _upsert_evidence(
            memory,
            "weak",
            "near_miss_candidates",
            {
                **common,
                "memory_id": f"round:{round_num}:near_miss",
                "strength": "weak_search_hint",
                "scientific_score": score,
                "incumbent_score": float(incumbent_score),
                "score_gap": score - float(incumbent_score),
                "qualification_tolerance": near_miss_tolerance,
                "equation": equation,
                "reason": (
                    "Completed protocol-valid candidate did not advance the "
                    "search incumbent; retain only as an exploratory hint."
                ),
            },
        )

    memory["updated_after_round"] = max(
        int(memory.get("updated_after_round", 0) or 0),
        int(round_num),
    )
    atomic_write_json(workspace / EVIDENCE_FILE, memory)
    return memory


def compact_evidence_memory(workspace: Path) -> dict[str, Any]:
    memory = read_evidence_memory(workspace)
    return {
        "updated_after_round": memory["updated_after_round"],
        "strong": {
            "search_outcomes": memory["strong"]["search_outcomes"][-10:],
            "residual_observations": memory["strong"][
                "residual_observations"
            ][-6:],
            "incumbent_history": memory["strong"]["incumbent_history"][-6:],
        },
        "weak": {
            "causal_hypotheses": memory["weak"]["causal_hypotheses"][-6:],
            "near_miss_candidates": memory["weak"][
                "near_miss_candidates"
            ][-6:],
        },
    }


def update_state(
    workspace: Path,
    *,
    round_num: int,
    current_result_file: str,
    incumbent_result_file: str,
    incumbent_action: str,
    incumbent_score: float,
    incumbent_equation: str | None,
    incumbent_config: dict[str, Any],
) -> dict[str, Any]:
    """Persist the search incumbent and select the next trust-region baseline."""
    control = read_control(workspace)
    if control is None:
        return {}
    state = read_state(workspace)
    if incumbent_action in {"initialize", "promote"}:
        stale_rounds = 0
    else:
        stale_rounds = int(state.get("stale_rounds", 0) or 0) + 1
    rollback_after = int(
        control["trust_region"]["rollback_after_stale_rounds"]
    )
    rollback_required = stale_rounds >= rollback_after
    baseline_result = (
        incumbent_result_file if rollback_required else current_result_file
    )
    payload = {
        "schema_version": 1,
        "updated_at": utc_now(),
        "last_closed_round": int(round_num),
        "stale_rounds": stale_rounds,
        "rollback_required": rollback_required,
        "incumbent": {
            "result_file": incumbent_result_file,
            "score": float(incumbent_score),
            "equation": incumbent_equation,
            "config": meaningful_config(
                incumbent_config,
                controller_owns_budget=bool(
                    control["dynamic_budget"].get("enabled")
                ),
            ),
        },
        "next_round": {
            "baseline_result_file": baseline_result,
            "mode": "rollback_to_incumbent" if rollback_required else "local_step",
            "max_step_changes": int(
                control["trust_region"]["max_step_changes"]
            ),
            "max_anchor_distance": int(
                control["trust_region"]["max_anchor_distance"]
            ),
        },
    }
    atomic_write_json(workspace / STATE_FILE, payload)
    return payload


def round_directive(workspace: Path, round_num: int) -> dict[str, Any] | None:
    control = read_control(workspace)
    state = read_state(workspace)
    if control is None or round_num <= 1 or not state.get("incumbent"):
        return None
    return {
        "round": round_num,
        "baseline_result_file": state["next_round"]["baseline_result_file"],
        "baseline_mode": state["next_round"]["mode"],
        "incumbent_result_file": state["incumbent"]["result_file"],
        "incumbent_score": state["incumbent"]["score"],
        "incumbent_config": state["incumbent"]["config"],
        "stale_rounds": state["stale_rounds"],
        "rollback_required": state["rollback_required"],
        "trust_region": control["trust_region"],
        "dynamic_budget": {
            "enabled": control["dynamic_budget"]["enabled"],
            "note": (
                "search.max_evals is controller-owned and will be allocated "
                "deterministically from the cumulative ledger"
            ),
        },
        "evidence_memory": compact_evidence_memory(workspace),
    }
