#!/usr/bin/env python3
"""Deterministic, configuration-driven symbolic-regression experiment runner."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import platform
import re
import socket
import struct
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

try:
    from .engine_telemetry import make_logger_spec, validation_curve
except ImportError:
    import importlib.util

    _telemetry_spec = importlib.util.spec_from_file_location(
        "hamilton_engine_telemetry", Path(__file__).with_name("engine_telemetry.py")
    )
    if _telemetry_spec is None or _telemetry_spec.loader is None:
        raise ImportError("could not load engine_telemetry.py")
    _telemetry_module = importlib.util.module_from_spec(_telemetry_spec)
    _telemetry_spec.loader.exec_module(_telemetry_module)
    make_logger_spec = _telemetry_module.make_logger_spec
    validation_curve = _telemetry_module.validation_curve


class ConfigError(ValueError):
    """Raised when an experiment configuration violates the runner contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON config relative to the workspace.")
    parser.add_argument("--validate-only", action="store_true", help="Validate without running PySR.")
    return parser.parse_args()


WARM_START_DIR = ".hamilton_warm_start"


def warm_start_session(config: dict[str, Any]) -> dict[str, Any] | None:
    value = config.get("search_session")
    if value is None:
        return None
    session = require_dict(value, "search_session")
    if session.get("mode") != "warm_start":
        raise ConfigError("search_session.mode must be 'warm_start'")
    session_id = session.get("session_id")
    if not isinstance(session_id, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", session_id) is None:
        raise ConfigError("search_session.session_id must be a safe non-empty identifier")
    round_number = positive_int(session.get("round"), "search_session.round")
    final_round = session.get("final_round", False)
    if not isinstance(final_round, bool):
        raise ConfigError("search_session.final_round must be boolean")
    round_action = session.get(
        "round_action", "initialize" if round_number == 1 else "modify"
    )
    if round_action not in {"initialize", "continue", "modify"}:
        raise ConfigError(
            "search_session.round_action must be initialize, continue, or modify"
        )
    allowed = session.get("compatible_change_fields", ["search.parsimony"])
    if not isinstance(allowed, list) or not all(
        field == "search.parsimony" for field in allowed
    ):
        raise ConfigError(
            "search_session.compatible_change_fields may contain only "
            "search.parsimony"
        )
    return {
        "mode": "warm_start",
        "session_id": session_id,
        "round": round_number,
        "final_round": final_round,
        "round_action": round_action,
        "compatible_change_fields": list(dict.fromkeys(allowed)),
    }


def _warm_message(connection: socket.socket, value: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    connection.sendall(struct.pack("!I", len(payload)) + payload)
    header = connection.recv(4)
    if len(header) != 4:
        raise RuntimeError("warm-start worker returned an incomplete header")
    size = struct.unpack("!I", header)[0]
    chunks = bytearray()
    while len(chunks) < size:
        block = connection.recv(size - len(chunks))
        if not block:
            raise RuntimeError("warm-start worker returned an incomplete response")
        chunks.extend(block)
    response = json.loads(chunks.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("warm-start worker response must be an object")
    return response


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _worker_alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and (
                exit_code.value == still_active
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _start_warm_worker(
    workspace: Path, session: dict[str, Any], metadata_path: Path
) -> dict[str, Any]:
    if session["round"] != 1:
        raise ConfigError(
            "warm-start worker state is unavailable after round 1; refusing a silent restart"
        )
    token = uuid.uuid4().hex
    worker = Path(__file__).with_name("warm_start_worker.py")
    command = [
        sys.executable,
        str(worker),
        "--workspace",
        str(workspace),
        "--port",
        "0",
        "--token",
        token,
        "--metadata",
        str(metadata_path),
    ]
    kwargs: dict[str, Any] = {
        "cwd": str(workspace),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + 180.0
    while time.monotonic() < deadline:
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = None
            if isinstance(metadata, dict) and metadata.get("status") == "ready":
                return metadata
        if process.poll() is not None:
            raise RuntimeError(
                f"warm-start worker exited during startup with code {process.returncode}"
            )
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError("warm-start worker did not become ready within 180 seconds")


def run_warm_start_round(
    config: dict[str, Any], workspace: Path
) -> dict[str, Any]:
    session = warm_start_session(config)
    if session is None:
        raise ConfigError("run_warm_start_round requires search_session")
    state_dir = workspace / WARM_START_DIR / session["session_id"]
    metadata_path = state_dir / "worker.json"
    metadata: dict[str, Any] | None = None
    if metadata_path.is_file():
        try:
            candidate = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            candidate = None
        if (
            isinstance(candidate, dict)
            and candidate.get("status") == "ready"
            and _worker_alive(candidate.get("pid"))
        ):
            metadata = candidate
        elif session["round"] > 1:
            raise ConfigError(
                "warm-start worker was lost after round 1; refusing a fresh PySR restart"
            )
    if metadata is None:
        metadata_path.unlink(missing_ok=True)
        metadata = _start_warm_worker(workspace, session, metadata_path)

    request_id = uuid.uuid4().hex
    request_path = state_dir / "requests" / f"{request_id}.json"
    response_path = state_dir / "responses" / f"{request_id}.json"
    request_relative = request_path.relative_to(workspace).as_posix()
    response_relative = response_path.relative_to(workspace).as_posix()
    _atomic_json(request_path, {
        "schema_version": 1,
        "config": config,
        "response_file": response_relative,
    })
    try:
        with socket.create_connection(
            ("127.0.0.1", int(metadata["port"])), timeout=21600
        ) as connection:
            response = _warm_message(connection, {
                "token": metadata["token"],
                "request_file": request_relative,
            })
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError(f"warm-start worker communication failed: {exc}") from exc
    if response.get("status") != "completed" or not response_path.is_file():
        detail = response.get("error", {})
        raise RuntimeError(
            f"warm-start worker failed: {detail.get('type')}: {detail.get('message')}"
        )
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("status") != "completed":
        raise RuntimeError("warm-start worker produced no completed result")
    return result


def require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be an object")
    return value


def require_list_of_strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise ConfigError(f"{name} must be a non-empty array of strings")
    return value


def positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{name} must be a positive finite number")
    return float(value)


def resolve_inside(workspace: Path, raw_path: str, name: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConfigError(f"{name} must be a non-empty path")
    candidate = (workspace / raw_path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise ConfigError(f"{name} must stay inside workspace: {raw_path}") from exc
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(workspace: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def consumed_search_evals(workspace: Path, exclude_result: Path | None = None) -> int:
    total = 0
    excluded = exclude_result.resolve() if exclude_result is not None else None
    for path in (workspace / "history").glob("round*/results/*.json"):
        if excluded is not None and path.resolve() == excluded:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") == "completed":
                total += int(payload["config"]["search"]["max_evals"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    return total


def evaluation_budget_limit(workspace: Path) -> int | None:
    budget_path = workspace / ".hamilton_budget.json"
    if not budget_path.is_file():
        return None
    try:
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        return positive_int(budget.get("max_total_evals"), "budget.max_total_evals")
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid .hamilton_budget.json: {exc}") from exc


@contextmanager
def evaluation_ledger_lock(workspace: Path) -> Iterator[None]:
    """Serialize ledger updates; OS locks are released even if the runner crashes."""
    lock_path = workspace / ".hamilton_evaluation_ledger.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def legacy_completed_attempts(workspace: Path) -> list[dict[str, Any]]:
    attempts = []
    for path in sorted((workspace / "history").glob("round*/results/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            requested = int(payload["config"]["search"]["max_evals"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        if payload.get("status") != "completed" or requested <= 0:
            continue
        relative = str(path.relative_to(workspace)).replace("\\", "/")
        attempts.append(
            {
                "attempt_id": f"legacy-{sha256_file(path)[:24]}",
                "experiment_id": payload.get("experiment_id"),
                "result_file": relative,
                "requested_evals": requested,
                "status": "legacy_completed",
                "reserved_at": payload.get("started_at"),
                "finished_at": payload.get("completed_at"),
                "result_sha256": sha256_file(path),
            }
        )
    return attempts


def read_evaluation_ledger(
    workspace: Path,
    *,
    initialize: bool = False,
) -> dict[str, Any]:
    path = workspace / ".hamilton_evaluation_ledger.json"
    limit = evaluation_budget_limit(workspace)
    if path.is_file():
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid .hamilton_evaluation_ledger.json: {exc}") from exc
        if ledger.get("schema_version") != 1 or not isinstance(ledger.get("attempts"), list):
            raise ConfigError("invalid Hamilton evaluation ledger schema")
        recorded_limit = ledger.get("max_total_evals")
        if recorded_limit != limit:
            if (
                isinstance(recorded_limit, int)
                and isinstance(limit, int)
                and limit > recorded_limit
            ):
                ledger.setdefault("budget_limit_history", []).append(
                    {
                        "previous_max_total_evals": recorded_limit,
                        "new_max_total_evals": limit,
                        "increased_at": utc_now(),
                    }
                )
                ledger["max_total_evals"] = limit
            else:
                raise ConfigError(
                    "evaluation budget limit cannot be removed or decreased after "
                    "ledger creation: "
                    f"recorded={recorded_limit}, configured={limit}"
                )
        return ledger
    return {
        "schema_version": 1,
        "max_total_evals": limit,
        "created_at": utc_now(),
        "attempts": legacy_completed_attempts(workspace) if initialize else [],
    }


def evaluation_ledger_total(ledger: dict[str, Any]) -> int:
    total = 0
    for attempt in ledger.get("attempts", []):
        try:
            requested = int(attempt["requested_evals"])
        except (KeyError, TypeError, ValueError):
            raise ConfigError("evaluation ledger contains an invalid requested_evals") from None
        if requested <= 0:
            raise ConfigError("evaluation ledger requested_evals must be positive")
        total += requested
    return total


def write_evaluation_ledger(workspace: Path, ledger: dict[str, Any]) -> None:
    path = workspace / ".hamilton_evaluation_ledger.json"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_search_control(workspace: Path) -> dict[str, Any] | None:
    path = workspace / ".hamilton_search_control.json"
    if not path.is_file():
        return None
    try:
        control = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid Hamilton search-control JSON: {exc}") from exc
    if control.get("schema_version") != 1:
        raise ConfigError("invalid Hamilton search-control schema")
    return control


def read_search_state(workspace: Path) -> dict[str, Any]:
    path = workspace / ".hamilton_search_state.json"
    if not path.is_file():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid Hamilton search-state JSON: {exc}") from exc
    if state.get("schema_version") != 1:
        raise ConfigError("invalid Hamilton search-state schema")
    return state


def controller_owns_budget(workspace: Path) -> bool:
    control = read_search_control(workspace)
    return bool(
        control
        and control.get("dynamic_budget", {}).get("enabled")
    )


def apply_controller_seed(
    workspace: Path,
    config: dict[str, Any],
    round_number: int | None,
) -> dict[str, Any] | None:
    """Override an adaptive round's authored seed from the frozen controller plan."""
    path = workspace / ".hamilton_seed_plan.json"
    if not path.is_file() or round_number is None:
        return None
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid .hamilton_seed_plan.json: {exc}") from exc
    seeds = plan.get("round_seeds")
    if (
        plan.get("schema_version") != 1
        or not isinstance(seeds, list)
        or not seeds
        or not all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds)
    ):
        raise ConfigError("invalid Hamilton seed-plan schema")
    if round_number > len(seeds):
        raise ConfigError(
            f"Hamilton seed plan has no seed for round {round_number}"
        )
    proposed = config["search"]["random_state"]
    assigned = int(seeds[round_number - 1])
    config["search"]["random_state"] = assigned
    assignment = {
        "mode": "controller_frozen_round_seed",
        "round": round_number,
        "proposed_seed_ignored": proposed,
        "assigned_seed": assigned,
    }
    config.setdefault("_controller", {})["seed_assignment"] = assignment
    return assignment


def search_space_weight(config: dict[str, Any]) -> float:
    search = config.get("search") or {}
    data = config.get("data") or {}
    operator_count = len(search.get("binary_operators") or []) + len(
        search.get("unary_operators") or []
    )
    feature_count = len(data.get("feature_columns") or [])
    maxsize = max(1, int(search.get("maxsize", 1) or 1))
    return float(max(1, operator_count) * max(1, feature_count) * maxsize)


def allocate_dynamic_evaluations(
    workspace: Path,
    config: dict[str, Any],
    round_number: int | None,
) -> dict[str, Any] | None:
    """Assign an effective per-round budget without exceeding the total ledger."""
    control = read_search_control(workspace)
    budget = (control or {}).get("dynamic_budget", {})
    if not budget.get("enabled"):
        return None
    if round_number is None:
        return None
    base_evals = positive_int(budget.get("base_evals"), "dynamic_budget.base_evals")
    min_evals = positive_int(budget.get("min_evals"), "dynamic_budget.min_evals")
    max_evals = positive_int(budget.get("max_evals"), "dynamic_budget.max_evals")
    quantum = positive_int(
        budget.get("rounding_quantum"), "dynamic_budget.rounding_quantum"
    )
    if not min_evals <= base_evals <= max_evals:
        raise ConfigError(
            "dynamic budget requires min_evals <= base_evals <= max_evals"
        )

    state = read_search_state(workspace)
    anchor_config = state.get("incumbent", {}).get("config")
    current_weight = search_space_weight(config)
    anchor_weight = (
        search_space_weight(anchor_config)
        if isinstance(anchor_config, dict) and anchor_config
        else current_weight
    )
    space_factor = math.sqrt(current_weight / max(anchor_weight, 1.0))
    space_factor = min(1.75, max(0.75, space_factor))
    stale_rounds = max(0, int(state.get("stale_rounds", 0) or 0))
    difficulty_factor = 1.0 + 0.15 * min(stale_rounds, 2)
    target = int(round(base_evals * space_factor * difficulty_factor))
    target = min(max_evals, max(min_evals, target))

    ledger_path = workspace / ".hamilton_evaluation_ledger.json"
    consumed = (
        evaluation_ledger_total(read_evaluation_ledger(workspace))
        if ledger_path.is_file()
        else consumed_search_evals(workspace)
    )
    limit = evaluation_budget_limit(workspace)
    remaining = None if limit is None else int(limit) - consumed
    max_rounds = positive_int(
        (control or {}).get("max_rounds"), "search_control.max_rounds"
    )
    future_rounds = max(0, max_rounds - round_number)
    if remaining is not None:
        future_reserve = min_evals * future_rounds
        affordable = remaining - future_reserve
        if affordable < min_evals:
            raise ConfigError(
                "insufficient cumulative PySR budget for the current dynamic "
                f"allocation and future minimum reserve: remaining={remaining}, "
                f"current_min={min_evals}, future_reserve={future_reserve}"
            )
        target = min(target, affordable)

    allocated = max(min_evals, (target // quantum) * quantum)
    if allocated > target:
        allocated = target
    if allocated <= 0:
        raise ConfigError("dynamic evaluation allocation produced no usable budget")
    proposed = int(config["search"]["max_evals"])
    config["search"]["max_evals"] = int(allocated)
    allocation = {
        "mode": "dynamic_cumulative_ledger",
        "round": round_number,
        "proposed_evals_ignored": proposed,
        "allocated_evals": int(allocated),
        "consumed_before": int(consumed),
        "total_limit": limit,
        "remaining_before": remaining,
        "future_minimum_reserve": (
            None if remaining is None else min_evals * future_rounds
        ),
        "space_factor": float(space_factor),
        "stale_rounds": stale_rounds,
        "difficulty_factor": float(difficulty_factor),
        "anchor_weight": float(anchor_weight),
        "current_weight": float(current_weight),
    }
    config.setdefault("_controller", {})["budget_allocation"] = allocation
    return allocation


def check_evaluation_budget(workspace: Path, requested: int) -> tuple[int, int | None]:
    ledger_path = workspace / ".hamilton_evaluation_ledger.json"
    if ledger_path.is_file():
        consumed = evaluation_ledger_total(read_evaluation_ledger(workspace))
    else:
        consumed = consumed_search_evals(workspace)
    limit = evaluation_budget_limit(workspace)
    if limit is not None and consumed + requested > limit:
        raise ConfigError(
            f"total PySR evaluation budget exceeded: consumed={consumed}, "
            f"requested={requested}, limit={limit}"
        )
    return consumed, limit


def reserve_evaluations(
    workspace: Path,
    config: dict[str, Any],
    result_path: Path,
) -> dict[str, Any]:
    requested = int(config["search"]["max_evals"])
    with evaluation_ledger_lock(workspace):
        ledger = read_evaluation_ledger(workspace, initialize=True)
        consumed = evaluation_ledger_total(ledger)
        limit = ledger.get("max_total_evals")
        if limit is not None and consumed + requested > int(limit):
            raise ConfigError(
                f"total PySR evaluation budget exceeded: consumed={consumed}, "
                f"requested={requested}, limit={limit}"
            )
        attempt = {
            "attempt_id": str(uuid.uuid4()),
            "experiment_id": config["experiment_id"],
            "config_sha256": sha256_file(
                resolve_inside(workspace, config["_config_file"], "config")
            ),
            "result_file": str(result_path.relative_to(workspace)).replace("\\", "/"),
            "requested_evals": requested,
            "status": "reserved",
            "reserved_at": utc_now(),
        }
        allocation = (config.get("_controller") or {}).get(
            "budget_allocation"
        )
        if isinstance(allocation, dict):
            attempt["budget_allocation"] = allocation
        ledger["attempts"].append(attempt)
        write_evaluation_ledger(workspace, ledger)
        return dict(attempt)


def finish_evaluation_attempt(
    workspace: Path,
    attempt_id: str,
    status: str,
    result_path: Path | None = None,
) -> None:
    if status not in {"completed", "failed"}:
        raise ValueError(f"invalid evaluation attempt status: {status}")
    with evaluation_ledger_lock(workspace):
        ledger = read_evaluation_ledger(workspace)
        matches = [
            attempt
            for attempt in ledger["attempts"]
            if attempt.get("attempt_id") == attempt_id
        ]
        if len(matches) != 1:
            raise RuntimeError(f"evaluation ledger attempt not found: {attempt_id}")
        attempt = matches[0]
        if attempt.get("status") != "reserved":
            raise RuntimeError(
                f"evaluation ledger attempt already finalized: {attempt_id}"
            )
        attempt["status"] = status
        attempt["finished_at"] = utc_now()
        if result_path is not None and result_path.is_file():
            attempt["result_sha256"] = sha256_file(result_path)
        write_evaluation_ledger(workspace, ledger)


def meaningful_config(
    config: dict[str, Any],
    *,
    controller_owned_budget: bool = False,
) -> dict[str, Any]:
    """Match Promotion's scientific config projection before PySR is entered."""
    projected = json.loads(
        json.dumps(
            {
                "data": config.get("data") or {},
                "search": config.get("search") or {},
                "verification": config.get("verification") or {},
            }
        )
    )
    if projected["data"].get("standardize_search") is False:
        projected["data"].pop("standardize_search")
    residual = projected["verification"].get("residual_diagnostics")
    if isinstance(residual, dict) and residual.get("enabled") is False:
        projected["verification"].pop("residual_diagnostics")
    long_horizon = projected["verification"].get("long_horizon_dynamics")
    if isinstance(long_horizon, dict) and long_horizon.get("enabled") is False:
        projected["verification"].pop("long_horizon_dynamics")
    weights = (
        projected["verification"]
        .get("candidate_ranking", {})
        .get("weights")
    )
    if isinstance(weights, dict) and weights.get("long_horizon_penalty") == 0.0:
        weights.pop("long_horizon_penalty")
    if controller_owned_budget:
        projected["search"].pop("max_evals", None)
    # The controller's frozen repeat plan owns seeds. A planned seed change between
    # rounds must not consume the one-field scientific trust-region allowance.
    projected["search"].pop("random_state", None)
    session = projected.get("search_session")
    if isinstance(session, dict):
        session.pop("round", None)
        session.pop("final_round", None)
        session.pop("round_action", None)
    return projected


def changed_config_fields(
    previous: object,
    current: object,
    prefix: str = "",
) -> list[str]:
    if isinstance(previous, dict) and isinstance(current, dict):
        fields: list[str] = []
        for key in sorted(set(previous) | set(current)):
            child = f"{prefix}.{key}" if prefix else str(key)
            fields.extend(
                changed_config_fields(previous.get(key), current.get(key), child)
            )
        return fields
    return [] if previous == current else [prefix]


def adaptive_round_number(config_path: Path, workspace: Path) -> int | None:
    try:
        relative = config_path.resolve().relative_to(workspace.resolve())
    except ValueError:
        return None
    if len(relative.parts) < 2 or relative.parts[0] != "history":
        return None
    match = re.fullmatch(r"round([1-9][0-9]*)", relative.parts[1])
    return int(match.group(1)) if match else None


def expected_adaptive_config_patch(workspace: Path) -> dict[str, Any] | None:
    """Read the governed next-round patch when a scientific decision is present."""
    plan_path = workspace / "plan.md"
    if not plan_path.is_file():
        return None
    content = plan_path.read_text(encoding="utf-8")
    begin = "<!-- EVO_SCIENTIFIC_DECISION_BEGIN -->"
    end = "<!-- EVO_SCIENTIFIC_DECISION_END -->"
    start = content.find(begin)
    if start < 0:
        return None
    stop = content.find(end, start + len(begin))
    if stop < 0:
        raise ConfigError("scientific decision block is not terminated")
    try:
        decision = json.loads(content[start + len(begin) : stop].strip())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"scientific decision JSON invalid: {exc}") from exc
    strategy = decision.get("next_strategy")
    if not isinstance(strategy, dict):
        return None
    action = strategy.get("action", "modify")
    if action == "continue":
        if strategy.get("config_field") not in {None, ""} or strategy.get("config_patch") != {}:
            raise ConfigError(
                "continue action requires no config_field and an empty config_patch"
            )
        return {}
    if action != "modify":
        raise ConfigError("next_strategy.action must be 'continue' or 'modify'")
    config_field = strategy.get("config_field")
    config_patch = strategy.get("config_patch")
    if not isinstance(config_field, str) or not config_field:
        raise ConfigError("next_strategy.config_field must be a non-empty string")
    if not isinstance(config_patch, dict) or list(config_patch) != [config_field]:
        raise ConfigError(
            "next_strategy.config_patch must contain exactly config_field"
        )
    return config_patch


def value_at_leaf(config: dict[str, Any], field: str) -> Any:
    value: Any = config
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ConfigError(f"adaptive config patch field is missing: {field}")
        value = value[part]
    return value


def audit_single_field_adaptation(
    workspace: Path,
    config_path: Path,
    config: dict[str, Any],
) -> list[str]:
    """Reject multi-field adaptive rounds before evaluations can be reserved."""
    round_number = adaptive_round_number(config_path, workspace)
    if round_number is None or round_number <= 1:
        return []
    control = read_search_control(workspace)
    state = read_search_state(workspace)
    controller_budget = controller_owns_budget(workspace)
    baseline_path = state.get("next_round", {}).get("baseline_result_file")
    previous_results = []
    if isinstance(baseline_path, str) and baseline_path:
        candidate = resolve_inside(
            workspace, baseline_path, "search_state.baseline_result_file"
        )
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"trust-region baseline result is unreadable: {baseline_path}"
            ) from exc
        if payload.get("status") != "completed":
            raise ConfigError("trust-region baseline result is not completed")
        previous_results.append(payload)
    else:
        results_dir = workspace / "history" / f"round{round_number - 1}" / "results"
        for path in sorted(results_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("status") == "completed":
                previous_results.append(payload)
    if len(previous_results) != 1:
        raise ConfigError(
            "adaptive pre-search audit requires exactly one trust-region baseline; "
            f"found {len(previous_results)}"
        )
    previous_config = meaningful_config(
        previous_results[0].get("config", {}),
        controller_owned_budget=controller_budget,
    )
    current_config = meaningful_config(
        config,
        controller_owned_budget=controller_budget,
    )
    changed = changed_config_fields(
        previous_config,
        current_config,
    )
    max_step_changes = int(
        (control or {})
        .get("trust_region", {})
        .get("max_step_changes", 1)
    )
    expected_patch = expected_adaptive_config_patch(workspace)
    allow_noop = bool(
        (control or {}).get("trust_region", {}).get("allow_noop_continue", False)
    )
    minimum_changes = 0 if allow_noop and expected_patch == {} else 1
    if not minimum_changes <= len(changed) <= max_step_changes:
        raise ConfigError(
            "adaptive round must change exactly one scientific config field or use an "
            "explicitly authorized no-op continuation "
            "within the trust-region step before PySR; "
            f"allowed_changes={minimum_changes}..{max_step_changes}, changed_fields={changed}"
        )
    anchor = state.get("incumbent", {}).get("config")
    if isinstance(anchor, dict) and anchor:
        anchor_distance = changed_config_fields(anchor, current_config)
        max_anchor_distance = int(
            (control or {})
            .get("trust_region", {})
            .get("max_anchor_distance", 2)
        )
        if len(anchor_distance) > max_anchor_distance:
            raise ConfigError(
                "adaptive round exceeds the incumbent trust region before PySR; "
                f"max_anchor_distance={max_anchor_distance}, "
                f"anchor_changed_fields={anchor_distance}"
            )
    if expected_patch:
        expected_field, expected_value = next(iter(expected_patch.items()))
        if controller_budget and expected_field == "search.max_evals":
            raise ConfigError(
                "search.max_evals is controller-owned while dynamic budgeting is enabled"
            )
        actual_field = changed[0]
        actual_value = value_at_leaf(current_config, actual_field)
        if actual_field != expected_field or actual_value != expected_value:
            raise ConfigError(
                "adaptive round must implement the governed next_strategy config_patch "
                f"before PySR; expected_patch={expected_patch}, "
                f"actual_change={{'{actual_field}': {actual_value!r}}}"
            )
    return changed


def load_and_validate(config_path: Path, workspace: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON: {exc}") from exc

    if config.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    session = warm_start_session(config)
    experiment_id = config.get("experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ConfigError("experiment_id must be a non-empty string")

    data = require_dict(config.get("data"), "data")
    features = require_list_of_strings(data.get("feature_columns"), "data.feature_columns")
    target = data.get("target_column")
    time_column = data.get("time_column")
    if not isinstance(target, str) or not target:
        raise ConfigError("data.target_column must be a non-empty string")
    if not isinstance(time_column, str) or not time_column:
        raise ConfigError("data.time_column must be a non-empty string")
    if len(set([time_column, *features, target])) != len([time_column, *features, target]):
        raise ConfigError("time, feature, and target column names must be distinct")

    allowed_raw = require_list_of_strings(data.get("allowed_files"), "data.allowed_files")
    train_raw = data.get("train_file")
    if train_raw not in allowed_raw:
        raise ConfigError("data.train_file must appear exactly in data.allowed_files")
    allowed_paths = [resolve_inside(workspace, item, "data.allowed_files") for item in allowed_raw]
    train_path = resolve_inside(workspace, train_raw, "data.train_file")
    if train_path not in allowed_paths:
        raise ConfigError("normalized train_file is not in the allowlist")
    if not train_path.is_file():
        raise ConfigError(f"training file does not exist: {train_raw}")

    max_rows_raw = data.get("max_rows")
    max_rows = None if max_rows_raw is None else positive_int(max_rows_raw, "data.max_rows")
    search_stride = positive_int(data.get("search_stride", 1), "data.search_stride")
    standardize_search = data.get("standardize_search", False)
    if not isinstance(standardize_search, bool):
        raise ConfigError("data.standardize_search must be boolean")
    validation_fraction = data.get("validation_fraction")
    if (
        isinstance(validation_fraction, bool)
        or not isinstance(validation_fraction, (int, float))
        or not 0 < float(validation_fraction) < 0.5
    ):
        raise ConfigError("data.validation_fraction must be greater than 0 and less than 0.5")

    search = require_dict(config.get("search"), "search")
    if search.get("engine") != "pysr":
        raise ConfigError("search.engine must be 'pysr'")
    for field in ("niterations", "max_evals", "populations", "population_size", "maxsize", "top_k"):
        positive_int(search.get(field), f"search.{field}")
    tournament_n = positive_int(search.get("tournament_selection_n"), "search.tournament_selection_n")
    if tournament_n >= search["population_size"]:
        raise ConfigError("search.tournament_selection_n must be smaller than search.population_size")
    if not isinstance(search.get("random_state"), int) or isinstance(search.get("random_state"), bool):
        raise ConfigError("search.random_state must be an integer")
    require_list_of_strings(search.get("binary_operators"), "search.binary_operators")
    unary = search.get("unary_operators", [])
    if not isinstance(unary, list) or not all(isinstance(x, str) and x for x in unary):
        raise ConfigError("search.unary_operators must be an array of strings")
    parsimony = search.get("parsimony", 0.0)
    if isinstance(parsimony, bool) or not isinstance(parsimony, (int, float)) or parsimony < 0:
        raise ConfigError("search.parsimony must be a non-negative number")

    verification = require_dict(config.get("verification", {}), "verification")
    short_ode = require_dict(verification.get("short_ode", {"enabled": False}), "verification.short_ode")
    if not isinstance(short_ode.get("enabled"), bool):
        raise ConfigError("verification.short_ode.enabled must be boolean")
    if short_ode["enabled"]:
        position = short_ode.get("position_column")
        velocity = short_ode.get("velocity_column")
        if position not in features or velocity not in features or position == velocity:
            raise ConfigError("short ODE position/velocity columns must be distinct feature columns")
        positive_float(short_ode.get("duration"), "verification.short_ode.duration")
        if positive_int(short_ode.get("points"), "verification.short_ode.points") < 2:
            raise ConfigError("verification.short_ode.points must be at least 2")
        positive_float(short_ode.get("state_limit", 1e6), "verification.short_ode.state_limit")

    long_horizon = require_dict(
        verification.get("long_horizon_dynamics", {"enabled": False}),
        "verification.long_horizon_dynamics",
    )
    if not isinstance(long_horizon.get("enabled"), bool):
        raise ConfigError("verification.long_horizon_dynamics.enabled must be boolean")
    if long_horizon["enabled"]:
        position = long_horizon.get("position_column")
        velocity = long_horizon.get("velocity_column")
        if position not in features or velocity not in features or position == velocity:
            raise ConfigError(
                "long-horizon position/velocity columns must be distinct feature columns"
            )
        if len(features) != 2 or set(features) != {position, velocity}:
            raise ConfigError(
                "long-horizon dynamics currently requires exactly position and velocity features"
            )
        positive_float(long_horizon.get("duration"), "verification.long_horizon_dynamics.duration")
        if positive_int(
            long_horizon.get("points"), "verification.long_horizon_dynamics.points"
        ) < 64:
            raise ConfigError("verification.long_horizon_dynamics.points must be at least 64")
        for name in (
            "state_limit",
            "rtol",
            "atol",
            "large_initial_scale",
            "stationary_amplitude_fraction",
            "amplitude_relative_tolerance",
            "frequency_relative_tolerance",
            "stationarity_relative_tolerance",
            "attractor_relative_tolerance",
        ):
            positive_float(
                long_horizon.get(name),
                f"verification.long_horizon_dynamics.{name}",
            )
        if float(long_horizon["large_initial_scale"]) <= 1.0:
            raise ConfigError(
                "verification.long_horizon_dynamics.large_initial_scale must be greater than 1"
            )
        steady_fraction = long_horizon.get("steady_state_fraction")
        if (
            isinstance(steady_fraction, bool)
            or not isinstance(steady_fraction, (int, float))
            or not math.isfinite(steady_fraction)
            or not 0.1 <= float(steady_fraction) <= 0.5
        ):
            raise ConfigError(
                "verification.long_horizon_dynamics.steady_state_fraction "
                "must be between 0.1 and 0.5"
            )
        positive_float(
            long_horizon.get("min_steady_cycles"),
            "verification.long_horizon_dynamics.min_steady_cycles",
        )
        if long_horizon.get("zero_initial_policy") not in {
            "report_only",
            "require_same_attractor",
        }:
            raise ConfigError(
                "verification.long_horizon_dynamics.zero_initial_policy must be "
                "'report_only' or 'require_same_attractor'"
            )

    ranking = require_dict(verification.get("candidate_ranking", {"enabled": False}), "verification.candidate_ranking")
    if not isinstance(ranking.get("enabled"), bool):
        raise ConfigError("verification.candidate_ranking.enabled must be boolean")
    if ranking["enabled"]:
        max_candidates = positive_int(
            ranking.get("max_candidates", search["top_k"]),
            "verification.candidate_ranking.max_candidates",
        )
        if max_candidates > search["top_k"]:
            raise ConfigError("verification.candidate_ranking.max_candidates cannot exceed search.top_k")
        weights = require_dict(ranking.get("weights"), "verification.candidate_ranking.weights")
        for name in ("validation_nrmse", "trajectory_nrmse", "complexity"):
            value = weights.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ConfigError(f"verification.candidate_ranking.weights.{name} must be non-negative")
        long_weight = weights.get("long_horizon_penalty", 0.0)
        if (
            isinstance(long_weight, bool)
            or not isinstance(long_weight, (int, float))
            or not math.isfinite(long_weight)
            or long_weight < 0
        ):
            raise ConfigError(
                "verification.candidate_ranking.weights.long_horizon_penalty "
                "must be non-negative"
            )
        weights["long_horizon_penalty"] = float(long_weight)
        positive_float(ranking.get("failure_penalty", 100.0), "verification.candidate_ranking.failure_penalty")

    residual = require_dict(
        verification.get("residual_diagnostics", {"enabled": True}),
        "verification.residual_diagnostics",
    )
    if not isinstance(residual.get("enabled"), bool):
        raise ConfigError("verification.residual_diagnostics.enabled must be boolean")
    if residual["enabled"]:
        residual["max_lag"] = positive_int(
            residual.get("max_lag", 50),
            "verification.residual_diagnostics.max_lag",
        )
        residual["feature_bins"] = positive_int(
            residual.get("feature_bins", 4),
            "verification.residual_diagnostics.feature_bins",
        )
        residual["phase_bins"] = positive_int(
            residual.get("phase_bins", 8),
            "verification.residual_diagnostics.phase_bins",
        )
        if not 2 <= residual["feature_bins"] <= 10:
            raise ConfigError("verification.residual_diagnostics.feature_bins must be between 2 and 10")
        if not 4 <= residual["phase_bins"] <= 36:
            raise ConfigError("verification.residual_diagnostics.phase_bins must be between 4 and 36")
        high_frequency_fraction = residual.get("high_frequency_fraction", 0.25)
        if (
            isinstance(high_frequency_fraction, bool)
            or not isinstance(high_frequency_fraction, (int, float))
            or not math.isfinite(high_frequency_fraction)
            or not 0 < float(high_frequency_fraction) <= 0.5
        ):
            raise ConfigError(
                "verification.residual_diagnostics.high_frequency_fraction "
                "must be greater than 0 and at most 0.5"
            )
        residual["high_frequency_fraction"] = float(high_frequency_fraction)

    output = require_dict(config.get("output"), "output")
    result_path = resolve_inside(workspace, output.get("result_file"), "output.result_file")
    run_directory = resolve_inside(workspace, output.get("run_directory"), "output.run_directory")
    if result_path.suffix.lower() != ".json":
        raise ConfigError("output.result_file must end in .json")

    normalized = json.loads(json.dumps(config))
    if session is not None:
        normalized["search_session"] = session
    normalized["_config_file"] = str(config_path.relative_to(workspace)).replace("\\", "/")
    normalized["data"]["max_rows"] = max_rows
    normalized["data"]["search_stride"] = search_stride
    normalized["data"]["standardize_search"] = standardize_search
    normalized["data"]["validation_fraction"] = float(validation_fraction)
    normalized["verification"]["candidate_ranking"] = ranking
    normalized["verification"]["residual_diagnostics"] = residual
    normalized["verification"]["long_horizon_dynamics"] = long_horizon
    apply_controller_seed(
        workspace,
        normalized,
        adaptive_round_number(config_path, workspace),
    )
    audit_single_field_adaptation(workspace, config_path, normalized)
    allocate_dynamic_evaluations(
        workspace,
        normalized,
        adaptive_round_number(config_path, workspace),
    )
    check_evaluation_budget(
        workspace,
        int(normalized["search"]["max_evals"]),
    )
    return normalized, {
        "train": train_path,
        "result": result_path,
        "run_directory": run_directory,
    }


def load_data(config: dict[str, Any], train_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data_cfg = config["data"]
    required = [data_cfg["time_column"], *data_cfg["feature_columns"], data_cfg["target_column"]]
    frame = pd.read_csv(train_path, usecols=required, nrows=data_cfg["max_rows"])
    if len(frame) < 10:
        raise ConfigError("selected training data must contain at least 10 rows")
    if frame[required].isna().any().any():
        raise ConfigError("selected data contains missing values")
    numeric = frame[required].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ConfigError("selected data contains non-numeric or non-finite values")
    frame = numeric
    if not frame[data_cfg["time_column"]].is_monotonic_increasing:
        raise ConfigError("time column must be monotonically increasing")

    val_rows = max(1, int(round(len(frame) * data_cfg["validation_fraction"])))
    train_rows = len(frame) - val_rows
    if train_rows < 2:
        raise ConfigError("validation split leaves fewer than two training rows")
    train = frame.iloc[:train_rows].copy()
    validation = frame.iloc[train_rows:].copy()
    split = {
        "selected_rows": len(frame),
        "train_rows": len(train),
        "validation_rows": len(validation),
        "search_rows": len(train.iloc[:: data_cfg["search_stride"]]),
        "search_stride": data_cfg["search_stride"],
        "train_time": [float(train.iloc[0][data_cfg["time_column"]]), float(train.iloc[-1][data_cfg["time_column"]])],
        "validation_time": [
            float(validation.iloc[0][data_cfg["time_column"]]),
            float(validation.iloc[-1][data_cfg["time_column"]]),
        ],
    }
    return train, validation, split


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    residual = y_true - y_pred
    mse = float(np.mean(residual**2))
    variance = float(np.var(y_true))
    return {
        "mse": mse,
        "rmse": float(math.sqrt(mse)),
        "mae": float(np.mean(np.abs(residual))),
        "r2": float(1.0 - mse / variance) if variance > 0 else float("nan"),
    }


def finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def safe_correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    if len(left) < 2 or len(left) != len(right):
        return None
    epsilon = np.finfo(float).eps
    if float(np.std(left)) <= epsilon or float(np.std(right)) <= epsilon:
        return None
    return finite_or_none(np.corrcoef(left, right)[0, 1])


def quantile_edges(values: np.ndarray, bins: int) -> list[float]:
    quantiles = np.linspace(0.0, 1.0, bins + 1)
    edges = np.unique(np.quantile(np.asarray(values, dtype=float), quantiles))
    return [float(value) for value in edges]


def residual_bins(
    coordinates: np.ndarray,
    residuals: np.ndarray,
    edges: list[float],
) -> list[dict[str, Any]]:
    if len(edges) < 2:
        return []
    coordinates = np.asarray(coordinates, dtype=float)
    residuals = np.asarray(residuals, dtype=float)
    interior = np.asarray(edges[1:-1], dtype=float)
    indices = np.searchsorted(interior, coordinates, side="right")
    records = []
    for index in range(len(edges) - 1):
        selected = residuals[indices == index]
        records.append(
            {
                "bin": index + 1,
                "lower": None if index == 0 else float(edges[index]),
                "upper": None if index == len(edges) - 2 else float(edges[index + 1]),
                "count": int(len(selected)),
                "mean": finite_or_none(np.mean(selected)) if len(selected) else None,
                "rmse": (
                    finite_or_none(math.sqrt(float(np.mean(selected**2))))
                    if len(selected)
                    else None
                ),
            }
        )
    return records


def build_residual_context(
    train: pd.DataFrame,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = config["verification"]["residual_diagnostics"]
    features = config["data"]["feature_columns"]
    target = config["data"]["target_column"]
    context: dict[str, Any] = {
        "target_scale": max(
            float(np.std(train[target].to_numpy(dtype=float))),
            np.finfo(float).eps,
        ),
        "feature_edges": {
            name: quantile_edges(
                train[name].to_numpy(dtype=float),
                cfg["feature_bins"],
            )
            for name in features
        },
        "feature_center": {
            name: float(np.mean(train[name].to_numpy(dtype=float))) for name in features
        },
        "feature_scale": {
            name: max(
                float(np.std(train[name].to_numpy(dtype=float))),
                np.finfo(float).eps,
            )
            for name in features
        },
    }
    short_ode = config["verification"]["short_ode"]
    position = short_ode.get("position_column")
    velocity = short_ode.get("velocity_column")
    if position in features and velocity in features and position != velocity:
        position_z = (
            train[position].to_numpy(dtype=float) - context["feature_center"][position]
        ) / context["feature_scale"][position]
        velocity_z = (
            train[velocity].to_numpy(dtype=float) - context["feature_center"][velocity]
        ) / context["feature_scale"][velocity]
        radius = np.sqrt(position_z**2 + velocity_z**2)
        context["oscillator"] = {
            "position": position,
            "velocity": velocity,
            "radius_edges": quantile_edges(radius, cfg["feature_bins"]),
        }
    return context


def temporal_residual_diagnostics(
    residuals: np.ndarray,
    time_values: np.ndarray,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    residuals = np.asarray(residuals, dtype=float)
    time_values = np.asarray(time_values, dtype=float)
    centered = residuals - float(np.mean(residuals))
    energy = float(np.dot(centered, centered))
    max_lag = min(int(cfg["max_lag"]), max(0, len(residuals) - 1))
    all_autocorrelation = {
        lag: safe_correlation(residuals[:-lag], residuals[lag:])
        for lag in range(1, max_lag + 1)
    }
    requested_lags = sorted({lag for lag in (1, 5, 10, max_lag) if 0 < lag <= max_lag})
    autocorrelation = {
        str(lag): all_autocorrelation[lag] for lag in requested_lags
    }
    finite_autocorrelation = {
        lag: value for lag, value in all_autocorrelation.items() if value is not None
    }
    if finite_autocorrelation:
        max_lag_key, max_lag_value = max(
            finite_autocorrelation.items(),
            key=lambda item: abs(item[1]),
        )
        strongest = {"lag": max_lag_key, "value": max_lag_value}
    else:
        strongest = {"lag": None, "value": None}

    raw_energy = float(np.dot(residuals, residuals))
    durbin_watson = (
        finite_or_none(np.sum(np.diff(residuals) ** 2) / raw_energy)
        if len(residuals) > 1 and raw_energy > np.finfo(float).eps
        else None
    )
    result: dict[str, Any] = {
        "trend_correlation": safe_correlation(residuals, time_values),
        "durbin_watson": durbin_watson,
        "autocorrelation": autocorrelation,
        "strongest_reported_autocorrelation": strongest,
    }

    if len(time_values) < 4:
        result["spectrum"] = {"status": "insufficient_points"}
        return result
    intervals = np.diff(time_values)
    median_interval = float(np.median(intervals))
    interval_mean = float(np.mean(intervals))
    irregularity = (
        finite_or_none(np.std(intervals) / abs(interval_mean))
        if abs(interval_mean) > np.finfo(float).eps
        else None
    )
    result["sampling"] = {
        "median_interval": median_interval,
        "relative_interval_std": irregularity,
    }
    if median_interval <= 0 or energy <= np.finfo(float).eps:
        result["spectrum"] = {"status": "undefined"}
        return result

    frequencies = np.fft.rfftfreq(len(centered), d=median_interval)
    powers = np.abs(np.fft.rfft(centered)) ** 2
    frequencies = frequencies[1:]
    powers = powers[1:]
    total_power = float(np.sum(powers))
    if not len(powers) or total_power <= np.finfo(float).eps:
        result["spectrum"] = {"status": "undefined"}
        return result
    dominant_index = int(np.argmax(powers))
    nyquist = 0.5 / median_interval
    high_frequency_cutoff = nyquist * (1.0 - cfg["high_frequency_fraction"])
    high_power = float(np.sum(powers[frequencies >= high_frequency_cutoff]))
    result["spectrum"] = {
        "status": "completed",
        "method": "rfft_using_median_sampling_interval",
        "dominant_frequency_hz": float(frequencies[dominant_index]),
        "dominant_power_fraction": float(powers[dominant_index] / total_power),
        "high_frequency_cutoff_hz": high_frequency_cutoff,
        "high_frequency_power_fraction": high_power / total_power,
    }
    return result


def split_residual_diagnostics(
    frame: pd.DataFrame,
    predictions: np.ndarray,
    config: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    features = config["data"]["feature_columns"]
    target = config["data"]["target_column"]
    time_column = config["data"]["time_column"]
    cfg = config["verification"]["residual_diagnostics"]
    target_values = frame[target].to_numpy(dtype=float)
    residuals = target_values - np.asarray(predictions, dtype=float)
    correlations: dict[str, float | None] = {}
    feature_bins: dict[str, list[dict[str, Any]]] = {}
    for name in features:
        values = frame[name].to_numpy(dtype=float)
        correlations[name] = safe_correlation(residuals, values)
        correlations[f"abs({name})"] = safe_correlation(residuals, np.abs(values))
        feature_bins[name] = residual_bins(
            values,
            residuals,
            context["feature_edges"][name],
        )
    correlations["prediction"] = safe_correlation(residuals, predictions)
    finite_correlations = {
        name: value for name, value in correlations.items() if value is not None
    }
    if finite_correlations:
        signal, value = max(finite_correlations.items(), key=lambda item: abs(item[1]))
        strongest_state = {"signal": signal, "value": value}
    else:
        strongest_state = {"signal": None, "value": None}

    result: dict[str, Any] = {
        "summary": {
            "count": int(len(residuals)),
            "mean": float(np.mean(residuals)),
            "std": float(np.std(residuals)),
            "rmse": float(math.sqrt(float(np.mean(residuals**2)))),
            "nrmse_train_target_scale": float(
                math.sqrt(float(np.mean(residuals**2))) / context["target_scale"]
            ),
            "max_abs": float(np.max(np.abs(residuals))),
            "quantiles": {
                "q05": float(np.quantile(residuals, 0.05)),
                "q50": float(np.quantile(residuals, 0.50)),
                "q95": float(np.quantile(residuals, 0.95)),
            },
        },
        "state_dependence": {
            "pearson_correlation": correlations,
            "strongest_absolute_correlation": strongest_state,
            "feature_quantile_bins": feature_bins,
        },
        "temporal_structure": temporal_residual_diagnostics(
            residuals,
            frame[time_column].to_numpy(dtype=float),
            cfg,
        ),
    }

    oscillator = context.get("oscillator")
    if oscillator:
        position = oscillator["position"]
        velocity = oscillator["velocity"]
        position_z = (
            frame[position].to_numpy(dtype=float) - context["feature_center"][position]
        ) / context["feature_scale"][position]
        velocity_z = (
            frame[velocity].to_numpy(dtype=float) - context["feature_center"][velocity]
        ) / context["feature_scale"][velocity]
        radius = np.sqrt(position_z**2 + velocity_z**2)
        phase = np.arctan2(velocity_z, position_z)
        phase_edges = [
            float(value) for value in np.linspace(-math.pi, math.pi, cfg["phase_bins"] + 1)
        ]
        result["oscillator_state"] = {
            "coordinates": {
                "position": position,
                "velocity": velocity,
                "normalization": "training_mean_and_population_std",
            },
            "standardized_radius_bins": residual_bins(
                radius,
                residuals,
                oscillator["radius_edges"],
            ),
            "phase_bins_radians": residual_bins(phase, residuals, phase_edges),
        }
    return result


def residual_diagnostics(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    train_predictions: np.ndarray,
    validation_predictions: np.ndarray,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = config["verification"]["residual_diagnostics"]
    if not cfg["enabled"]:
        return {"enabled": False, "status": "disabled"}
    context = build_residual_context(train, config)
    reference = {
        "target_population_std": context["target_scale"],
        "feature_quantile_edges": context["feature_edges"],
        "feature_mean": context["feature_center"],
        "feature_population_std": context["feature_scale"],
    }
    if context.get("oscillator"):
        reference["standardized_radius_quantile_edges"] = context["oscillator"][
            "radius_edges"
        ]
    return {
        "enabled": True,
        "status": "completed",
        "definition": "target_minus_prediction_in_original_units",
        "reference_fit": "training_block_only",
        "reference": reference,
        "role": "diagnostic_only_not_in_scientific_score",
        "train": split_residual_diagnostics(
            train,
            train_predictions,
            config,
            context,
        ),
        "validation": split_residual_diagnostics(
            validation,
            validation_predictions,
            config,
            context,
        ),
        "interpretation_warning": (
            "Correlation, autocorrelation, spectral peaks, and state-bin patterns diagnose "
            "unexplained structure but do not identify a unique missing equation term. "
            "Derivative estimation noise can also create temporal and high-frequency residuals."
        ),
    }


def build_search_transform(
    train: pd.DataFrame,
    features: list[str],
    target: str,
    enabled: bool,
) -> dict[str, Any]:
    """Build a leakage-free affine transform from the complete discovery block."""
    if not enabled:
        return {
            "enabled": False,
            "fit_source": "training_block_only",
            "feature_mean": {},
            "feature_std": {},
            "target_mean": None,
            "target_std": None,
        }

    feature_values = train[features].to_numpy(dtype=float)
    target_values = train[target].to_numpy(dtype=float)
    feature_means = np.mean(feature_values, axis=0)
    feature_stds = np.std(feature_values, axis=0)
    target_mean = float(np.mean(target_values))
    target_std = float(np.std(target_values))
    epsilon = np.finfo(float).eps

    degenerate = [
        name
        for name, scale in zip(features, feature_stds, strict=True)
        if not math.isfinite(float(scale)) or float(scale) <= epsilon
    ]
    if degenerate:
        raise ConfigError(
            "cannot standardize constant or near-constant feature columns: "
            + ", ".join(degenerate)
        )
    if not math.isfinite(target_std) or target_std <= epsilon:
        raise ConfigError("cannot standardize a constant or near-constant target column")

    return {
        "enabled": True,
        "fit_source": "training_block_only",
        "feature_mean": {
            name: float(mean)
            for name, mean in zip(features, feature_means, strict=True)
        },
        "feature_std": {
            name: float(scale)
            for name, scale in zip(features, feature_stds, strict=True)
        },
        "target_mean": target_mean,
        "target_std": target_std,
        "search_equation": "z_target = g(z_features)",
        "raw_equation": (
            "target = target_mean + target_std * "
            "g((feature - feature_mean) / feature_std)"
        ),
    }


def transform_search_arrays(
    frame: pd.DataFrame,
    features: list[str],
    target: str,
    transform: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    feature_values = frame[features].to_numpy(dtype=float)
    target_values = frame[target].to_numpy(dtype=float)
    if not transform["enabled"]:
        return feature_values, target_values

    means = np.asarray([transform["feature_mean"][name] for name in features], dtype=float)
    scales = np.asarray([transform["feature_std"][name] for name in features], dtype=float)
    return (
        (feature_values - means) / scales,
        (target_values - float(transform["target_mean"])) / float(transform["target_std"]),
    )


def restore_original_units(
    search_expression: Any,
    features: list[str],
    transform: dict[str, Any],
) -> Any:
    """Convert z_target=g(z_features) into a law over the original variables."""
    import sympy

    expression = sympy.sympify(search_expression)
    if not transform["enabled"]:
        return sympy.simplify(expression)

    substitutions = {
        sympy.Symbol(name): (
            sympy.Symbol(name) - transform["feature_mean"][name]
        )
        / transform["feature_std"][name]
        for name in features
    }
    substituted = expression.subs(substitutions, simultaneous=True)
    restored = transform["target_mean"] + transform["target_std"] * substituted
    return sympy.simplify(restored)


def run_short_ode(
    expression: Any,
    config: dict[str, Any],
    validation: pd.DataFrame,
) -> dict[str, Any]:
    ode_cfg = config["verification"]["short_ode"]
    if not ode_cfg["enabled"]:
        return {"enabled": False, "status": "skipped"}

    from scipy.integrate import solve_ivp
    import sympy

    features = config["data"]["feature_columns"]
    position = ode_cfg["position_column"]
    velocity = ode_cfg["velocity_column"]
    if len(features) != 2 or set(features) != {position, velocity}:
        return {
            "enabled": True,
            "status": "failed",
            "reason": "short ODE currently requires exactly position and velocity features",
        }

    symbols = [sympy.Symbol(name) for name in features]
    acceleration = sympy.lambdify(symbols, expression, modules="numpy")
    x0 = float(validation.iloc[0][position])
    v0 = float(validation.iloc[0][velocity])
    t0 = float(validation.iloc[0][config["data"]["time_column"]])
    duration = float(ode_cfg["duration"])
    points = int(ode_cfg["points"])
    state_limit = float(ode_cfg.get("state_limit", 1e6))
    order = {name: index for index, name in enumerate(features)}

    def rhs(_time: float, state: np.ndarray) -> list[float]:
        if not np.isfinite(state).all() or np.max(np.abs(state)) > state_limit:
            raise FloatingPointError(f"ODE state exceeded state_limit={state_limit}")
        feature_values = [0.0] * len(features)
        feature_values[order[position]] = float(state[0])
        feature_values[order[velocity]] = float(state[1])
        value = float(acceleration(*feature_values))
        if not math.isfinite(value) or abs(value) > state_limit**2:
            raise FloatingPointError("candidate acceleration became non-finite or unbounded")
        return [float(state[1]), value]

    t_eval = np.linspace(t0, t0 + duration, points)
    solution = solve_ivp(
        rhs,
        (t0, t0 + duration),
        [x0, v0],
        t_eval=t_eval,
        rtol=1e-6,
        atol=1e-8,
        max_step=duration / max(points - 1, 1),
    )
    record: dict[str, Any] = {
        "enabled": True,
        "status": "completed" if solution.success else "failed",
        "success": bool(solution.success),
        "message": str(solution.message),
        "duration": duration,
        "points": len(solution.t),
    }
    if solution.success:
        observed_position = np.interp(
            solution.t,
            validation[config["data"]["time_column"]].to_numpy(dtype=float),
            validation[position].to_numpy(dtype=float),
        )
        record["position_trajectory_mse"] = float(np.mean((solution.y[0] - observed_position) ** 2))
        record["final_state"] = {"position": float(solution.y[0, -1]), "velocity": float(solution.y[1, -1])}
    return record


def _relative_error(value: float, reference: float) -> float:
    scale = max(abs(float(reference)), np.finfo(float).eps)
    return abs(float(value) - float(reference)) / scale


def _steady_state_summary(
    times: np.ndarray,
    positions: np.ndarray,
    steady_fraction: float,
    min_cycles: float,
    stationarity_tolerance: float,
    stationary_scale: float | None = None,
    stationary_amplitude_fraction: float = 0.0,
) -> dict[str, Any]:
    """Summarize a frozen tail window without returning pointwise trajectory data."""
    count = len(times)
    tail_count = max(32, int(math.ceil(count * steady_fraction)))
    if count < 64 or tail_count > count:
        return {
            "status": "failed",
            "failure_class": "insufficient_samples",
            "reason": "at least 64 total samples and 32 steady-window samples are required",
        }
    tail_times = np.asarray(times[-tail_count:], dtype=float)
    tail_positions = np.asarray(positions[-tail_count:], dtype=float)
    if not np.isfinite(tail_times).all() or not np.isfinite(tail_positions).all():
        return {
            "status": "failed",
            "failure_class": "non_finite_trajectory",
            "reason": "steady-state window contains non-finite values",
        }
    deltas = np.diff(tail_times)
    if len(deltas) == 0 or np.any(deltas <= 0):
        return {
            "status": "failed",
            "failure_class": "invalid_time_grid",
            "reason": "steady-state time grid must be strictly increasing",
        }
    dt = float(np.median(deltas))
    if not np.allclose(deltas, dt, rtol=1e-4, atol=max(1e-12, abs(dt) * 1e-7)):
        uniform_times = np.linspace(float(tail_times[0]), float(tail_times[-1]), tail_count)
        tail_positions = np.interp(uniform_times, tail_times, tail_positions)
        tail_times = uniform_times
        dt = float(tail_times[1] - tail_times[0])

    quantile_low, quantile_high = np.quantile(tail_positions, [0.05, 0.95])
    amplitude = 0.5 * float(quantile_high - quantile_low)
    centered = tail_positions - np.mean(tail_positions)
    time_centered = tail_times - np.mean(tail_times)
    slope = float(np.polyfit(time_centered, centered, 1)[0])
    detrended = centered - slope * time_centered
    signal_scale = max(float(np.std(tail_positions)), np.finfo(float).eps)
    stationary_threshold = max(
        32.0 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(tail_positions)))),
        float(stationary_amplitude_fraction) * float(stationary_scale or 0.0),
    )
    stationary_signal = amplitude <= stationary_threshold

    dominant_frequency: float | None = None
    observed_cycles: float | None = None
    frequency_status = "stationary"
    if not stationary_signal:
        windowed = detrended * np.hanning(tail_count)
        powers = np.abs(np.fft.rfft(windowed)) ** 2
        frequencies = np.fft.rfftfreq(tail_count, d=dt)
        if len(powers) > 1 and float(np.sum(powers[1:])) > np.finfo(float).eps:
            dominant_index = int(np.argmax(powers[1:]) + 1)
            dominant_frequency = float(frequencies[dominant_index])
            observed_cycles = dominant_frequency * float(tail_times[-1] - tail_times[0])
            frequency_status = (
                "completed" if observed_cycles >= min_cycles else "insufficient_cycles"
            )
        else:
            frequency_status = "not_identifiable"

    half = tail_count // 2
    first_window = tail_positions[:half]
    second_window = tail_positions[half:]
    if frequency_status == "completed" and dominant_frequency:
        cycle_samples = max(4, int(round(1.0 / (dominant_frequency * dt))))
        complete_cycles = tail_count // cycle_samples
        if complete_cycles >= 2:
            cycle_start = tail_count - complete_cycles * cycle_samples
            first_window = tail_positions[cycle_start : cycle_start + cycle_samples]
            second_window = tail_positions[-cycle_samples:]
    first_amplitude = 0.5 * float(
        np.quantile(first_window, 0.95) - np.quantile(first_window, 0.05)
    )
    second_amplitude = 0.5 * float(
        np.quantile(second_window, 0.95) - np.quantile(second_window, 0.05)
    )
    amplitude_drift = abs(second_amplitude - first_amplitude) / max(
        amplitude, np.finfo(float).eps
    )
    first_center = 0.5 * float(
        np.quantile(first_window, 0.95) + np.quantile(first_window, 0.05)
    )
    second_center = 0.5 * float(
        np.quantile(second_window, 0.95) + np.quantile(second_window, 0.05)
    )
    center_drift = abs(second_center - first_center) / max(
        amplitude, signal_scale, np.finfo(float).eps
    )
    stationarity_pass = bool(
        stationary_signal
        or (
            amplitude_drift <= stationarity_tolerance
            and center_drift <= stationarity_tolerance
            and frequency_status == "completed"
        )
    )
    return {
        "status": "completed",
        "window": {
            "start_time": float(tail_times[0]),
            "end_time": float(tail_times[-1]),
            "samples": tail_count,
            "fraction": float(steady_fraction),
        },
        "amplitude": {
            "method": "half_5_to_95_percentile_span",
            "value": amplitude,
        },
        "dominant_frequency_hz": dominant_frequency,
        "frequency_status": frequency_status,
        "observed_cycles": observed_cycles,
        "stationarity": {
            "amplitude_relative_drift": amplitude_drift,
            "center_relative_drift": center_drift,
            "tolerance": float(stationarity_tolerance),
            "passed": bool(stationarity_pass),
        },
        "qualitative_behavior": "stationary" if stationary_signal else "oscillatory",
        "stationary_amplitude_threshold": stationary_threshold,
    }


def run_long_horizon_dynamics(
    expression: Any,
    config: dict[str, Any],
    train: pd.DataFrame,
    validation: pd.DataFrame,
) -> dict[str, Any]:
    """Evaluate public Tier-0 long-horizon dynamics from deterministic initial states."""
    dynamics_cfg = config["verification"]["long_horizon_dynamics"]
    if not dynamics_cfg["enabled"]:
        return {"enabled": False, "status": "skipped", "ranking_penalty": 0.0}

    from scipy.integrate import solve_ivp
    import sympy

    features = config["data"]["feature_columns"]
    position = dynamics_cfg["position_column"]
    velocity = dynamics_cfg["velocity_column"]
    time_column = config["data"]["time_column"]
    symbols = [sympy.Symbol(name) for name in features]
    acceleration = sympy.lambdify(symbols, expression, modules="numpy")
    order = {name: index for index, name in enumerate(features)}
    state_limit = float(dynamics_cfg["state_limit"])
    duration = float(dynamics_cfg["duration"])
    points = int(dynamics_cfg["points"])
    steady_fraction = float(dynamics_cfg["steady_state_fraction"])
    min_cycles = float(dynamics_cfg["min_steady_cycles"])
    stationarity_tolerance = float(dynamics_cfg["stationarity_relative_tolerance"])

    discovery_scales = {
        name: max(
            float(np.quantile(np.abs(train[name].to_numpy(dtype=float)), 0.95)),
            float(np.std(train[name].to_numpy(dtype=float))),
            np.finfo(float).eps,
        )
        for name in (position, velocity)
    }

    reference = _steady_state_summary(
        validation[time_column].to_numpy(dtype=float),
        validation[position].to_numpy(dtype=float),
        steady_fraction,
        min_cycles,
        stationarity_tolerance,
        discovery_scales[position],
        float(dynamics_cfg["stationary_amplitude_fraction"]),
    )
    if reference.get("status") != "completed":
        return {
            "enabled": True,
            "status": "failed",
            "failure_class": "reference_unavailable",
            "reason": reference.get("reason"),
            "reference": reference,
            "ranking_penalty": float(
                config["verification"]["candidate_ranking"].get("failure_penalty", 100.0)
            ),
        }

    initial_states = {
        "observed_validation": [
            float(validation.iloc[0][position]),
            float(validation.iloc[0][velocity]),
        ],
        "zero": [0.0, 0.0],
        "large": [
            float(dynamics_cfg["large_initial_scale"]) * discovery_scales[position],
            float(dynamics_cfg["large_initial_scale"]) * discovery_scales[velocity],
        ],
    }
    t_eval = np.linspace(0.0, duration, points)

    def rhs(_time: float, state: np.ndarray) -> list[float]:
        if not np.isfinite(state).all():
            raise FloatingPointError("candidate state became non-finite")
        if np.max(np.abs(state)) > state_limit:
            raise OverflowError(f"candidate state exceeded state_limit={state_limit}")
        feature_values = [0.0] * len(features)
        feature_values[order[position]] = float(state[0])
        feature_values[order[velocity]] = float(state[1])
        value = float(acceleration(*feature_values))
        if not math.isfinite(value):
            raise FloatingPointError("candidate acceleration became non-finite")
        if abs(value) > state_limit**2:
            raise OverflowError("candidate acceleration exceeded the deterministic limit")
        return [float(state[1]), value]

    rollouts: dict[str, Any] = {}
    for label, initial_state in initial_states.items():
        try:
            solution = solve_ivp(
                rhs,
                (0.0, duration),
                initial_state,
                method="DOP853",
                t_eval=t_eval,
                rtol=float(dynamics_cfg["rtol"]),
                atol=float(dynamics_cfg["atol"]),
                max_step=duration / max(points - 1, 1),
            )
            if not solution.success or len(solution.t) != points:
                rollouts[label] = {
                    "status": "failed",
                    "failure_class": "solver_failed",
                    "reason": str(solution.message),
                    "initial_state": {position: initial_state[0], velocity: initial_state[1]},
                }
                continue
            summary = _steady_state_summary(
                solution.t,
                solution.y[0],
                steady_fraction,
                min_cycles,
                stationarity_tolerance,
                discovery_scales[position],
                float(dynamics_cfg["stationary_amplitude_fraction"]),
            )
            summary["initial_state"] = {
                position: initial_state[0],
                velocity: initial_state[1],
            }
            summary["final_state"] = {
                position: float(solution.y[0, -1]),
                velocity: float(solution.y[1, -1]),
            }
            rollouts[label] = summary
        except OverflowError as exc:
            rollouts[label] = {
                "status": "failed",
                "failure_class": "state_limit_exceeded",
                "reason": str(exc),
                "initial_state": {position: initial_state[0], velocity: initial_state[1]},
            }
        except (FloatingPointError, ValueError, TypeError) as exc:
            rollouts[label] = {
                "status": "failed",
                "failure_class": "non_finite_rhs",
                "reason": str(exc),
                "initial_state": {position: initial_state[0], velocity: initial_state[1]},
            }

    completed = [item for item in rollouts.values() if item.get("status") == "completed"]
    integration_pass = len(completed) == len(initial_states)
    observed = rollouts.get("observed_validation", {})
    reference_amplitude = float(reference["amplitude"]["value"])
    observed_amplitude = (
        float(observed["amplitude"]["value"])
        if observed.get("status") == "completed"
        else None
    )
    if (
        reference.get("qualitative_behavior") == "stationary"
        and observed.get("qualitative_behavior") == "stationary"
    ):
        amplitude_error = 0.0
    else:
        amplitude_error = (
            _relative_error(observed_amplitude, reference_amplitude)
            if observed_amplitude is not None
            else None
        )
    reference_frequency = reference.get("dominant_frequency_hz")
    observed_frequency = observed.get("dominant_frequency_hz")
    if (
        reference.get("qualitative_behavior") == "stationary"
        and observed.get("qualitative_behavior") == "stationary"
    ):
        frequency_error = 0.0
        frequency_comparison = "both_stationary"
    elif observed_frequency is not None and reference_frequency is not None:
        frequency_error = _relative_error(
            float(observed_frequency),
            float(reference_frequency),
        )
        frequency_comparison = "dominant_frequency"
    else:
        frequency_error = None
        frequency_comparison = "not_comparable"
    reference_match = {
        "amplitude_relative_error": amplitude_error,
        "frequency_relative_error": frequency_error,
        "frequency_comparison": frequency_comparison,
        "amplitude_tolerance": float(dynamics_cfg["amplitude_relative_tolerance"]),
        "frequency_tolerance": float(dynamics_cfg["frequency_relative_tolerance"]),
        "passed": bool(
            amplitude_error is not None
            and frequency_error is not None
            and amplitude_error <= float(dynamics_cfg["amplitude_relative_tolerance"])
            and frequency_error <= float(dynamics_cfg["frequency_relative_tolerance"])
        ),
    }

    pairwise: list[dict[str, Any]] = []
    labels = ["observed_validation", "large"]
    if dynamics_cfg["zero_initial_policy"] == "require_same_attractor":
        labels.append("zero")
    for left_index, left_label in enumerate(labels):
        for right_label in labels[left_index + 1 :]:
            left = rollouts[left_label]
            right = rollouts[right_label]
            amplitude_difference = None
            frequency_difference = None
            if left.get("status") == "completed" and right.get("status") == "completed":
                if (
                    left.get("qualitative_behavior") == "stationary"
                    and right.get("qualitative_behavior") == "stationary"
                ):
                    amplitude_difference = 0.0
                    frequency_difference = 0.0
                else:
                    amplitude_difference = _relative_error(
                        float(left["amplitude"]["value"]),
                        float(right["amplitude"]["value"]),
                    )
                if frequency_difference is None and (
                    left.get("dominant_frequency_hz") is not None
                    and right.get("dominant_frequency_hz") is not None
                ):
                    frequency_difference = _relative_error(
                        float(left["dominant_frequency_hz"]),
                        float(right["dominant_frequency_hz"]),
                    )
            tolerance = float(dynamics_cfg["attractor_relative_tolerance"])
            pairwise.append(
                {
                    "initial_conditions": [left_label, right_label],
                    "amplitude_relative_difference": amplitude_difference,
                    "frequency_relative_difference": frequency_difference,
                    "passed": bool(
                        amplitude_difference is not None
                        and frequency_difference is not None
                        and amplitude_difference <= tolerance
                        and frequency_difference <= tolerance
                    ),
                }
            )
    attractor_consistency = {
        "tolerance": float(dynamics_cfg["attractor_relative_tolerance"]),
        "pairwise": pairwise,
        "passed": bool(pairwise and all(item["passed"] for item in pairwise)),
    }
    stationarity_pass = bool(
        completed and len(completed) == len(initial_states)
        and all(item["stationarity"]["passed"] for item in completed)
    )
    overall_pass = bool(
        integration_pass
        and stationarity_pass
        and reference_match["passed"]
        and attractor_consistency["passed"]
    )
    failure_classes = sorted(
        {
            item.get("failure_class")
            for item in rollouts.values()
            if item.get("status") != "completed" and item.get("failure_class")
        }
    )
    if not stationarity_pass:
        failure_classes.append("nonstationary_or_unresolved_tail")
    if not reference_match["passed"]:
        failure_classes.append("reference_mismatch")
    if not attractor_consistency["passed"]:
        failure_classes.append("attractor_mismatch")

    failure_penalty = float(
        config["verification"]["candidate_ranking"].get("failure_penalty", 100.0)
    )
    score_components: dict[str, float] = {}

    def score_value(name: str, value: float | None) -> None:
        score_components[name] = (
            min(float(value), failure_penalty)
            if value is not None and math.isfinite(value)
            else 1.0
        )

    score_value("reference_amplitude_relative_error", amplitude_error)
    score_value("reference_frequency_relative_error", frequency_error)
    required_stationarity = ["observed_validation", "large"]
    if dynamics_cfg["zero_initial_policy"] == "require_same_attractor":
        required_stationarity.append("zero")
    for label in required_stationarity:
        item = rollouts[label]
        stationarity = item.get("stationarity", {})
        if item.get("status") != "completed":
            score_components[f"stationarity_{label}"] = failure_penalty
        elif stationarity.get("passed"):
            score_components[f"stationarity_{label}"] = 0.0
        else:
            amplitude_excess = float(
                stationarity.get("amplitude_relative_drift", failure_penalty)
            ) / stationarity_tolerance
            center_excess = float(
                stationarity.get("center_relative_drift", failure_penalty)
            ) / stationarity_tolerance
            score_components[f"stationarity_{label}"] = min(
                max(1.0, amplitude_excess, center_excess),
                failure_penalty,
            )
    for item in pairwise:
        label = "_vs_".join(item["initial_conditions"])
        score_value(
            f"attractor_amplitude_{label}",
            item["amplitude_relative_difference"],
        )
        score_value(
            f"attractor_frequency_{label}",
            item["frequency_relative_difference"],
        )
    ranking_penalty = (
        failure_penalty
        if not integration_pass
        else float(np.mean(list(score_components.values())))
    )
    return {
        "enabled": True,
        "status": "completed",
        "tier": "public_tier0",
        "definition": "deterministic_long_horizon_candidate_dynamics",
        "reference": reference,
        "initial_condition_policy": {
            "observed_validation": "first state of the public contiguous validation block",
            "zero": "exact zero position and velocity",
            "large": "positive discovery-block 95th-absolute scale times large_initial_scale",
            "zero_initial_policy": dynamics_cfg["zero_initial_policy"],
            "discovery_scales": discovery_scales,
        },
        "rollouts": rollouts,
        "gates": {
            "integration": integration_pass,
            "stationarity": stationarity_pass,
            "reference_match": reference_match,
            "attractor_consistency": attractor_consistency,
            "overall_pass": overall_pass,
        },
        "failure_classes": sorted(set(failure_classes)),
        "ranking_penalty": ranking_penalty,
        "ranking_penalty_definition": "mean_continuous_long_horizon_error_components",
        "ranking_penalty_components": score_components,
    }


def finite_predictions(expression: Any, features: list[str], frame: pd.DataFrame) -> np.ndarray:
    import sympy

    symbols = [sympy.Symbol(name) for name in features]
    function = sympy.lambdify(symbols, expression, modules="numpy")
    values = [frame[name].to_numpy(dtype=float) for name in features]
    prediction = np.asarray(function(*values), dtype=float)
    if prediction.ndim == 0:
        prediction = np.full(len(frame), float(prediction))
    prediction = prediction.reshape(-1)
    if len(prediction) != len(frame) or not np.isfinite(prediction).all():
        raise FloatingPointError("candidate produced invalid pointwise predictions")
    return prediction


def linear_diagnostic(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    features: list[str],
    target: str,
) -> dict[str, Any]:
    """Fit an intercept plus raw variables as a data-pipeline diagnostic, not discovery."""
    x_train = np.column_stack([np.ones(len(train)), train[features].to_numpy(dtype=float)])
    x_validation = np.column_stack([np.ones(len(validation)), validation[features].to_numpy(dtype=float)])
    y_train = train[target].to_numpy(dtype=float)
    y_validation = validation[target].to_numpy(dtype=float)
    coefficients = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
    feature_scales = np.std(train[features].to_numpy(dtype=float), axis=0)
    target_scale = max(float(np.std(y_train)), np.finfo(float).eps)
    standardized_effects = coefficients[1:] * feature_scales / target_scale
    return {
        "role": "diagnostic_only",
        "terms": ["intercept", *features],
        "coefficients": [float(value) for value in coefficients],
        "scale_aware": {
            "method": "coefficient_times_train_std_over_target_std",
            "feature_std": {
                name: float(scale) for name, scale in zip(features, feature_scales, strict=True)
            },
            "target_std": target_scale,
            "standardized_effect": {
                name: float(effect)
                for name, effect in zip(features, standardized_effects, strict=True)
            },
            "warning": (
                "Compare standardized effects, not raw coefficients, across variables "
                "with different units. This remains a diagnostic, not a discovered law."
            ),
        },
        "train": regression_metrics(y_train, x_train @ coefficients),
        "validation": regression_metrics(y_validation, x_validation @ coefficients),
    }


def evaluate_candidates(
    model: Any,
    equations: pd.DataFrame,
    config: dict[str, Any],
    train: pd.DataFrame,
    validation: pd.DataFrame,
    search_transform: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    import sympy

    search = config["search"]
    ranking = config["verification"]["candidate_ranking"]
    limit = ranking.get("max_candidates", search["top_k"]) if ranking["enabled"] else search["top_k"]
    rows = equations.sort_values("loss", ascending=True).head(limit)
    features = config["data"]["feature_columns"]
    target = config["data"]["target_column"]
    if search_transform is None:
        search_transform = build_search_transform(
            train,
            features,
            target,
            config["data"].get("standardize_search", False),
        )
    y_train = train[target].to_numpy(dtype=float)
    y_validation = validation[target].to_numpy(dtype=float)
    validation_scale = max(float(np.std(y_validation)), np.finfo(float).eps)
    position = config["verification"]["short_ode"].get("position_column")
    position_scale = (
        max(float(np.std(validation[position].to_numpy(dtype=float))), np.finfo(float).eps)
        if position in validation
        else 1.0
    )
    records: list[dict[str, Any]] = []

    for pysr_rank, (index, row) in enumerate(rows.iterrows(), start=1):
        record: dict[str, Any] = {
            "pysr_rank": pysr_rank,
            "equation": str(row["equation"]),
            "loss": float(row["loss"]),
            "complexity": int(row["complexity"]),
            "pysr_score": float(row["score"]) if "score" in row and pd.notna(row["score"]) else None,
        }
        try:
            search_expression = sympy.simplify(model.sympy(index=int(index)))
            expression = restore_original_units(search_expression, features, search_transform)
            train_prediction = finite_predictions(expression, features, train)
            validation_prediction = finite_predictions(expression, features, validation)
            train_metrics = regression_metrics(y_train, train_prediction)
            validation_metrics = regression_metrics(y_validation, validation_prediction)
            record["search_space_equation"] = str(search_expression)
            record["simplified_equation"] = str(expression)
            record["metrics"] = {"train": train_metrics, "validation": validation_metrics}
            try:
                ode = run_short_ode(expression, config, validation)
            except Exception as exc:
                ode = {"enabled": True, "status": "failed", "reason": str(exc)}
            try:
                long_horizon = run_long_horizon_dynamics(
                    expression,
                    config,
                    train,
                    validation,
                )
            except Exception as exc:
                long_horizon = {
                    "enabled": True,
                    "status": "failed",
                    "failure_class": "evaluator_error",
                    "reason": str(exc),
                    "ranking_penalty": float(ranking.get("failure_penalty", 100.0)),
                }
            record["verification"] = {
                "short_ode": ode,
                "long_horizon_dynamics": long_horizon,
            }

            validation_nrmse = validation_metrics["rmse"] / validation_scale
            trajectory_nrmse = (
                math.sqrt(float(ode["position_trajectory_mse"])) / position_scale
                if ode.get("status") == "completed" and "position_trajectory_mse" in ode
                else float(ranking.get("failure_penalty", 100.0))
            )
            complexity_normalized = record["complexity"] / search["maxsize"]
            weights = ranking.get(
                "weights",
                {
                    "validation_nrmse": 1.0,
                    "trajectory_nrmse": 0.0,
                    "complexity": 0.0,
                    "long_horizon_penalty": 0.0,
                },
            )
            long_horizon_penalty = float(long_horizon.get("ranking_penalty", 0.0))
            scientific_score = (
                float(weights["validation_nrmse"]) * validation_nrmse
                + float(weights["trajectory_nrmse"]) * trajectory_nrmse
                + float(weights["complexity"]) * complexity_normalized
                + float(weights.get("long_horizon_penalty", 0.0)) * long_horizon_penalty
            )
            record["ranking"] = {
                "validation_nrmse": validation_nrmse,
                "trajectory_nrmse": trajectory_nrmse,
                "complexity_normalized": complexity_normalized,
                "long_horizon_penalty": long_horizon_penalty,
                "scientific_score": scientific_score,
            }
        except Exception as exc:
            record["evaluation_error"] = {"type": type(exc).__name__, "message": str(exc)}
            record["ranking"] = {"scientific_score": float(ranking.get("failure_penalty", 100.0))}
        records.append(record)

    return records


def _run_experiment_with_model(
    config: dict[str, Any],
    paths: dict[str, Path],
    workspace: Path,
    model: Any | None = None,
    *,
    cumulative_max_evals: int | None = None,
    engine_evals_before: float = 0.0,
) -> tuple[dict[str, Any], Any]:
    started_at = utc_now()
    started = time.perf_counter()
    train, validation, split = load_data(config, paths["train"])
    features = config["data"]["feature_columns"]
    target = config["data"]["target_column"]
    search = config["search"]
    search_transform = build_search_transform(
        train,
        features,
        target,
        config["data"]["standardize_search"],
    )

    from pysr import PySRRegressor

    paths["run_directory"].parent.mkdir(parents=True, exist_ok=True)
    telemetry_path = paths["run_directory"] / "engine_telemetry.jsonl"
    telemetry_logger = make_logger_spec(telemetry_path, log_interval=1)
    effective_max_evals = int(search["max_evals"])
    session = warm_start_session(config)
    if model is None:
        model = PySRRegressor(
            niterations=search["niterations"],
            max_evals=effective_max_evals,
            populations=search["populations"],
            population_size=search["population_size"],
            tournament_selection_n=search["tournament_selection_n"],
            maxsize=search["maxsize"],
            parsimony=float(search.get("parsimony", 0.0)),
            binary_operators=search["binary_operators"],
            unary_operators=search.get("unary_operators") or None,
            random_state=search["random_state"],
            deterministic=True,
            parallelism="serial",
            warm_start=session is not None,
            model_selection="best",
            verbosity=0,
            progress=False,
            output_directory=str(paths["run_directory"].parent),
            run_id=paths["run_directory"].name,
            logger_spec=telemetry_logger,
        )
    else:
        if session is None or not bool(getattr(model, "warm_start", False)):
            raise ConfigError("an existing PySR model requires an active warm-start session")
        model.max_evals = effective_max_evals
        model.niterations = search["niterations"]
        model.maxsize = search["maxsize"]
        model.parsimony = float(search.get("parsimony", 0.0))
        # PySR's SearchState.num_evals and max_evals are per fit() invocation even
        # when the population is warm-started. The existing logger keeps its writer,
        # so truncate only its JSONL sink to isolate this round's incremental curve.
        telemetry_path.write_text("", encoding="utf-8")
    search_train = train.iloc[:: config["data"]["search_stride"]]
    search_features, search_target = transform_search_arrays(
        search_train,
        features,
        target,
        search_transform,
    )
    model.fit(
        search_features,
        search_target,
        variable_names=features,
    )

    import sympy

    y_validation = validation[target].to_numpy(dtype=float)
    validation_scale = max(float(np.std(y_validation)), np.finfo(float).eps)

    def telemetry_prediction(equation: str) -> np.ndarray:
        search_expression = sympy.sympify(equation)
        expression = restore_original_units(
            search_expression, features, search_transform
        )
        return finite_predictions(expression, features, validation)

    engine_telemetry = validation_curve(
        telemetry_path,
        predict_equation=telemetry_prediction,
        target=y_validation,
        target_scale=validation_scale,
    )
    round_engine_evals = float(engine_telemetry["final_engine_measured_evaluations"])
    engine_evals_after = engine_evals_before + round_engine_evals
    if session is not None:
        engine_telemetry["warm_start_session"] = {
            "session_id": session["session_id"],
            "round": session["round"],
            "engine_evaluations_before": engine_evals_before,
            "engine_evaluations_after": engine_evals_after,
            "round_engine_measured_evaluations": round_engine_evals,
            "effective_round_max_evals": effective_max_evals,
            "cumulative_requested_evaluations": int(
                cumulative_max_evals or search["max_evals"]
            ),
            "state_preserved": True,
        }

    equations = model.equations_
    if isinstance(equations, list):
        equations = equations[0]
    candidates = evaluate_candidates(
        model,
        equations,
        config,
        train,
        validation,
        search_transform,
    )
    if not candidates:
        raise RuntimeError("PySR returned no evaluable candidates")
    ranking_enabled = config["verification"]["candidate_ranking"]["enabled"]
    if ranking_enabled:
        selected = min(candidates, key=lambda item: item["ranking"]["scientific_score"])
        selection_method = "scientific_score"
    else:
        selected = min(candidates, key=lambda item: item["loss"])
        selection_method = "pysr_loss"
    if "metrics" not in selected:
        raise RuntimeError("selected candidate could not be evaluated")
    selected_verification = dict(selected["verification"])
    try:
        import sympy

        selected_expression = sympy.sympify(selected["simplified_equation"])
        selected_train_prediction = finite_predictions(selected_expression, features, train)
        selected_validation_prediction = finite_predictions(
            selected_expression,
            features,
            validation,
        )
        selected_verification["residual_diagnostics"] = residual_diagnostics(
            train,
            validation,
            selected_train_prediction,
            selected_validation_prediction,
            config,
        )
    except Exception as exc:
        selected_verification["residual_diagnostics"] = {
            "enabled": config["verification"]["residual_diagnostics"]["enabled"],
            "status": "failed",
            "reason": str(exc),
        }

    result = {
        "schema_version": 1,
        "experiment_id": config["experiment_id"],
        "status": "completed",
        "started_at": started_at,
        "completed_at": utc_now(),
        "runtime_seconds": time.perf_counter() - started,
        "config": config,
        "data": {
            "train_file": config["data"]["train_file"],
            "sha256": sha256_file(paths["train"]),
            "split": split,
            "search_transform": search_transform,
        },
        "diagnostics": {
            "linear_raw_features": linear_diagnostic(train, validation, features, target),
        },
        "candidates": candidates,
        "selected": {
            "selection_method": selection_method,
            "equation": selected["equation"],
            "search_space_equation": selected["search_space_equation"],
            "simplified_equation": selected["simplified_equation"],
            "loss": selected["loss"],
            "complexity": selected["complexity"],
            "scientific_score": selected["ranking"]["scientific_score"],
        },
        "metrics": selected["metrics"],
        "verification": selected_verification,
        "reproducibility": {
            "random_state": search["random_state"],
            "deterministic": True,
            "parallelism": "serial",
            "git_commit": git_revision(workspace),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "engine_telemetry": engine_telemetry,
    }
    return result, model


def run_experiment(
    config: dict[str, Any],
    paths: dict[str, Path],
    workspace: Path,
) -> dict[str, Any]:
    result, _ = _run_experiment_with_model(config, paths, workspace)
    return result


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def compact_summary(result: dict[str, Any], result_path: Path | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "experiment_id": result.get("experiment_id"),
        "status": result.get("status"),
        "result_file": str(result_path) if result_path else None,
    }
    if result.get("status") == "completed":
        summary.update(
            {
                "selected_equation": result["selected"]["simplified_equation"],
                "search_space_equation": result["selected"]["search_space_equation"],
                "search_standardized": result["data"]["search_transform"]["enabled"],
                "selection_method": result["selected"]["selection_method"],
                "scientific_score": result["selected"]["scientific_score"],
                "train_mse": result["metrics"]["train"]["mse"],
                "train_r2": result["metrics"]["train"]["r2"],
                "validation_mse": result["metrics"]["validation"]["mse"],
                "validation_r2": result["metrics"]["validation"]["r2"],
                "ode_status": result["verification"]["short_ode"]["status"],
                "long_horizon_status": result["verification"]
                .get("long_horizon_dynamics", {})
                .get("status", "skipped"),
                "long_horizon_pass": result["verification"]
                .get("long_horizon_dynamics", {})
                .get("gates", {})
                .get("overall_pass"),
                "residual_diagnostics_status": result["verification"][
                    "residual_diagnostics"
                ]["status"],
                "validation_residual_max_state_correlation": (
                    result["verification"]["residual_diagnostics"]
                    .get("validation", {})
                    .get("state_dependence", {})
                    .get("strongest_absolute_correlation")
                ),
                "validation_residual_max_autocorrelation": (
                    result["verification"]["residual_diagnostics"]
                    .get("validation", {})
                    .get("temporal_structure", {})
                    .get("strongest_reported_autocorrelation")
                ),
                "runtime_seconds": result["runtime_seconds"],
            }
        )
    else:
        summary["error"] = result.get("error")
    return summary


def main() -> int:
    args = parse_args()
    workspace = Path.cwd().resolve()
    config_path: Path | None = None
    result_path: Path | None = None
    experiment_id: str | None = None
    evaluation_attempt: dict[str, Any] | None = None
    stage = "configuration"
    try:
        config_path = resolve_inside(workspace, args.config, "config")
        if not config_path.is_file():
            raise ConfigError(f"config file does not exist: {args.config}")
        config, paths = load_and_validate(config_path, workspace)
        experiment_id = config["experiment_id"]
        result_path = paths["result"]
        if args.validate_only:
            summary = {
                "experiment_id": experiment_id,
                "status": "validated",
                "config_file": str(config_path),
                "result_file": str(result_path),
            }
            print("===SR_EXPERIMENT_SUMMARY_BEGIN===")
            print(json.dumps(summary, ensure_ascii=False))
            print("===SR_EXPERIMENT_SUMMARY_END===")
            return 0

        stage = "execution"
        evaluation_attempt = reserve_evaluations(
            workspace,
            config,
            result_path,
        )
        result = (
            run_warm_start_round(config, workspace)
            if warm_start_session(config) is not None
            else run_experiment(config, paths, workspace)
        )
        result["evaluation_budget"] = {
            "attempt_id": evaluation_attempt["attempt_id"],
            "requested_evals": evaluation_attempt["requested_evals"],
            "reservation_status": "reserved_before_pysr",
        }
        write_result(result_path, result)
        finish_evaluation_attempt(
            workspace,
            evaluation_attempt["attempt_id"],
            "completed",
            result_path,
        )
        summary = compact_summary(result, result_path)
        print("===SR_EXPERIMENT_SUMMARY_BEGIN===")
        print(json.dumps(summary, ensure_ascii=False))
        print("===SR_EXPERIMENT_SUMMARY_END===")
        return 0
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "experiment_id": experiment_id,
            "status": "failed",
            "completed_at": utc_now(),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "stage": stage,
            },
        }
        if evaluation_attempt is not None:
            failure["evaluation_budget"] = {
                "attempt_id": evaluation_attempt["attempt_id"],
                "requested_evals": evaluation_attempt["requested_evals"],
                "reservation_status": "consumed_by_failed_attempt",
            }
        if result_path is not None:
            try:
                write_result(result_path, failure)
            except Exception:
                pass
        if evaluation_attempt is not None:
            try:
                finish_evaluation_attempt(
                    workspace,
                    evaluation_attempt["attempt_id"],
                    "failed",
                    result_path,
                )
            except Exception as ledger_exc:
                failure["evaluation_ledger_error"] = {
                    "type": type(ledger_exc).__name__,
                    "message": str(ledger_exc),
                }
        print("===SR_EXPERIMENT_SUMMARY_BEGIN===")
        print(json.dumps(compact_summary(failure, result_path), ensure_ascii=False))
        print("===SR_EXPERIMENT_SUMMARY_END===")
        if os.environ.get("SR_EXPERIMENT_DEBUG") == "1":
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
