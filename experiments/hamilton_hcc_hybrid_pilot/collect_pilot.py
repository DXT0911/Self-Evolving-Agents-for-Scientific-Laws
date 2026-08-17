#!/usr/bin/env python3
"""Collect HCC hybrid pilot results into a machine-readable evidence bundle.

Reads each arm's final incumbent scientific score, val R², token cost, and round-1
compliance, then computes the pre-registered paired sign test (H vs B, minimize).
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUNDLE = HERE / "run_bundle"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import write_json


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def _val_r2(result: dict[str, Any]) -> float | None:
    validation = (result.get("metrics") or {}).get("validation")
    if isinstance(validation, dict) and validation.get("r2") is not None:
        return float(validation["r2"])
    return None


def collect_hcc(job: dict[str, Any], ws: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "arm": "hcc_llm",
        "task_id": job["task_id"],
        "repeat_id": job["repeat_id"],
        "seed": job.get("seed"),
        "status": "missing",
        "final_scientific_score": None,
        "val_r2": None,
        "llm_tokens": None,
        "round1_compliant": None,
        "closed_rounds": None,
    }
    state_path = ws / ".hamilton_search_state.json"
    if not state_path.is_file():
        return row
    state = read_json(state_path)
    row["status"] = "completed"
    incumbent = state.get("incumbent") or {}
    row["final_scientific_score"] = incumbent.get("score")
    result_file = incumbent.get("result_file")
    if result_file:
        result_path = ws / result_file
        if result_path.is_file():
            row["val_r2"] = _val_r2(read_json(result_path))

    # Round-1 compliance against the frozen config.
    r1_path = ws / "history/round1/experiment.json"
    if r1_path.is_file():
        r1 = read_json(r1_path).get("search") or {}
        compliant = (
            r1.get("binary_operators") == list(frozen["binary_operators"])
            and r1.get("unary_operators") == list(frozen["unary_operators"])
            and int(r1.get("niterations", 0) or 0) == int(frozen["niterations"])
            and int(r1.get("maxsize", 0) or 0) == int(frozen["maxsize"])
            and abs(float(r1.get("parsimony", 0) or 0) - float(frozen["parsimony"])) < 1e-12
        )
        row["round1_compliant"] = compliant

    # Token cost + closed rounds from the experiment record.
    root = REPO / job["root"]
    records = sorted(glob.glob(str(root / "records" / "experiment_*.json")))
    if records:
        record = read_json(Path(records[-1]))
        row["llm_tokens"] = record.get("total_token_usage")
        row["closed_rounds"] = len(record.get("rounds") or [])
    return row


def collect_bare(job: dict[str, Any], ws: Path) -> dict[str, Any]:
    row: dict[str, Any] = {
        "arm": "bare_pysr",
        "task_id": job["task_id"],
        "repeat_id": job["repeat_id"],
        "seed": job.get("seed"),
        "status": "missing",
        "final_scientific_score": None,
        "val_r2": None,
        "llm_tokens": 0,
        "round1_compliant": True,
        "closed_rounds": None,
    }
    summary_path = ws / "baseline_summary.json"
    if not summary_path.is_file():
        return row
    summary = read_json(summary_path)
    row["status"] = summary.get("status", "completed")
    incumbent = summary.get("incumbent") or {}
    row["final_scientific_score"] = incumbent.get("score")
    row["llm_tokens"] = summary.get("llm_tokens", 0)
    row["closed_rounds"] = len(summary.get("rounds") or [])
    result_file = incumbent.get("result_file")
    if result_file:
        result_path = ws / result_file
        if result_path.is_file():
            row["val_r2"] = _val_r2(read_json(result_path))
    return row


def binom_cdf(k: int, n: int) -> float:
    return sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)


def sign_test(wins: int, losses: int, ties: int = 0) -> dict[str, Any]:
    n = wins + losses
    if n == 0:
        return {"wins": wins, "losses": losses, "ties": ties, "n": 0, "p_two_sided": None}
    k = min(wins, losses)
    p_two = min(1.0, 2.0 * binom_cdf(k, n))
    return {"wins": wins, "losses": losses, "ties": ties, "n": n, "p_two_sided": p_two}


def collect(bundle: Path = BUNDLE) -> dict[str, Any]:
    matrix = read_json(bundle / "run_matrix.json")
    manifest = load_yaml(HERE / "pilot_manifest.yaml")
    frozen = manifest["frozen_round1"]

    rows = []
    for job in matrix["jobs"]:
        ws = REPO / job["workspace"]
        if job["arm"] == "hcc_llm":
            rows.append(collect_hcc(job, ws, frozen))
        else:
            rows.append(collect_bare(job, ws))

    paired = []
    wins = losses = ties = 0
    for task_id in sorted({r["task_id"] for r in rows}):
        for repeat_id in sorted({r["repeat_id"] for r in rows if r["task_id"] == task_id}):
            by_arm = {
                r["arm"]: r
                for r in rows
                if r["task_id"] == task_id and r["repeat_id"] == repeat_id
            }
            h = by_arm.get("hcc_llm", {})
            b = by_arm.get("bare_pysr", {})
            h_score = h.get("final_scientific_score")
            b_score = b.get("final_scientific_score")
            outcome = None
            if h_score is not None and b_score is not None:
                if h_score < b_score - 1e-12:
                    outcome = "H_wins"
                    wins += 1
                elif b_score < h_score - 1e-12:
                    outcome = "H_loses"
                    losses += 1
                else:
                    outcome = "tie"
                    ties += 1
            paired.append({
                "task_id": task_id,
                "repeat_id": repeat_id,
                "hcc_score": h_score,
                "bare_score": b_score,
                "hcc_val_r2": h.get("val_r2"),
                "bare_val_r2": b.get("val_r2"),
                "hcc_tokens": h.get("llm_tokens"),
                "outcome": outcome,
            })

    evidence = {
        "schema_version": 1,
        "experiment_id": matrix["experiment_id"],
        "status": "collected",
        "interpretation": "development_pilot_only_not_confirmatory",
        "primary": {
            "metric": "final_incumbent_scientific_score",
            "direction": "minimize",
            "sign_test": sign_test(wins, losses, ties),
        },
        "paired_comparisons": paired,
        "non_compliant_hcc_cells": [
            {"task_id": r["task_id"], "repeat_id": r["repeat_id"]}
            for r in rows
            if r["arm"] == "hcc_llm" and r.get("round1_compliant") is False
        ],
        "rows": rows,
    }
    write_json(bundle / "pilot_evidence.json", evidence)
    return evidence


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
