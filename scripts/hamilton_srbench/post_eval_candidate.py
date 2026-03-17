#!/usr/bin/env python3
"""SRBENCH_ANCHOR_POST_EVAL

Deterministically post-evaluate a symbolic-regression candidate on a full
OpenEvolve problem pack with repeated train-time restarts and held-out metrics.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType

import numpy as np
from scipy.optimize import minimize


DEFAULT_RESTARTS = 8
DEFAULT_PARAM_DIM = 10
DEFAULT_SEED = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-evaluate one SRBench candidate program.")
    parser.add_argument("--program", required=True, help="Path to candidate_model.py or initial_program.py")
    parser.add_argument("--problem-dir", required=True, help="Problem directory containing full train/test/OOD arrays")
    parser.add_argument("--label", default=None, help="Optional label for reporting")
    parser.add_argument("--restarts", type=int, default=DEFAULT_RESTARTS, help="Number of BFGS restarts")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Base seed for restart initialization")
    parser.add_argument(
        "--param-dim",
        type=int,
        default=DEFAULT_PARAM_DIM,
        help="Parameter dimension expected by the candidate function",
    )
    parser.add_argument("--json-out", default=None, help="Optional JSON output path")
    return parser.parse_args()


def load_module(module_name: str, module_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_candidate(program_path: Path):
    module = load_module(f"candidate_{program_path.stem}", program_path)
    if not hasattr(module, "run_search") or not callable(module.run_search):
        raise RuntimeError(f"{program_path} does not define callable run_search()")
    func = module.run_search()
    if not callable(func):
        raise RuntimeError(f"{program_path} run_search() did not return a callable")
    return func


def load_array(problem_dir: Path, name: str) -> np.ndarray | None:
    path = problem_dir / name
    if not path.exists():
        return None
    return np.load(path)


def safe_predict(func, x: np.ndarray, params: np.ndarray) -> np.ndarray:
    y = func(x, params)
    y = np.asarray(y, dtype=float)
    if y.shape != (x.shape[0],):
        raise RuntimeError(f"Prediction shape mismatch: got {y.shape}, expected {(x.shape[0],)}")
    if np.any(~np.isfinite(y)):
        raise RuntimeError("Prediction contains NaN or inf")
    return y


def mse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean((y_true - y_pred) ** 2))


def nmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = float(np.mean((y_true - np.mean(y_true)) ** 2))
    return float(mse(y_true, y_pred) / (denom + 1e-12))


def objective(params: np.ndarray, func, x: np.ndarray, y: np.ndarray) -> float:
    try:
        y_pred = safe_predict(func, x, params)
    except Exception:
        return float("inf")
    return mse(y, y_pred)


def optimize_params(func, x_train: np.ndarray, y_train: np.ndarray, param_dim: int, restarts: int, seed: int):
    best = None
    history = []

    for restart in range(restarts):
        rng = np.random.default_rng(seed + restart)
        init = rng.random(param_dim, dtype=float)
        try:
            result = minimize(objective, init, args=(func, x_train, y_train), method="BFGS")
            params = result.x if hasattr(result, "x") else init
            train_mse = objective(params, func, x_train, y_train)
            success = bool(getattr(result, "success", False))
            message = str(getattr(result, "message", ""))
        except Exception as exc:
            params = init
            train_mse = float("inf")
            success = False
            message = str(exc)

        record = {
            "restart": restart,
            "seed": seed + restart,
            "train_mse": float(train_mse),
            "success": success,
            "message": message,
            "params": params.tolist(),
        }
        history.append(record)

        if best is None or train_mse < best["train_mse"]:
            best = record

    if best is None:
        raise RuntimeError("No optimization result was produced.")
    return best, history


def metric_block(func, params: np.ndarray, x: np.ndarray | None, y: np.ndarray | None) -> dict | None:
    if x is None or y is None:
        return None
    y_pred = safe_predict(func, x, params)
    raw_mse = mse(y, y_pred)
    return {
        "mse": raw_mse,
        "nmse": nmse(y, y_pred),
        "negative_mse": -raw_mse,
        "combined_score": -math.log10(raw_mse + 1e-9),
    }


def evaluate_program(
    program_path: Path, problem_dir: Path, label: str, restarts: int, seed: int, param_dim: int
) -> dict:
    func = load_candidate(program_path)

    x_train = load_array(problem_dir, "X_train_for_eval.npy")
    y_train = load_array(problem_dir, "y_train_for_eval.npy")
    x_test = load_array(problem_dir, "X_test_for_eval.npy")
    y_test = load_array(problem_dir, "y_test_for_eval.npy")
    x_ood = load_array(problem_dir, "X_ood_test_for_eval.npy")
    y_ood = load_array(problem_dir, "y_ood_test_for_eval.npy")

    if x_train is None or y_train is None:
        raise RuntimeError(f"Missing train arrays in {problem_dir}")

    best, restart_history = optimize_params(func, x_train, y_train, param_dim, restarts, seed)
    best_params = np.asarray(best["params"], dtype=float)

    result = {
        "label": label,
        "program_path": str(program_path.resolve()),
        "problem_dir": str(problem_dir.resolve()),
        "restarts": restarts,
        "seed": seed,
        "best_restart": best["restart"],
        "best_seed": best["seed"],
        "optimization_success": best["success"],
        "optimization_message": best["message"],
        "best_params": best["params"],
        "train": metric_block(func, best_params, x_train, y_train),
        "test": metric_block(func, best_params, x_test, y_test),
        "ood": metric_block(func, best_params, x_ood, y_ood),
        "restart_history": restart_history,
    }
    return result


def main() -> None:
    args = parse_args()
    program_path = Path(args.program).resolve()
    problem_dir = Path(args.problem_dir).resolve()
    label = args.label or program_path.stem

    result = evaluate_program(
        program_path=program_path,
        problem_dir=problem_dir,
        label=label,
        restarts=args.restarts,
        seed=args.seed,
        param_dim=args.param_dim,
    )

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
