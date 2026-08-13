"""Controller-only tiered OOD evaluation for frozen Hamilton candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class OODProtocolError(ValueError):
    """Raised when a candidate or OOD access violates the evaluation protocol."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_object(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OODProtocolError(f"invalid {name}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OODProtocolError(f"{name} must be a JSON object: {path}")
    return value


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def resolve_inside(root: Path, raw: str, name: str) -> Path:
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise OODProtocolError(f"{name} must stay inside {root}: {raw}") from exc
    return candidate


def infer_condition_from_train_file(train_file: str) -> str:
    match = re.search(r"U(\d{3})_train\.csv$", str(train_file))
    if not match:
        raise OODProtocolError(
            f"cannot infer operating condition from training file: {train_file}"
        )
    return f"{int(match.group(1)) / 100:.2f}"


def _model_from_result(workspace: Path, result_path: Path) -> dict[str, Any]:
    result = read_object(result_path, "experiment result")
    if result.get("status") != "completed":
        raise OODProtocolError(f"cannot freeze incomplete result: {result_path}")
    config = result.get("config", {})
    data = config.get("data", {})
    features = data.get("feature_columns")
    if not isinstance(features, list) or not features:
        raise OODProtocolError("result has no feature_columns")
    equation = result.get("selected", {}).get("simplified_equation")
    if not isinstance(equation, str) or not equation.strip():
        raise OODProtocolError("result has no selected original-unit equation")
    short_ode = config.get("verification", {}).get("short_ode", {})
    relative = str(result_path.resolve().relative_to(workspace.resolve())).replace("\\", "/")
    training_conditions = result.get("data", {}).get("training_conditions")
    condition: str | None = None
    try:
        condition = infer_condition_from_train_file(data.get("train_file", ""))
    except OODProtocolError:
        if "U" not in features:
            raise
    if training_conditions is None:
        if condition is None:
            raise OODProtocolError(
                "global result must record data.training_conditions before freezing"
            )
        training_conditions = [condition]
    if not isinstance(training_conditions, list) or not all(
        isinstance(item, (str, int, float)) for item in training_conditions
    ):
        raise OODProtocolError("data.training_conditions must be a list when present")
    return {
        "source_result": relative,
        "source_sha256": sha256_file(result_path),
        "equation": equation,
        "feature_columns": features,
        "target_column": data.get("target_column"),
        "time_column": data.get("time_column"),
        "position_column": short_ode.get("position_column", "x"),
        "velocity_column": short_ode.get("velocity_column", "v"),
        "training_conditions": [f"{float(item):.2f}" for item in training_conditions],
        "condition": condition,
    }


def freeze_candidate_bundle(
    workspace: Path,
    result_files: list[str],
    output_path: Path,
) -> dict[str, Any]:
    if not result_files:
        raise OODProtocolError("at least one completed result is required")
    models = [
        _model_from_result(
            workspace,
            resolve_inside(workspace, raw, "result_file"),
        )
        for raw in result_files
    ]
    exact_models: dict[str, dict[str, Any]] = {}
    global_models = []
    for model in models:
        if "U" in model["feature_columns"]:
            global_models.append(model)
        else:
            condition = model["condition"]
            if condition is None:
                raise OODProtocolError("exact-condition model has no operating condition")
            if condition in exact_models:
                raise OODProtocolError(f"multiple frozen models for condition {condition}")
            exact_models[condition] = model
    if len(global_models) > 1:
        raise OODProtocolError("a frozen bundle may contain at most one global U model")
    contents = {
        "schema_version": 1,
        "status": "frozen",
        "created_at": utc_now(),
        "exact_condition_models": exact_models,
        "global_model": global_models[0] if global_models else None,
    }
    contents["freeze_id"] = canonical_hash(
        {
            "exact_condition_models": exact_models,
            "global_model": contents["global_model"],
        }
    )
    write_object(output_path, contents)
    return contents


def load_frozen_bundle(path: Path) -> dict[str, Any]:
    bundle = read_object(path, "frozen candidate bundle")
    if bundle.get("schema_version") != 1 or bundle.get("status") != "frozen":
        raise OODProtocolError("candidate bundle is not frozen schema version 1")
    expected = canonical_hash(
        {
            "exact_condition_models": bundle.get("exact_condition_models", {}),
            "global_model": bundle.get("global_model"),
        }
    )
    if bundle.get("freeze_id") != expected:
        raise OODProtocolError("frozen candidate hash mismatch")
    return bundle


def verify_frozen_sources(bundle: dict[str, Any], workspace: Path) -> None:
    models = list(bundle.get("exact_condition_models", {}).values())
    global_model = bundle.get("global_model")
    if isinstance(global_model, dict):
        models.append(global_model)
    for model in models:
        source = resolve_inside(workspace, model["source_result"], "source_result")
        if not source.is_file() or sha256_file(source) != model.get("source_sha256"):
            raise OODProtocolError(
                f"frozen source result changed or disappeared: {model['source_result']}"
            )


class OODAccessLedger:
    """Persist and enforce access budgets outside the agent workspace."""

    def __init__(self, path: Path, tier_policy: dict[str, Any]):
        self.path = path
        self.tier_policy = tier_policy
        self.payload = (
            read_object(path, "OOD access ledger")
            if path.is_file()
            else {"schema_version": 1, "accesses": []}
        )

    def begin(self, tier: str, freeze_id: str) -> int:
        if tier not in self.tier_policy:
            raise OODProtocolError(f"unknown OOD tier: {tier}")
        policy = self.tier_policy[tier]
        accesses = self.payload["accesses"]
        completed_or_started = [
            item for item in accesses if item.get("tier") == tier
        ]
        maximum = int(policy.get("max_total_evaluations", 0))
        if maximum <= 0:
            raise OODProtocolError(f"{tier} is not available for evaluation")
        if len(completed_or_started) >= maximum:
            raise OODProtocolError(
                f"{tier} OOD access budget exhausted: {len(completed_or_started)}/{maximum}"
            )
        if any(
            item.get("tier") == tier and item.get("freeze_id") == freeze_id
            for item in accesses
        ):
            raise OODProtocolError(f"{tier} already accessed for frozen candidate {freeze_id}")
        entry = {
            "tier": tier,
            "freeze_id": freeze_id,
            "started_at": utc_now(),
            "status": "started",
        }
        accesses.append(entry)
        write_object(self.path, self.payload)
        return len(accesses) - 1

    def finish(
        self,
        index: int,
        status: str,
        result_file: str | None = None,
        result_sha256: str | None = None,
    ) -> None:
        entry = self.payload["accesses"][index]
        entry["status"] = status
        entry["completed_at"] = utc_now()
        if result_file:
            entry["result_file"] = result_file
        if result_sha256:
            entry["result_sha256"] = result_sha256
        write_object(self.path, self.payload)


def regression_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    residual = observed - predicted
    mse = float(np.mean(residual**2))
    variance = float(np.var(observed))
    scale = float(np.std(observed))
    return {
        "mse": mse,
        "rmse": math.sqrt(mse),
        "mae": float(np.mean(np.abs(residual))),
        "nrmse": math.sqrt(mse) / scale if scale > np.finfo(float).eps else None,
        "r2": 1.0 - mse / variance if variance > np.finfo(float).eps else None,
    }


def prepare_frame(
    path: Path,
    model: dict[str, Any],
    condition: dict[str, Any],
) -> pd.DataFrame:
    required = {
        model["time_column"],
        model["target_column"],
        model["position_column"],
        model["velocity_column"],
    }
    required.update(name for name in model["feature_columns"] if name != "U")
    frame = pd.read_csv(path, usecols=sorted(required))
    for name in required:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    if frame[list(required)].isna().any().any():
        raise OODProtocolError(f"OOD dataset contains missing or non-numeric values: {path}")
    if "U" in model["feature_columns"]:
        frame["U"] = float(condition["U"])
    if not np.isfinite(frame[[*required, *(["U"] if "U" in frame else [])]].to_numpy()).all():
        raise OODProtocolError(f"OOD dataset contains non-finite values: {path}")
    if not frame[model["time_column"]].is_monotonic_increasing:
        raise OODProtocolError(f"OOD time column is not monotonic: {path}")
    return frame


def pointwise_evaluation(
    model: dict[str, Any],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    import sympy

    symbols = [sympy.Symbol(name) for name in model["feature_columns"]]
    expression = sympy.sympify(model["equation"])
    function = sympy.lambdify(symbols, expression, modules="numpy")
    values = [frame[name].to_numpy(dtype=float) for name in model["feature_columns"]]
    prediction = np.asarray(function(*values), dtype=float)
    if prediction.ndim == 0:
        prediction = np.full(len(frame), float(prediction))
    prediction = prediction.reshape(-1)
    if len(prediction) != len(frame) or not np.isfinite(prediction).all():
        raise OODProtocolError("frozen equation produced invalid pointwise predictions")
    observed = frame[model["target_column"]].to_numpy(dtype=float)
    return {
        "metrics": regression_metrics(observed, prediction),
        "prediction": prediction,
    }


def trajectory_evaluation(
    model: dict[str, Any],
    frame: pd.DataFrame,
    condition: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    from scipy.integrate import solve_ivp
    import sympy

    features = model["feature_columns"]
    position = model["position_column"]
    velocity = model["velocity_column"]
    allowed = {position, velocity, "U"}
    unsupported = set(features) - allowed
    if unsupported:
        return {
            "status": "not_applicable",
            "reason": f"trajectory evaluator has no fixed context for features: {sorted(unsupported)}",
        }
    expression = sympy.sympify(model["equation"])
    symbols = [sympy.Symbol(name) for name in features]
    acceleration = sympy.lambdify(symbols, expression, modules="numpy")
    order = {name: index for index, name in enumerate(features)}
    fixed = {"U": float(condition["U"])} if "U" in features else {}
    time_column = model["time_column"]
    t0 = float(frame.iloc[0][time_column])
    available_duration = float(frame.iloc[-1][time_column]) - t0
    requested_duration = float(settings.get("trajectory_duration", available_duration))
    duration = min(available_duration, requested_duration)
    points = min(int(settings.get("trajectory_points", 2000)), len(frame))
    if duration <= 0 or points < 2:
        return {"status": "failed", "reason": "insufficient trajectory duration"}
    state_limit = float(settings.get("state_limit", 1e6))

    def rhs(_time: float, state: np.ndarray) -> list[float]:
        if not np.isfinite(state).all() or np.max(np.abs(state)) > state_limit:
            raise FloatingPointError("OOD trajectory exceeded state limit")
        feature_values = [0.0] * len(features)
        feature_values[order[position]] = float(state[0])
        feature_values[order[velocity]] = float(state[1])
        for name, value in fixed.items():
            feature_values[order[name]] = value
        candidate = float(acceleration(*feature_values))
        if not math.isfinite(candidate) or abs(candidate) > state_limit**2:
            raise FloatingPointError("OOD acceleration became non-finite or unbounded")
        return [float(state[1]), candidate]

    evaluation_times = np.linspace(t0, t0 + duration, points)
    solution = solve_ivp(
        rhs,
        (t0, t0 + duration),
        [
            float(frame.iloc[0][position]),
            float(frame.iloc[0][velocity]),
        ],
        t_eval=evaluation_times,
        rtol=1e-6,
        atol=1e-8,
        max_step=duration / max(points - 1, 1),
    )
    record: dict[str, Any] = {
        "status": "completed" if solution.success else "failed",
        "success": bool(solution.success),
        "message": str(solution.message),
        "duration": duration,
        "points": int(len(solution.t)),
    }
    if not solution.success:
        return record
    observed_position = np.interp(
        solution.t,
        frame[time_column].to_numpy(dtype=float),
        frame[position].to_numpy(dtype=float),
    )
    residual = solution.y[0] - observed_position
    observed_scale = float(np.std(observed_position))
    tail_start = max(0, int(0.75 * len(solution.t)))
    predicted_tail = solution.y[0, tail_start:]
    observed_tail = observed_position[tail_start:]
    predicted_amplitude = 0.5 * float(np.max(predicted_tail) - np.min(predicted_tail))
    observed_amplitude = 0.5 * float(np.max(observed_tail) - np.min(observed_tail))
    record.update(
        {
            "position_rmse": float(math.sqrt(float(np.mean(residual**2)))),
            "position_nrmse": (
                float(math.sqrt(float(np.mean(residual**2))) / observed_scale)
                if observed_scale > np.finfo(float).eps
                else None
            ),
            "tail_amplitude": {
                "predicted": predicted_amplitude,
                "observed": observed_amplitude,
                "relative_error": (
                    abs(predicted_amplitude - observed_amplitude) / observed_amplitude
                    if observed_amplitude > np.finfo(float).eps
                    else None
                ),
            },
            "final_state": {
                "predicted": {
                    "position": float(solution.y[0, -1]),
                    "velocity": float(solution.y[1, -1]),
                },
                "observed": {
                    "position": float(observed_position[-1]),
                    "velocity": float(
                        np.interp(
                            solution.t[-1],
                            frame[time_column].to_numpy(dtype=float),
                            frame[velocity].to_numpy(dtype=float),
                        )
                    ),
                },
            },
        }
    )
    final_position_error = (
        record["final_state"]["predicted"]["position"]
        - record["final_state"]["observed"]["position"]
    )
    final_velocity_error = (
        record["final_state"]["predicted"]["velocity"]
        - record["final_state"]["observed"]["velocity"]
    )
    record["final_state"]["euclidean_error"] = float(
        math.hypot(final_position_error, final_velocity_error)
    )
    return record


def evaluate_dataset(
    model: dict[str, Any],
    dataset_path: Path,
    condition: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    frame = prepare_frame(dataset_path, model, condition)
    pointwise = pointwise_evaluation(model, frame)
    return {
        "condition": condition,
        "rows": len(frame),
        "pointwise": pointwise["metrics"],
        "trajectory": trajectory_evaluation(model, frame, condition, settings),
    }


def _global_model_for_tier(bundle: dict[str, Any], tier: str) -> dict[str, Any]:
    import sympy

    model = bundle.get("global_model")
    if not isinstance(model, dict):
        raise OODProtocolError(
            f"{tier} requires a frozen global equation with wind speed U as a feature"
        )
    if "U" not in model.get("feature_columns", []):
        raise OODProtocolError(f"{tier} global equation does not contain feature U")
    if sympy.Symbol("U") not in sympy.sympify(model.get("equation", "")).free_symbols:
        raise OODProtocolError(f"{tier} global equation does not explicitly depend on U")
    training_conditions = model.get("training_conditions", [])
    if tier == "tier2" and len(set(training_conditions)) < 2:
        raise OODProtocolError("tier2 requires a global model trained on at least two conditions")
    if tier == "tier3" and len(set(training_conditions)) < 3:
        raise OODProtocolError("tier3 requires a global model trained on at least three conditions")
    return model


def evaluate_tier(
    tier: str,
    bundle: dict[str, Any],
    manifest: dict[str, Any],
    workspace: Path,
    private_root: Path,
) -> dict[str, Any]:
    if tier == "tier0":
        return {
            "tier": tier,
            "status": "handled_by_discovery_runner",
            "description": "contiguous tail validation on an agent-visible training file",
        }
    settings = manifest["tier_policy"][tier]
    evaluations = []
    if tier == "tier1":
        exact_models = bundle.get("exact_condition_models", {})
        global_model = bundle.get("global_model")
        for condition_id, condition_spec in manifest["conditions"].items():
            model = exact_models.get(condition_id)
            if (
                model is None
                and isinstance(global_model, dict)
                and condition_id in global_model.get("training_conditions", [])
            ):
                model = global_model
            if model is None:
                continue
            dataset = resolve_inside(
                private_root,
                condition_spec["paired_initial_condition_file"],
                "paired_initial_condition_file",
            )
            evaluations.append(
                evaluate_dataset(
                    model,
                    dataset,
                    {"U": float(condition_id), "kind": "paired_initial_condition"},
                    settings,
                )
            )
        if not evaluations:
            raise OODProtocolError("tier1 found no frozen model with a paired private dataset")
    elif tier == "tier2":
        model = _global_model_for_tier(bundle, tier)
        training_conditions = set(model["training_conditions"])
        for condition_id, condition_spec in manifest["conditions"].items():
            if condition_id in training_conditions:
                continue
            dataset = resolve_inside(
                workspace,
                condition_spec["public_training_file"],
                "public_training_file",
            )
            evaluations.append(
                evaluate_dataset(
                    model,
                    dataset,
                    {"U": float(condition_id), "kind": "held_out_operating_condition"},
                    settings,
                )
            )
        if not evaluations:
            raise OODProtocolError("tier2 has no operating condition held out from model training")
    elif tier == "tier3":
        model = _global_model_for_tier(bundle, tier)
        for regime in manifest["regime_conditions"]:
            dataset = resolve_inside(
                private_root,
                regime["file"],
                "regime_file",
            )
            evaluations.append(
                evaluate_dataset(
                    model,
                    dataset,
                    {
                        "U": float(regime["U"]),
                        "kind": "external_regime",
                        "regime_id": regime["id"],
                    },
                    settings,
                )
            )
    else:
        raise OODProtocolError(f"unknown tier: {tier}")
    return {
        "schema_version": 1,
        "tier": tier,
        "status": "completed",
        "freeze_id": bundle["freeze_id"],
        "evaluated_at": utc_now(),
        "feedback_policy": settings["feedback_policy"],
        "evaluations": evaluations,
    }


def release_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Return aggregate metrics without private filenames, raw rows, or reference answers."""
    summaries = []
    for evaluation in result.get("evaluations", []):
        condition = evaluation.get("condition", {})
        public_condition = {
            key: condition[key]
            for key in ("U", "kind")
            if key in condition
        }
        summaries.append(
            {
                "condition": public_condition,
                "pointwise": evaluation.get("pointwise"),
                "trajectory": evaluation.get("trajectory"),
            }
        )
    return {
        "schema_version": 1,
        "tier": result.get("tier"),
        "status": result.get("status"),
        "freeze_id": result.get("freeze_id"),
        "feedback_policy": result.get("feedback_policy"),
        "evaluations": summaries,
        "warning": (
            "This is a one-shot final attestation. It must not be used to start another "
            "adaptive research round."
            if result.get("feedback_policy") == "final_only"
            else "This summary is holdout evidence. Reusing it for adaptation consumes the "
            "tier's feedback budget and prevents treating the same tier as a final unbiased test."
        ),
    }


def run_evaluation(
    tier: str,
    workspace: Path,
    private_root: Path,
    bundle_path: Path,
    output_path: Path,
    release_path: Path | None = None,
) -> dict[str, Any]:
    manifest = read_object(private_root / "benchmark_private.json", "private manifest")
    policy = manifest.get("tier_policy")
    if not isinstance(policy, dict):
        raise OODProtocolError("private manifest has no tier_policy")
    bundle = load_frozen_bundle(bundle_path)
    verify_frozen_sources(bundle, workspace)
    if tier == "tier0":
        result = evaluate_tier(tier, bundle, manifest, workspace, private_root)
        write_object(output_path, result)
        return result
    if release_path is not None and policy[tier]["feedback_policy"] == "final_only":
        raise OODProtocolError("tier3 summary cannot be released before finalization")
    try:
        output_path.resolve().relative_to(private_root.resolve())
    except ValueError as exc:
        raise OODProtocolError("full OOD result must remain inside the private root") from exc
    if release_path is not None:
        try:
            release_path.resolve().relative_to(workspace.resolve())
        except ValueError as exc:
            raise OODProtocolError(
                "released development summary must stay inside the agent workspace"
            ) from exc
    ledger = OODAccessLedger(private_root / "ood_access_ledger.json", policy)
    ledger_index = ledger.begin(tier, bundle["freeze_id"])
    try:
        result = evaluate_tier(tier, bundle, manifest, workspace, private_root)
        write_object(output_path, result)
        if release_path is not None:
            write_object(release_path, release_summary(result))
        ledger.finish(
            ledger_index,
            "completed",
            str(output_path.resolve()),
            sha256_file(output_path),
        )
        return result
    except Exception:
        ledger.finish(ledger_index, "failed")
        raise


def finalize_tier3(
    private_root: Path,
    result_path: Path,
    workspace: Path,
    output_path: Path,
) -> dict[str, Any]:
    try:
        result_path.resolve().relative_to(private_root.resolve())
    except ValueError as exc:
        raise OODProtocolError("tier3 result must come from the private root") from exc
    result = read_object(result_path, "tier3 result")
    if result.get("tier") != "tier3" or result.get("status") != "completed":
        raise OODProtocolError("only a completed tier3 result can be finalized")
    ledger = read_object(private_root / "ood_access_ledger.json", "OOD access ledger")
    normalized_result = str(result_path.resolve())
    matching = [
        entry
        for entry in ledger.get("accesses", [])
        if entry.get("tier") == "tier3"
        and entry.get("freeze_id") == result.get("freeze_id")
        and entry.get("status") == "completed"
        and entry.get("result_file") == normalized_result
        and entry.get("result_sha256") == sha256_file(result_path)
    ]
    if not matching:
        raise OODProtocolError("tier3 result has no matching completed private-ledger access")
    output_path = output_path.resolve()
    try:
        output_path.relative_to(workspace.resolve())
    except ValueError as exc:
        raise OODProtocolError("final attestation must be written inside the workspace") from exc
    if (workspace / ".hamilton_final_ood.lock").exists():
        raise OODProtocolError("workspace already has a finalized tier3 OOD attestation")
    attestation = release_summary(result)
    attestation.update(
        {
            "finalized_at": utc_now(),
            "no_further_adaptation_allowed": True,
            "attestation_sha256": sha256_file(result_path),
        }
    )
    write_object(output_path, attestation)
    write_object(
        workspace / ".hamilton_final_ood.lock",
        {
            "freeze_id": result["freeze_id"],
            "attestation_file": str(output_path.relative_to(workspace.resolve())).replace("\\", "/"),
            "finalized_at": attestation["finalized_at"],
        },
    )
    return attestation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--workspace", required=True)
    freeze.add_argument("--result", action="append", required=True)
    freeze.add_argument("--output", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--tier", choices=["tier0", "tier1", "tier2", "tier3"], required=True)
    evaluate.add_argument("--workspace", required=True)
    evaluate.add_argument("--private-root", required=True)
    evaluate.add_argument("--bundle", required=True)
    evaluate.add_argument("--output", required=True)
    evaluate.add_argument("--release-summary")
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--private-root", required=True)
    finalize.add_argument("--result", required=True)
    finalize.add_argument("--workspace", required=True)
    finalize.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "freeze":
        freeze_candidate_bundle(
            Path(args.workspace).resolve(),
            args.result,
            Path(args.output).resolve(),
        )
    elif args.command == "evaluate":
        run_evaluation(
            args.tier,
            Path(args.workspace).resolve(),
            Path(args.private_root).resolve(),
            Path(args.bundle).resolve(),
            Path(args.output).resolve(),
            Path(args.release_summary).resolve() if args.release_summary else None,
        )
    else:
        finalize_tier3(
            Path(args.private_root).resolve(),
            Path(args.result).resolve(),
            Path(args.workspace).resolve(),
            Path(args.output).resolve(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
