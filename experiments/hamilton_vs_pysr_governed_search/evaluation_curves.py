#!/usr/bin/env python3
"""Build episode-boundary evaluation curves without invoking PySR or an LLM.

The legacy pilot records requested evaluation reservations at round/episode boundaries,
not engine-measured per-evaluation timestamps. Every point here is therefore a completed
boundary observation, and no finer-grained claim is made.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_BUNDLE = HERE / "launch_bundle"
DEFAULT_OUTPUT = DEFAULT_BUNDLE / "offline_analysis" / "evaluation_curves.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _finite_nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def checkpoint_validation_nrmse(result: dict[str, Any]) -> dict[str, float]:
    """Return selected and best-observed candidate validation NRMSE."""
    if result.get("status") != "completed":
        raise ValueError("result is not completed")
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("completed result has no candidates")

    usable: list[tuple[str, str, float]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        ranking = candidate.get("ranking", {})
        if not isinstance(ranking, dict) or "validation_nrmse" not in ranking:
            continue
        try:
            score = _finite_nonnegative(
                ranking["validation_nrmse"],
                f"candidate {index} validation_nrmse",
            )
        except ValueError:
            continue
        usable.append(
            (
                str(candidate.get("equation", "")),
                str(candidate.get("simplified_equation", "")),
                score,
            )
        )
    if not usable:
        raise ValueError("completed result has no finite validation NRMSE")

    selected = result.get("selected", {})
    selected_raw_equation = str(selected.get("equation", ""))
    selected_equation = str(selected.get("simplified_equation", ""))
    selected_matches = [
        score
        for raw_equation, equation, score in usable
        if raw_equation == selected_raw_equation and equation == selected_equation
    ]
    if not selected_matches:
        selected_matches = [
            score for _, equation, score in usable if equation == selected_equation
        ]
    if len(selected_matches) != 1:
        raise ValueError("selected equation does not identify exactly one candidate")
    return {
        "selected_validation_nrmse": selected_matches[0],
        "best_candidate_validation_nrmse": min(score for _, _, score in usable),
    }


def build_boundary_curve(
    checkpoints: Iterable[dict[str, Any]],
    total_evaluations: int,
) -> list[dict[str, Any]]:
    """Convert per-episode scores to a cumulative best-so-far boundary curve."""
    if isinstance(total_evaluations, bool) or total_evaluations <= 0:
        raise ValueError("total_evaluations must be positive")
    cumulative = 0
    best = math.inf
    curve: list[dict[str, Any]] = []
    for sequence, checkpoint in enumerate(checkpoints, start=1):
        requested = checkpoint.get("requested_evaluations")
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise ValueError(f"checkpoint {sequence} has invalid requested_evaluations")
        score = _finite_nonnegative(
            checkpoint.get("best_candidate_validation_nrmse"),
            f"checkpoint {sequence} best_candidate_validation_nrmse",
        )
        cumulative += requested
        if cumulative > total_evaluations:
            raise ValueError("checkpoint budgets exceed total_evaluations")
        best = min(best, score)
        curve.append(
            {
                "checkpoint": sequence,
                "requested_evaluations": requested,
                "cumulative_requested_evaluations": cumulative,
                "normalized_evaluation_fraction": cumulative / total_evaluations,
                "checkpoint_best_candidate_validation_nrmse": score,
                "best_so_far_validation_nrmse": best,
                "selected_validation_nrmse": _finite_nonnegative(
                    checkpoint.get("selected_validation_nrmse"),
                    f"checkpoint {sequence} selected_validation_nrmse",
                ),
                "result_file": str(checkpoint.get("result_file", "")),
            }
        )
    if not curve or cumulative != total_evaluations:
        raise ValueError("checkpoints must cover exactly total_evaluations")
    return curve


def endpoint_step_auc(curve: list[dict[str, Any]]) -> float | None:
    """Return budget-weighted endpoint-step AUC, requiring two observations."""
    if len(curve) < 2:
        return None
    area = 0.0
    previous_fraction = 0.0
    for point in curve:
        fraction = float(point["normalized_evaluation_fraction"])
        if fraction <= previous_fraction or fraction > 1.0 + 1e-12:
            raise ValueError("curve fractions must increase and end at one")
        area += (fraction - previous_fraction) * float(
            point["best_so_far_validation_nrmse"]
        )
        previous_fraction = fraction
    if not math.isclose(previous_fraction, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("curve must end at normalized evaluation fraction one")
    return area


def _result_checkpoint(path: Path, requested: int, root: Path) -> dict[str, Any]:
    metrics = checkpoint_validation_nrmse(_read_json(path))
    return {
        **metrics,
        "requested_evaluations": requested,
        "result_file": path.resolve().relative_to(root.resolve()).as_posix(),
    }


def _job_checkpoints(
    job: dict[str, Any], bundle: Path, trace: dict[str, Any]
) -> list[dict[str, Any]]:
    workspace_value = Path(str(job["workspace"]))
    local_workspace = REPO / workspace_value
    if local_workspace.is_dir():
        workspace = local_workspace
    else:
        # Launch bundles are intentionally Git-ignored and may be handed over outside the
        # checkout that generated run_matrix.json.  Resolve the suffix after the bundle
        # directory instead of coupling offline analysis to this module's repository.
        parts = workspace_value.parts
        try:
            bundle_index = parts.index("launch_bundle")
        except ValueError as exc:
            raise ValueError(
                f"workspace is neither local nor launch-bundle relative: {workspace_value}"
            ) from exc
        workspace = bundle.joinpath(*parts[bundle_index + 1 :])
    arm = job["arm"]
    attempts = trace["attempts"]
    if arm == "governed_hamilton":
        ledger = _read_json(workspace / ".hamilton_evaluation_ledger.json")
        ledger_attempts = ledger.get("attempts", [])
        if len(ledger_attempts) != len(attempts):
            raise ValueError("Hamilton ledger and paired trace lengths differ")
        return [
            _result_checkpoint(
                workspace / str(ledger_item["result_file"]),
                int(trace_item["requested_evals"]),
                bundle,
            )
            for ledger_item, trace_item in zip(ledger_attempts, attempts)
        ]
    if arm == "fixed_schedule_pysr":
        return [
            _result_checkpoint(
                workspace / "results" / f"episode_{index}.json",
                int(item["requested_evals"]),
                bundle,
            )
            for index, item in enumerate(attempts, start=1)
        ]
    if arm == "ordinary_pysr":
        total = int(trace["actual_total_evals"])
        return [_result_checkpoint(workspace / "results" / "result.json", total, bundle)]
    raise ValueError(f"unknown arm: {arm}")


def collect_completed_curves(bundle: Path = DEFAULT_BUNDLE) -> dict[str, Any]:
    """Collect every fully materialized task/repeat/arm in a launch bundle."""
    matrix = _read_json(bundle / "run_matrix.json")
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for job in matrix.get("jobs", []):
        task_id = str(job["task_id"])
        repeat_id = str(job["repeat_id"])
        arm = str(job["arm"])
        trace_path = bundle / "paired_budget_traces" / task_id / f"{repeat_id}.json"
        if not trace_path.is_file():
            skipped.append(
                {"task_id": task_id, "repeat_id": repeat_id, "arm_id": arm,
                 "reason": "paired_budget_trace_missing"}
            )
            continue
        trace = _read_json(trace_path)
        try:
            checkpoints = _job_checkpoints(job, bundle, trace)
            curve = build_boundary_curve(checkpoints, int(trace["actual_total_evals"]))
        except FileNotFoundError:
            skipped.append(
                {"task_id": task_id, "repeat_id": repeat_id, "arm_id": arm,
                 "reason": "result_missing"}
            )
            continue
        auc = endpoint_step_auc(curve)
        records.append(
            {
                "task_id": task_id,
                "repeat_id": repeat_id,
                "arm_id": arm,
                "total_requested_evaluations": int(trace["actual_total_evals"]),
                "measurement_resolution": "completed_episode_boundaries",
                "checkpoint_count": len(curve),
                "curve": curve,
                "anytime_best_validation_auc": auc,
                "anytime_auc_eligible": auc is not None,
                "ineligibility_reason": (
                    None if auc is not None else "fewer_than_two_observed_boundaries"
                ),
            }
        )
    return {
        "schema_version": 1,
        "analysis_status": "post_hoc_legacy_reconstruction_not_preregistered",
        "source": "offline_public_pilot_results",
        "uses_engine_measured_evaluations": False,
        "budget_axis": "cumulative_requested_evaluations",
        "metric": "best_observed_candidate_validation_nrmse",
        "interpolation": "episode_endpoint_step_weighted_by_requested_budget",
        "warning": (
            "Legacy results contain completed-boundary reservations, not per-evaluation "
            "timestamps. Ordinary one-shot runs have no valid anytime AUC."
        ),
        "records": records,
        "skipped": skipped,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = collect_completed_curves(args.bundle.resolve())
    _write_json(args.output.resolve(), report)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
