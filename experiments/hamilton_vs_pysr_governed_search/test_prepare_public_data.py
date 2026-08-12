"""Offline tests for opaque public benchmark preparation."""

from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from .prepare_public_data import (
    DYNAMIC_FAMILY,
    STATIC_FAMILY,
    check_prepared_expectations,
    prepare_task,
    sha256_file,
)
from .validate_manifest import ManifestError


class PublicDataPreparationTests(unittest.TestCase):
    @staticmethod
    def write_fixture(path: Path) -> None:
        frame = pd.DataFrame(
            {
                "semantic_a": range(12),
                "semantic_b": [value * 2 for value in range(12)],
                "target": [value * 3 for value in range(12)],
            }
        )
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            frame.to_csv(stream, sep="\t", index=False)

    def test_static_preparation_is_opaque_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tsv.gz"
            first = root / "first.csv"
            second = root / "second.csv"
            self.write_fixture(source)
            expected = sha256_file(source)

            record = prepare_task(
                source,
                first,
                task_id="static_s00",
                family_id=STATIC_FAMILY,
                expected_sha256=expected,
                split_seed=7,
            )
            prepare_task(
                source,
                second,
                task_id="static_s00",
                family_id=STATIC_FAMILY,
                expected_sha256=expected,
                split_seed=7,
            )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(record["columns"], ["t", "x1", "x2", "y"])
            self.assertNotIn("semantic", first.read_text(encoding="utf-8"))
            self.assertFalse(record["ground_truth_in_output"])

    def test_dynamic_preparation_preserves_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tsv.gz"
            destination = root / "prepared.csv"
            self.write_fixture(source)
            record = prepare_task(
                source,
                destination,
                task_id="dynamic_d00",
                family_id=DYNAMIC_FAMILY,
                expected_sha256=sha256_file(source),
                split_seed=7,
            )
            prepared = pd.read_csv(destination)
            self.assertEqual(prepared["x1"].tolist(), list(range(12)))
            self.assertEqual(
                record["ordering"],
                "source_order_preserved_for_contiguous_split",
            )
            self.assertIsNone(record["split_seed"])

    def test_hash_mismatch_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tsv.gz"
            self.write_fixture(source)
            with self.assertRaisesRegex(ManifestError, "SHA-256 mismatch"):
                prepare_task(
                    source,
                    root / "prepared.csv",
                    task_id="static_s00",
                    family_id=STATIC_FAMILY,
                    expected_sha256="0" * 64,
                    split_seed=7,
                )

    def test_prepared_fingerprint_drift_is_rejected(self) -> None:
        task = {
            "id": "static_s00",
            "prepared_sha256": "0" * 64,
            "prepared_rows": 12,
            "prepared_features": 2,
        }
        record = {
            "prepared_sha256": "1" * 64,
            "rows": 12,
            "feature_count": 2,
        }
        with self.assertRaisesRegex(ManifestError, "prepared_sha256 mismatch"):
            check_prepared_expectations(task, record)


if __name__ == "__main__":
    unittest.main()
