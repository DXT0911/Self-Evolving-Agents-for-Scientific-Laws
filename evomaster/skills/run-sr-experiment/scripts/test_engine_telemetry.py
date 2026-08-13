import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from .engine_telemetry import read_payloads, validation_curve


class EngineTelemetryTests(unittest.TestCase):
    def test_builds_monotonic_best_so_far_validation_curve(self) -> None:
        payloads = [
            {"num_evals": 10.0, "log_step": 0, "equations": {"complexity=1": {"equation": "bad"}}},
            {"num_evals": 20.5, "log_step": 1, "equations": {"complexity=2": {"equation": "good"}}},
            {"num_evals": 30.0, "log_step": 2, "equations": {"complexity=3": {"equation": "worse"}}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in payloads), encoding="utf-8")
            predictions = {
                "bad": np.asarray([2.0, 2.0]),
                "good": np.asarray([1.0, 1.0]),
                "worse": np.asarray([1.5, 1.5]),
            }
            report = validation_curve(
                path,
                predict_equation=lambda equation: predictions[equation],
                target=np.asarray([1.0, 1.0]),
                target_scale=1.0,
            )
        self.assertEqual(report["final_engine_measured_evaluations"], 30.0)
        self.assertEqual(
            [point["best_so_far_validation_nrmse"] for point in report["curve"]],
            [1.0, 0.0, 0.0],
        )

    def test_rejects_nonmonotonic_engine_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            path.write_text(
                '{"num_evals":20,"equations":{"complexity=1":{"equation":"x"}}}\n'
                '{"num_evals":10,"equations":{"complexity=1":{"equation":"x"}}}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not monotonic"):
                validation_curve(
                    path,
                    predict_equation=lambda _: np.asarray([0.0]),
                    target=np.asarray([0.0]),
                    target_scale=1.0,
                )

    def test_rejects_missing_numeric_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.jsonl"
            path.write_text('{"equations":{}}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "num_evals"):
                read_payloads(path)


if __name__ == "__main__":
    unittest.main()
