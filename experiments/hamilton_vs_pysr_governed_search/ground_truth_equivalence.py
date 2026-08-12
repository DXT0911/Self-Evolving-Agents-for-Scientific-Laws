#!/usr/bin/env python3
"""Controller-only symbolic and numerical ground-truth equivalence checks."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import re
from pathlib import Path
from typing import Any

import numpy as np
import sympy
import yaml


HERE = Path(__file__).resolve().parent
DEFAULT_REGISTRY = HERE / "controller_ground_truth.yaml"
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
SAFE_CHARS = re.compile(r"^[A-Za-z0-9_+\-*/().,\s]+$")
SAFE_FUNCTIONS = {
    "sin": sympy.sin,
    "cos": sympy.cos,
    "exp": sympy.exp,
    "tanh": sympy.tanh,
    "sqrt": sympy.sqrt,
    "Abs": sympy.Abs,
    "abs": sympy.Abs,
    "pi": sympy.pi,
    "E": sympy.E,
}


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        raise ValueError("unsupported ground-truth registry")
    if registry.get("visibility") != "controller_only_never_copy_to_agent_workspace":
        raise ValueError("ground-truth registry must be controller-only")
    if registry.get("status") not in {
        "post_hoc_pilot_analysis_only",
        "frozen_before_formal_execution",
    }:
        raise ValueError("ground-truth registry must declare its analysis status")
    return registry


def parse_expression(text: str, variables: list[str]) -> sympy.Expr:
    if not isinstance(text, str) or not text.strip() or not SAFE_CHARS.fullmatch(text):
        raise ValueError("expression contains unsupported characters")
    allowed_names = set(variables) | set(SAFE_FUNCTIONS)
    unknown = set(IDENTIFIER.findall(text)) - allowed_names
    if unknown:
        raise ValueError(f"expression contains unknown identifiers: {sorted(unknown)}")
    symbols = {name: sympy.Symbol(name, real=True) for name in variables}
    local_dict = {**SAFE_FUNCTIONS, **symbols}
    global_dict = {
        "__builtins__": {},
        "Integer": sympy.Integer,
        "Float": sympy.Float,
        "Rational": sympy.Rational,
    }
    expression = sympy.parse_expr(
        text,
        local_dict=local_dict,
        global_dict=global_dict,
        evaluate=True,
    )
    if not isinstance(expression, sympy.Expr):
        raise ValueError("expression did not parse to a scalar SymPy expression")
    if not expression.free_symbols <= set(symbols.values()):
        raise ValueError("expression contains undeclared symbols")
    return expression


def _challenge_points(task: dict[str, Any]) -> np.ndarray:
    variables = list(task["variables"])
    challenge = task["challenge"]
    domains = challenge["domains"]
    bounds: list[tuple[float, float]] = []
    for variable in variables:
        low, high = map(float, domains[variable])
        if not math.isfinite(low) or not math.isfinite(high) or low >= high:
            raise ValueError(f"invalid challenge domain for {variable}")
        bounds.append((low, high))
    anchors = list(
        itertools.product(*[(low, (low + high) / 2, high) for low, high in bounds])
    )
    generator = random.Random(int(challenge["seed"]))
    random_points = [
        [generator.uniform(low, high) for low, high in bounds]
        for _ in range(int(challenge["random_points"]))
    ]
    return np.asarray([*anchors, *random_points], dtype=float)


def _evaluate(
    expression: sympy.Expr,
    symbols: list[sympy.Symbol],
    points: np.ndarray,
) -> np.ndarray:
    function = sympy.lambdify(symbols, expression, modules="numpy")
    with np.errstate(all="ignore"):
        values = np.asarray(function(*[points[:, index] for index in range(len(symbols))]))
    if values.ndim == 0:
        values = np.full(points.shape[0], values.item())
    values = np.asarray(values, dtype=np.complex128).reshape(-1)
    if values.size != points.shape[0]:
        raise ValueError("expression returned an unexpected result shape")
    if np.any(~np.isfinite(values)) or np.max(np.abs(values.imag)) > 1e-12:
        raise ValueError("expression is non-finite or complex on the challenge grid")
    return values.real.astype(float)


def verify_equivalence(
    task_id: str,
    candidate_text: str,
    registry_path: Path = DEFAULT_REGISTRY,
    normalized_rmse_tolerance: float = 1e-8,
    normalized_max_error_tolerance: float = 1e-7,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    task = registry.get("tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"ground truth task is not registered: {task_id}")
    if task.get("applicable") is False:
        return {
            "schema_version": 1,
            "task_id": task_id,
            "applicable": False,
            "reason": str(task.get("reason", "not_applicable")),
            "equivalent_ground_truth": None,
        }

    variables = [str(value) for value in task["variables"]]
    candidate = parse_expression(candidate_text, variables)
    truth = parse_expression(str(task["expression"]), variables)
    difference = sympy.cancel(sympy.together(candidate - truth))
    algebraic = bool(difference == 0 or sympy.simplify(difference) == 0)

    points = _challenge_points(task)
    symbols = [sympy.Symbol(name, real=True) for name in variables]
    numerical_error: str | None = None
    normalized_rmse: float | None = None
    normalized_max_error: float | None = None
    numeric = False
    try:
        observed = _evaluate(candidate, symbols, points)
        expected = _evaluate(truth, symbols, points)
        error = observed - expected
        scale = max(float(np.sqrt(np.mean(expected**2))), 1.0)
        normalized_rmse = float(np.sqrt(np.mean(error**2)) / scale)
        normalized_max_error = float(np.max(np.abs(error)) / scale)
        numeric = (
            normalized_rmse <= normalized_rmse_tolerance
            and normalized_max_error <= normalized_max_error_tolerance
        )
    except (ValueError, TypeError, OverflowError) as exc:
        numerical_error = f"{type(exc).__name__}: {exc}"

    candidate_variables = sorted(str(symbol) for symbol in candidate.free_symbols)
    truth_variables = sorted(str(symbol) for symbol in truth.free_symbols)
    candidate_set = set(candidate_variables)
    truth_set = set(truth_variables)
    precision = (
        len(candidate_set & truth_set) / len(candidate_set)
        if candidate_set else float(not truth_set)
    )
    recall = (
        len(candidate_set & truth_set) / len(truth_set)
        if truth_set else float(not candidate_set)
    )
    return {
        "schema_version": 1,
        "task_id": task_id,
        "applicable": True,
        "candidate_equation": str(candidate),
        "algebraic_equivalent": algebraic,
        "challenge_grid": {
            "controller_only": True,
            "point_count": int(points.shape[0]),
            "normalized_rmse": normalized_rmse,
            "normalized_max_error": normalized_max_error,
            "normalized_rmse_tolerance": normalized_rmse_tolerance,
            "normalized_max_error_tolerance": normalized_max_error_tolerance,
            "numerically_equivalent": numeric,
            "evaluation_error": numerical_error,
        },
        "variable_selection": {
            "candidate": candidate_variables,
            "ground_truth": truth_variables,
            "precision": precision,
            "recall": recall,
        },
        "equivalent_ground_truth": algebraic or numeric,
    }


def selected_equation(result_path: Path) -> str:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "completed":
        raise ValueError("result is not completed")
    equation = result.get("selected", {}).get("simplified_equation")
    if not isinstance(equation, str) or not equation:
        raise ValueError("result has no selected simplified equation")
    return equation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--equation")
    source.add_argument("--result", type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    equation = (
        args.equation if args.equation is not None else selected_equation(args.result)
    )
    print(
        json.dumps(
            verify_equivalence(task_id=args.task_id, candidate_text=equation,
                               registry_path=args.registry.resolve()),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
