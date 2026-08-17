#!/usr/bin/env python3
"""Run the frozen HCC hybrid pilot matrix (2 tasks x 3 seeds x 2 arms = 12 runs).

Invocation:
  python run_matrix.py --arm bare_pysr --workers 3   # 6 fast no-LLM cells
  python run_matrix.py --arm hcc_llm   --workers 1   # 6 LLM-loop cells (sequential)
  python run_matrix.py --collect                      # paired sign test over results

Each H-arm cell is reset to its frozen inputs before running; each B-arm cell resets
its own per-run state inside execute_baseline.py. Per-cell stdout is captured to
<root>/run.log and a JSON summary is written to run_matrix_results.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUN_BUNDLE = HERE / "run_bundle"
HCC_CONFIG = REPO / "configs" / "hamilton" / "config_hcc_hybrid_pilot.yaml"
BASELINE_EXEC = HERE / "execute_baseline.py"
COLLECT_EXEC = HERE / "collect_pilot.py"

TASKS = ["static_s02", "dynamic_d01"]
REPEATS = ["repeat_1", "repeat_2", "repeat_3"]

# Frozen H-arm workspace inputs (everything else in the workspace is generated and
# reset before each run).
H_GENERATED = (
    ".hamilton_budget.json",
    ".hamilton_search_control.json",
    ".hamilton_search_state.json",
    ".hamilton_evaluation_ledger.json",
    ".hamilton_evaluation_ledger.lock",
    "findings.md",
    "plan.md",
)


def reset_h_cell(h_root: Path) -> None:
    ws = h_root / "workspaces" / "task_0"
    for name in H_GENERATED:
        (ws / name).unlink(missing_ok=True)
    for sub in ("history", "lib"):
        shutil.rmtree(ws / sub, ignore_errors=True)
    for sub in ("records", "trajectories", "logs"):
        shutil.rmtree(h_root / sub, ignore_errors=True)


def run_subprocess(cmd: list[str], log_path: Path, cwd: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(cmd)}\n\n")
        fh.flush()
        proc = subprocess.run(
            cmd, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    return proc.returncode


def run_h_cell(task_id: str, repeat: str) -> dict[str, Any]:
    h_root = RUN_BUNDLE / "hcc_llm" / task_id / repeat
    reset_h_cell(h_root)
    cmd = [
        sys.executable, str(REPO / "run.py"), "--agent", "hamilton",
        "--config", str(HCC_CONFIG),
        "--task", f"Execute frozen HCC hybrid task {task_id}, {repeat}.",
        "--run-dir", str(h_root),
    ]
    rc = run_subprocess(cmd, h_root / "run.log", REPO)
    return {
        "arm": "hcc_llm", "task_id": task_id, "repeat": repeat,
        "returncode": rc, "log": str((h_root / "run.log").relative_to(REPO)),
    }


def run_b_cell(task_id: str, repeat: str) -> dict[str, Any]:
    b_ws = RUN_BUNDLE / "bare_pysr" / task_id / repeat / "workspace"
    cmd = [sys.executable, str(BASELINE_EXEC), "--workspace", str(b_ws)]
    log_path = RUN_BUNDLE / "bare_pysr" / task_id / repeat / "run.log"
    rc = run_subprocess(cmd, log_path, REPO)
    return {
        "arm": "bare_pysr", "task_id": task_id, "repeat": repeat,
        "returncode": rc, "log": str(log_path.relative_to(REPO)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["hcc_llm", "bare_pysr"], default=None)
    parser.add_argument("--task", choices=TASKS, default=None)
    parser.add_argument("--repeat", choices=REPEATS, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--collect", action="store_true")
    args = parser.parse_args()

    cells: list[tuple[str, str, str]] = []
    for arm in (["hcc_llm", "bare_pysr"] if args.arm is None else [args.arm]):
        for task_id in TASKS:
            for repeat in REPEATS:
                if args.task and args.task != task_id:
                    continue
                if args.repeat and args.repeat != repeat:
                    continue
                cells.append((arm, task_id, repeat))

    runner = {"hcc_llm": run_h_cell, "bare_pysr": run_b_cell}
    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(runner[arm], task_id, repeat): (arm, task_id, repeat)
                   for arm, task_id, repeat in cells}
        for fut in as_completed(futures):
            arm, task_id, repeat = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                result = {"arm": arm, "task_id": task_id, "repeat": repeat,
                          "returncode": None, "error": repr(exc)}
            results.append(result)
            print(f"[{arm}/{task_id}/{repeat}] rc={result.get('returncode')}", flush=True)

    results.sort(key=lambda r: (r["arm"], r["task_id"], r["repeat"]))
    summary = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "cells": results,
        "returncode_zero": sum(1 for r in results if r.get("returncode") == 0),
        "total": len(results),
    }
    (HERE / "run_matrix_results.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.collect:
        collect_cmd = [sys.executable, str(COLLECT_EXEC)]
        rc = run_subprocess(collect_cmd, HERE / "collect.log", REPO)
        print(f"[collect_pilot] rc={rc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
