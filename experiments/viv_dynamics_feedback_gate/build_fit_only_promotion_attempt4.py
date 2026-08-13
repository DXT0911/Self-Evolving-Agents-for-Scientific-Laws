#!/usr/bin/env python3
"""Freeze fit-only Round 3 Promotion attempt 4 for four audit corrections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = HERE / "launch_bundle_replacement_2026-08-13"
SOURCE = BUNDLE / "configs/fit_only_round3_promotion_retry_2.yaml"
OUTPUT = BUNDLE / "configs/fit_only_round3_promotion_attempt4.yaml"
LOCK_PATH = BUNDLE / "fit_only_round3_promotion_attempt4_lock.json"
WORKSPACE = BUNDLE / "runs/fit_only_hamilton/workspaces/task_0"
STATE = WORKSPACE / "history/round3/promotion_state.json"
RESULT = WORKSPACE / "history/round3/results/result.json"
LEDGER = WORKSPACE / ".hamilton_evaluation_ledger.json"
ATTEMPT3_RECORD = BUNDLE / "runs/fit_only_hamilton/records/experiment_20260813_181150.json"

EXPECTED_ERRORS = [
    "incumbent must retain: history/round2/results/result.json",
    "protocol evidence must enumerate exactly the completed valid-round results and explicitly exclude invalid attempts from scientific evidence",
    "residual feedback does not belong to the current round",
    "residual feedback must cite a current-round result",
]
PRIOR_CONSERVATIVE_TOKENS = 669347
ATTEMPT3_ACTUAL_TOKENS = 8066
REMAINING_TOKENS = 61281
FIT_ONLY_CEILING = 738694
ALL_HAMILTON_CEILING = 1338694


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def build() -> dict:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("status") != "pending" or state.get("attempts") != 3:
        raise RuntimeError(f"unexpected Promotion state: {state}")
    if state.get("errors") != EXPECTED_ERRORS:
        raise RuntimeError(f"unexpected audit errors: {state.get('errors')}")

    record = json.loads(ATTEMPT3_RECORD.read_text(encoding="utf-8"))
    if record.get("total_token_usage") != ATTEMPT3_ACTUAL_TOKENS:
        raise RuntimeError("attempt 3 token usage does not equal 8,066")
    if PRIOR_CONSERVATIVE_TOKENS + ATTEMPT3_ACTUAL_TOKENS + REMAINING_TOKENS != FIT_ONLY_CEILING:
        raise RuntimeError("fit-only token arithmetic is inconsistent")

    result = json.loads(RESULT.read_text(encoding="utf-8"))
    if result.get("status") != "completed":
        raise RuntimeError("Round 3 result is not completed")
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    attempts = ledger.get("attempts", [])
    if len(attempts) != 3 or any(item.get("status") != "completed" for item in attempts):
        raise RuntimeError("evaluation ledger must have three completed attempts")
    if sum(int(item.get("requested_evals", 0)) for item in attempts) != 12000:
        raise RuntimeError("evaluation ledger is not exactly 12,000")

    config = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    experiment = config["experiment"]
    experiment["max_total_tokens"] = REMAINING_TOKENS
    experiment["max_tokens_per_round"] = 1
    experiment["promotion"]["max_tokens"] = REMAINING_TOKENS
    experiment["promotion"]["max_attempts"] = 4
    OUTPUT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    lock = {
        "schema_version": 1,
        "status": "fit_only_round3_promotion_attempt4_frozen",
        "purpose": "correct_exactly_four_deterministic_audit_errors",
        "audit_errors": EXPECTED_ERRORS,
        "promotion_attempts_before_retry": 3,
        "promotion_attempts_total_ceiling": 4,
        "prior_conservative_tokens": PRIOR_CONSERVATIVE_TOKENS,
        "attempt3_actual_tokens": ATTEMPT3_ACTUAL_TOKENS,
        "attempt4_token_ceiling": REMAINING_TOKENS,
        "authorized_fit_only_ceiling": FIT_ONLY_CEILING,
        "authorized_all_hamilton_ceiling": ALL_HAMILTON_CEILING,
        "additional_requested_evaluations": 0,
        "requested_evaluations_completed_fit_only": 12000,
        "downstream_arms_permitted_by_this_lock": False,
        "hashes": {
            relative(OUTPUT): sha256(OUTPUT),
            relative(STATE): sha256(STATE),
            relative(RESULT): sha256(RESULT),
            relative(LEDGER): sha256(LEDGER),
            relative(ATTEMPT3_RECORD): sha256(ATTEMPT3_RECORD),
        },
    }
    LOCK_PATH.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
