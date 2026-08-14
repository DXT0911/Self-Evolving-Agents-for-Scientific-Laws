#!/usr/bin/env python3
"""Execute one v4 binding-policy Hamilton pair without LLM orchestration."""

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
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import write_json
from playground.hamilton.core.search_control import (
    initialize_control,
    round_directive,
    update_state,
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _set_leaf(payload: dict[str, Any], dotted: str, value: Any) -> None:
    node = payload
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            raise ValueError(f"binding patch path is absent: {dotted}")
        node = child
    if parts[-1] not in node:
        raise ValueError(f"binding patch leaf is absent: {dotted}")
    node[parts[-1]] = value


def _engine_evals(result: dict[str, Any]) -> float:
    telemetry = result.get("engine_telemetry", {})
    warm = telemetry.get("warm_start_session", {}) if isinstance(telemetry, dict) else {}
    for value in (
        warm.get("round_engine_measured_evaluations"),
        telemetry.get("engine_measured_evaluations") if isinstance(telemetry, dict) else None,
    ):
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def execute(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    config = yaml.safe_load(
        (REPO / "configs/hamilton/config_governed_pysr_v4_pilot.yaml").read_text(
            encoding="utf-8"
        )
    )
    experiment = dict(config["experiment"])
    write_json(workspace / ".hamilton_budget.json", {
        "schema_version": 1,
        "max_total_evals": int(experiment["max_total_evals"]),
        "retry_policy": "one_retry_only_when_engine_evaluations_zero",
    })
    control = initialize_control(workspace, experiment)
    if not control.get("deterministic_policy", {}).get("binding"):
        raise ValueError("v4 executor requires a binding deterministic policy")

    baseline = _read(workspace / "round1_baseline.json")
    incumbent: dict[str, Any] | None = None
    rounds = []
    for round_num in range(1, 4):
        if round_num == 1:
            current = copy.deepcopy(baseline)
            decision = {"action": "initialize", "config_patch": {}, "authority": "controller"}
        else:
            directive = round_directive(workspace, round_num)
            if not isinstance(directive, dict):
                raise RuntimeError(f"round {round_num} has no controller directive")
            decision = directive["controller_policy"]["recommended_action"]
            action = decision.get("action")
            if action not in {"continue", "modify"} or decision.get("requires_restart"):
                raise RuntimeError(
                    f"binding action cannot execute in frozen warm pilot: {decision}"
                )
            baseline_path = workspace / directive["baseline_result_file"]
            current = copy.deepcopy(_read(baseline_path)["config"])
            current.pop("_controller", None)
            for field, value in decision.get("config_patch", {}).items():
                _set_leaf(current, field, value)
            session = current.setdefault("search_session", {})
            session.update({
                "mode": "warm_start",
                "round": round_num,
                "final_round": round_num == 3,
                "round_action": action,
                "compatible_change_fields": ["search.parsimony"],
            })
            current["search"]["max_evals"] = 1000
            current["output"]["result_file"] = f"history/round{round_num}/results/result.json"
            current["output"]["run_directory"] = "session/pysr"
            current["experiment_id"] = (
                baseline["experiment_id"].rsplit("__round", 1)[0] + f"__round{round_num}"
            )

        config_path = workspace / f"history/round{round_num}/experiment.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(config_path, current)
        result_path = workspace / f"history/round{round_num}/results/result.json"
        attempts = 0
        while True:
            attempts += 1
            completed = subprocess.run(
                [sys.executable, str(RUNNER), "--config", str(config_path.relative_to(workspace))],
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=21600,
            )
            if result_path.is_file():
                result = _read(result_path)
            else:
                result = {"status": "failed", "error": completed.stderr[-2000:]}
            if completed.returncode == 0 and result.get("status") == "completed":
                break
            if attempts >= 2 or _engine_evals(result) != 0:
                raise RuntimeError(
                    f"round {round_num} failed without an authorized retry: "
                    f"returncode={completed.returncode}, engine_evals={_engine_evals(result)}, "
                    f"error={result.get('error')}"
                )

        selected = result.get("selected", {})
        score = float(selected["scientific_score"])
        if incumbent is None or score < float(incumbent["score"]) - 1e-12:
            incumbent_action = "initialize" if incumbent is None else "promote"
            incumbent = {
                "score": score,
                "equation": selected.get("simplified_equation"),
                "result_file": f"history/round{round_num}/results/result.json",
                "config": result["config"],
            }
        else:
            incumbent_action = "retain"
        state = update_state(
            workspace,
            round_num=round_num,
            current_result_file=f"history/round{round_num}/results/result.json",
            incumbent_result_file=str(incumbent["result_file"]),
            incumbent_action=incumbent_action,
            incumbent_score=float(incumbent["score"]),
            incumbent_equation=incumbent.get("equation"),
            incumbent_config=incumbent["config"],
        )
        rounds.append({
            "round": round_num,
            "binding_action": decision,
            "selected_score": score,
            "incumbent_action": incumbent_action,
            "incumbent_score": incumbent["score"],
            "engine_measured_evaluations": _engine_evals(result),
            "attempts": attempts,
            "next_controller_policy": state.get("next_round", {}).get("controller_policy"),
        })

    summary = {
        "schema_version": 1,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "binding_controller_with_llm_advisory_authority_disabled",
        "llm_tokens": 0,
        "rounds": rounds,
        "incumbent": incumbent,
    }
    write_json(workspace / "v4_governed_summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.workspace), indent=2))
