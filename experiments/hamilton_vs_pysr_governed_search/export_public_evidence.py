#!/usr/bin/env python3
"""Export a path-safe, public-only record of the completed operational gate.

The ignored launch bundle is the input.  The exporter deliberately uses field
allowlists: it never copies workspaces, prompts, LLM transcripts, raw data, private/OOD
assets, absolute paths, UUID attempt identifiers, or PySR/Julia caches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "launch_bundle"
DEFAULT_OUTPUT = HERE / "public_evidence" / "operational_gate_v1"
TASKS = ("static_s01", "dynamic_d01", "viv_u248")
REPEAT = "repeat_1"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _pick(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def _residual_summary(result: dict[str, Any]) -> dict[str, Any]:
    residual = result.get("verification", {}).get("residual_diagnostics", {})
    output = _pick(residual, ("enabled", "status", "definition", "role"))
    for split in ("train", "validation"):
        block = residual.get(split, {})
        temporal = block.get("temporal_structure", {})
        output[split] = {
            "summary": _pick(
                block.get("summary", {}),
                ("count", "mean", "std", "rmse", "nrmse_train_target_scale", "max_abs"),
            ),
            "strongest_state_dependence": block.get("state_dependence", {}).get(
                "strongest_absolute_correlation"
            ),
            "temporal_structure": {
                **_pick(temporal, ("trend_correlation", "durbin_watson")),
                "strongest_reported_autocorrelation": temporal.get(
                    "strongest_reported_autocorrelation"
                ),
                "spectrum": _pick(
                    temporal.get("spectrum", {}),
                    (
                        "status",
                        "dominant_frequency_hz",
                        "dominant_power_fraction",
                        "high_frequency_cutoff_hz",
                        "high_frequency_power_fraction",
                    ),
                ),
            },
        }
    return output


def compact_result(
    result: dict[str, Any], *, task_id: str, arm_id: str, checkpoint: str
) -> dict[str, Any]:
    config = result.get("config", {})
    selected = result.get("selected", {})
    short_ode = result.get("verification", {}).get("short_ode", {})
    return {
        "schema_version": 1,
        "task_id": task_id,
        "repeat_id": REPEAT,
        "arm_id": arm_id,
        "checkpoint": checkpoint,
        "experiment_id": result.get("experiment_id"),
        "status": result.get("status"),
        "started_at": result.get("started_at"),
        "completed_at": result.get("completed_at"),
        "runtime_seconds": result.get("runtime_seconds"),
        "data": {
            "sha256": result.get("data", {}).get("sha256"),
            "split": result.get("data", {}).get("split"),
            "feature_columns": config.get("data", {}).get("feature_columns"),
            "target_column": config.get("data", {}).get("target_column"),
        },
        "search": _pick(
            config.get("search", {}),
            (
                "engine",
                "binary_operators",
                "unary_operators",
                "max_evals",
                "niterations",
                "populations",
                "population_size",
                "tournament_selection_n",
                "maxsize",
                "parsimony",
                "top_k",
                "random_state",
            ),
        ),
        "selected": _pick(
            selected,
            (
                "selection_method",
                "equation",
                "search_space_equation",
                "simplified_equation",
                "loss",
                "complexity",
                "scientific_score",
            ),
        ),
        "metrics": result.get("metrics"),
        "ranking": next(
            (
                candidate.get("ranking")
                for candidate in result.get("candidates", [])
                if candidate.get("equation") == selected.get("equation")
            ),
            None,
        ),
        "short_ode": short_ode,
        "residual_diagnostics": _residual_summary(result),
        "reproducibility": _pick(
            result.get("reproducibility", {}),
            (
                "random_state",
                "deterministic",
                "parallelism",
                "git_commit",
                "python",
                "platform",
                "numpy",
                "pandas",
            ),
        ),
        "evaluation_budget": _pick(
            result.get("evaluation_budget", {}),
            ("requested_evals", "reservation_status"),
        ),
    }


def compact_promotion(state: dict[str, Any], *, round_number: int) -> dict[str, Any]:
    closure = state.get("result", {}).get("signal", {}).get("closure", {})
    decision = closure.get("scientific_decision", {})
    return {
        "schema_version": 1,
        "round": round_number,
        "status": state.get("status"),
        "attempts": state.get("attempts"),
        "errors": state.get("errors"),
        "closed": closure.get("closed"),
        "completed_result_files": closure.get("completed_result_files"),
        "changed_config_fields": closure.get("changed_config_fields"),
        "meaningful_config_change": closure.get("meaningful_config_change"),
        "single_config_change": closure.get("single_config_change"),
        "incumbent_expected": decision.get("incumbent_expected"),
        "incumbent_action_expected": decision.get("incumbent_action_expected"),
        "residual_feedback": decision.get("residual_feedback"),
        "search_advancement_gates_valid": decision.get(
            "search_advancement_gates_valid"
        ),
        "success_gates_valid": decision.get("success_gates_valid"),
    }


def export(source: Path, output: Path) -> dict[str, Any]:
    if source.resolve() == output.resolve() or source.resolve() in output.resolve().parents:
        raise ValueError("output must not contain or replace the source launch bundle")

    records: list[dict[str, str]] = []
    for task_id in TASKS:
        trace = _read(source / "paired_budget_traces" / task_id / f"{REPEAT}.json")
        trace_out = output / "budget_traces" / task_id / f"{REPEAT}.json"
        _write(trace_out, trace)
        records.append({"kind": "budget_trace", "file": trace_out.relative_to(output).as_posix()})

        hamilton = (
            source
            / "governed_hamilton"
            / task_id
            / REPEAT
            / "workspaces"
            / "task_0"
        )
        for round_number in (1, 2, 3):
            result = _read(
                hamilton
                / "history"
                / f"round{round_number}"
                / "results"
                / "result.json"
            )
            result_out = (
                output
                / "results"
                / task_id
                / REPEAT
                / "governed_hamilton"
                / f"round_{round_number}.json"
            )
            _write(
                result_out,
                compact_result(
                    result,
                    task_id=task_id,
                    arm_id="governed_hamilton",
                    checkpoint=f"round_{round_number}",
                ),
            )
            records.append({"kind": "result", "file": result_out.relative_to(output).as_posix()})

            promotion = _read(
                hamilton / "history" / f"round{round_number}" / "promotion_state.json"
            )
            promotion_out = (
                output
                / "promotions"
                / task_id
                / REPEAT
                / f"round_{round_number}.json"
            )
            _write(
                promotion_out,
                compact_promotion(promotion, round_number=round_number),
            )
            records.append({"kind": "promotion", "file": promotion_out.relative_to(output).as_posix()})

        ordinary_path = (
            source / "ordinary_pysr" / task_id / REPEAT / "workspace" / "results" / "result.json"
        )
        ordinary_out = output / "results" / task_id / REPEAT / "ordinary_pysr" / "endpoint.json"
        _write(
            ordinary_out,
            compact_result(
                _read(ordinary_path),
                task_id=task_id,
                arm_id="ordinary_pysr",
                checkpoint="endpoint",
            ),
        )
        records.append({"kind": "result", "file": ordinary_out.relative_to(output).as_posix()})

        for episode in (1, 2, 3):
            fixed_path = (
                source
                / "fixed_schedule_pysr"
                / task_id
                / REPEAT
                / "workspace"
                / "results"
                / f"episode_{episode}.json"
            )
            fixed_out = (
                output
                / "results"
                / task_id
                / REPEAT
                / "fixed_schedule_pysr"
                / f"episode_{episode}.json"
            )
            _write(
                fixed_out,
                compact_result(
                    _read(fixed_path),
                    task_id=task_id,
                    arm_id="fixed_schedule_pysr",
                    checkpoint=f"episode_{episode}",
                ),
            )
            records.append({"kind": "result", "file": fixed_out.relative_to(output).as_posix()})

    checksums: dict[str, str] = {}
    for path in sorted(output.rglob("*.json")):
        if path.name == "manifest.json":
            continue
        checksums[path.relative_to(output).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    manifest = {
        "schema_version": 1,
        "package_id": "hamilton-vs-pysr-operational-gate-v1-public-evidence",
        "source_git_commit": "b87800bcdcf3d2a1e4dd4548b7a63a5d52c3e147",
        "tasks": list(TASKS),
        "repeats": [REPEAT],
        "arms": ["governed_hamilton", "ordinary_pysr", "fixed_schedule_pysr"],
        "private_ood_included": False,
        "raw_data_included": False,
        "llm_transcripts_included": False,
        "claim_status": "runtime_pilot_not_formal_multi_repeat_benchmark",
        "records": records,
        "sha256": checksums,
    }
    _write(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = export(args.source.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "records": len(manifest["records"]),
                "private_ood_included": False,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
