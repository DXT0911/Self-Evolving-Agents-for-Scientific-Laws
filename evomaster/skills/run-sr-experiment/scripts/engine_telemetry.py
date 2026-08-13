"""PySR/SymbolicRegression engine-evaluation telemetry.

The backend already tracks ``SearchState.num_evals`` and exposes it through its logger
payload together with the current Pareto equations.  This module writes that payload to
JSONL without requiring TensorBoard and converts it into a compact validation curve.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np


def make_logger_spec(path: Path, log_interval: int = 1) -> Any:
    """Return a PySR logger spec whose Julia logger writes one JSON object per callback."""
    from pysr.julia_import import jl
    from pysr.logger_specs import AbstractLoggerSpec

    def jsonable(value: Any) -> Any:
        """Convert PythonCall's lightweight Julia wrappers into JSON values."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if hasattr(value, "items"):
            return {str(key): jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)) or (
            hasattr(value, "__iter__") and not isinstance(value, (bytes, bytearray))
        ):
            return [jsonable(item) for item in value]
        raise TypeError(f"unsupported Julia telemetry value: {type(value).__name__}")

    write_lock = threading.Lock()

    def write_payload(payload: Any) -> None:
        line = json.dumps(
            jsonable(payload), ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
        with write_lock, path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")

    class HamiltonJSONLLoggerSpec(AbstractLoggerSpec):
        def create_logger(self) -> Any:
            jl.seval(
                r'''
                import PythonCall
                if !isdefined(Main, :HamiltonJSONLLogger)
                    mutable struct HamiltonJSONLLogger <: SymbolicRegression.AbstractSRLogger
                        writer::PythonCall.Py
                        log_interval::Int
                        step::Int
                    end
                    SymbolicRegression.get_logger(logger::HamiltonJSONLLogger) =
                        Logging.ConsoleLogger(stderr, Logging.Error)
                    function SymbolicRegression.LoggingModule.logging_callback!(
                        logger::HamiltonJSONLLogger; state, datasets, ropt, options
                    )
                        if logger.log_interval > 0 && logger.step % logger.log_interval == 0
                            payload = SymbolicRegression.LoggingModule.log_payload(
                                logger, state, datasets, options
                            )
                            payload["log_step"] = logger.step
                            logger.writer(payload)
                        end
                        logger.step += 1
                        return nothing
                    end
                end
                '''
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            constructor = jl.seval("HamiltonJSONLLogger")
            return constructor(write_payload, int(log_interval), 0)

        def write_hparams(self, logger: Any, hparams: dict[str, Any]) -> None:
            return None

        def close(self, logger: Any) -> None:
            return None

    return HamiltonJSONLLoggerSpec()


def read_payloads(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError("PySR engine telemetry file was not created")
    payloads = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        measured = value.get("num_evals")
        if isinstance(measured, bool) or not isinstance(measured, (int, float)):
            raise ValueError(f"telemetry line {number} lacks numeric num_evals")
        measured = float(measured)
        if not math.isfinite(measured) or measured < 0:
            raise ValueError(f"telemetry line {number} has invalid num_evals")
        value["num_evals"] = measured
        payloads.append(value)
    if not payloads:
        raise ValueError("PySR engine telemetry contains no checkpoints")
    return payloads


def validation_curve(
    path: Path,
    *,
    predict_equation: Callable[[str], np.ndarray],
    target: np.ndarray,
    target_scale: float,
) -> dict[str, Any]:
    """Evaluate every logged Pareto front on the frozen validation target."""
    if not math.isfinite(target_scale) or target_scale <= 0:
        raise ValueError("target_scale must be positive and finite")
    points: list[dict[str, Any]] = []
    best_so_far = math.inf
    previous_evals = -math.inf
    for payload in read_payloads(path):
        measured = float(payload["num_evals"])
        if measured < previous_evals:
            raise ValueError("engine evaluation telemetry is not monotonic")
        previous_evals = measured
        candidates: list[tuple[float, int, str]] = []
        for key, item in payload.get("equations", {}).items():
            if not isinstance(item, dict) or not isinstance(item.get("equation"), str):
                continue
            try:
                prediction = np.asarray(predict_equation(item["equation"]), dtype=float)
                if prediction.shape != target.shape or not np.all(np.isfinite(prediction)):
                    continue
                nrmse = float(np.sqrt(np.mean((target - prediction) ** 2)) / target_scale)
                complexity = int(str(key).split("=", 1)[1])
            except (ValueError, TypeError, OverflowError, IndexError):
                continue
            if math.isfinite(nrmse):
                candidates.append((nrmse, complexity, item["equation"]))
        if not candidates:
            continue
        checkpoint_best, complexity, equation = min(candidates)
        best_so_far = min(best_so_far, checkpoint_best)
        point = {
            "log_step": int(payload.get("log_step", len(points))),
            "engine_measured_evaluations": measured,
            "checkpoint_best_validation_nrmse": checkpoint_best,
            "best_so_far_validation_nrmse": best_so_far,
            "checkpoint_best_complexity": complexity,
            "checkpoint_best_equation": equation,
        }
        if points and measured == points[-1]["engine_measured_evaluations"]:
            points[-1] = point
        else:
            points.append(point)
    if not points:
        raise ValueError("no telemetry equation was evaluable on validation data")
    return {
        "schema_version": 1,
        "source": "symbolic_regression_logger_state_num_evals",
        "uses_engine_measured_evaluations": True,
        "checkpoint_count": len(points),
        "final_engine_measured_evaluations": points[-1]["engine_measured_evaluations"],
        "curve": points,
    }
