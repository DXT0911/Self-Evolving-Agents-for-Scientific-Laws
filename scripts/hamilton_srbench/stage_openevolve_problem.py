#!/usr/bin/env python3
"""SRBENCH_ANCHOR_STAGE_SCRIPT

SRBENCH_ANCHOR_STAGE_HASH_AUDIT

Stage an OpenEvolve symbolic regression problem into the Hamilton SRBench area.

By default this copies only training-visible assets so Hamilton cannot see held-out
test/OOD arrays during its multi-round search.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


VISIBLE_FILES = {
    "initial_program.py",
    "evaluator.py",
    "config.yaml",
    "X_train_for_eval.npy",
    "y_train_for_eval.npy",
}

HIDDEN_FILES = {
    "X_test_for_eval.npy",
    "y_test_for_eval.npy",
    "X_ood_test_for_eval.npy",
    "y_ood_test_for_eval.npy",
}

METADATA_FILES = {
    "export_manifest.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_file(path: Path) -> dict[str, int | str]:
    stat = path.stat()
    return {
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
    }


def tracked_source_inventory(src: Path) -> dict[str, dict[str, int | str]]:
    inventory = {}
    for file_name in sorted(VISIBLE_FILES | HIDDEN_FILES | METADATA_FILES):
        source = src / file_name
        if source.exists():
            inventory[file_name] = describe_file(source)
    return inventory


def source_pack_fingerprint(inventory: dict[str, dict[str, int | str]]) -> str:
    canonical = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage an OpenEvolve SR problem for Hamilton.")
    parser.add_argument("--src", required=True, help="Source OpenEvolve problem directory")
    parser.add_argument(
        "--dst-root",
        default=None,
        help="Destination root, defaults to playground/hamilton_srbench/problems",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Also copy held-out test/OOD arrays into the staged directory",
    )
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def infer_destination(src: Path, dst_root: Path) -> Path:
    split_name = src.parent.name
    problem_name = src.name
    return dst_root / split_name / problem_name


def stage_problem(src: Path, dst: Path, include_hidden: bool) -> None:
    dst.mkdir(parents=True, exist_ok=True)

    copied = []
    hidden = []
    source_inventory = tracked_source_inventory(src)

    for file_name in sorted(VISIBLE_FILES):
        source = src / file_name
        if source.exists():
            shutil.copy2(source, dst / file_name)
            copied.append(file_name)

    for file_name in sorted(HIDDEN_FILES):
        source = src / file_name
        if not source.exists():
            continue
        if include_hidden:
            shutil.copy2(source, dst / file_name)
            copied.append(file_name)
        else:
            hidden.append(file_name)

    for file_name in sorted(METADATA_FILES):
        source = src / file_name
        if source.exists():
            shutil.copy2(source, dst / file_name)
            copied.append(file_name)

    manifest = {
        "source_dir": str(src.resolve()),
        "staged_dir": str(dst.resolve()),
        "copied_files": copied,
        "hidden_files": hidden,
        "include_hidden": include_hidden,
        "source_inventory": source_inventory,
        "copied_inventory": {name: source_inventory[name] for name in copied if name in source_inventory},
        "train_hashes": {
            name: source_inventory[name]["sha256"]
            for name in ("X_train_for_eval.npy", "y_train_for_eval.npy")
            if name in source_inventory
        },
        "source_pack_fingerprint": source_pack_fingerprint(source_inventory),
    }
    (dst / "problem_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    src = Path(args.src).resolve()
    if not src.is_dir():
        raise SystemExit(f"Source problem directory not found: {src}")

    dst_root = Path(args.dst_root).resolve() if args.dst_root else repo_root() / "playground" / "hamilton_srbench" / "problems"
    dst = infer_destination(src, dst_root)

    stage_problem(src, dst, include_hidden=args.include_hidden)
    print(f"Staged problem to: {dst}")


if __name__ == "__main__":
    main()
