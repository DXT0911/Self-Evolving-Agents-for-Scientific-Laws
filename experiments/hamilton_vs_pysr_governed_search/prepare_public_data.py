"""Prepare opaque public benchmark inputs without exposing reference equations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .validate_manifest import ManifestError, load_manifest


STATIC_FAMILY = "blind_static_known_truth"
DYNAMIC_FAMILY = "known_dynamics_derivatives"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def prepare_task(
    source: Path,
    destination: Path,
    *,
    task_id: str,
    family_id: str,
    expected_sha256: str,
    split_seed: int,
) -> dict[str, Any]:
    if not source.is_file():
        raise ManifestError(f"{task_id}: source file is missing: {source}")
    actual_source_sha256 = sha256_file(source)
    if actual_source_sha256 != expected_sha256:
        raise ManifestError(
            f"{task_id}: source SHA-256 mismatch: "
            f"expected {expected_sha256}, got {actual_source_sha256}"
        )

    frame = pd.read_csv(source, sep="\t", compression="gzip")
    if "target" not in frame.columns:
        raise ManifestError(f"{task_id}: PMLB input must contain target")
    if len(frame) < 10:
        raise ManifestError(f"{task_id}: input has too few rows")
    if frame.columns.duplicated().any():
        raise ManifestError(f"{task_id}: input has duplicate columns")

    numeric = frame.apply(pd.to_numeric, errors="raise")
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ManifestError(f"{task_id}: input contains non-finite values")

    feature_columns = [column for column in numeric.columns if column != "target"]
    if not feature_columns:
        raise ManifestError(f"{task_id}: input has no feature columns")

    if family_id == STATIC_FAMILY:
        permutation = np.random.default_rng(split_seed).permutation(len(numeric))
        numeric = numeric.iloc[permutation].reset_index(drop=True)
        ordering = "deterministic_permutation_before_contiguous_split"
    elif family_id == DYNAMIC_FAMILY:
        numeric = numeric.reset_index(drop=True)
        ordering = "source_order_preserved_for_contiguous_split"
    else:
        raise ManifestError(f"{task_id}: unsupported preparation family {family_id}")

    rename = {
        name: f"x{index}"
        for index, name in enumerate(feature_columns, start=1)
    }
    rename["target"] = "y"
    opaque = numeric.rename(columns=rename)
    opaque.insert(0, "t", np.arange(len(opaque), dtype=int))

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    opaque.to_csv(temporary, index=False)
    os.replace(temporary, destination)

    return {
        "schema_version": 1,
        "task_id": task_id,
        "family_id": family_id,
        "public_only": True,
        "ground_truth_in_output": False,
        "source_sha256": actual_source_sha256,
        "prepared_sha256": sha256_file(destination),
        "rows": int(len(opaque)),
        "feature_count": len(feature_columns),
        "columns": list(opaque.columns),
        "target_column": "y",
        "time_column": "t",
        "ordering": ordering,
        "split_seed": split_seed if family_id == STATIC_FAMILY else None,
    }


def check_prepared_expectations(task: dict[str, Any], record: dict[str, Any]) -> None:
    expected = {
        "prepared_sha256": record["prepared_sha256"],
        "prepared_rows": record["rows"],
        "prepared_features": record["feature_count"],
    }
    for field, actual in expected.items():
        declared = task.get(field)
        if declared is not None and declared != actual:
            raise ManifestError(
                f"{task['id']}: {field} mismatch: expected {declared}, got {actual}"
            )


def prepare_manifest(
    manifest_path: Path,
    output_root: Path,
    *,
    split_seed: int,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    experiment_root = manifest_path.resolve().parent
    records = []
    for family in manifest.get("dataset_families", []):
        family_id = family.get("id")
        if family_id not in {STATIC_FAMILY, DYNAMIC_FAMILY}:
            continue
        for task in family.get("tasks", []):
            task_id = task["id"]
            source = (experiment_root / task["input"]).resolve()
            destination = (output_root / task_id / "input" / "data.csv").resolve()
            try:
                destination.relative_to(output_root.resolve())
            except ValueError as exc:
                raise ManifestError(f"{task_id}: output escaped preparation root") from exc
            record = prepare_task(
                source,
                destination,
                task_id=task_id,
                family_id=family_id,
                expected_sha256=task["sha256"],
                split_seed=split_seed,
            )
            check_prepared_expectations(task, record)
            record["prepared_input"] = str(
                destination.relative_to(experiment_root)
            ).replace("\\", "/")
            metadata_path = destination.parents[1] / "metadata.json"
            _atomic_json(metadata_path, record)
            records.append(record)

    lock = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "public_only": True,
        "task_count": len(records),
        "tasks": records,
    }
    _atomic_json(output_root / "prepared_data_lock.json", lock)
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "prepared_data",
    )
    parser.add_argument("--split-seed", type=int, default=20260727)
    args = parser.parse_args()
    try:
        lock = prepare_manifest(
            args.manifest,
            args.output_root.resolve(),
            split_seed=args.split_seed,
        )
    except (ManifestError, OSError, ValueError) as exc:
        print(f"public-data preparation failed: {exc}")
        return 1
    print(
        json.dumps(
            {
                "status": "completed",
                "public_only": True,
                "task_count": lock["task_count"],
                "lock_file": str(args.output_root / "prepared_data_lock.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
