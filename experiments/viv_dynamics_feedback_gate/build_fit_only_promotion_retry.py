#!/usr/bin/env python3
"""Freeze the one-shot retry of the interrupted fit-only Round 3 Promotion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = HERE / "launch_bundle_replacement_2026-08-13"
SOURCE = BUNDLE / "configs/fit_only_round3_promotion_recovery.yaml"
OUTPUT = BUNDLE / "configs/fit_only_round3_promotion_retry.yaml"
LOCK_PATH = BUNDLE / "fit_only_round3_promotion_retry_lock.json"
STOP_ATTESTATION = BUNDLE / "STOP_ATTESTATION_2026-08-13.json"
WORKSPACE = BUNDLE / "runs/fit_only_hamilton/workspaces/task_0"
RESULT = WORKSPACE / "history/round3/results/result.json"
PROMOTION_STATE = WORKSPACE / "history/round3/promotion_state.json"
EVALUATION_LEDGER = WORKSPACE / ".hamilton_evaluation_ledger.json"

PRIOR_CONSERVATIVE_TOKENS = 600000
RETRY_LIMIT = 69347
AUTHORIZED_ARM_CEILING = 669347
AUTHORIZED_ALL_HAMILTON_CEILING = 1269347


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def build() -> dict:
    stop = json.loads(STOP_ATTESTATION.read_text(encoding="utf-8"))
    if stop.get("status") != "stopped_non_executable":
        raise RuntimeError("missing stopped, non-executable attestation")
    if stop["fit_only_hamilton"].get("conservative_tokens_charged") != 600000:
        raise RuntimeError("unexpected conservative token charge")
    if stop["fit_only_hamilton"].get("retry_permitted_under_current_ceiling") is not False:
        raise RuntimeError("stop attestation does not prohibit the old-ceiling retry")

    state = json.loads(PROMOTION_STATE.read_text(encoding="utf-8"))
    if state.get("status") != "pending" or state.get("attempts") != 1:
        raise RuntimeError(f"unexpected Promotion state: {state}")

    result = json.loads(RESULT.read_text(encoding="utf-8"))
    if result.get("status") != "completed":
        raise RuntimeError("fit-only Round 3 result is not completed")

    ledger = json.loads(EVALUATION_LEDGER.read_text(encoding="utf-8"))
    attempts = ledger.get("attempts", [])
    if sum(int(item.get("requested_evals", 0)) for item in attempts) != 12000:
        raise RuntimeError("fit-only evaluation ledger is not exactly 12,000")
    if any(item.get("status") != "completed" for item in attempts) or len(attempts) != 3:
        raise RuntimeError("fit-only evaluation ledger must contain three completed searches")

    config = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    experiment = config["experiment"]
    experiment["max_total_tokens"] = RETRY_LIMIT
    experiment["max_tokens_per_round"] = 1
    experiment["promotion"]["max_tokens"] = RETRY_LIMIT
    # The interrupted call is attempt 1. A ceiling of 2 permits exactly one retry.
    experiment["promotion"]["max_attempts"] = 2
    OUTPUT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    lock = {
        "schema_version": 1,
        "status": "fit_only_round3_promotion_single_retry_frozen",
        "promotion_attempts_before_retry": 1,
        "promotion_attempts_total_ceiling": 2,
        "prior_conservative_tokens": PRIOR_CONSERVATIVE_TOKENS,
        "retry_token_ceiling": RETRY_LIMIT,
        "authorized_fit_only_ceiling": AUTHORIZED_ARM_CEILING,
        "authorized_all_hamilton_ceiling": AUTHORIZED_ALL_HAMILTON_CEILING,
        "additional_requested_evaluations": 0,
        "requested_evaluations_completed": 12000,
        "downstream_arms_permitted_by_this_lock": False,
        "hashes": {
            relative(OUTPUT): sha256(OUTPUT),
            relative(STOP_ATTESTATION): sha256(STOP_ATTESTATION),
            relative(RESULT): sha256(RESULT),
            relative(PROMOTION_STATE): sha256(PROMOTION_STATE),
            relative(EVALUATION_LEDGER): sha256(EVALUATION_LEDGER),
        },
    }
    LOCK_PATH.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
