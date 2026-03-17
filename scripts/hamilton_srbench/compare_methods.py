#!/usr/bin/env python3
"""SRBENCH_ANCHOR_COMPARE_METHODS

Compare Hamilton and OpenEvolve candidate programs on the same full problem pack
using a shared deterministic post-evaluation protocol.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from post_eval_candidate import evaluate_program


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Hamilton and OpenEvolve programs on one SRBench problem.")
    parser.add_argument("--problem-dir", required=True, help="Full problem directory with train/test/OOD arrays")
    parser.add_argument("--hamilton-program", required=True, help="Hamilton candidate_model.py path")
    parser.add_argument("--openevolve-program", required=True, help="OpenEvolve program path")
    parser.add_argument(
        "--baseline-program",
        default=None,
        help="Optional baseline program path, e.g. initial_program.py",
    )
    parser.add_argument("--restarts", type=int, default=8, help="Number of optimization restarts")
    parser.add_argument("--seed", type=int, default=0, help="Base seed for optimization restarts")
    parser.add_argument("--param-dim", type=int, default=10, help="Parameter dimension")
    parser.add_argument("--json-out", default=None, help="Optional JSON output path")
    return parser.parse_args()


def metric_value(result: dict, split: str, metric: str) -> str:
    block = result.get(split)
    if block is None or metric not in block:
        return "n/a"
    return f"{block[metric]:.6g}"


def render_table(results: list[dict]) -> str:
    headers = ["label", "train_mse", "train_score", "test_mse", "test_nmse", "ood_mse", "ood_nmse"]
    rows = [headers]
    for result in results:
        rows.append(
            [
                result["label"],
                metric_value(result, "train", "mse"),
                metric_value(result, "train", "combined_score"),
                metric_value(result, "test", "mse"),
                metric_value(result, "test", "nmse"),
                metric_value(result, "ood", "mse"),
                metric_value(result, "ood", "nmse"),
            ]
        )

    widths = [max(len(row[idx]) for row in rows) for idx in range(len(headers))]
    formatted = []
    for row_idx, row in enumerate(rows):
        formatted.append(" | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)))
        if row_idx == 0:
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
    problem_manifest = load_problem_manifest(problem_dir)

    programs = [
        ("hamilton", Path(args.hamilton_program).resolve()),
        ("openevolve", Path(args.openevolve_program).resolve()),
    ]
    if args.baseline_program:
        programs.insert(0, ("baseline", Path(args.baseline_program).resolve()))

    results = []
    for label, program_path in programs:
        results.append(
            evaluate_program(
                program_path=program_path,
                problem_dir=problem_dir,
                label=label,
                restarts=args.restarts,
                seed=args.seed,
                param_dim=args.param_dim,
            )
        )

    payload = {
        "problem_dir": str(problem_dir),
        "problem_pack_fingerprint": None if problem_manifest is None else problem_manifest.get("source_pack_fingerprint"),
        "problem_train_hashes": None if problem_manifest is None else problem_manifest.get("train_hashes"),
        "restarts": args.restarts,
        "seed": args.seed,
        "param_dim": args.param_dim,
        "results": results,
        "summary_table": render_table(results),
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).write_text(output, encoding="utf-8")

    print(payload["summary_table"])
    print()
    print(output)


if __name__ == "__main__":
    main()
