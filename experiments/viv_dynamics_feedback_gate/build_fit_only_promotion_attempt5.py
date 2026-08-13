#!/usr/bin/env python3
"""Freeze fit-only Round 3 Promotion attempt 5 after runtime contract fixes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = HERE / "launch_bundle_replacement_2026-08-13"
SOURCE = BUNDLE / "configs/fit_only_round3_promotion_attempt4.yaml"
OUTPUT = BUNDLE / "configs/fit_only_round3_promotion_attempt5.yaml"
LOCK_PATH = BUNDLE / "fit_only_round3_promotion_attempt5_lock.json"
WORKSPACE = BUNDLE / "runs/fit_only_hamilton/workspaces/task_0"
STATE = WORKSPACE / "history/round3/promotion_state.json"
RESULT = WORKSPACE / "history/round3/results/result.json"
LEDGER = WORKSPACE / ".hamilton_evaluation_ledger.json"
ATTEMPT4_RECORD = BUNDLE / "runs/fit_only_hamilton/records/experiment_20260813_192023.json"
ATTEMPT4_STOP = BUNDLE / "STOP_ATTESTATION_PROMOTION_ATTEMPT4_2026-08-13.json"
EDITOR = ROOT / "evomaster/agent/tools/builtin/editor.py"
AGENT = ROOT / "evomaster/agent/agent.py"

EXPECTED_ERRORS = [
    "incumbent must retain: history/round2/results/result.json",
    "protocol evidence must enumerate exactly the completed valid-round results and explicitly exclude invalid attempts from scientific evidence",
    "residual feedback does not belong to the current round",
    "residual feedback must cite a current-round result",
]
FIT_ONLY_USAGE_BEFORE_ATTEMPT5 = 767482
ATTEMPT5_LIMIT = 90000
FIT_ONLY_CEILING = 857482
ALL_HAMILTON_CEILING = 1457482
COMPLETION_LIMIT = 12000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def build() -> dict:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("status") != "pending" or state.get("attempts") != 4:
        raise RuntimeError(f"unexpected Promotion state: {state}")
    if state.get("errors") != EXPECTED_ERRORS:
        raise RuntimeError(f"unexpected audit errors: {state.get('errors')}")
    if state.get("fast_finish_eligible") is not False:
        raise RuntimeError("attempt 5 must perform the full scientific correction")

    record = json.loads(ATTEMPT4_RECORD.read_text(encoding="utf-8"))
    if record.get("total_token_usage") != 90069:
        raise RuntimeError("attempt 4 token usage does not equal 90,069")
    stop = json.loads(ATTEMPT4_STOP.read_text(encoding="utf-8"))
    if stop.get("status") != "attempt4_incomplete_token_overrun":
        raise RuntimeError("attempt 4 stop attestation is missing")
    if FIT_ONLY_USAGE_BEFORE_ATTEMPT5 + ATTEMPT5_LIMIT != FIT_ONLY_CEILING:
        raise RuntimeError("fit-only token arithmetic is inconsistent")

    if "str | None" not in EDITOR.read_text(encoding="utf-8"):
        raise RuntimeError("null-compatible editor fix is absent")
    if "completion_limit" not in AGENT.read_text(encoding="utf-8"):
        raise RuntimeError("hard token preflight fix is absent")

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
    config["llm"]["openai"]["max_tokens"] = COMPLETION_LIMIT
    experiment = config["experiment"]
    experiment["max_total_tokens"] = ATTEMPT5_LIMIT
    experiment["max_tokens_per_round"] = 1
    experiment["promotion"]["max_tokens"] = ATTEMPT5_LIMIT
    experiment["promotion"]["max_attempts"] = 5
    OUTPUT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    lock = {
        "schema_version": 1,
        "status": "fit_only_round3_promotion_attempt5_frozen",
        "purpose": "correct_exactly_four_deterministic_audit_errors_and_close",
        "audit_errors": EXPECTED_ERRORS,
        "promotion_attempts_before_retry": 4,
        "promotion_attempts_total_ceiling": 5,
        "fit_only_usage_before_attempt5": FIT_ONLY_USAGE_BEFORE_ATTEMPT5,
        "attempt5_token_ceiling": ATTEMPT5_LIMIT,
        "per_completion_token_ceiling": COMPLETION_LIMIT,
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
            relative(ATTEMPT4_RECORD): sha256(ATTEMPT4_RECORD),
            relative(ATTEMPT4_STOP): sha256(ATTEMPT4_STOP),
            relative(EDITOR): sha256(EDITOR),
            relative(AGENT): sha256(AGENT),
        },
    }
    LOCK_PATH.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
