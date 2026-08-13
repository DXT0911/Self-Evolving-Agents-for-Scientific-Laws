import json
import tempfile
import unittest
from pathlib import Path

from .export_public_evidence import compact_result


class PublicEvidenceExportTests(unittest.TestCase):
    def test_compact_result_uses_allowlists(self) -> None:
        source = {
            "experiment_id": "demo",
            "status": "completed",
            "config": {
                "data": {"feature_columns": ["x1"], "target_column": "y"},
                "search": {"engine": "pysr", "max_evals": 10, "secret": "drop"},
                "absolute_path": "C:/private/workspace",
            },
            "data": {"sha256": "abc", "split": {"train_rows": 8}},
            "selected": {"equation": "x1", "scientific_score": 0.1},
            "metrics": {"validation": {"r2": 1.0}},
            "candidates": [{"equation": "x1", "ranking": {"validation_nrmse": 0.0}}],
            "verification": {},
            "reproducibility": {"git_commit": "deadbeef", "home": "C:/Users/demo"},
            "evaluation_budget": {"attempt_id": "private-uuid", "requested_evals": 10},
        }
        compact = compact_result(
            source, task_id="task", arm_id="ordinary_pysr", checkpoint="endpoint"
        )
        rendered = json.dumps(compact)
        self.assertNotIn("C:/private", rendered)
        self.assertNotIn("C:/Users", rendered)
        self.assertNotIn("private-uuid", rendered)
        self.assertNotIn("secret", rendered)
        self.assertEqual(compact["evaluation_budget"]["requested_evals"], 10)

    def test_json_output_has_no_nan(self) -> None:
        compact = compact_result(
            {"config": {}, "selected": {}, "verification": {}},
            task_id="task",
            arm_id="arm",
            checkpoint="point",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            path.write_text(json.dumps(compact, allow_nan=False), encoding="utf-8")
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
