#!/usr/bin/env python3
"""SRBENCH_ANCHOR_SELECT_BEST

Evaluate multiple Hamilton candidate programs on the same SRBench problem pack
and optionally promote the best one to a target path.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from post_eval_candidate import evaluate_program


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select the best Hamilton SRBench candidate.")
    parser.add_argument("--problem-dir", required=True, help="Problem directory with visible train arrays")
    parser.add_argument(
        "--program",
        action="append",
        required=True,
        help="Candidate program path. Repeat this flag for multiple candidates.",
    )
    parser.add_argument("--restarts", type=int, default=4, help="Number of optimization restarts")
    parser.add_argument("--seed", type=int, default=0, help="Base seed for restart initialization")
    parser.add_argument("--param-dim", type=int, default=10, help="Parameter dimension")
    parser.add_argument("--promote-to", default=None, help="Optional path to copy the winning program to")
    parser.add_argument("--json-out", default=None, help="Optional JSON output path")
    return parser.parse_args()


def candidate_sort_key(result: dict) -> tuple[float, float, int]:
    train = result.get("train") or {}
    combined_score = float(train.get("combined_score", float("-inf")))
    mse = float(train.get("mse", float("inf")))
    success = 1 if result.get("optimization_success") else 0
    return (combined_score, -mse, success)


def render_table(results: list[dict]) -> str:
    headers = ["rank", "label", "train_mse", "train_score", "success", "program"]
    rows = [headers]
    for idx, result in enumerate(results, start=1):
        train = result.get("train") or {}
        rows.append(
            [
                str(idx),
                result["label"],
                f"{train.get('mse', float('nan')):.6g}",
                f"{train.get('combined_score', float('-inf')):.6g}",
                "yes" if result.get("optimization_success") else "no",
                result["program_path"],
            ]
        )

    widths = [max(len(row[col]) for row in rows) for col in range(len(headers))]
    formatted = []
    for idx, row in enumerate(rows):
        formatted.append(" | ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)))
        if idx == 0:
            formatted.append("-+-".join("-" * width for width in widths))
    return "\n".join(formatted)


def load_problem_manifest(problem_dir: Path) -> dict | None:
    manifest_path = problem_dir / "problem_manifest.json"
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    problem_dir = Path(args.problem_dir).resolve()
    programs = [Path(path).resolve() for path in args.program]
    problem_manifest = load_problem_manifest(problem_dir)

    results = []
    for program_path in programs:
        results.append(
            evaluate_program(
                program_path=program_path,
                problem_dir=problem_dir,
                label=program_path.stem,
                restarts=args.restarts,
                seed=args.seed,
                param_dim=args.param_dim,
            )
        )

    ranked = sorted(results, key=candidate_sort_key, reverse=True)
    best = ranked[0]

    if args.promote_to:
        promote_path = Path(args.promote_to).resolve()
        promote_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best["program_path"], promote_path)

    payload = {
        "problem_dir": str(problem_dir),
        "problem_pack_fingerprint": None if problem_manifest is None else problem_manifest.get("source_pack_fingerprint"),
        "problem_train_hashes": None if problem_manifest is None else problem_manifest.get("train_hashes"),
        "restarts": args.restarts,
        "seed": args.seed,
        "param_dim": args.param_dim,
        "ranked_results": ranked,
        "best_program_path": best["program_path"],
        "summary_table": render_table(ranked),
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).write_text(output, encoding="utf-8")

    print(payload["summary_table"])
    print()
    print(output)


if __name__ == "__main__":
    main()
