#!/usr/bin/env python3
"""Execute one bare-PySR baseline (arm B): 3 independent cold-start rounds, no LLM.

Reads the frozen `round1_baseline.json`, runs three 1500-eval cold-start PySR rounds
with a controller-owned seed (`.hamilton_seed_plan.json`), keeping the lowest
scientific score as incumbent. Makes zero LLM calls.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUNNER = REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import write_json
from playground.hamilton.core.search_control import (
    initialize_control,
    round_directive,
    update_state,
)

MAX_ROUNDS = 3
PER_ROUND = 1500
MAX_TOTAL_EVALS = 4500


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def engine_evals(result: dict[str, Any]) -> float:
    telemetry = result.get("engine_telemetry", {})
    warm = telemetry.get("warm_start_session", {}) if isinstance(telemetry, dict) else {}
    return float(warm.get("round_engine_measured_evaluations", 0) or 0)


def persist_noop_continue(workspace: Path) -> None:
    """Authorize the next round's no-op continuation in the trust-region audit.

    ``audit_single_field_adaptation`` allows ``changed_fields=[]`` only when
    ``allow_noop_continue`` is set AND the state carries a binding ``continue``
    controller policy (so ``expected_adaptive_config_patch`` returns ``{}``).
    """
    state = read(workspace / ".hamilton_search_state.json")
    policy = state.setdefault("next_round", {}).setdefault("controller_policy", {})
    policy["enabled"] = True
    policy["binding"] = True
    policy["action"] = {"action": "continue", "config_patch": {}, "requires_restart": False}
    policy["source"] = "controller"
    policy["adopted"] = True
    write_json(workspace / ".hamilton_search_state.json", state)


def reset_workspace_state(workspace: Path) -> None:
    """Drop generated per-run state so a fresh baseline execution is idempotent.

    Keeps the frozen inputs (round1_baseline.json, .hamilton_seed_plan.json,
    .hamilton_budget.json, input/data.csv) and removes the evaluation ledger,
    search control/state, and any round/session artifacts a prior run left behind.
    """
    for name in (
        ".hamilton_evaluation_ledger.json",
        ".hamilton_evaluation_ledger.lock",
        ".hamilton_search_control.json",
        ".hamilton_search_state.json",
        "baseline_summary.json",
    ):
        (workspace / name).unlink(missing_ok=True)
    for sub in ("history", "session"):
        shutil.rmtree(workspace / sub, ignore_errors=True)


def execute(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    reset_workspace_state(workspace)
    baseline = read(workspace / "round1_baseline.json")
    experiment = {
        "max_rounds": MAX_ROUNDS,
        "max_total_evals": MAX_TOTAL_EVALS,
        "search_control": {
            "trust_region": {
                "enabled": True,
                "allow_noop_continue": True,
                "max_anchor_distance": 2,
                "max_step_changes": 1,
                "rollback_after_stale_rounds": 3,
            },
            "dynamic_budget": {
                "enabled": True,
                "base_evals": PER_ROUND,
                "min_evals": PER_ROUND,
                "max_evals": PER_ROUND,
                "rounding_quantum": 500,
            },
        },
    }
    initialize_control(workspace, experiment)

    base_experiment_id = baseline["experiment_id"].rsplit("__round", 1)[0]
    incumbent: dict[str, Any] | None = None
    rounds: list[dict[str, Any]] = []

    for round_num in range(1, MAX_ROUNDS + 1):
        if round_num == 1:
            current = copy.deepcopy(baseline)
        else:
            directive = round_directive(workspace, round_num)
            if not isinstance(directive, dict):
                raise RuntimeError(f"round {round_num} lacks a controller directive")
            base_file = directive["baseline_result_file"]
            current = copy.deepcopy(read(workspace / base_file)["config"])
            current.pop("_controller", None)
            current.pop("search_session", None)
            current["experiment_id"] = f"{base_experiment_id}__round{round_num}"
            current["output"]["result_file"] = f"history/round{round_num}/results/result.json"
            current["output"]["run_directory"] = f"history/round{round_num}/results/pysr"
            current["search"]["max_evals"] = PER_ROUND

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
                "config": result.get("config"),
            }
        else:
            incumbent_action = "retain"

        update_state(
            workspace,
            round_num=round_num,
            current_result_file=f"history/round{round_num}/results/result.json",
            incumbent_result_file=incumbent["result_file"],
            incumbent_action=incumbent_action,
            incumbent_score=float(incumbent["score"]),
            incumbent_equation=incumbent.get("equation"),
            incumbent_config=incumbent["config"],
        )
        if round_num < MAX_ROUNDS:
            persist_noop_continue(workspace)
        rounds.append({
            "round": round_num,
            "selected_score": score,
            "incumbent_action": incumbent_action,
            "incumbent_score": float(incumbent["score"]),
            "engine_measured_evaluations": engine_evals(result),
            "attempts": attempts,
        })

    summary = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "arm": "bare_pysr",
        "execution_mode": "independent_cold_start_pysr_no_llm",
        "llm_tokens": 0,
        "llm_calls": 0,
        "rounds": rounds,
        "incumbent": incumbent,
    }
    write_json(workspace / "baseline_summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.workspace), indent=2, ensure_ascii=False))
