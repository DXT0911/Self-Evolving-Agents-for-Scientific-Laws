#!/usr/bin/env python3
"""Finalize pilot ledger reservations whose runner processes were externally terminated."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUNDLE = HERE / "pilot_bundle"
TASK = "static_s01"
REPEAT = "repeat_1"


def load_runner():
    path = REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"
    spec = importlib.util.spec_from_file_location("pilot_ledger_runner", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workspaces() -> list[Path]:
    return [
        BUNDLE / arm / TASK / REPEAT /
        ("workspaces/task_0" if arm == "governed_hamilton" else "workspace")
        for arm in (
            "ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr",
            "governed_hamilton",
        )
    ]


def finalize() -> dict[str, object]:
    runner = load_runner()
    finalized = []
    for workspace in workspaces():
        ledger_path = workspace / ".hamilton_evaluation_ledger.json"
        if not ledger_path.is_file():
            continue
        with runner.evaluation_ledger_lock(workspace):
            ledger = runner.read_evaluation_ledger(workspace)
            changed = False
            for attempt in ledger.get("attempts", []):
                if attempt.get("status") != "reserved":
                    continue
                attempt["status"] = "failed"
                attempt["finished_at"] = runner.utc_now()
                attempt["failure_class"] = "external_runner_process_termination"
                attempt["scientific_evidence"] = False
                attempt["engine_evaluations"] = None
                finalized.append({
                    "workspace": workspace.relative_to(REPO).as_posix(),
                    "attempt_id": attempt.get("attempt_id"),
                    "experiment_id": attempt.get("experiment_id"),
                    "requested_evals": attempt.get("requested_evals"),
                })
                changed = True
            if changed:
                runner.write_evaluation_ledger(workspace, ledger)
    return {"schema_version": 1, "finalized_count": len(finalized), "attempts": finalized}


if __name__ == "__main__":
    print(json.dumps(finalize(), indent=2))
