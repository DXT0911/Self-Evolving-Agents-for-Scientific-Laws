#!/usr/bin/env python3
"""Materialize the authorized public-U248 three-arm bundle without running it."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "launch_bundle"
DATA = ROOT / "playground/hamilton/workspace/input/U248_train.csv"
RUNNER = ROOT / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py"
SEEDS = [2101, 2102, 2103]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def copy_public_data(workspace: Path) -> None:
    destination = workspace / "input/data.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA, destination)
    if sha256(destination) != sha256(DATA):
        raise RuntimeError("materialized public data hash mismatch")


def long_horizon() -> dict[str, Any]:
    return {
        "enabled": True,
        "position_column": "x",
        "velocity_column": "v",
        "duration": 60.0,
        "points": 3000,
        "steady_state_fraction": 0.4,
        "min_steady_cycles": 3.0,
        "state_limit": 1_000_000.0,
        "rtol": 1e-8,
        "atol": 1e-10,
        "large_initial_scale": 2.0,
        "stationary_amplitude_fraction": 0.001,
        "zero_initial_policy": "report_only",
        "amplitude_relative_tolerance": 0.20,
        "frequency_relative_tolerance": 0.10,
        "stationarity_relative_tolerance": 0.15,
        "attractor_relative_tolerance": 0.20,
    }


def runner_config(arm: str, max_evals: int, seed: int, result_file: str) -> dict[str, Any]:
    dynamics = arm == "dynamics_aware_hamilton" or arm == "direct_pysr"
    return {
        "schema_version": 1,
        "experiment_id": f"viv_dynamics_feedback__{arm}",
        "data": {
            "train_file": "input/data.csv",
            "allowed_files": ["input/data.csv"],
            "time_column": "t",
            "feature_columns": ["x", "v"],
            "target_column": "a",
            "max_rows": None,
            "search_stride": 5,
            "standardize_search": False,
            "validation_fraction": 0.2,
        },
        "search": {
            "engine": "pysr",
            "binary_operators": ["+", "-", "*", "/"],
            "unary_operators": ["sin", "cos", "exp"],
            "niterations": 1000,
            "populations": 8,
            "population_size": 32,
            "tournament_selection_n": 12,
            "maxsize": 31,
            "parsimony": 0.001,
            "top_k": 10,
            "max_evals": max_evals,
            "random_state": seed,
        },
        "verification": {
            "short_ode": {
                "enabled": dynamics,
                "position_column": "x",
                "velocity_column": "v",
                "duration": 10.0,
                "points": 1000,
                "state_limit": 1_000_000.0,
            },
            "long_horizon_dynamics": long_horizon() if dynamics else {"enabled": False},
            "residual_diagnostics": {
                "enabled": True,
                "max_lag": 50,
                "feature_bins": 4,
                "phase_bins": 8,
                "high_frequency_fraction": 0.25,
            },
            "candidate_ranking": {
                "enabled": True,
                "max_candidates": 10,
                "failure_penalty": 100.0,
                "weights": {
                    "validation_nrmse": 1.0,
                    "trajectory_nrmse": 1.0 if dynamics else 0.0,
                    "complexity": 0.05,
                    "long_horizon_penalty": 1.0 if dynamics else 0.0,
                },
            },
        },
        "output": {
            "result_file": result_file,
            "run_directory": result_file.replace(".json", "-pysr"),
        },
    }


def hamilton_config() -> dict[str, Any]:
    return {
        "llm": {
            "openai": {
                "provider": "openai",
                "model": "deepseek-v4-pro",
                "api_key": "${HAMILTON_API_KEY}",
                "base_url": "https://api.deepseek.com",
                "temperature": 0.7,
                "max_tokens": 30000,
                "timeout": 120,
                "max_retries": 3,
                "retry_delay": 1.0,
            },
            "default": "openai",
        },
        "agents": {
            "hamilton": {
                "llm": "openai",
                "max_turns": 20,
                "enable_tools": True,
                "context": {
                    "max_tokens": 120000,
                    "truncation_strategy": "latest_half",
                    "preserve_system_messages": True,
                    "preserve_recent_turns": 10,
                },
                "system_prompt_file": str(ROOT / "playground/hamilton/prompts/hamilton_adaptive_system.txt"),
                "user_prompt_file": str(ROOT / "playground/hamilton/prompts/hamilton_adaptive_user.txt"),
                "skills": ["pysr", "run-sr-experiment", "evo-protocol"],
                "tools": {"builtin": ["str_replace_editor", "think", "finish"]},
            }
        },
        "session": {"type": "local", "local": {
            "working_dir": "./playground/hamilton/workspace",
            "timeout": 21600,
            "blocked_read_extensions": [".csv", ".tsv", ".parquet", ".feather"],
            "gpu_devices": None, "cpu_devices": None, "symlinks": {},
        }},
        "experiment": {
            "max_rounds": 3,
            "max_total_tokens": 600000,
            "max_tokens_per_round": 160000,
            "scientific_governance": True,
            "require_literature_grounding": False,
            "max_total_evals": 12000,
            "search_control": {
                "search_advancement": {"min_score_improvement": 0.0},
                "trust_region": {"enabled": True, "max_anchor_distance": 2,
                    "max_step_changes": 1, "rollback_after_stale_rounds": 2},
                "dynamic_budget": {"enabled": True, "base_evals": 4000,
                    "min_evals": 2000, "max_evals": 6000, "rounding_quantum": 500},
            },
            "pysr_preflight": {"enabled": True, "timeout_seconds": 180},
            "promotion": {"max_tokens": 160000, "max_attempts": 3},
        },
        "llm_output": {"show_in_console": True, "log_to_file": True},
        "logging": {"level": "INFO", "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s", "console": True},
        "project_root": ".",
        "debug": False,
    }


def task_text(arm: str, baseline: dict[str, Any]) -> str:
    treatment = (
        "Do not enable, inspect, infer, or cite short-ODE or long-horizon dynamics during search. "
        "They are withheld until the endpoint is frozen."
        if arm == "fit_only_hamilton"
        else "Use the controller-produced short-ODE and long-horizon summaries as search evidence."
    )
    return f"""# Authorized public U248 Hamilton arm: {arm}

Use only `input/data.csv` through the standard runner. Discover `a=f(x,v)`.
Private/OOD data, literature lookup, and cross-arm memory are forbidden.
{treatment}

Run exactly three governed rounds under the controller-owned cumulative ceiling of 12,000
requested evaluations and round seeds {SEEDS}. Round 1 must use `round1_baseline.json`.
Complete Promotion and closure after every round; do not stop on solver completion alone.

```json
{json.dumps(baseline, indent=2, sort_keys=True)}
```
"""


def build(output: Path = OUTPUT) -> dict[str, Any]:
    if sha256(DATA) != "c6d99ed7ee5d7f177195767f232990968c3b9a64e0fbd902fd0dc59feeb52635":
        raise RuntimeError("public U248 input changed")
    output.mkdir(parents=True, exist_ok=True)
    config_path = output / "configs/hamilton.yaml"
    write_text(config_path, yaml.safe_dump(hamilton_config(), sort_keys=False))
    jobs = []
    for arm in ("fit_only_hamilton", "dynamics_aware_hamilton"):
        run_dir = output / "runs" / arm
        workspace = run_dir / "workspaces/task_0"
        copy_public_data(workspace)
        baseline = runner_config(arm, 4000, SEEDS[0], "history/round1/results/result.json")
        write_json(workspace / "round1_baseline.json", baseline)
        write_json(workspace / ".hamilton_seed_plan.json", {
            "schema_version": 1, "arm_id": arm, "round_seeds": SEEDS, "controller_owned": True,
        })
        write_text(workspace / "task.md", task_text(arm, baseline))
        jobs.append({
            "arm": arm, "cwd": rel(ROOT), "run_dir": rel(run_dir),
            "command": ["python", "run.py", "--agent", "hamilton", "--config", rel(config_path),
                        "--task", rel(workspace / "task.md"), "--run-dir", rel(run_dir)],
            "llm_token_ceiling": 600000, "requested_evaluation_ceiling": 12000,
        })
    direct = output / "runs/direct_pysr/workspace"
    copy_public_data(direct)
    write_json(direct / "config.json", runner_config("direct_pysr", 12000, SEEDS[0], "results/result.json"))
    write_json(direct / ".hamilton_budget.json", {"max_total_evals": 12000})
    jobs.append({
        "arm": "direct_pysr", "cwd": rel(direct),
        "command": ["python", rel(RUNNER), "--config", "config.json"],
        "llm_token_ceiling": 0, "requested_evaluation_ceiling": 12000,
    })
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    matrix = {
        "schema_version": 1, "status": "frozen_authorized", "execution_permitted": True,
        "private_ood_permitted": False, "git_commit": head,
        "execution_order": [job["arm"] for job in jobs], "jobs": jobs,
        "resource_ceilings": {"requested_evaluations_all_arms": 36000,
                              "deepseek_tokens_all_hamilton_arms": 1200000},
    }
    matrix_path = output / "run_matrix.json"
    write_json(matrix_path, matrix)
    script = r'''$ErrorActionPreference = "Continue"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$LogRoot = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$env:PYTHONUTF8 = "1"
function Run-Step([string]$Name, [string]$WorkingDirectory, [string[]]$Arguments) {
  $Log = Join-Path $LogRoot ($Name + ".log")
  Push-Location $WorkingDirectory
  try {
    & python @Arguments 2>&1 | Tee-Object -FilePath $Log | ForEach-Object { Write-Host $_ }
    $Code = $LASTEXITCODE
    return [int]$Code
  }
  finally { Pop-Location }
}
$Preflight = Run-Step "00_preflight" $Repo @("-m", "playground.hamilton.core.pysr_preflight", "--timeout", "180")
if ($Preflight -ne 0) { exit $Preflight }
$FitRun = Join-Path $PSScriptRoot "runs\fit_only_hamilton"
$DynRun = Join-Path $PSScriptRoot "runs\dynamics_aware_hamilton"
$Direct = Join-Path $PSScriptRoot "runs\direct_pysr\workspace"
$Code = Run-Step "01_fit_only_hamilton" $Repo @("run.py", "--agent", "hamilton", "--config", (Join-Path $PSScriptRoot "configs\hamilton.yaml"), "--task", (Join-Path $FitRun "workspaces\task_0\task.md"), "--run-dir", $FitRun)
if ($Code -ne 0) { exit $Code }
$Code = Run-Step "02_fit_only_endpoint" $Repo @("-m", "experiments.viv_dynamics_feedback_gate.evaluate_endpoint", "--workspace", (Join-Path $FitRun "workspaces\task_0"), "--output", (Join-Path $FitRun "endpoint.json"))
if ($Code -ne 0) { exit $Code }
$Code = Run-Step "03_dynamics_aware_hamilton" $Repo @("run.py", "--agent", "hamilton", "--config", (Join-Path $PSScriptRoot "configs\hamilton.yaml"), "--task", (Join-Path $DynRun "workspaces\task_0\task.md"), "--run-dir", $DynRun)
if ($Code -ne 0) { exit $Code }
$Code = Run-Step "04_dynamics_aware_endpoint" $Repo @("-m", "experiments.viv_dynamics_feedback_gate.evaluate_endpoint", "--workspace", (Join-Path $DynRun "workspaces\task_0"), "--output", (Join-Path $DynRun "endpoint.json"))
if ($Code -ne 0) { exit $Code }
$Code = Run-Step "05_direct_pysr" $Direct @((Join-Path $Repo "evomaster\skills\run-sr-experiment\scripts\run_experiment.py"), "--config", "config.json")
if ($Code -ne 0) { exit $Code }
$Code = Run-Step "06_direct_endpoint" $Repo @("-m", "experiments.viv_dynamics_feedback_gate.evaluate_endpoint", "--source-result", (Join-Path $Direct "results\result.json"), "--output", (Join-Path $PSScriptRoot "runs\direct_pysr\endpoint.json"))
exit $Code
'''
    script_path = output / "run_authorized.ps1"
    write_text(script_path, script)
    sources = [HERE / "PROTOCOL.md", HERE / "arm_specs.yaml", HERE / "preparation_manifest.yaml",
               HERE / "build_launch_bundle.py", HERE / "validate_launch_bundle.py",
               HERE / "evaluate_endpoint.py", DATA, RUNNER, config_path, matrix_path, script_path]
    lock = {
        "schema_version": 1, "status": "frozen_authorized", "git_commit": head,
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "pysr": "1.5.9", "julia": "1.11.9"},
        "hashes": {rel(path): sha256(path) for path in sources},
    }
    write_json(output / "freeze_lock.json", lock)
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
