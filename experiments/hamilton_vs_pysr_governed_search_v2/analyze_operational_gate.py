#!/usr/bin/env python3
"""Collect the four frozen v2 objectives from the completed operational gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.ground_truth_equivalence import (
    verify_equivalence,
)

DEFAULT_BUNDLE = HERE / "launch_bundle" / "operational_gate"
DEFAULT_OUTPUT = HERE / "public_evidence" / "operational_gate_v2"
TASKS = ("static_s02", "dynamic_d02")
ARMS = ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr", "governed_hamilton")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _result_paths(bundle: Path, arm: str, task: str) -> list[Path]:
    base = bundle / arm / task / "repeat_1"
    if arm == "governed_hamilton":
        return sorted((base / "workspaces/task_0/history").glob("round*/results/result.json"))
    workspace = base / "workspace"
    if arm == "ordinary_pysr":
        return [workspace / "results/result.json"]
    return sorted((workspace / "results").glob("episode_*.json"))


def _selected_candidate(result: dict[str, Any]) -> dict[str, Any]:
    selected = result["selected"]
    for candidate in result["candidates"]:
        if candidate.get("simplified_equation") == selected.get("simplified_equation"):
            return candidate
    raise ValueError("selected candidate is absent from candidates")


def _combined_curve(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    curve: list[dict[str, Any]] = []
    offset = 0.0
    best = float("inf")
    for episode, result in enumerate(results, start=1):
        telemetry = result["engine_telemetry"]
        for checkpoint in telemetry["curve"]:
            nrmse = float(checkpoint["checkpoint_best_validation_nrmse"])
            best = min(best, nrmse)
            curve.append({
                "episode": episode,
                "engine_measured_evaluations": offset + float(checkpoint["engine_measured_evaluations"]),
                "checkpoint_validation_nrmse": nrmse,
                "best_so_far_validation_nrmse": best,
            })
        offset += float(telemetry["final_engine_measured_evaluations"])
    return curve, offset


def _hamilton_cost(bundle: Path, task: str) -> dict[str, Any]:
    records = sorted((bundle / "governed_hamilton" / task / "repeat_1/records").glob("*.json"))
    token_total = 0
    active_seconds = 0.0
    starts: list[datetime] = []
    ends: list[datetime] = []
    audit: list[dict[str, Any]] = []
    for path in records:
        value = _read(path)
        tokens = int(value.get("total_token_usage", 0))
        start = datetime.fromisoformat(value["start_time"])
        end = datetime.fromisoformat(value["end_time"])
        token_total += tokens
        active_seconds += (end - start).total_seconds()
        starts.append(start)
        ends.append(end)
        audit.append({"record": path.name, "tokens": tokens, "active_seconds": (end - start).total_seconds()})
    return {
        "llm_tokens": token_total,
        "controller_active_seconds": active_seconds,
        "controller_elapsed_span_seconds": (max(ends) - min(starts)).total_seconds(),
        "record_count": len(records),
        "records": audit,
    }


def analyze(bundle: Path = DEFAULT_BUNDLE) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    curves: dict[str, Any] = {}
    equivalence: dict[str, Any] = {}
    registry = HERE / "controller_ground_truth.yaml"
    for task in TASKS:
        equivalence[task] = {}
        for arm in ARMS:
            paths = _result_paths(bundle, arm, task)
            if not paths or not all(path.is_file() for path in paths):
                raise FileNotFoundError(f"missing completed result(s): {arm}/{task}")
            results = [_read(path) for path in paths]
            if not all(result.get("status") == "completed" for result in results):
                raise ValueError(f"non-completed result: {arm}/{task}")
            candidates = [_selected_candidate(result) for result in results]
            winner_index = min(
                range(len(results)),
                key=lambda index: float(candidates[index]["ranking"]["scientific_score"]),
            )
            winner = results[winner_index]
            candidate = candidates[winner_index]
            curve, actual_evals = _combined_curve(results)
            key = f"{task}/{arm}"
            curves[key] = curve
            eq = verify_equivalence(
                task, winner["selected"]["simplified_equation"], registry_path=registry
            )
            equivalence[task][arm] = eq
            search_seconds = sum(float(result["runtime_seconds"]) for result in results)
            cost = _hamilton_cost(bundle, task) if arm == "governed_hamilton" else {
                "llm_tokens": 0,
                "controller_active_seconds": search_seconds,
                "controller_elapsed_span_seconds": search_seconds,
                "record_count": 0,
                "records": [],
            }
            rows.append({
                "task_id": task,
                "arm": arm,
                "episode_count": len(results),
                "winning_episode": winner_index + 1,
                "equation": winner["selected"]["simplified_equation"],
                "scientific_score": float(candidate["ranking"]["scientific_score"]),
                "validation_nrmse": float(candidate["ranking"]["validation_nrmse"]),
                "validation_r2": float(candidate["metrics"]["validation"]["r2"]),
                "ground_truth_equivalent": bool(eq["equivalent_ground_truth"]),
                "ground_truth_challenge_nrmse": eq["challenge_grid"]["normalized_rmse"],
                "requested_evaluations": sum(int(result["evaluation_budget"]["requested_evals"]) for result in results),
                "engine_measured_evaluations": actual_evals,
                "search_runtime_seconds": search_seconds,
                **{key: value for key, value in cost.items() if key != "records"},
                "llm_records": cost["records"],
                "result_sha256": [_sha(path) for path in paths],
            })
    return {
        "schema_version": 1,
        "experiment_id": "hamilton-vs-pysr-governed-search-v2-operational-gate",
        "scope": {"tasks": list(TASKS), "repeats": ["repeat_1"], "arms": list(ARMS)},
        "interpretation": "operational_gate_only_not_confirmatory",
        "objectives": {
            "terminal_validation_accuracy": rows,
            "ground_truth_recovery_and_reliability": equivalence,
            "engine_measured_evaluation_efficiency": curves,
            "llm_and_wall_clock_cost": [
                {key: row[key] for key in (
                    "task_id", "arm", "llm_tokens", "search_runtime_seconds",
                    "controller_active_seconds", "controller_elapsed_span_seconds",
                )}
                for row in rows
            ],
        },
    }


def write_analysis(analysis: dict[str, Any], output: Path, bundle: Path = DEFAULT_BUNDLE) -> None:
    analysis_dir = output / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "operational_gate_summary.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    rows = analysis["objectives"]["terminal_validation_accuracy"]
    flat_fields = [
        "task_id", "arm", "episode_count", "winning_episode", "scientific_score",
        "validation_nrmse", "validation_r2", "ground_truth_equivalent",
        "ground_truth_challenge_nrmse", "requested_evaluations",
        "engine_measured_evaluations", "search_runtime_seconds", "llm_tokens",
        "controller_active_seconds", "controller_elapsed_span_seconds", "equation",
    ]
    with (analysis_dir / "operational_gate_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=flat_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in flat_fields})

    traces_dir = output / "paired_budget_traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        source = bundle / "paired_budget_traces" / task / "repeat_1.json"
        target = traces_dir / f"{task}__repeat_1.json"
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    provenance_files = [
        HERE / "manifest.yaml",
        HERE / "dataset_split.yaml",
        HERE / "controller_ground_truth.yaml",
        HERE / "PROTOCOL.md",
        HERE / "RESULTS.zh-CN.md",
        HERE / "freeze_paired_budget.py",
        HERE / "analyze_operational_gate.py",
        REPO / "docs/sragent/HAMILTON_V2_COLLABORATOR_HANDOFF.zh-CN.md",
        REPO / "configs/hamilton/config_governed_pysr_v2.yaml",
        REPO / "playground/hamilton/core/promotion_exp.py",
        REPO / "evomaster/skills/run-sr-experiment/scripts/run_experiment.py",
    ]
    provenance = {
        "schema_version": 1,
        "git_revision_at_search_time": "efd35c51187587f3430a9d60bf3ff4f49185358e",
        "formal_search_complete": True,
        "requested_evaluations_added_during_recovery": 0,
        "startup_incident": {
            "arm": "ordinary_pysr/static_s02/repeat_1",
            "cause": "non-escalated sandbox could not create the JuliaPkg lock under the user profile",
            "engine_telemetry_created": False,
            "engine_evaluations_consumed": 0,
            "preserved_local_record": "preflight_failed_zero_engine_evals_ledger.json",
            "excluded_from_scientific_budget": True,
        },
        "files": {
            path.resolve().relative_to(REPO.resolve()).as_posix(): _sha(path)
            for path in provenance_files
        },
    }
    (output / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "README.md").write_text(
        """# Hamilton vs PySR v2 operational-gate evidence

This is the compact, public, post-run evidence for the two-task, one-repeat
operational gate. It is an engineering and falsification gate, not a
confirmatory benchmark.

- `analysis/operational_gate_summary.csv` is the human-readable endpoint table.
- `analysis/operational_gate_summary.json` also contains controller-only
  challenge-grid equivalence results and engine-measured anytime curves.
- `paired_budget_traces/` proves that all four arms received the same frozen
  requested-evaluation schedule or total.
- `provenance.json` binds the evidence to protocol, controller, runner, and
  result hashes and records the zero-evaluation Julia sandbox startup incident.

Selection is by the frozen `scientific_score`; validation NRMSE is reported
separately. For episodic arms, the best completed episode is the terminal
incumbent. Engine evaluations come from PySR/SymbolicRegression telemetry and
therefore may exceed the requested cap because the engine reports batched
work. No arm recovered the exact registered ground-truth equation.
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    analysis = analyze(args.bundle.resolve())
    write_analysis(analysis, args.output.resolve(), args.bundle.resolve())
    print(json.dumps(analysis["objectives"]["terminal_validation_accuracy"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
