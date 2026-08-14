"""Replay governed search decisions on frozen Hamilton result files.

This tool never invokes an LLM, PySR, Julia, or a private evaluator.  It audits
what a frozen deterministic policy would have recommended from evidence that
was already available after each completed round.  It does not claim the
counterfactual outcome of an action that was not actually executed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from .governed_policy import (
    PolicyThresholds,
    choose_action,
    diagnostic_snapshot,
    infer_process_state,
    policy_manifest,
)


def replay_results(
    results: Iterable[tuple[str, dict[str, Any]]],
    *,
    thresholds: PolicyThresholds | None = None,
) -> dict[str, Any]:
    policy = thresholds or PolicyThresholds()
    incumbent_score: float | None = None
    stale_rounds = 0
    rounds: list[dict[str, Any]] = []
    action_counts: dict[str, int] = {}

    for position, (source, result) in enumerate(results, start=1):
        if result.get("status") != "completed":
            rounds.append(
                {
                    "round": position,
                    "source": source,
                    "status": "excluded",
                    "reason": "result_not_completed",
                }
            )
            continue
        snapshot = diagnostic_snapshot(
            result,
            incumbent_score_before=incumbent_score,
            stale_rounds_before=stale_rounds,
        )
        decision = choose_action(snapshot, thresholds=policy)
        score = float(snapshot["scientific_score"])
        advanced = incumbent_score is None or score < incumbent_score
        if advanced:
            incumbent_score = score
            stale_rounds = 0
        else:
            stale_rounds += 1
        action_counts[decision["action"]] = action_counts.get(decision["action"], 0) + 1
        rounds.append(
            {
                "round": position,
                "source": source,
                "status": "replayed",
                "observed_incumbent_advanced": advanced,
                "snapshot": snapshot,
                "process_state": infer_process_state(snapshot),
                "recommended_action": decision,
            }
        )

    return {
        "schema_version": 1,
        "mode": "offline_decision_replay",
        "scientific_boundary": (
            "Recommendations use frozen observed outcomes only. This replay does not "
            "estimate the performance of unexecuted counterfactual actions."
        ),
        "policy": policy_manifest(policy),
        "summary": {
            "input_records": len(rounds),
            "replayed_records": sum(item["status"] == "replayed" for item in rounds),
            "action_counts": action_counts,
            "final_observed_incumbent_score": incumbent_score,
        },
        "rounds": rounds,
    }


def load_result_paths(paths: Iterable[Path]) -> list[tuple[str, dict[str, Any]]]:
    loaded = []
    for path in paths:
        resolved = path.resolve()
        loaded.append(
            (
                path.as_posix(),
                json.loads(resolved.read_text(encoding="utf-8")),
            )
        )
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = replay_results(load_result_paths(args.result))
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
