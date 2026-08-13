#!/usr/bin/env python3
"""Validate the materialized VIV dynamics-feedback launch bundle without running it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build_launch_bundle import HERE, OUTPUT, ROOT, sha256


def validate(bundle: Path = OUTPUT) -> list[str]:
    errors: list[str] = []
    try:
        matrix = json.loads((bundle / "run_matrix.json").read_text(encoding="utf-8"))
        lock = json.loads((bundle / "freeze_lock.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"bundle metadata unreadable: {exc}"]
    if matrix.get("status") != "frozen_authorized" or matrix.get("execution_permitted") is not True:
        errors.append("bundle is not explicitly authorized")
    if matrix.get("private_ood_permitted") is not False:
        errors.append("private/OOD must remain forbidden")
    jobs = matrix.get("jobs", [])
    if [job.get("arm") for job in jobs] != ["fit_only_hamilton", "dynamics_aware_hamilton", "direct_pysr"]:
        errors.append("three-arm execution order mismatch")
    if sum(int(job.get("requested_evaluation_ceiling", 0)) for job in jobs) != 36000:
        errors.append("requested-evaluation ceiling mismatch")
    if sum(int(job.get("llm_token_ceiling", 0)) for job in jobs) != 1200000:
        errors.append("LLM token ceiling mismatch")
    ceilings = matrix.get("resource_ceilings", {})
    if ceilings.get("previous_interrupted_direct_pysr") != 12000:
        errors.append("previous interrupted reservation is not preserved")
    if ceilings.get("cumulative_requested_evaluations") != 48000:
        errors.append("cumulative requested-evaluation ceiling mismatch")
    for raw, expected in lock.get("hashes", {}).items():
        path = ROOT / raw
        if not path.is_file() or sha256(path) != expected:
            errors.append(f"hash mismatch: {raw}")
    fit = json.loads((bundle / "runs/fit_only_hamilton/workspaces/task_0/round1_baseline.json").read_text(encoding="utf-8"))
    dyn = json.loads((bundle / "runs/dynamics_aware_hamilton/workspaces/task_0/round1_baseline.json").read_text(encoding="utf-8"))
    if fit["verification"]["short_ode"]["enabled"] or fit["verification"]["long_horizon_dynamics"]["enabled"]:
        errors.append("fit-only search leaks dynamics evidence")
    if not dyn["verification"]["short_ode"]["enabled"] or not dyn["verification"]["long_horizon_dynamics"]["enabled"]:
        errors.append("dynamics-aware search lacks dynamics evidence")
    forbidden = ("/private/", "\\private\\", "_test.csv", "/ood/", "\\ood\\")
    serialized = json.dumps(matrix).lower()
    for marker in forbidden:
        if marker in serialized:
            errors.append(f"forbidden path marker: {marker}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=OUTPUT)
    args = parser.parse_args()
    problems = validate(args.bundle.resolve())
    if problems:
        print("launch bundle validation failed:\n" + "\n".join(f"- {item}" for item in problems))
        raise SystemExit(1)
    print("launch bundle validation passed")
