"""Deterministic term-level diagnostics for frozen symbolic expressions.

This module performs no symbolic search.  It decomposes an already selected
expression into additive terms, refits linear weights, and measures the held-out
NRMSE increase caused by removing each term.  Refitting avoids attributing a
large effect to a term merely because the remaining coefficients were frozen.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


def _prediction(expression: Any, features: list[str], frame: Any) -> np.ndarray:
    import sympy

    symbols = [sympy.Symbol(name) for name in features]
    function = sympy.lambdify(symbols, expression, modules="numpy")
    columns = [frame[name].to_numpy(dtype=float) for name in features]
    values = np.asarray(function(*columns), dtype=float)
    if values.ndim == 0:
        values = np.full(len(frame), float(values), dtype=float)
    values = np.ravel(values)
    if len(values) != len(frame) or not np.all(np.isfinite(values)):
        raise ValueError("term produced non-finite predictions or the wrong shape")
    return values


def _fit_and_nrmse(
    train_matrix: np.ndarray,
    validation_matrix: np.ndarray,
    y_train: np.ndarray,
    y_validation: np.ndarray,
) -> tuple[np.ndarray, float]:
    design_train = np.column_stack([np.ones(len(train_matrix)), train_matrix])
    design_validation = np.column_stack(
        [np.ones(len(validation_matrix)), validation_matrix]
    )
    coefficients, *_ = np.linalg.lstsq(design_train, y_train, rcond=None)
    prediction = design_validation @ coefficients
    scale = max(float(np.std(y_validation)), np.finfo(float).eps)
    nrmse = math.sqrt(float(np.mean((y_validation - prediction) ** 2))) / scale
    return coefficients, float(nrmse)


def additive_term_influence(
    expression: str,
    *,
    train: Any,
    validation: Any,
    feature_columns: Iterable[str],
    target_column: str,
    max_terms: int = 12,
) -> dict[str, Any]:
    """Compute leave-one-term-out validation influence with coefficient refits."""
    import sympy

    if max_terms <= 0:
        raise ValueError("max_terms must be positive")
    features = list(feature_columns)
    parsed = sympy.expand(sympy.sympify(expression))
    terms = list(sympy.Add.make_args(parsed))
    if len(terms) > max_terms:
        return {
            "enabled": True,
            "status": "skipped",
            "reason": "expression_exceeds_max_terms",
            "term_count": len(terms),
            "max_terms": int(max_terms),
        }

    train_columns = [_prediction(term, features, train) for term in terms]
    validation_columns = [_prediction(term, features, validation) for term in terms]
    train_matrix = np.column_stack(train_columns)
    validation_matrix = np.column_stack(validation_columns)
    y_train = train[target_column].to_numpy(dtype=float)
    y_validation = validation[target_column].to_numpy(dtype=float)
    coefficients, full_nrmse = _fit_and_nrmse(
        train_matrix,
        validation_matrix,
        y_train,
        y_validation,
    )

    records: list[dict[str, Any]] = []
    for index, term in enumerate(terms):
        keep = [position for position in range(len(terms)) if position != index]
        if keep:
            _, ablated_nrmse = _fit_and_nrmse(
                train_matrix[:, keep],
                validation_matrix[:, keep],
                y_train,
                y_validation,
            )
        else:
            baseline = np.full(len(y_validation), float(np.mean(y_train)))
            scale = max(float(np.std(y_validation)), np.finfo(float).eps)
            ablated_nrmse = (
                math.sqrt(float(np.mean((y_validation - baseline) ** 2))) / scale
            )
        records.append(
            {
                "term": str(term),
                "refit_weight": float(coefficients[index + 1]),
                "validation_nrmse_without_term": float(ablated_nrmse),
                "validation_nrmse_delta": float(ablated_nrmse - full_nrmse),
            }
        )

    records.sort(key=lambda item: item["validation_nrmse_delta"], reverse=True)
    return {
        "enabled": True,
        "status": "completed",
        "method": "additive_leave_one_term_out_with_linear_refit",
        "selection_boundary": (
            "Diagnostic credit is conditional on this additive decomposition; "
            "it is not proof of a unique physical mechanism."
        ),
        "term_count": len(terms),
        "full_refit_validation_nrmse": float(full_nrmse),
        "intercept": float(coefficients[0]),
        "terms": records,
    }


def diagnose_frozen_result(result_path: Path, workspace: Path) -> dict[str, Any]:
    """Reconstruct the public train/validation split recorded by a result."""
    resolved_workspace = workspace.resolve()
    resolved_result = result_path.resolve()
    resolved_result.relative_to(resolved_workspace)
    result = json.loads(resolved_result.read_text(encoding="utf-8"))
    config = result.get("config", {})
    data_config = config.get("data", {})
    train_path = (resolved_workspace / data_config["train_file"]).resolve()
    train_path.relative_to(resolved_workspace)
    frame = pd.read_csv(train_path)
    max_rows = data_config.get("max_rows")
    if max_rows is not None:
        frame = frame.iloc[: int(max_rows)].copy()
    train_rows = int(result.get("data", {}).get("split", {}).get("train_rows", 0))
    validation_rows = int(
        result.get("data", {}).get("split", {}).get("validation_rows", 0)
    )
    if train_rows <= 0 or validation_rows <= 0 or train_rows + validation_rows > len(frame):
        raise ValueError("result does not contain a reproducible contiguous split")
    train = frame.iloc[:train_rows]
    validation = frame.iloc[train_rows : train_rows + validation_rows]
    return {
        "schema_version": 1,
        "mode": "offline_frozen_result_diagnostic",
        "result_file": result_path.as_posix(),
        "result_status": result.get("status"),
        "diagnostic": additive_term_influence(
            result["selected"]["simplified_equation"],
            train=train,
            validation=validation,
            feature_columns=data_config["feature_columns"],
            target_column=data_config["target_column"],
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", nargs="+", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = [diagnose_frozen_result(path, args.workspace) for path in args.result]
    payload = {
        "schema_version": 1,
        "mode": "offline_frozen_result_diagnostics",
        "scientific_boundary": (
            "Term influence is conditional on additive decomposition and the frozen "
            "public validation split; it does not identify a unique physical cause."
        ),
        "records": records,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
