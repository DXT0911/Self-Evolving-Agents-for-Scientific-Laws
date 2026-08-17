#!/usr/bin/env python3
"""Materialize one governed adaptive config from the controller baseline and L2 patch."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any


DECISION_BEGIN = "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->"
DECISION_END = "<!-- EVO_SCIENTIFIC_DECISION_END -->"


def resolve_inside(workspace: Path, raw: str, label: str) -> Path:
    path = (workspace / raw).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the workspace") from exc
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def decision_patch(workspace: Path) -> tuple[str, str | None, Any]:
    content = (workspace / "plan.md").read_text(encoding="utf-8")
    start = content.find(DECISION_BEGIN)
    stop = content.find(DECISION_END, start + len(DECISION_BEGIN))
    if start < 0 or stop < 0:
        raise ValueError("plan.md lacks a complete scientific decision block")
    decision = json.loads(content[start + len(DECISION_BEGIN) : stop].strip())
    strategy = decision.get("next_strategy")
    if not isinstance(strategy, dict):
        raise ValueError("scientific decision lacks next_strategy")
    action = strategy.get("action", "modify")
    if action == "continue":
        if strategy.get("config_field") not in {None, ""}:
            raise ValueError("continue action must not declare config_field")
        if strategy.get("config_patch") != {}:
            raise ValueError("continue action requires an empty config_patch")
        return action, None, None
    if action not in {"modify", "restart"}:
        raise ValueError("next_strategy.action must be 'continue', 'modify', or 'restart'")
    field = strategy.get("config_field")
    patch = strategy.get("config_patch")
    if action == "restart" and field in {None, ""} and patch == {}:
        return action, None, None
    if not isinstance(field, str) or not field:
        raise ValueError("next_strategy.config_field must be non-empty")
    if not isinstance(patch, dict) or list(patch) != [field]:
        raise ValueError("next_strategy.config_patch must contain exactly config_field")
    return action, field, patch[field]


def set_existing_leaf(config: dict[str, Any], field: str, value: Any) -> None:
    target: Any = config
    parts = field.split(".")
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            raise ValueError(f"adaptive patch field is missing: {field}")
        target = target[part]
    if not isinstance(target, dict) or parts[-1] not in target:
        raise ValueError(f"adaptive patch field is missing: {field}")
    target[parts[-1]] = value


def materialize(workspace: Path, round_number: int) -> tuple[Path, dict[str, Any]]:
    if round_number <= 1:
        raise ValueError("adaptive config materialization requires round > 1")
    state = load_json(workspace / ".hamilton_search_state.json", "search state")
    baseline_rel = state.get("next_round", {}).get("baseline_result_file")
    if not isinstance(baseline_rel, str) or not baseline_rel:
        raise ValueError("search state lacks next-round baseline")
    baseline_path = resolve_inside(workspace, baseline_rel, "baseline result")
    baseline = load_json(baseline_path, "baseline result")
    if baseline.get("status") != "completed":
        raise ValueError("baseline result is not completed")
    config = copy.deepcopy(baseline.get("config"))
    if not isinstance(config, dict):
        raise ValueError("baseline result lacks config")
    config.pop("_config_file", None)
    config.pop("_controller", None)

    action, field, value = decision_patch(workspace)
    bridge_policy_path = workspace / ".hamilton_bridge_policy.json"
    if action == "restart" and bridge_policy_path.is_file():
        bridge_policy = load_json(bridge_policy_path, "bridge policy")
        restart_rounds = bridge_policy.get("restart_rounds")
        if not isinstance(restart_rounds, list) or round_number not in restart_rounds:
            raise ValueError(
                f"restart is not authorized for bridge-pilot round {round_number}"
            )
    if field is not None:
        set_existing_leaf(config, field, value)

    seed_plan = load_json(workspace / ".hamilton_seed_plan.json", "seed plan")
    seeds = seed_plan.get("round_seeds")
    if not isinstance(seeds, list) or round_number > len(seeds):
        raise ValueError(f"seed plan lacks round {round_number}")
    session = config.get("search_session")
    warm_start = isinstance(session, dict) and session.get("mode") == "warm_start"
    if not warm_start:
        config["search"]["random_state"] = seeds[round_number - 1]
    else:
        session["round"] = round_number
        session["final_round"] = round_number == len(seeds)
        session["round_action"] = action
        if action == "restart" and field is not None:
            session["compatible_change_fields"] = [field]

    prior_id = str(baseline.get("experiment_id") or config.get("experiment_id") or "")
    if re.search(r"__round\d+$", prior_id):
        experiment_id = re.sub(r"__round\d+$", f"__round{round_number}", prior_id)
    else:
        experiment_id = f"{prior_id or 'governed_hamilton'}__round{round_number}"
    config["experiment_id"] = experiment_id
    run_directory = (
        config["output"]["run_directory"]
        if warm_start
        else f"history/round{round_number}/results/result-pysr"
    )
    config["output"] = {
        "result_file": f"history/round{round_number}/results/result.json",
        "run_directory": run_directory,
    }

    output = workspace / "history" / f"round{round_number}" / "experiment.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return output, {
        "status": "materialized",
        "round": round_number,
        "baseline_result_file": baseline_rel,
        "action": action,
        "config_field": field,
        "config_value": value,
        "assigned_seed": config["search"]["random_state"],
        "config_file": output.relative_to(workspace).as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, required=True)
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    try:
        _, summary = materialize(workspace, args.round)
    except Exception as exc:
        summary = {
            "status": "failed",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
