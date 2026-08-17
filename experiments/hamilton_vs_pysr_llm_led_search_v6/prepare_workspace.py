#!/usr/bin/env python3
"""Create a clean Hamilton v6 workspace from an existing prepared workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_CONFIG = REPO / "configs/hamilton/config_llm_led_pysr_v6.yaml"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def prepare(source: Path, output: Path, config_path: Path = DEFAULT_CONFIG) -> Path:
    source = source.resolve()
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output workspace must be empty: {output}")
    data_source = source / "input/data.csv"
    baseline_source = source / "round1_baseline.json"
    if not data_source.is_file() or not baseline_source.is_file():
        raise ValueError("source workspace requires input/data.csv and round1_baseline.json")

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    experiment = cfg["experiment"]
    baseline = read_object(baseline_source)
    output.mkdir(parents=True, exist_ok=True)
    (output / "input").mkdir()
    shutil.copy2(data_source, output / "input/data.csv")

    session_key = hashlib.sha256(str(output).encode("utf-8")).hexdigest()[:12]
    baseline["experiment_id"] = f"hamilton-v6-{session_key}__round1"
    baseline["search"]["max_evals"] = int(experiment["evals_per_round"])
    baseline["search_session"] = {
        "mode": "warm_start",
        "session_id": f"hamilton-v6-{session_key}",
        "round": 1,
        "final_round": int(experiment["max_rounds"]) == 1,
        "round_action": "initialize",
        "compatible_change_fields": ["search.parsimony"],
    }
    baseline["output"] = {
        "result_file": "history/round1/results/result.json",
        "run_directory": "session/pysr",
    }
    (output / "round1_baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source_task = source / "task.md"
    task_text = (
        source_task.read_text(encoding="utf-8")
        if source_task.is_file()
        else "# Hamilton v6 symbolic-regression task\n"
    )
    (output / "task.md").write_text(
        task_text.rstrip()
        + "\n\nThe LLM selects the binding next-round action inside a controller-validated envelope.\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-workspace", type=Path, required=True)
    parser.add_argument("--output-workspace", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(prepare(args.source_workspace, args.output_workspace, args.config))
