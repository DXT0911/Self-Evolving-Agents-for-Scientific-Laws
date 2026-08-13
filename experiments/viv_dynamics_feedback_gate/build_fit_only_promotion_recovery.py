#!/usr/bin/env python3
"""Freeze the promotion-only recovery after fit-only Round 3 search completed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = HERE / "launch_bundle_replacement_2026-08-13"
SOURCE = BUNDLE / "configs/hamilton.yaml"
OUTPUT = BUNDLE / "configs/fit_only_round3_promotion_recovery.yaml"
RECORD_DIR = BUNDLE / "runs/fit_only_hamilton/records"
ARM_LIMIT = 600000
PRIOR_TOKEN_USAGE = 530653
RECOVERY_LIMIT = ARM_LIMIT - PRIOR_TOKEN_USAGE


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    records = sorted(RECORD_DIR.glob("experiment_*.json"))
    recorded = sum(
        int(json.loads(path.read_text(encoding="utf-8")).get("total_token_usage", 0))
        for path in records
    )
    recovery_log = BUNDLE / "logs/01b_fit_only_round3_recovery.stderr.log"
    log_text = recovery_log.read_text(encoding="utf-8", errors="replace")
    if recorded != 446259 or "used=84394" not in log_text:
        raise RuntimeError(
            f"unexpected recorded/logged token evidence: recorded={recorded}"
        )
    result = BUNDLE / "runs/fit_only_hamilton/workspaces/task_0/history/round3/results/result.json"
    if json.loads(result.read_text(encoding="utf-8")).get("status") != "completed":
        raise RuntimeError("fit-only Round 3 result is not completed")
    config = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    experiment = config["experiment"]
    experiment["max_total_tokens"] = RECOVERY_LIMIT
    experiment["max_tokens_per_round"] = 1
    experiment["promotion"]["max_tokens"] = RECOVERY_LIMIT
    OUTPUT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    lock = {
        "schema_version": 1,
        "status": "fit_only_round3_promotion_recovery_frozen",
        "prior_token_usage": PRIOR_TOKEN_USAGE,
        "promotion_token_ceiling": RECOVERY_LIMIT,
        "authorized_arm_ceiling": ARM_LIMIT,
        "requested_evaluations_completed": 12000,
        "hashes": {
            str(OUTPUT.relative_to(ROOT)).replace("\\", "/"): sha256(OUTPUT),
            str(result.relative_to(ROOT)).replace("\\", "/"): sha256(result),
            str(recovery_log.relative_to(ROOT)).replace("\\", "/"): sha256(recovery_log),
        },
    }
    (BUNDLE / "fit_only_round3_promotion_recovery_lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return lock


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
