"""One-shot, advisory-only planner for governed Hamilton rounds."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .governed_policy import ATOMIC_ACTIONS, validate_planner_proposal
from .search_control import atomic_write_json, compact_evidence_memory


LEDGER_FILE = ".hamilton_planner_ledger.json"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _planner_input(
    workspace: Path,
    *,
    round_num: int,
    result: dict[str, Any],
    controller_policy: dict[str, Any],
    allowed_variables: list[str],
    allowed_operators: list[str],
) -> dict[str, Any]:
    selected = result.get("selected", {})
    memory = compact_evidence_memory(workspace)
    strong = memory.get("strong", {})
    weak = memory.get("weak", {})
    routed = memory.get("routed", {})

    def rounded(value: object) -> float | None:
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            return None

    prior_scores = [
        rounded(item.get("outcome", {}).get("scientific_score"))
        for item in strong.get("search_outcomes", [])[-3:]
        if isinstance(item, dict)
    ]
    prior_hypotheses = [
        {
            "hypothesis": item.get("diagnosed_failure"),
            "status": item.get("status"),
        }
        for item in weak.get("causal_hypotheses", [])[-2:]
        if isinstance(item, dict)
    ]
    raw_snapshot = controller_policy.get("snapshot", {})
    safe_snapshot = {
        key: value if isinstance(value, bool) else rounded(value)
        for key, value in raw_snapshot.items()
        if key in {
            "scientific_score",
            "validation_nrmse",
            "score_improvement",
            "improved",
            "complexity_fraction",
            "parsimony",
            "material_residual_correlation",
            "positive_influence_terms",
            "stale_rounds_before",
            "rollback_required",
        }
    }
    return {
        "round": round_num,
        "selected": {
            "scientific_score": rounded(selected.get("scientific_score")),
            "complexity": int(selected.get("complexity", 0) or 0),
        },
        "diagnostic_snapshot": safe_snapshot,
        "controller_action": {
            "action": controller_policy.get("action", {}).get("action"),
            "reason": controller_policy.get("action", {}).get("reason"),
        },
        "memory_summary": {
            "updated_after_round": memory.get("updated_after_round", 0),
            "prior_scores": prior_scores,
            "prior_hypotheses": prior_hypotheses,
            "partition_counts": {
                name: len(items) if isinstance(items, list) else 0
                for name, items in routed.items()
            },
        },
        "frozen_envelope": {
            "variables": allowed_variables,
            "operators": allowed_operators,
            "planner_authority": "advisory_only",
        },
        "privacy_boundary": (
            "No raw rows, equations, coefficients, term text, configs, paths, or "
            "result hashes are included in this planner payload."
        ),
    }


def call_compressed_planner(
    workspace: Path,
    *,
    round_num: int,
    result: dict[str, Any],
    controller_policy: dict[str, Any],
    allowed_variables: list[str],
    allowed_operators: list[str],
    model: str = "deepseek-v4-flash",
    base_url: str = "https://api.deepseek.com",
    max_output_tokens: int = 800,
    max_total_tokens: int = 60000,
) -> dict[str, Any]:
    """Make exactly one logical planner call and persist an idempotent audit record."""
    workspace = workspace.resolve()
    payload = _planner_input(
        workspace,
        round_num=round_num,
        result=result,
        controller_policy=controller_policy,
        allowed_variables=allowed_variables,
        allowed_operators=allowed_operators,
    )
    input_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    ledger_path = workspace / LEDGER_FILE
    ledger = (
        json.loads(ledger_path.read_text(encoding="utf-8"))
        if ledger_path.is_file()
        else {"schema_version": 1, "model": model, "token_ceiling": max_total_tokens, "calls": []}
    )
    for record in ledger.get("calls", []):
        if record.get("round") == round_num:
            if record.get("input_sha256") != input_hash:
                raise ValueError("planner round already exists with different frozen input")
            return dict(record["proposal"])
    used = sum(int(item.get("usage", {}).get("total_tokens", 0)) for item in ledger["calls"])
    if used + max_output_tokens >= max_total_tokens:
        raise RuntimeError("planner token ceiling cannot safely admit another call")
    api_key = os.environ.get("HAMILTON_API_KEY")
    if not api_key:
        raise RuntimeError("HAMILTON_API_KEY is required for the compressed planner")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=2)
    system = (
        "Return one compact JSON object only. You are an advisory symbolic-regression "
        "planner. State one falsifiable structural hypothesis using only the frozen "
        "variables/operators. You cannot choose candidates, budgets, config values, "
        "or override the supplied controller action. Required keys: hypothesis, "
        "candidate_variables, candidate_operators, requested_action, falsification."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": _canonical(payload)},
        ],
        temperature=0.0,
        max_tokens=max_output_tokens,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
        timeout=120,
    )
    content = response.choices[0].message.content or ""
    proposal = validate_planner_proposal(
        json.loads(content),
        allowed_variables=allowed_variables,
        allowed_operators=allowed_operators,
    )
    usage = {
        "prompt_tokens": int(response.usage.prompt_tokens),
        "completion_tokens": int(response.usage.completion_tokens),
        "total_tokens": int(response.usage.total_tokens),
    }
    if used + usage["total_tokens"] > max_total_tokens:
        raise RuntimeError("planner provider usage exceeded the frozen token ceiling")
    record = {
        "round": round_num,
        "called_at": _utc_now(),
        "model": model,
        "thinking": "disabled",
        "response_format": "json_object",
        "input_sha256": input_hash,
        "usage": usage,
        "proposal": proposal,
    }
    ledger["calls"].append(record)
    ledger["total_token_usage"] = used + usage["total_tokens"]
    atomic_write_json(ledger_path, ledger)
    round_dir = workspace / "history" / f"round{round_num}"
    atomic_write_json(round_dir / "planner_proposal.json", record)
    return proposal


def _validate_atomic_intent(atomic: object) -> dict[str, Any]:
    """Structural check of an LLM atomic action intent (envelope/bounds are applied later)."""
    if not isinstance(atomic, dict):
        raise ValueError("planner atomic_action must be an object")
    action = atomic.get("action")
    if action not in ATOMIC_ACTIONS:
        raise ValueError(
            f"planner atomic_action.action must be one of {sorted(ATOMIC_ACTIONS)}"
        )
    normalized: dict[str, Any] = {"action": action}
    if action in {"add_operator", "remove_operator"}:
        operator = atomic.get("operator")
        if not isinstance(operator, str) or not operator:
            raise ValueError(f"{action} requires a non-empty operator name")
        normalized["operator"] = operator
    if action == "adjust_parsimony":
        try:
            normalized["value"] = float(atomic.get("value"))
        except (TypeError, ValueError):
            raise ValueError("adjust_parsimony requires a numeric value")
    return normalized


def _atomic_planner_input(
    workspace: Path,
    *,
    round_num: int,
    result: dict[str, Any],
    controller_policy: dict[str, Any],
    current_operators: list[str],
    allowed_operators: list[str],
    parsimony_bounds: tuple[float, float],
) -> dict[str, Any]:
    selected = result.get("selected", {})
    memory = compact_evidence_memory(workspace)

    def rounded(value: object) -> float | None:
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            return None

    raw_snapshot = controller_policy.get("snapshot", {})
    safe_snapshot = {
        key: value if isinstance(value, bool) else rounded(value)
        for key, value in raw_snapshot.items()
        if key in {
            "scientific_score",
            "validation_nrmse",
            "score_improvement",
            "improved",
            "complexity_fraction",
            "parsimony",
            "material_residual_correlation",
            "positive_influence_terms",
            "stale_rounds_before",
            "rollback_required",
        }
    }
    current = list(current_operators)
    return {
        "round": round_num,
        "selected": {
            "scientific_score": rounded(selected.get("scientific_score")),
            "complexity": int(selected.get("complexity", 0) or 0),
        },
        "diagnostic_snapshot": safe_snapshot,
        "controller_action": {
            "action": controller_policy.get("action", {}).get("action"),
            "reason": controller_policy.get("action", {}).get("reason"),
        },
        "memory_summary": {
            "updated_after_round": memory.get("updated_after_round", 0),
            "prior_scores": [
                rounded(item.get("outcome", {}).get("scientific_score"))
                for item in memory.get("strong", {}).get("search_outcomes", [])[-3:]
                if isinstance(item, dict)
            ],
            "partition_counts": {
                name: len(items) if isinstance(items, list) else 0
                for name, items in memory.get("routed", {}).items()
            },
        },
        "frozen_envelope": {
            "current_unary_operators": current,
            "addable_unary_operators": [
                op for op in allowed_operators if op not in current
            ],
            "removable_unary_operators": current,
            "parsimony_bounds": [
                float(parsimony_bounds[0]),
                float(parsimony_bounds[1]),
            ],
            "atomic_actions": sorted(ATOMIC_ACTIONS),
            "planner_authority": "propose_one_atomic_action_adopted_or_rejected_by_controller",
        },
        "privacy_boundary": (
            "No raw rows, equations, coefficients, term text, configs, paths, or "
            "result hashes are included in this planner payload."
        ),
    }


ATOMIC_LEDGER_FILE = ".hamilton_atomic_planner_ledger.json"


def call_atomic_planner(
    workspace: Path,
    *,
    round_num: int,
    result: dict[str, Any],
    controller_policy: dict[str, Any],
    current_operators: list[str],
    allowed_operators: list[str],
    parsimony_bounds: tuple[float, float],
    model: str = "deepseek-v4-flash",
    base_url: str = "https://api.deepseek.com",
    max_output_tokens: int = 800,
    max_total_tokens: int = 60000,
) -> dict[str, Any]:
    """Make exactly one atomic-intervention planner call and persist an audit record.

    Unlike :func:`call_compressed_planner` (advisory only), the returned
    ``atomic_action`` is a real intent that :func:`review_planner_proposal` can adopt
    or reject.  It never returns a concrete config patch: the controller computes the
    patch from the current operator set and frozen envelope.
    """
    workspace = workspace.resolve()
    payload = _atomic_planner_input(
        workspace,
        round_num=round_num,
        result=result,
        controller_policy=controller_policy,
        current_operators=current_operators,
        allowed_operators=allowed_operators,
        parsimony_bounds=parsimony_bounds,
    )
    input_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    ledger_path = workspace / ATOMIC_LEDGER_FILE
    ledger = (
        json.loads(ledger_path.read_text(encoding="utf-8"))
        if ledger_path.is_file()
        else {"schema_version": 1, "model": model, "token_ceiling": max_total_tokens, "calls": []}
    )
    for record in ledger.get("calls", []):
        if record.get("round") == round_num:
            if record.get("input_sha256") != input_hash:
                raise ValueError("atomic planner round already exists with different frozen input")
            return dict(record["proposal"])
    used = sum(int(item.get("usage", {}).get("total_tokens", 0)) for item in ledger["calls"])
    if used + max_output_tokens >= max_total_tokens:
        raise RuntimeError("atomic planner token ceiling cannot safely admit another call")
    api_key = os.environ.get("HAMILTON_API_KEY")
    if not api_key:
        raise RuntimeError("HAMILTON_API_KEY is required for the atomic planner")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=2)
    system = (
        "Return one compact JSON object only. You are a symbolic-regression intervention "
        "planner. Given the sanitized diagnostic snapshot and the frozen operator envelope, "
        "propose exactly one atomic action that the controller will validate, then adopt "
        "or reject. You cannot choose budgets, equations, or config values outside the "
        "frozen bounds. Required keys: hypothesis, falsification, atomic_action.\n"
        "atomic_action is exactly one of:\n"
        '  {"action":"continue_warm"}\n'
        '  {"action":"adjust_parsimony","value":<float within parsimony_bounds>}\n'
        '  {"action":"add_operator","operator":"<name in addable_unary_operators>"}\n'
        '  {"action":"remove_operator","operator":"<name in removable_unary_operators>"}\n'
        '  {"action":"restart_same"}\n'
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": _canonical(payload)},
        ],
        temperature=0.0,
        max_tokens=max_output_tokens,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
        timeout=120,
    )
    content = response.choices[0].message.content or ""
    parsed = json.loads(content)
    hypothesis = parsed.get("hypothesis")
    falsification = parsed.get("falsification")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("atomic planner proposal requires a non-empty hypothesis")
    if not isinstance(falsification, str) or not falsification.strip():
        raise ValueError("atomic planner proposal requires a non-empty falsification")
    atomic = _validate_atomic_intent(parsed.get("atomic_action"))
    proposal = {
        "hypothesis": hypothesis.strip(),
        "falsification": falsification.strip(),
        "atomic_action": atomic,
        "authority": "propose_one_atomic_action_adopted_or_rejected_by_controller",
    }
    usage = {
        "prompt_tokens": int(response.usage.prompt_tokens),
        "completion_tokens": int(response.usage.completion_tokens),
        "total_tokens": int(response.usage.total_tokens),
    }
    if used + usage["total_tokens"] > max_total_tokens:
        raise RuntimeError("atomic planner provider usage exceeded the frozen token ceiling")
    record = {
        "round": round_num,
        "called_at": _utc_now(),
        "model": model,
        "thinking": "disabled",
        "response_format": "json_object",
        "input_sha256": input_hash,
        "usage": usage,
        "proposal": proposal,
    }
    ledger["calls"].append(record)
    ledger["total_token_usage"] = used + usage["total_tokens"]
    atomic_write_json(ledger_path, ledger)
    round_dir = workspace / "history" / f"round{round_num}"
    atomic_write_json(round_dir / "atomic_planner_proposal.json", record)
    return proposal
