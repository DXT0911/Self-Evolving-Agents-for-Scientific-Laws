#!/usr/bin/env python3
"""Execute one v6 three-arm governed Hamilton pair.

Arms (see design doc docs/sragent/HAMILTON_V6_CAUSAL_ABLATION_DESIGN_2026-08-16.zh-CN.md):

- ``arm_a_persistent_pysr``: persistent warm-start, controller only, always continue.
- ``arm_b_rule_hamilton``: persistent warm-start, deterministic rule intervention.
- ``arm_c_llm_hamilton``: persistent warm-start, LLM atomic action adopted/rejected
  by the controller.

The controller owns final execution authority in every arm.  The LLM (arm C only)
proposes one atomic action from the frozen whitelist; the controller validates it and
either adopts it or falls back to the deterministic rule.
"""

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
CONFIG = REPO / "configs/hamilton/config_governed_pysr_v6_pilot.yaml"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import write_json
from playground.hamilton.core.compressed_planner import call_atomic_planner
from playground.hamilton.core.governed_policy import (
    choose_atomic_action,
    normalize_atomic_action,
)
from playground.hamilton.core.search_control import (
    initialize_control,
    persist_binding_action,
    review_planner_proposal,
    round_directive,
    update_state,
)

ARMS = {
    "arm_a_persistent_pysr",
    "arm_b_rule_hamilton",
    "arm_c_llm_hamilton",
}


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


def execute(workspace: Path, arm: str) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm!r}")
    workspace = workspace.resolve()
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    experiment = dict(cfg["experiment"])
    atomic = experiment["atomic_policy"]
    max_rounds = int(experiment.get("max_rounds", 3) or 3)
    per_round = int(
        experiment.get("search_control", {})
        .get("dynamic_budget", {})
        .get("base_evals", 1500)
    )
    write_json(workspace / ".hamilton_budget.json", {
        "schema_version": 1,
        "max_total_evals": int(experiment["max_total_evals"]),
        "retry_policy": "one_retry_only_when_engine_evaluations_zero",
    })
    control = initialize_control(workspace, experiment)
    if not control["deterministic_policy"]["binding"]:
        raise ValueError("v6 requires a binding deterministic policy")
    baseline = read(workspace / "round1_baseline.json")
    initial_operators = list(atomic["initial_unary_operators"])
    allowed_operators = list(atomic["allowed_unary_operators"])
    parsimony_bounds = (
        float(atomic["parsimony_bounds"][0]),
        float(atomic["parsimony_bounds"][1]),
    )
    current_operators = list(initial_operators)
    incumbent: dict[str, Any] | None = None
    rounds: list[dict[str, Any]] = []

    for round_num in range(1, max_rounds + 1):
        if round_num == 1:
            current = copy.deepcopy(baseline)
            binding = {
                "action": "continue",
                "config_patch": {},
                "requires_restart": False,
                "source": "controller",
                "adopted": True,
                "authority": "deterministic_controller",
            }
        else:
            directive = round_directive(workspace, round_num)
            if not isinstance(directive, dict):
                raise RuntimeError(f"round {round_num} lacks a controller directive")
            binding = directive["controller_policy"]["recommended_action"]
            base_file = directive["baseline_result_file"]
            current = copy.deepcopy(read(workspace / base_file)["config"])
            current.pop("_controller", None)
            for field, value in binding.get("config_patch", {}).items():
                set_leaf(current, field, value)
            if "search.unary_operators" in binding.get("config_patch", {}):
                current_operators = list(
                    binding["config_patch"]["search.unary_operators"]
                )
            restart = bool(binding.get("requires_restart"))
            compatible = (
                [binding["config_field"]]
                if restart and binding.get("config_field")
                else ["search.parsimony"]
            )
            current["search_session"].update({
                "round": round_num,
                "final_round": round_num == max_rounds,
                "round_action": "restart" if restart else binding.get("action", "continue"),
                "compatible_change_fields": compatible,
            })
            current["search"]["max_evals"] = per_round
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
        snapshot = state["next_round"]["controller_policy"]["snapshot"]

        binding_next: dict[str, Any] | None = None
        if round_num < max_rounds:
            if arm == "arm_a_persistent_pysr":
                binding_next = normalize_atomic_action(
                    {"action": "continue_warm"},
                    current_operators=current_operators,
                    allowed_operators=allowed_operators,
                    parsimony_bounds=parsimony_bounds,
                )
                binding_next.update(
                    source="controller", adopted=True,
                    authority="deterministic_controller",
                )
            elif arm == "arm_b_rule_hamilton":
                rule_intent = choose_atomic_action(
                    snapshot,
                    current_operators=current_operators,
                    allowed_operators=allowed_operators,
                )
                binding_next = normalize_atomic_action(
                    rule_intent,
                    current_operators=current_operators,
                    allowed_operators=allowed_operators,
                    parsimony_bounds=parsimony_bounds,
                    reason=rule_intent.get("reason", ""),
                )
                binding_next.update(
                    source="rule", adopted=True,
                    authority="deterministic_controller",
                )
            elif arm == "arm_c_llm_hamilton":
                proposal = call_atomic_planner(
                    workspace,
                    round_num=round_num,
                    result=result,
                    controller_policy=state["next_round"]["controller_policy"],
                    current_operators=current_operators,
                    allowed_operators=allowed_operators,
                    parsimony_bounds=parsimony_bounds,
                    model="deepseek-v4-flash",
                    max_output_tokens=800,
                    max_total_tokens=60000,
                )
                binding_next = review_planner_proposal(
                    proposal,
                    snapshot,
                    current_operators=current_operators,
                    allowed_operators=allowed_operators,
                    parsimony_bounds=parsimony_bounds,
                )
            persist_binding_action(workspace, binding_next)

        rounds.append({
            "round": round_num,
            "binding_action": binding,
            "selected_score": score,
            "incumbent_action": incumbent_action,
            "incumbent_score": incumbent["score"],
            "engine_measured_evaluations": engine_evals(result),
            "attempts": attempts,
            "next_binding_action": binding_next,
        })

    planner_ledger_path = workspace / ".hamilton_atomic_planner_ledger.json"
    llm_tokens = 0
    planner_calls = 0
    if planner_ledger_path.is_file():
        ledger = read(planner_ledger_path)
        llm_tokens = int(ledger.get("total_token_usage", 0) or 0)
        planner_calls = len(ledger.get("calls", []))
    summary = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "arm": arm,
        "execution_mode": "three_arm_governed_ablation",
        "llm_tokens": llm_tokens,
        "planner_calls": planner_calls,
        "rounds": rounds,
        "incumbent": incumbent,
    }
    write_json(workspace / "v6_governed_summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--arm", required=True, choices=sorted(ARMS))
    args = parser.parse_args()
    print(json.dumps(execute(args.workspace, args.arm), indent=2, ensure_ascii=False))
