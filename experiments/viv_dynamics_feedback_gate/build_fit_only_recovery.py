#!/usr/bin/env python3
"""Freeze a bounded Round-3 recovery config for the fit-only Hamilton arm."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = HERE / "launch_bundle_replacement_2026-08-13"
SOURCE = BUNDLE / "configs/hamilton.yaml"
OUTPUT = BUNDLE / "configs/fit_only_round3_recovery.yaml"
RECORD_DIR = BUNDLE / "runs/fit_only_hamilton/records"
USED_TOKENS = 446259
ARM_LIMIT = 600000
RECOVERY_LIMIT = 150000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    records = sorted(RECORD_DIR.glob("experiment_*.json"))
    if not records:
        raise RuntimeError("fit-only experiment record is missing")
    record = json.loads(records[-1].read_text(encoding="utf-8"))
    actual = int(record.get("total_token_usage", -1))
    if actual != USED_TOKENS:
        raise RuntimeError(f"unexpected prior token usage: {actual}")
    if USED_TOKENS + RECOVERY_LIMIT > ARM_LIMIT:
        raise RuntimeError("recovery would exceed the authorized per-arm token ceiling")
    config = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    experiment = config["experiment"]
    experiment["max_total_tokens"] = RECOVERY_LIMIT
    experiment["max_tokens_per_round"] = 90000
    experiment["promotion"]["max_tokens"] = 60000
    OUTPUT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    lock = {
        "schema_version": 1,
        "status": "fit_only_round3_recovery_frozen",
        "prior_token_usage": USED_TOKENS,
        "recovery_token_ceiling": RECOVERY_LIMIT,
        "cumulative_arm_token_ceiling": USED_TOKENS + RECOVERY_LIMIT,
        "authorized_arm_ceiling": ARM_LIMIT,
        "completed_requested_evaluations": 8000,
        "remaining_requested_evaluation_ceiling": 4000,
        "hashes": {
            str(OUTPUT.relative_to(ROOT)).replace("\\", "/"): sha256(OUTPUT),
            str(records[-1].relative_to(ROOT)).replace("\\", "/"): sha256(records[-1]),
        },
    }
    lock_path = BUNDLE / "fit_only_round3_recovery_lock.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
