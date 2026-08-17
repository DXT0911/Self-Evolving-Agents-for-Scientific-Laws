#!/usr/bin/env python3
"""Execute Hamilton v6 with an LLM-led, controller-validated search loop."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUNNER = REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"
CLOSE_WORKER = REPO / "evomaster/skills/run-sr-experiment/scripts/close_warm_start_session.py"
DEFAULT_CONFIG = REPO / "configs/hamilton/config_llm_led_pysr_v6.yaml"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import write_json
from playground.hamilton.core.compressed_planner import (
    LLM_DECISION_LEDGER_FILE,
    call_llm_decision_planner,
)
from playground.hamilton.core.decision_feedback import record_decision_feedback
from playground.hamilton.core.findings_writer import write_findings
from playground.hamilton.core.governed_policy import (
    PolicyThresholds,
    build_llm_action_candidates,
)
from playground.hamilton.core.search_control import (
    initialize_control,
    update_evidence_memory,
    update_state,
)


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def set_leaf(payload: dict[str, Any], dotted: str, value: Any) -> None:
    node: Any = payload
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"candidate patch field is missing: {dotted}")
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        raise ValueError(f"candidate patch field is missing: {dotted}")
    node[parts[-1]] = value


def engine_evals(result: dict[str, Any]) -> float:
    telemetry = result.get("engine_telemetry", {})
    warm = telemetry.get("warm_start_session", {}) if isinstance(telemetry, dict) else {}
    return float(warm.get("round_engine_measured_evaluations", 0) or 0)


def terminal_decision(reason: str) -> dict[str, Any]:
    return {
        "hypothesis": "The configured stopping gate has been reached.",
        "candidate_variables": [],
        "candidate_operators": [],
        "selected_candidate_id": "stop",
        "rationale": reason,
        "expected_effect": "Preserve the incumbent without spending more search budget.",
        "falsification": "A separately approved run with more budget finds a better result.",
        "selected_action": {
            "id": "stop",
            "action": "stop",
            "reason": reason,
            "config_field": None,
            "config_patch": {},
            "requires_restart": False,
            "authority": "budget_or_stopping_gate",
        },
        "authority": "budget_or_stopping_gate",
        "planner_status": "not_called",
    }


def write_plan(
    workspace: Path,
    *,
    round_num: int,
    decision: dict[str, Any],
    result_file: str,
) -> None:
    action = decision["selected_action"]
    payload = {
        "round": round_num,
        "protocol_evidence": {
            "valid_result_files": [result_file],
            "invalid_attempts_used_as_scientific_evidence": False,
        },
        "search_advancement_gates": [{"name": "runner_completed", "passed": True}],
        "next_strategy": {
            "action": action["action"],
            "config_field": action.get("config_field"),
            "config_patch": action.get("config_patch", {}),
            "diagnosed_failure": decision["hypothesis"],
            "alternative_explanation": "The pattern may reflect finite search or noise.",
            "expected_effect": decision["expected_effect"],
            "expected_residual_change": decision["expected_effect"],
            "falsification": decision["falsification"],
            "planner_decision": decision,
        },
    }
    text = (
        "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->\n"
    )
    temporary = workspace / "plan.md.tmp"
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(workspace / "plan.md")


def close_worker(workspace: Path, config_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(CLOSE_WORKER),
            "--config",
            str(config_path.relative_to(workspace)),
        ],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "failed to close warm-start worker after early stop: "
            f"{completed.stderr or completed.stdout}"
        )


def execute(workspace: Path, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    workspace = workspace.resolve()
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    experiment = dict(cfg["experiment"])
    min_rounds = int(experiment["min_rounds"])
    max_rounds = int(experiment["max_rounds"])
    evals_per_round = int(experiment["evals_per_round"])
    max_total_evals = int(experiment["max_total_evals"])
    early_stop_patience = int(experiment["early_stop_patience"])
    if not 1 <= min_rounds <= max_rounds:
        raise ValueError("experiment requires 1 <= min_rounds <= max_rounds")
    if evals_per_round <= 0 or max_total_evals < evals_per_round:
        raise ValueError("invalid evaluation budget")

    write_json(workspace / ".hamilton_budget.json", {
        "schema_version": 1,
        "max_total_evals": max_total_evals,
        "retry_policy": "one_retry_only_when_engine_evaluations_zero",
    })
    control = initialize_control(workspace, experiment)
    deterministic = control["deterministic_policy"]
    if deterministic["binding"]:
        raise ValueError("v6 requires the LLM choice to be binding, not the fallback policy")

    baseline = read(workspace / "round1_baseline.json")
    allowed_variables = list(baseline["data"]["feature_columns"])
    allowed_operators = [
        *baseline["search"]["binary_operators"],
        *baseline["search"]["unary_operators"],
    ]
    llm_name = cfg["llm"]["default"]
    llm = cfg["llm"][llm_name]
    planner_cfg = experiment["llm_decision_planner"]
    thresholds = PolicyThresholds(**deterministic.get("thresholds", {}))
    warm_fields = list(deterministic.get("warm_compatible_fields", ["search.parsimony"]))
    timeout = int(cfg.get("session", {}).get("local", {}).get("timeout", 21600))

    incumbent: dict[str, Any] | None = None
    rounds: list[dict[str, Any]] = []
    pending_action = {
        "id": "initialize",
        "action": "initialize",
        "config_patch": {},
        "authority": "initial_configuration",
    }
    requested_evals = 0
    stop_reason: str | None = None
    last_config_path: Path | None = None
    write_findings(workspace, rounds=rounds, incumbent=None, status="initialized")

    for round_num in range(1, max_rounds + 1):
        remaining = max_total_evals - requested_evals
        if remaining <= 0:
            stop_reason = "maximum total evaluation budget reached"
            break
        round_evals = min(evals_per_round, remaining)
        if round_num == 1:
            current = copy.deepcopy(baseline)
        else:
            state = read(workspace / ".hamilton_search_state.json")
            baseline_result = read(workspace / state["next_round"]["baseline_result_file"])
            current = copy.deepcopy(baseline_result["config"])
            current.pop("_config_file", None)
            current.pop("_controller", None)
            for field, value in pending_action.get("config_patch", {}).items():
                set_leaf(current, field, value)
            current["search_session"].update({
                "round": round_num,
                "final_round": round_num == max_rounds or round_evals == remaining,
                "round_action": pending_action["action"],
            })
            current["output"]["result_file"] = f"history/round{round_num}/results/result.json"
            current["output"]["run_directory"] = "session/pysr"
            root_id = baseline["experiment_id"].rsplit("__round", 1)[0]
            current["experiment_id"] = f"{root_id}__round{round_num}"
        current["search"]["max_evals"] = round_evals

        config_file = workspace / f"history/round{round_num}/experiment.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        write_json(config_file, current)
        last_config_path = config_file
        result_file = f"history/round{round_num}/results/result.json"
        result_path = workspace / result_file
        attempts = 0
        while True:
            attempts += 1
            completed = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config_file.relative_to(workspace))],
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            result = read(result_path) if result_path.is_file() else {"status": "failed"}
            if completed.returncode == 0 and result.get("status") == "completed":
                break
            if attempts >= 2 or engine_evals(result) != 0:
                raise RuntimeError(
                    f"round {round_num} failed without an authorized zero-engine retry: "
                    f"returncode={completed.returncode}, engine_evals={engine_evals(result)}, "
                    f"stderr={completed.stderr[-2000:]}"
                )
        requested_evals += round_evals

        score = float(result["selected"]["scientific_score"])
        if incumbent is None or score < float(incumbent["score"]) - 1e-12:
            incumbent_action = "initialize" if incumbent is None else "promote"
            incumbent = {
                "score": score,
                "equation": result["selected"].get("simplified_equation"),
                "result_file": result_file,
                "config": result["config"],
            }
        else:
            incumbent_action = "retain"
        state = update_state(
            workspace,
            round_num=round_num,
            current_result_file=result_file,
            incumbent_result_file=incumbent["result_file"],
            incumbent_action=incumbent_action,
            incumbent_score=float(incumbent["score"]),
            incumbent_equation=incumbent.get("equation"),
            incumbent_config=incumbent["config"],
        )
        next_policy = state["next_round"]["controller_policy"]
        if rounds:
            feedback = record_decision_feedback(
                workspace,
                previous_round=rounds[-1],
                current_round_num=round_num,
                current_incumbent_score=float(incumbent["score"]),
                current_snapshot=next_policy["snapshot"],
                min_score_improvement=thresholds.min_score_improvement,
            )
            rounds[-1]["llm_feedback"] = feedback

        if round_num >= max_rounds:
            stop_reason = "maximum configured rounds reached"
            decision = terminal_decision(stop_reason)
        elif requested_evals >= max_total_evals:
            stop_reason = "maximum total evaluation budget reached"
            decision = terminal_decision(stop_reason)
        elif round_num >= min_rounds and int(state.get("stale_rounds", 0)) >= early_stop_patience:
            stop_reason = f"no incumbent improvement for {early_stop_patience} rounds"
            decision = terminal_decision(stop_reason)
        else:
            envelope = build_llm_action_candidates(
                next_policy["snapshot"],
                thresholds=thresholds,
                warm_compatible_fields=warm_fields,
                allow_stop=round_num >= min_rounds,
            )
            decision = call_llm_decision_planner(
                workspace,
                round_num=round_num,
                result=result,
                controller_policy=next_policy,
                action_envelope=envelope,
                allowed_variables=allowed_variables,
                allowed_operators=allowed_operators,
                model=str(llm["model"]),
                base_url=str(llm["base_url"]),
                max_output_tokens=int(planner_cfg["max_output_tokens"]),
                max_total_tokens=int(experiment["max_total_tokens"]),
                timeout=float(llm.get("timeout", 120)),
            )
            if decision["selected_action"]["action"] == "stop":
                stop_reason = "LLM selected the controller-approved stop candidate"

        write_plan(
            workspace,
            round_num=round_num,
            decision=decision,
            result_file=result_file,
        )
        memory = update_evidence_memory(
            workspace,
            round_num=round_num,
            current_result_file=result_file,
            incumbent_result_file=incumbent["result_file"],
            incumbent_action=incumbent_action,
            incumbent_score=float(incumbent["score"]),
            changed_fields=list(pending_action.get("config_patch", {})),
            governance_audit={
                "incumbent_valid": True,
                "search_advancement_gates_valid": True,
                "protocol_evidence_valid": True,
                "residual_feedback_valid": True,
            },
        )
        record = {
            "round": round_num,
            "binding_action": pending_action,
            "llm_decision": decision,
            "selected_score": score,
            "selected_equation": result["selected"].get("simplified_equation"),
            "incumbent_action": incumbent_action,
            "incumbent_score": incumbent["score"],
            "engine_measured_evaluations": engine_evals(result),
            "requested_evaluations": round_evals,
            "attempts": attempts,
            "memory_updated_after_round": memory["updated_after_round"],
            "diagnostic_snapshot": next_policy["snapshot"],
        }
        rounds.append(record)
        is_stopping = decision["selected_action"]["action"] == "stop"
        write_findings(
            workspace,
            rounds=rounds,
            incumbent=incumbent,
            status="completed" if is_stopping else "running",
            stop_reason=stop_reason if is_stopping else None,
        )
        if is_stopping:
            if not bool(current.get("search_session", {}).get("final_round")):
                close_worker(workspace, config_file)
            break
        pending_action = decision["selected_action"]

    if last_config_path is None:
        raise RuntimeError("Hamilton stopped before completing any round")
    ledger_path = workspace / LLM_DECISION_LEDGER_FILE
    ledger = read(ledger_path) if ledger_path.is_file() else {"calls": [], "total_token_usage": 0}
    summary = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "llm_binding_choice_inside_controller_envelope",
        "stop_reason": stop_reason,
        "completed_rounds": len(rounds),
        "requested_evaluations": requested_evals,
        "llm_tokens": int(ledger.get("total_token_usage", 0)),
        "planner_calls": len(ledger.get("calls", [])),
        "planner_fallbacks": sum(
            1 for item in ledger.get("calls", []) if item.get("status") == "fallback"
        ),
        "rounds": rounds,
        "incumbent": incumbent,
    }
    write_json(workspace / "v6_llm_led_summary.json", summary)
    write_findings(
        workspace,
        rounds=rounds,
        incumbent=incumbent,
        status="completed",
        stop_reason=stop_reason,
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(execute(args.workspace, args.config), indent=2, ensure_ascii=False))
