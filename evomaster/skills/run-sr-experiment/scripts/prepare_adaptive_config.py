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


def decision_patch(workspace: Path) -> tuple[str, Any]:
    content = (workspace / "plan.md").read_text(encoding="utf-8")
    start = content.find(DECISION_BEGIN)
    stop = content.find(DECISION_END, start + len(DECISION_BEGIN))
    if start < 0 or stop < 0:
        raise ValueError("plan.md lacks a complete scientific decision block")
    decision = json.loads(content[start + len(DECISION_BEGIN) : stop].strip())
    strategy = decision.get("next_strategy")
    if not isinstance(strategy, dict):
        raise ValueError("scientific decision lacks next_strategy")
    field = strategy.get("config_field")
    patch = strategy.get("config_patch")
    if not isinstance(field, str) or not field:
        raise ValueError("next_strategy.config_field must be non-empty")
    if not isinstance(patch, dict) or list(patch) != [field]:
        raise ValueError("next_strategy.config_patch must contain exactly config_field")
    return field, patch[field]


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

    field, value = decision_patch(workspace)
    set_existing_leaf(config, field, value)

    seed_plan = load_json(workspace / ".hamilton_seed_plan.json", "seed plan")
    seeds = seed_plan.get("round_seeds")
    if not isinstance(seeds, list) or round_number > len(seeds):
        raise ValueError(f"seed plan lacks round {round_number}")
    config["search"]["random_state"] = seeds[round_number - 1]

    prior_id = str(baseline.get("experiment_id") or config.get("experiment_id") or "")
    if re.search(r"__round\d+$", prior_id):
        experiment_id = re.sub(r"__round\d+$", f"__round{round_number}", prior_id)
    else:
        experiment_id = f"{prior_id or 'governed_hamilton'}__round{round_number}"
    config["experiment_id"] = experiment_id
    config["output"] = {
        "result_file": f"history/round{round_number}/results/result.json",
        "run_directory": f"history/round{round_number}/results/result-pysr",
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
        "config_field": field,
        "config_value": value,
        "assigned_seed": seeds[round_number - 1],
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
