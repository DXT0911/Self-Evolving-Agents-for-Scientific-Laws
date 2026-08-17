"""Compressed planners for governed Hamilton rounds."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .governed_policy import (
    fallback_planner_decision,
    validate_planner_decision,
    validate_planner_proposal,
)
from .search_control import atomic_write_json, compact_evidence_memory


LEDGER_FILE = ".hamilton_planner_ledger.json"
LLM_DECISION_LEDGER_FILE = ".hamilton_llm_decision_ledger.json"


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


def _llm_decision_input(
    workspace: Path,
    *,
    round_num: int,
    result: dict[str, Any],
    controller_policy: dict[str, Any],
    action_envelope: dict[str, Any],
    allowed_variables: list[str],
    allowed_operators: list[str],
) -> dict[str, Any]:
    selected = result.get("selected")
    selected = selected if isinstance(selected, dict) else {}
    memory = compact_evidence_memory(workspace)
    strong = memory.get("strong") if isinstance(memory.get("strong"), dict) else {}
    weak = memory.get("weak") if isinstance(memory.get("weak"), dict) else {}

    def rounded(value: object) -> float | None:
        try:
            return round(float(value), 8)
        except (TypeError, ValueError):
            return None

    raw_snapshot = controller_policy.get("snapshot", {})
    snapshot = {
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
    prior_outcomes = []
    for item in strong.get("search_outcomes", [])[-5:]:
        if not isinstance(item, dict):
            continue
        outcome = item.get("outcome") if isinstance(item.get("outcome"), dict) else {}
        prior_outcomes.append({
            "round": item.get("round"),
            "scientific_score": rounded(outcome.get("scientific_score")),
            "incumbent_action": outcome.get("incumbent_action"),
        })
    prior_hypotheses = []
    for item in weak.get("causal_hypotheses", [])[-4:]:
        if isinstance(item, dict):
            prior_hypotheses.append({
                "hypothesis": item.get("diagnosed_failure"),
                "status": item.get("status"),
            })
    equation = selected.get("simplified_equation")
    if isinstance(equation, str):
        equation = equation[:1000]
    else:
        equation = None
    return {
        "decision_after_round": round_num,
        "current_result": {
            "scientific_score": rounded(selected.get("scientific_score")),
            "complexity": int(selected.get("complexity", 0) or 0),
            "equation": equation,
        },
        "diagnostic_snapshot": snapshot,
        "prior_outcomes": prior_outcomes,
        "prior_hypotheses": prior_hypotheses,
        "action_candidates": action_envelope["candidates"],
        "fallback_candidate_id": action_envelope["fallback_candidate_id"],
        "frozen_envelope": {
            "variables": allowed_variables,
            "operators": allowed_operators,
            "planner_authority": (
                "choose exactly one candidate id; the validated choice is binding"
            ),
        },
        "privacy_boundary": (
            "No raw data rows, file paths, API secrets, or unrestricted config fields "
            "are included. The selected equation and aggregate diagnostics are included."
        ),
    }


def call_llm_decision_planner(
    workspace: Path,
    *,
    round_num: int,
    result: dict[str, Any],
    controller_policy: dict[str, Any],
    action_envelope: dict[str, Any],
    allowed_variables: list[str],
    allowed_operators: list[str],
    model: str = "deepseek-v4-pro",
    base_url: str = "https://api.deepseek.com",
    max_output_tokens: int = 1000,
    max_total_tokens: int = 60000,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Let the LLM make a binding choice inside a controller-owned envelope.

    Provider, parsing, validation, and token failures are converted into an
    auditable deterministic fallback so a long PySR run can continue safely.
    """
    workspace = workspace.resolve()
    candidates = list(action_envelope.get("candidates", []))
    fallback_id = str(action_envelope.get("fallback_candidate_id", ""))
    payload = _llm_decision_input(
        workspace,
        round_num=round_num,
        result=result,
        controller_policy=controller_policy,
        action_envelope=action_envelope,
        allowed_variables=allowed_variables,
        allowed_operators=allowed_operators,
    )
    input_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    ledger_path = workspace / LLM_DECISION_LEDGER_FILE
    ledger = (
        json.loads(ledger_path.read_text(encoding="utf-8"))
        if ledger_path.is_file()
        else {
            "schema_version": 1,
            "model": model,
            "token_ceiling": max_total_tokens,
            "calls": [],
            "total_token_usage": 0,
        }
    )
    for record in ledger.get("calls", []):
        if record.get("round") == round_num:
            if record.get("input_sha256") != input_hash:
                raise ValueError("LLM decision round already exists with different frozen input")
            return dict(record["decision"])

    used = sum(int(item.get("usage", {}).get("total_tokens", 0)) for item in ledger["calls"])
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    error: dict[str, str] | None = None
    try:
        if used + max_output_tokens >= max_total_tokens:
            raise RuntimeError("planner token ceiling cannot safely admit another call")
        api_key = os.environ.get("HAMILTON_API_KEY")
        if not api_key:
            raise RuntimeError("HAMILTON_API_KEY is required for the LLM decision planner")

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, max_retries=2)
        system = (
            "Return one compact JSON object only. You are the primary strategy selector "
            "for a symbolic-regression agent. Compare the measured result, residual "
            "diagnostics, prior outcomes, and controller-approved action candidates. "
            "Choose exactly one selected_candidate_id. Your validated choice will control "
            "the next PySR round. You may not invent config values, budgets, variables, "
            "operators, or candidate ids. Required keys: hypothesis, candidate_variables, "
            "candidate_operators, selected_candidate_id, rationale, expected_effect, "
            "falsification. Keep every explanation concise and falsifiable."
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
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
        decision = validate_planner_decision(
            json.loads(content),
            action_candidates=candidates,
            allowed_variables=allowed_variables,
            allowed_operators=allowed_operators,
        )
        response_usage = response.usage
        usage = {
            "prompt_tokens": int(getattr(response_usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(response_usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(response_usage, "total_tokens", 0) or 0),
        }
        if used + usage["total_tokens"] > max_total_tokens:
            raise RuntimeError("planner provider usage exceeded the frozen token ceiling")
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        decision = fallback_planner_decision(
            action_candidates=candidates,
            fallback_candidate_id=fallback_id,
            reason=f"LLM planner fallback after {error['type']}: {error['message']}",
        )

    record = {
        "round": round_num,
        "called_at": _utc_now(),
        "model": model,
        "thinking": "disabled",
        "response_format": "json_object",
        "input_sha256": input_hash,
        "usage": usage,
        "status": decision["planner_status"],
        "decision": decision,
    }
    if error is not None:
        record["error"] = error
    ledger["calls"].append(record)
    ledger["total_token_usage"] = used + usage["total_tokens"]
    atomic_write_json(ledger_path, ledger)
    round_dir = workspace / "history" / f"round{round_num}"
    round_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(round_dir / "llm_decision.json", record)
    return decision
