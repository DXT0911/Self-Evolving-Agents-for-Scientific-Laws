from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from .evaluation_curves import (
    _job_checkpoints,
    build_boundary_curve,
    checkpoint_validation_nrmse,
    endpoint_step_auc,
)


class EvaluationCurveTests(unittest.TestCase):
    def test_builds_best_so_far_curve_and_budget_weighted_auc(self) -> None:
        curve = build_boundary_curve(
            [
                {"requested_evaluations": 20, "best_candidate_validation_nrmse": 0.8,
                 "selected_validation_nrmse": 0.9},
                {"requested_evaluations": 30, "best_candidate_validation_nrmse": 0.5,
                 "selected_validation_nrmse": 0.6},
                {"requested_evaluations": 50, "best_candidate_validation_nrmse": 0.7,
                 "selected_validation_nrmse": 0.75},
            ],
            100,
        )
        self.assertEqual(
            [point["best_so_far_validation_nrmse"] for point in curve],
            [0.8, 0.5, 0.5],
        )
        self.assertAlmostEqual(
            endpoint_step_auc(curve),
            0.2 * 0.8 + 0.3 * 0.5 + 0.5 * 0.5,
        )

    def test_one_shot_result_is_not_anytime_auc_eligible(self) -> None:
        curve = build_boundary_curve(
            [{"requested_evaluations": 100, "best_candidate_validation_nrmse": 0.2,
              "selected_validation_nrmse": 0.2}],
            100,
        )
        self.assertIsNone(endpoint_step_auc(curve))

    def test_extracts_selected_and_best_candidate_scores(self) -> None:
        metrics = checkpoint_validation_nrmse(
            {
                "status": "completed",
                "selected": {"equation": "raw_x1", "simplified_equation": "x1"},
                "candidates": [
                    {"equation": "raw_x1", "simplified_equation": "x1",
                     "ranking": {"validation_nrmse": 0.4}},
                    {"equation": "raw_x2", "simplified_equation": "x2",
                     "ranking": {"validation_nrmse": 0.2}},
                ],
            }
        )
        self.assertEqual(metrics["selected_validation_nrmse"], 0.4)
        self.assertEqual(metrics["best_candidate_validation_nrmse"], 0.2)

    def test_rejects_incomplete_budget_coverage(self) -> None:
        with self.assertRaisesRegex(ValueError, "cover exactly"):
            build_boundary_curve(
                [{"requested_evaluations": 90, "best_candidate_validation_nrmse": 0.2,
                  "selected_validation_nrmse": 0.2}],
                100,
            )

    def test_resolves_handed_off_bundle_outside_current_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "renamed_bundle"
            workspace = bundle / "ordinary_pysr" / "task" / "repeat_1" / "workspace"
            result = workspace / "results" / "result.json"
            result.parent.mkdir(parents=True)
            result.write_text(
                '{"status":"completed","selected":{"equation":"x",'
                '"simplified_equation":"x"},"candidates":[{"equation":"x",'
                '"simplified_equation":"x","ranking":{"validation_nrmse":0.1}}]}',
                encoding="utf-8",
            )
            checkpoints = _job_checkpoints(
                {
                    "arm": "ordinary_pysr",
                    "workspace": (
                        "experiments/hamilton_vs_pysr_governed_search/launch_bundle/"
                        "ordinary_pysr/task/repeat_1/workspace"
                    ),
                },
                bundle,
                {"actual_total_evals": 10, "attempts": []},
            )
            self.assertEqual(checkpoints[0]["requested_evaluations"], 10)


if __name__ == "__main__":
    unittest.main()
