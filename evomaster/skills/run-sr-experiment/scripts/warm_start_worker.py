#!/usr/bin/env python3
"""Workspace-local persistent PySR worker for governed warm-start rounds."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import struct
import sys
import traceback
import uuid
import time
from pathlib import Path
from typing import Any


def _load_runner():
    path = Path(__file__).with_name("run_experiment.py")
    spec = importlib.util.spec_from_file_location("hamilton_standard_runner", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load standard runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receive(connection: socket.socket) -> dict[str, Any]:
    header = connection.recv(4)
    if len(header) != 4:
        raise ValueError("incomplete warm-start request header")
    size = struct.unpack("!I", header)[0]
    if size <= 0 or size > 1024 * 1024:
        raise ValueError("invalid warm-start request size")
    chunks = bytearray()
    while len(chunks) < size:
        block = connection.recv(size - len(chunks))
        if not block:
            raise ValueError("incomplete warm-start request body")
        chunks.extend(block)
    value = json.loads(chunks.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("warm-start request must be an object")
    return value


def _send(connection: socket.socket, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    connection.sendall(struct.pack("!I", len(payload)) + payload)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        for attempt in range(100):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 99:
                    raise
                time.sleep(0.01)
    finally:
        temporary.unlink(missing_ok=True)


def _scientific_projection(config: dict[str, Any]) -> dict[str, Any]:
    projected = json.loads(json.dumps(config))
    for field in ("experiment_id", "output", "_config_file", "_controller"):
        projected.pop(field, None)
    projected.get("search", {}).pop("max_evals", None)
    session = projected.get("search_session")
    if isinstance(session, dict):
        session.pop("round", None)
        session.pop("final_round", None)
        session.pop("round_action", None)
    return projected


def _changed(previous: Any, current: Any, prefix: str = "") -> list[str]:
    if isinstance(previous, dict) and isinstance(current, dict):
        changes: list[str] = []
        for key in sorted(set(previous) | set(current)):
            child = f"{prefix}.{key}" if prefix else key
            changes.extend(_changed(previous.get(key), current.get(key), child))
        return changes
    return [] if previous == current else [prefix]


def _validate_transition(
    previous: dict[str, Any], current: dict[str, Any], allowed: list[str]
) -> list[str]:
    if current["search"]["random_state"] != previous["search"]["random_state"]:
        raise ValueError("warm-start random_state must remain unchanged")
    if current["output"]["run_directory"] != previous["output"]["run_directory"]:
        raise ValueError("warm-start output.run_directory must remain unchanged")
    changes = _changed(_scientific_projection(previous), _scientific_projection(current))
    disallowed = [field for field in changes if field not in allowed]
    if disallowed:
        raise ValueError(f"warm-start transition changes incompatible fields: {disallowed}")
    return changes


def serve(workspace: Path, port: int, token: str, metadata_path: Path) -> int:
    runner = _load_runner()
    model = None
    previous_config: dict[str, Any] | None = None
    previous_engine_evals = 0.0
    cumulative_requested = 0
    expected_round = 1

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen(1)
        actual_port = int(server.getsockname()[1])
        _atomic_json(metadata_path, {
            "schema_version": 1,
            "status": "ready",
            "pid": os.getpid(),
            "port": actual_port,
            "token": token,
        })
        while True:
            connection, _ = server.accept()
            with connection:
                response: dict[str, Any]
                close_after = False
                fatal = False
                try:
                    request = _receive(connection)
                    if request.get("token") != token:
                        raise PermissionError("invalid warm-start worker token")
                    if request.get("command") == "close":
                        response = {"status": "completed", "closed": True}
                        _send(connection, response)
                        _atomic_json(metadata_path, {
                            "schema_version": 1,
                            "status": "closed",
                            "pid": os.getpid(),
                            "port": actual_port,
                        })
                        return 0
                    request_path = runner.resolve_inside(
                        workspace, request.get("request_file"), "warm-start request file"
                    )
                    payload = json.loads(request_path.read_text(encoding="utf-8"))
                    config = payload["config"]
                    session = runner.warm_start_session(config)
                    if session is None:
                        raise ValueError("request lacks warm-start session")
                    if session["round"] != expected_round:
                        raise ValueError(
                            f"warm-start worker expected round {expected_round}, got {session['round']}"
                        )
                    if previous_config is not None:
                        changes = _validate_transition(
                            previous_config, config, session["compatible_change_fields"]
                        )
                    else:
                        changes = []
                    cumulative_requested += int(config["search"]["max_evals"])
                    paths = {
                        "train": runner.resolve_inside(workspace, config["data"]["train_file"], "train"),
                        "result": runner.resolve_inside(workspace, config["output"]["result_file"], "result"),
                        "run_directory": runner.resolve_inside(
                            workspace, config["output"]["run_directory"], "run directory"
                        ),
                    }
                    result, model = runner._run_experiment_with_model(
                        config,
                        paths,
                        workspace,
                        model,
                        cumulative_max_evals=cumulative_requested,
                        engine_evals_before=previous_engine_evals,
                    )
                    previous_engine_evals = float(
                        result["engine_telemetry"]["warm_start_session"][
                            "engine_evaluations_after"
                        ]
                    )
                    result["warm_start_transition"] = {
                        "round": expected_round,
                        "changed_fields": changes,
                        "cumulative_requested_evaluations": cumulative_requested,
                    }
                    response_path = runner.resolve_inside(
                        workspace, payload["response_file"], "warm-start response file"
                    )
                    _atomic_json(response_path, {"status": "completed", "result": result})
                    previous_config = config
                    expected_round += 1
                    close_after = bool(session["final_round"])
                    response = {"status": "completed", "response_file": payload["response_file"]}
                except Exception as exc:
                    fatal = True
                    response = {
                        "status": "failed",
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }
                    try:
                        if "payload" in locals() and isinstance(payload, dict):
                            response_path = runner.resolve_inside(
                                workspace, payload["response_file"], "warm-start response file"
                            )
                            _atomic_json(response_path, {
                                **response,
                                "traceback": traceback.format_exc(),
                            })
                    except Exception:
                        pass
                _send(connection, response)
            if fatal:
                _atomic_json(metadata_path, {
                    "schema_version": 1,
                    "status": "failed",
                    "pid": os.getpid(),
                    "port": actual_port,
                    "error": response.get("error"),
                })
                return 1
            if close_after:
                _atomic_json(metadata_path, {
                    "schema_version": 1,
                    "status": "closed",
                    "pid": os.getpid(),
                    "port": actual_port,
                })
                return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    return serve(
        args.workspace.resolve(), args.port, args.token, args.metadata.resolve()
    )


if __name__ == "__main__":
    raise SystemExit(main())
