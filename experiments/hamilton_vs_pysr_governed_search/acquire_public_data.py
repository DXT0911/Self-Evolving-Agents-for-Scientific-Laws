#!/usr/bin/env python3
"""Download the frozen public PMLB inputs and verify their manifest fingerprints."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

from .validate_manifest import load_manifest


HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "pilot_manifest.yaml"
DEFAULT_OUTPUT = HERE / "data_cache"
PMLB_MEDIA = "https://media.githubusercontent.com/media/EpistasisLab/pmlb"


def source_url(task: dict[str, Any]) -> str:
    dataset = str(task["source_dataset"])
    revision = str(task["source_revision"])
    return f"{PMLB_MEDIA}/{revision}/datasets/{dataset}/{dataset}.tsv.gz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for family in manifest.get("dataset_families", []):
        if family.get("source") not in {"pmlb_srbench", "pmlb_ode_strogatz"}:
            continue
        for task in family.get("tasks", []):
            destination = output / Path(str(task["input"])).name
            expected_bytes = int(task["bytes"])
            expected_sha = str(task["sha256"])
            status = "already_verified"
            if not destination.is_file() or destination.stat().st_size != expected_bytes or sha256(destination) != expected_sha:
                temporary = destination.with_suffix(destination.suffix + ".part")
                if temporary.exists():
                    temporary.unlink()
                with urllib.request.urlopen(source_url(task), timeout=120) as response:
                    with temporary.open("wb") as handle:
                        while chunk := response.read(1024 * 1024):
                            handle.write(chunk)
                if temporary.stat().st_size != expected_bytes:
                    temporary.unlink(missing_ok=True)
                    raise ValueError(f"{task['id']}: downloaded byte count does not match manifest")
                actual_sha = sha256(temporary)
                if actual_sha != expected_sha:
                    temporary.unlink(missing_ok=True)
                    raise ValueError(f"{task['id']}: downloaded SHA-256 does not match manifest")
                temporary.replace(destination)
                status = "downloaded_and_verified"
            records.append(
                {
                    "task_id": task["id"],
                    "source_dataset": task["source_dataset"],
                    "source_revision": task["source_revision"],
                    "bytes": destination.stat().st_size,
                    "sha256": sha256(destination),
                    "status": status,
                }
            )
    return {
        "schema_version": 1,
        "public_only": True,
        "private_ood_accessed": False,
        "output": str(output),
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = acquire(args.manifest.resolve(), args.output.resolve())
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
