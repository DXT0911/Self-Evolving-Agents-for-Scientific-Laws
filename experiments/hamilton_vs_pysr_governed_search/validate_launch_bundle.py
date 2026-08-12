#!/usr/bin/env python3
"""Static launch-bundle audit; never imports or invokes PySR, Julia, or an LLM."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

try:
    from .build_launch_bundle import DEFAULT_OUTPUT, REPO, sha256
except ImportError:
    from build_launch_bundle import DEFAULT_OUTPUT, REPO, sha256


RUNNER_PATH = (
    REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"
)


def load_runner():
    spec = importlib.util.spec_from_file_location("public_pilot_runner_audit", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner: {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_bundle(bundle: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    matrix_path = bundle / "run_matrix.json"
    lock_path = bundle / "freeze_lock.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if matrix.get("execution_permitted") is not False:
        errors.append("run matrix must keep execution_permitted=false")
    if matrix.get("private_ood_permitted") is not False:
        errors.append("run matrix must keep private_ood_permitted=false")
    if matrix.get("job_count") != 99 or len(matrix.get("jobs", [])) != 99:
        errors.append("run matrix must contain exactly 99 arm jobs")
    matrix_key = (
        "experiments/hamilton_vs_pysr_governed_search/"
        "launch_bundle/run_matrix.json"
    )
    if lock.get("hashes", {}).get(matrix_key) != sha256(matrix_path):
        errors.append("run matrix hash does not match freeze lock")

    runner = load_runner()
    config_count = 0
    loaded_tasks: set[str] = set()
    realized_baseline_budgets: dict[tuple[str, str], dict[str, int]] = {}
    expected_config_count = 33
    for job in matrix.get("jobs", []):
        workspace = REPO / job["workspace"]
        arm = job["arm"]
        if arm == "ordinary_pysr":
            if job["state"] == "waiting_for_paired_hamilton_budget_trace":
                config_paths = []
                if (workspace / "experiment.json").exists():
                    errors.append(f"pending ordinary job already has a config: {workspace}")
            else:
                config_paths = [workspace / "experiment.json"]
                expected_config_count += 1
        elif arm == "fixed_schedule_pysr":
            config_paths = sorted((workspace / "episodes").glob("episode_*.json"))
            if job["state"] == "waiting_for_paired_hamilton_budget_trace":
                if config_paths:
                    errors.append(f"pending fixed job already has configs: {workspace}")
                config_paths = []
            else:
                expected_config_count += len(config_paths)
        elif arm == "governed_hamilton":
            config_paths = [workspace / "round1_baseline.json"]
            seed_plan_path = workspace / ".hamilton_seed_plan.json"
            if (
                not seed_plan_path.is_file()
                or sha256(seed_plan_path) != job.get("seed_plan_sha256")
            ):
                errors.append(f"Hamilton seed plan is missing or changed: {workspace}")
        else:
            errors.append(f"unknown arm: {arm}")
            continue

        job_budget = 0
        for config_path in config_paths:
            try:
                ledger_path = workspace / ".hamilton_evaluation_ledger.json"
                completed_baseline = None
                if arm == "governed_hamilton" and ledger_path.is_file():
                    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                    authored = json.loads(config_path.read_text(encoding="utf-8"))
                    completed_baseline = next(
                        (
                            attempt
                            for attempt in ledger.get("attempts", [])
                            if attempt.get("experiment_id") == authored.get("experiment_id")
                            and attempt.get("status") == "completed"
                        ),
                        None,
                    )
                if completed_baseline is not None:
                    result_path = workspace / completed_baseline["result_file"]
                    if (
                        not result_path.is_file()
                        or sha256(result_path)
                        != completed_baseline.get("result_sha256")
                    ):
                        raise ValueError("completed Hamilton baseline result changed")
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    config = result["config"]
                    paths = {
                        "train": workspace / config["data"]["train_file"],
                    }
                else:
                    config, paths = runner.load_and_validate(config_path, workspace)
                config_count += 1
                job_budget += int(config["search"]["max_evals"])
                task_id = job["task_id"]
                if task_id not in loaded_tasks:
                    runner.load_data(config, paths["train"])
                    loaded_tasks.add(task_id)
            except Exception as exc:
                errors.append(f"{config_path}: {type(exc).__name__}: {exc}")
        if arm in {"ordinary_pysr", "fixed_schedule_pysr"} and config_paths:
            declared = int(job["evaluation_budget"])
            if job_budget != declared:
                errors.append(
                    f"{arm}/{job['task_id']}/{job['repeat_id']} budget mismatch: "
                    f"{job_budget} != {declared}"
                )
            realized_baseline_budgets.setdefault(
                (job["task_id"], job["repeat_id"]), {}
            )[arm] = declared

    if config_count != expected_config_count:
        errors.append(
            f"expected {expected_config_count} materialized runner configs, "
            f"found {config_count}"
        )
    if loaded_tasks != {
        "static_s01", "static_s02", "static_s03", "static_s04", "static_s05",
        "static_s06", "dynamic_d01", "dynamic_d02", "dynamic_d03", "dynamic_d04",
        "viv_u248",
    }:
        errors.append("not every frozen task passed a data load")
    for pair, arm_budgets in realized_baseline_budgets.items():
        if (
            set(arm_budgets) != {"ordinary_pysr", "fixed_schedule_pysr"}
            or len(set(arm_budgets.values())) != 1
        ):
            errors.append(f"paired replay budgets do not match for {pair}: {arm_budgets}")

    result = {
        "valid": not errors,
        "errors": errors,
        "job_count": len(matrix.get("jobs", [])),
        "runner_config_count": config_count,
        "data_task_count": len(loaded_tasks),
        "paired_replay_count": len(realized_baseline_budgets),
        "hamilton_evaluation_ceiling_per_arm": 396000,
        "execution_permitted": False,
        "private_ood_permitted": False,
    }
    if errors:
        raise ValueError(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(audit_bundle(args.bundle.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
