#!/usr/bin/env python3
"""Batch controller-only equivalence checks for completed public pilot results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .evaluation_curves import DEFAULT_BUNDLE, collect_completed_curves
    from .ground_truth_equivalence import (
        DEFAULT_REGISTRY,
        load_registry,
        selected_equation,
        verify_equivalence,
    )
except ImportError:
    from evaluation_curves import DEFAULT_BUNDLE, collect_completed_curves
    from ground_truth_equivalence import (
        DEFAULT_REGISTRY,
        load_registry,
        selected_equation,
        verify_equivalence,
    )


DEFAULT_OUTPUT = (
    DEFAULT_BUNDLE / "offline_analysis" / "ground_truth_equivalence.json"
)


def collect_completed_equivalence(
    bundle: Path = DEFAULT_BUNDLE,
    registry_path: Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    registered = registry.get("tasks", {})
    curves = collect_completed_curves(bundle)
    records: list[dict[str, Any]] = []
    for arm_record in curves["records"]:
        task_id = arm_record["task_id"]
        if task_id not in registered:
            records.append(
                {
                    "task_id": task_id,
                    "repeat_id": arm_record["repeat_id"],
                    "arm_id": arm_record["arm_id"],
                    "applicable": None,
                    "reason": "ground_truth_task_not_registered",
                    "checkpoints": [],
                }
            )
            continue
        checkpoints: list[dict[str, Any]] = []
        for point in arm_record["curve"]:
            result_path = bundle / point["result_file"]
            equation = selected_equation(result_path)
            verification = verify_equivalence(
                task_id=task_id,
                candidate_text=equation,
                registry_path=registry_path,
            )
            checkpoints.append(
                {
                    "checkpoint": point["checkpoint"],
                    "cumulative_requested_evaluations": point[
                        "cumulative_requested_evaluations"
                    ],
                    "result_file": point["result_file"],
                    "verification": verification,
                }
            )
        applicable = bool(checkpoints[0]["verification"]["applicable"])
        decisions = [
            item["verification"]["equivalent_ground_truth"] for item in checkpoints
        ]
        records.append(
            {
                "task_id": task_id,
                "repeat_id": arm_record["repeat_id"],
                "arm_id": arm_record["arm_id"],
                "applicable": applicable,
                "checkpoints": checkpoints,
                "ever_equivalent_at_observed_boundary": (
                    any(value is True for value in decisions) if applicable else None
                ),
                "last_observed_boundary_equivalent": (
                    decisions[-1] if applicable else None
                ),
            }
        )
    return {
        "schema_version": 1,
        "analysis_status": "post_hoc_pilot_analysis_not_preregistered",
        "source": "completed_public_pilot_result_boundaries",
        "controller_only": True,
        "private_ood_accessed": False,
        "selection_warning": (
            "Both ever-observed and last-observed decisions are reported. Neither is "
            "silently substituted for a separately governed terminal incumbent."
        ),
        "claim_limit": (
            "The registry, challenge grid, and tolerances were added after the first "
            "pilot outcomes and cannot support a retrospective preregistration claim."
        ),
        "records": records,
        "skipped_runs": curves["skipped"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = collect_completed_equivalence(
        bundle=args.bundle.resolve(), registry_path=args.registry.resolve()
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(
        {
            "output": str(output),
            "completed_arm_records": len(report["records"]),
            "skipped_arm_records": len(report["skipped_runs"]),
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
