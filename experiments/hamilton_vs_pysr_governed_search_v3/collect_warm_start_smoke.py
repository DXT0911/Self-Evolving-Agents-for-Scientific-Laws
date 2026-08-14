#!/usr/bin/env python3
"""Export compact evidence from the v3 warm-start equivalence smoke."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "runs/warm_start_equivalence"
OUTPUT = HERE / "warm_start_smoke_evidence.json"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect() -> dict:
    paths = {
        "ordinary": RUN / "ordinary/results/result.json",
        "warm_round1": RUN / "warm/history/round1/results/result.json",
        "warm_round2": RUN / "warm/history/round2/results/result.json",
        "modify_round1": RUN / "warm_modify/history/round1/results/result.json",
        "modify_round2": RUN / "warm_modify/history/round2/results/result.json",
    }
    values = {name: read(path) for name, path in paths.items()}
    if not all(value.get("status") == "completed" for value in values.values()):
        raise ValueError("all smoke results must be completed")
    ordinary = values["ordinary"]
    final = values["warm_round2"]
    warm_engine = final["engine_telemetry"]["warm_start_session"]
    worker = read(RUN / "warm/.hamilton_warm_start/static-s01-repeat-1/worker.json")
    modify_worker = read(
        RUN / "warm_modify/.hamilton_warm_start/static-s01-modify-repeat-1/worker.json"
    )
    modify_final = values["modify_round2"]
    modify_transition = modify_final["warm_start_transition"]
    modify_engine = modify_final["engine_telemetry"]["warm_start_session"]
    modify_passed = (
        modify_transition["changed_fields"] == ["search.parsimony"]
        and modify_engine["state_preserved"] is True
        and modify_worker.get("status") == "closed"
    )
    endpoint_fields = {
        "equation": lambda value: value["selected"]["simplified_equation"],
        "scientific_score": lambda value: value["selected"]["scientific_score"],
        "validation_mse": lambda value: value["metrics"]["validation"]["mse"],
        "validation_r2": lambda value: value["metrics"]["validation"]["r2"],
    }
    equality = {
        field: function(ordinary) == function(final)
        for field, function in endpoint_fields.items()
    }
    ordinary_evals = float(
        ordinary["engine_telemetry"]["final_engine_measured_evaluations"]
    )
    warm_evals = float(warm_engine["engine_evaluations_after"])
    return {
        "schema_version": 1,
        "status": (
            "passed"
            if all(equality.values())
            and worker.get("status") == "closed"
            and modify_passed
            else "failed"
        ),
        "purpose": "implementation_equivalence_not_scientific_arm",
        "task": "static_s01_development_only",
        "requested_evaluations": {"ordinary": 2000, "warm_segments": [1000, 1000]},
        "endpoint_exact_equality": equality,
        "endpoint": {field: function(final) for field, function in endpoint_fields.items()},
        "engine_measured_evaluations": {
            "ordinary": ordinary_evals,
            "warm_segmented_total": warm_evals,
            "difference": warm_evals - ordinary_evals,
            "relative_overhead": (warm_evals - ordinary_evals) / ordinary_evals,
            "rounds": [
                values["warm_round1"]["engine_telemetry"]["warm_start_session"]["round_engine_measured_evaluations"],
                values["warm_round2"]["engine_telemetry"]["warm_start_session"]["round_engine_measured_evaluations"],
            ],
        },
        "worker_final_status": worker.get("status"),
        "compatible_change_smoke": {
            "status": "passed" if modify_passed else "failed",
            "changed_fields": modify_transition["changed_fields"],
            "state_preserved": modify_engine["state_preserved"],
            "worker_final_status": modify_worker.get("status"),
            "round_engine_measured_evaluations": modify_engine[
                "round_engine_measured_evaluations"
            ],
            "policy": {
                "allowed": ["search.parsimony"],
                "fixed": ["search.maxsize", "search.random_state"],
            },
        },
        "result_sha256": {name: sha(path) for name, path in paths.items()},
        "conclusion": "do_not_add_continuation_schedule_as_formal_arm",
    }


if __name__ == "__main__":
    evidence = collect()
    OUTPUT.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
