#!/usr/bin/env python3
"""SRBENCH_ANCHOR_OPENEVOLVE_RUNNER

Prepare and optionally run OpenEvolve on one full SRBench problem pack.

This wrapper keeps Hamilton-visible train-only packs separate from the full pack
used for final comparison. It also normalizes the expected OpenEvolve working
layout and the location of the evolved best program.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


DEFAULT_WORKDIR_ROOT = Path("playground/hamilton_srbench/openevolve_runs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare or run OpenEvolve on one SRBench problem pack.")
    parser.add_argument("--problem-dir", required=True, help="Full problem pack directory with train/test/OOD arrays")
    parser.add_argument(
        "--workdir-root",
        default=str(DEFAULT_WORKDIR_ROOT),
        help="Root directory for OpenEvolve working copies",
    )
    parser.add_argument(
        "--openevolve-root",
        default=None,
        help="Optional local OpenEvolve repo root containing openevolve-run.py",
    )
    parser.add_argument("--iterations", type=int, default=50, help="Number of OpenEvolve iterations")
    parser.add_argument("--primary-model", default=None, help="Override llm.primary_model in config")
    parser.add_argument("--secondary-model", default=None, help="Override llm.secondary_model in config")
    parser.add_argument("--api-base", default=None, help="Override llm.api_base in config")
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable name that holds the OpenAI-compatible API key",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Only prepare the OpenEvolve workdir and resolved config, do not execute the run",
    )
    parser.add_argument("--json-out", default=None, help="Optional JSON manifest output path")
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def infer_problem_key(problem_dir: Path) -> tuple[str, str]:
    return problem_dir.parent.name, problem_dir.name


def resolve_launcher(openevolve_root: str | None) -> list[str]:
    if openevolve_root:
        root = Path(openevolve_root).resolve()
        launcher_py = root / "openevolve-run.py"
        if launcher_py.is_file():
            return [sys.executable, str(launcher_py)]
        launcher_bin = root / "openevolve-run"
        if launcher_bin.is_file():
            return [str(launcher_bin)]
        raise SystemExit(f"OpenEvolve launcher not found under: {root}")

    repo_launcher = repo_root() / ".venv" / "bin" / "openevolve-run"
    if repo_launcher.is_file():
        return [str(repo_launcher)]

    for launcher_name in ("openevolve-run.py", "openevolve-run"):
        installed_launcher = shutil.which(launcher_name)
        if installed_launcher:
            return [installed_launcher]

    raise SystemExit(
        "OpenEvolve launcher not found. Install `openevolve` or pass --openevolve-root pointing to a repo with openevolve-run.py."
    )


def copy_problem_pack(problem_dir: Path, workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    for source in problem_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, workdir / source.name)


def mirror_problem_subtree(problem_dir: Path, workdir: Path) -> Path:
    split_name, problem_name = infer_problem_key(problem_dir)
    nested_dir = workdir / "problems" / split_name / problem_name
    nested_dir.mkdir(parents=True, exist_ok=True)
    for source in problem_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, nested_dir / source.name)
    return nested_dir


def load_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def write_config(config: dict, config_path: Path) -> None:
    text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    config_path.write_text(text, encoding="utf-8")


def apply_overrides(config: dict, args: argparse.Namespace) -> dict:
    llm_cfg = config.setdefault("llm", {})
    if args.primary_model:
        llm_cfg["primary_model"] = args.primary_model
    if args.secondary_model:
        llm_cfg["secondary_model"] = args.secondary_model
    if args.api_base:
        llm_cfg["api_base"] = args.api_base
    return config


def build_manifest(problem_dir: Path, workdir: Path, config_path: Path, args: argparse.Namespace) -> dict:
    split_name, problem_name = infer_problem_key(problem_dir)
    return {
        "problem_dir": str(problem_dir.resolve()),
        "split": split_name,
        "problem": problem_name,
        "workdir": str(workdir.resolve()),
        "nested_problem_dir": str((workdir / "problems" / split_name / problem_name).resolve()),
        "config_path": str(config_path.resolve()),
        "iterations": args.iterations,
        "api_key_env": args.api_key_env,
        "best_program_path": str((workdir / "openevolve_output" / "best" / "best_program.py").resolve()),
        "checkpoint_dir": str((workdir / "openevolve_output" / "checkpoints").resolve()),
    }


def run_openevolve(launcher: list[str], workdir: Path, args: argparse.Namespace) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if not env.get(args.api_key_env):
        raise SystemExit(
            f"Missing API key environment variable `{args.api_key_env}`. Set it before running OpenEvolve."
        )

    command = launcher + [
        "initial_program.py",
        "evaluator.py",
        "--config",
        "config.yaml",
        "--iterations",
        str(args.iterations),
    ]
    return subprocess.run(command, cwd=workdir, env=env, check=False)


def main() -> None:
    args = parse_args()
    problem_dir = Path(args.problem_dir).resolve()
    if not problem_dir.is_dir():
        raise SystemExit(f"Problem directory not found: {problem_dir}")

    split_name, problem_name = infer_problem_key(problem_dir)
    workdir_root = Path(args.workdir_root)
    if not workdir_root.is_absolute():
        workdir_root = repo_root() / workdir_root
    workdir = (workdir_root / split_name / problem_name).resolve()

    copy_problem_pack(problem_dir, workdir)
    mirror_problem_subtree(problem_dir, workdir)
    config_path = workdir / "config.yaml"
    config = apply_overrides(load_config(config_path), args)
    write_config(config, config_path)

    manifest = build_manifest(problem_dir, workdir, config_path, args)
    manifest_path = workdir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    exit_code = None
    if not args.prepare_only:
        launcher = resolve_launcher(args.openevolve_root)
        result = run_openevolve(launcher, workdir, args)
        exit_code = result.returncode
        manifest["exit_code"] = exit_code
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if args.prepare_only:
        print("Prepared OpenEvolve workdir without execution.")
    elif exit_code == 0:
        print("OpenEvolve run completed successfully.")


if __name__ == "__main__":
    main()
