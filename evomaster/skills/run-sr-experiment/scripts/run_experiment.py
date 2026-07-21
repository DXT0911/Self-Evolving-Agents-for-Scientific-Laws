#!/usr/bin/env python3
"""Deterministic, configuration-driven symbolic-regression experiment runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class ConfigError(ValueError):
    """Raised when an experiment configuration violates the runner contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON config relative to the workspace.")
    parser.add_argument("--validate-only", action="store_true", help="Validate without running PySR.")
    return parser.parse_args()


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


def load_and_validate(config_path: Path, workspace: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON: {exc}") from exc

    if config.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
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

    budget_path = workspace / ".hamilton_budget.json"
    if budget_path.is_file():
        try:
            budget = json.loads(budget_path.read_text(encoding="utf-8"))
            total_limit = positive_int(budget.get("max_total_evals"), "budget.max_total_evals")
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid .hamilton_budget.json: {exc}") from exc
        consumed = consumed_search_evals(workspace, exclude_result=result_path)
        requested = int(search["max_evals"])
        if consumed + requested > total_limit:
            raise ConfigError(
                f"total PySR evaluation budget exceeded: consumed={consumed}, "
                f"requested={requested}, limit={total_limit}"
            )

    normalized = json.loads(json.dumps(config))
    normalized["data"]["max_rows"] = max_rows
    normalized["data"]["search_stride"] = search_stride
    normalized["data"]["standardize_search"] = standardize_search
    normalized["data"]["validation_fraction"] = float(validation_fraction)
    normalized["verification"]["candidate_ranking"] = ranking
    normalized["verification"]["residual_diagnostics"] = residual
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
            record["verification"] = {"short_ode": ode}

            validation_nrmse = validation_metrics["rmse"] / validation_scale
            trajectory_nrmse = (
                math.sqrt(float(ode["position_trajectory_mse"])) / position_scale
                if ode.get("status") == "completed" and "position_trajectory_mse" in ode
                else float(ranking.get("failure_penalty", 100.0))
            )
            complexity_normalized = record["complexity"] / search["maxsize"]
            weights = ranking.get(
                "weights",
                {"validation_nrmse": 1.0, "trajectory_nrmse": 0.0, "complexity": 0.0},
            )
            scientific_score = (
                float(weights["validation_nrmse"]) * validation_nrmse
                + float(weights["trajectory_nrmse"]) * trajectory_nrmse
                + float(weights["complexity"]) * complexity_normalized
            )
            record["ranking"] = {
                "validation_nrmse": validation_nrmse,
                "trajectory_nrmse": trajectory_nrmse,
                "complexity_normalized": complexity_normalized,
                "scientific_score": scientific_score,
            }
        except Exception as exc:
            record["evaluation_error"] = {"type": type(exc).__name__, "message": str(exc)}
            record["ranking"] = {"scientific_score": float(ranking.get("failure_penalty", 100.0))}
        records.append(record)

    return records


def run_experiment(
    config: dict[str, Any],
    paths: dict[str, Path],
    workspace: Path,
) -> dict[str, Any]:
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
    model = PySRRegressor(
        niterations=search["niterations"],
        max_evals=search["max_evals"],
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
        model_selection="best",
        verbosity=0,
        progress=False,
        output_directory=str(paths["run_directory"].parent),
        run_id=paths["run_directory"].name,
    )
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

    return {
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
    }


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
        result = run_experiment(config, paths, workspace)
        write_result(result_path, result)
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
        if result_path is not None:
            try:
                write_result(result_path, failure)
            except Exception:
                pass
        print("===SR_EXPERIMENT_SUMMARY_BEGIN===")
        print(json.dumps(compact_summary(failure, result_path), ensure_ascii=False))
        print("===SR_EXPERIMENT_SUMMARY_END===")
        if os.environ.get("SR_EXPERIMENT_DEBUG") == "1":
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
