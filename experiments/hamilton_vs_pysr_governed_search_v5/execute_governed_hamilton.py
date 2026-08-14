#!/usr/bin/env python3
"""Execute one full v5 Hamilton pair: one-shot planner plus binding controller."""

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
CONFIG = REPO / "configs/hamilton/config_governed_pysr_v5_pilot.yaml"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import write_json
from playground.hamilton.core.compressed_planner import call_compressed_planner
from playground.hamilton.core.search_control import (
    initialize_control,
    round_directive,
    update_evidence_memory,
    update_state,
)


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def set_leaf(payload: dict[str, Any], dotted: str, value: Any) -> None:
    node = payload
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def engine_evals(result: dict[str, Any]) -> float:
    telemetry = result.get("engine_telemetry", {})
    warm = telemetry.get("warm_start_session", {}) if isinstance(telemetry, dict) else {}
    return float(warm.get("round_engine_measured_evaluations", 0) or 0)


def write_plan(
    workspace: Path,
    *,
    round_num: int,
    proposal: dict[str, Any],
    controller_action: dict[str, Any],
    result_file: str,
) -> None:
    action = controller_action.get("action", "stop")
    decision = {
        "round": round_num,
        "protocol_evidence": {
            "valid_result_files": [result_file],
            "invalid_attempts_used_as_scientific_evidence": False,
        },
        "search_advancement_gates": [{"name": "runner_completed", "passed": True}],
        "next_strategy": {
            "action": action,
            "config_field": controller_action.get("config_field"),
            "config_patch": controller_action.get("config_patch", {}),
            "diagnosed_failure": proposal["hypothesis"],
            "alternative_explanation": "The measured pattern may reflect finite search or noise.",
            "expected_effect": "Advisory hypothesis only; controller action remains authoritative.",
            "expected_residual_change": "Tested only if a later controller action enters its envelope.",
            "falsification": proposal["falsification"],
            "planner_proposal": proposal,
        },
    }
    text = (
        "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->\n"
        + json.dumps(decision, ensure_ascii=False, indent=2)
        + "\n<!-- EVO_SCIENTIFIC_DECISION_END -->\n"
    )
    (workspace / "plan.md").write_text(text, encoding="utf-8")


def execute(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    experiment = dict(cfg["experiment"])
    write_json(workspace / ".hamilton_budget.json", {
        "schema_version": 1,
        "max_total_evals": int(experiment["max_total_evals"]),
        "retry_policy": "one_retry_only_when_engine_evaluations_zero",
    })
    control = initialize_control(workspace, experiment)
    if not control["deterministic_policy"]["binding"]:
        raise ValueError("v5 requires a binding deterministic policy")
    baseline = read(workspace / "round1_baseline.json")
    allowed_variables = list(baseline["data"]["feature_columns"])
    allowed_operators = [
        *baseline["search"]["binary_operators"],
        *baseline["search"]["unary_operators"],
    ]
    incumbent: dict[str, Any] | None = None
    rounds = []

    for round_num in range(1, 4):
        if round_num == 1:
            current = copy.deepcopy(baseline)
            binding_action = {"action": "initialize", "config_patch": {}, "authority": "controller"}
        else:
            directive = round_directive(workspace, round_num)
            if not isinstance(directive, dict):
                raise RuntimeError(f"round {round_num} lacks a controller directive")
            binding_action = directive["controller_policy"]["recommended_action"]
            action = binding_action.get("action")
            if action not in {"continue", "modify"} or binding_action.get("requires_restart"):
                raise RuntimeError(f"non-warm binding action cannot run in this pilot: {binding_action}")
            current = copy.deepcopy(read(workspace / directive["baseline_result_file"])["config"])
            current.pop("_controller", None)
            for field, value in binding_action.get("config_patch", {}).items():
                set_leaf(current, field, value)
            current["search_session"].update({
                "round": round_num,
                "final_round": round_num == 3,
                "round_action": action,
            })
            current["search"]["max_evals"] = 1500
            current["output"]["result_file"] = f"history/round{round_num}/results/result.json"
            current["output"]["run_directory"] = "session/pysr"
            current["experiment_id"] = baseline["experiment_id"].rsplit("__round", 1)[0] + f"__round{round_num}"

        config_path = workspace / f"history/round{round_num}/experiment.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(config_path, current)
        result_path = workspace / f"history/round{round_num}/results/result.json"
        attempts = 0
        while True:
            attempts += 1
            completed = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config_path.relative_to(workspace))],
                cwd=workspace, text=True, capture_output=True, timeout=21600,
            )
            result = read(result_path) if result_path.is_file() else {"status": "failed"}
            if completed.returncode == 0 and result.get("status") == "completed":
                break
            if attempts >= 2 or engine_evals(result) != 0:
                raise RuntimeError(
                    f"round {round_num} failed without an authorized zero-engine retry: "
                    f"returncode={completed.returncode}, engine_evals={engine_evals(result)}"
                )

        score = float(result["selected"]["scientific_score"])
        if incumbent is None or score < float(incumbent["score"]) - 1e-12:
            incumbent_action = "initialize" if incumbent is None else "promote"
            incumbent = {
                "score": score,
                "equation": result["selected"].get("simplified_equation"),
                "result_file": f"history/round{round_num}/results/result.json",
                "config": result["config"],
            }
        else:
            incumbent_action = "retain"
        state = update_state(
            workspace,
            round_num=round_num,
            current_result_file=f"history/round{round_num}/results/result.json",
            incumbent_result_file=incumbent["result_file"],
            incumbent_action=incumbent_action,
            incumbent_score=float(incumbent["score"]),
            incumbent_equation=incumbent.get("equation"),
            incumbent_config=incumbent["config"],
        )
        next_policy = state["next_round"]["controller_policy"]
        proposal = call_compressed_planner(
            workspace,
            round_num=round_num,
            result=result,
            controller_policy=next_policy,
            allowed_variables=allowed_variables,
            allowed_operators=allowed_operators,
            model="deepseek-v4-flash",
            max_output_tokens=800,
            max_total_tokens=60000,
        )
        result_file = f"history/round{round_num}/results/result.json"
        write_plan(
            workspace,
            round_num=round_num,
            proposal=proposal,
            controller_action=next_policy["action"],
            result_file=result_file,
        )
        memory = update_evidence_memory(
            workspace,
            round_num=round_num,
            current_result_file=result_file,
            incumbent_result_file=incumbent["result_file"],
            incumbent_action=incumbent_action,
            incumbent_score=float(incumbent["score"]),
            changed_fields=list(binding_action.get("config_patch", {})),
            governance_audit={
                "incumbent_valid": True,
                "search_advancement_gates_valid": True,
                "protocol_evidence_valid": True,
                "residual_feedback_valid": True,
            },
        )
        rounds.append({
            "round": round_num,
            "binding_action": binding_action,
            "planner_proposal": proposal,
            "selected_score": score,
            "incumbent_action": incumbent_action,
            "incumbent_score": incumbent["score"],
            "engine_measured_evaluations": engine_evals(result),
            "attempts": attempts,
            "memory_updated_after_round": memory["updated_after_round"],
            "next_controller_policy": next_policy,
        })

    planner_ledger = read(workspace / ".hamilton_planner_ledger.json")
    summary = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "one_shot_llm_planner_plus_binding_controller",
        "llm_tokens": planner_ledger["total_token_usage"],
        "planner_calls": len(planner_ledger["calls"]),
        "rounds": rounds,
        "incumbent": incumbent,
    }
    write_json(workspace / "v5_governed_summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.workspace), indent=2, ensure_ascii=False))
