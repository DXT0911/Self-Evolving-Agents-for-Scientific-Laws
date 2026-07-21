"""Controller-side Julia/PySR readiness check for Hamilton.

This runs before the research agent receives a turn. It does not read data,
call an LLM, fit a model, or consume PySR evaluations.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class PySRPreflightError(RuntimeError):
    """Julia/PySR is not ready for a scientific run."""


def default_juliapkg_project() -> Path:
    override = os.environ.get("PYTHON_JULIAPKG_PROJECT")
    if override:
        path = Path(override)
        if not path.is_absolute():
            raise PySRPreflightError(
                "PYTHON_JULIAPKG_PROJECT must be an absolute path"
            )
        return path
    depot = os.environ.get("JULIA_DEPOT_PATH", "").split(os.pathsep)[0]
    depot_path = Path(depot) if depot else Path.home() / ".julia"
    return depot_path / "environments" / "pyjuliapkg"


def probe_juliapkg_lock(project: Path) -> dict[str, Any]:
    """Distinguish an active lock from an unheld leftover lock file."""
    lock_path = project / "lock.pid"
    if not lock_path.exists():
        return {"status": "clear", "path": str(lock_path), "existed": False}

    try:
        from filelock import FileLock, Timeout
    except ImportError as exc:
        raise PySRPreflightError(
            "filelock is unavailable; cannot safely inspect the JuliaPkg lock"
        ) from exc

    lock = FileLock(str(lock_path))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise PySRPreflightError(
            "JuliaPkg is actively locked at "
            f"{lock_path}. Another Python/Julia process is resolving packages. "
            "Wait for it to finish or terminate only a verified orphan process."
        ) from exc
    else:
        lock.release()
        return {
            "status": "clear",
            "path": str(lock_path),
            "existed": True,
            "leftover_lock_released": True,
        }


def warm_pysr(timeout_seconds: int = 180) -> dict[str, Any]:
    """Import PySR, start Julia, and load SymbolicRegression without fitting."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    code = (
        "import json, time\n"
        "started = time.perf_counter()\n"
        "import pysr\n"
        "from juliacall import Main as jl\n"
        "julia_version = str(jl.seval('VERSION'))\n"
        "jl.seval('using SymbolicRegression')\n"
        "print(json.dumps({"
        "'status':'ready',"
        "'pysr_version':pysr.__version__,"
        "'julia_version':julia_version,"
        "'elapsed_seconds':round(time.perf_counter()-started, 3)"
        "}), flush=True)\n"
    )
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PySRPreflightError(
            f"PySR warm-up exceeded {timeout_seconds}s. Check the JuliaPkg lock "
            "or instantiate/precompile Julia packages outside the research loop."
        ) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        if len(detail) > 2000:
            detail = detail[-2000:]
        raise PySRPreflightError(
            f"PySR warm-up failed with exit code {completed.returncode}: {detail}"
        )

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise PySRPreflightError("PySR warm-up returned no readiness record")
    try:
        record = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise PySRPreflightError(
            f"PySR warm-up returned an invalid readiness record: {lines[-1]}"
        ) from exc
    record["controller_elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return record


def run_preflight(timeout_seconds: int = 180) -> dict[str, Any]:
    project = default_juliapkg_project()
    return {
        "status": "ready",
        "juliapkg_project": str(project),
        "lock": probe_juliapkg_lock(project),
        "warmup": warm_pysr(timeout_seconds=timeout_seconds),
        "consumes_llm_tokens": False,
        "consumes_pysr_evaluations": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        result = run_preflight(timeout_seconds=args.timeout)
    except (PySRPreflightError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
