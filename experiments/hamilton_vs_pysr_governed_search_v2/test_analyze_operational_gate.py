import unittest

from experiments.hamilton_vs_pysr_governed_search_v2.analyze_operational_gate import (
    _combined_curve,
    _selected_candidate,
)


class AnalyzeOperationalGateTests(unittest.TestCase):
    def test_combined_curve_offsets_restarts_and_keeps_global_best(self) -> None:
        results = [
            {"engine_telemetry": {"final_engine_measured_evaluations": 12, "curve": [
                {"engine_measured_evaluations": 5, "checkpoint_best_validation_nrmse": 0.8},
                {"engine_measured_evaluations": 12, "checkpoint_best_validation_nrmse": 0.4},
            ]}},
            {"engine_telemetry": {"final_engine_measured_evaluations": 9, "curve": [
                {"engine_measured_evaluations": 4, "checkpoint_best_validation_nrmse": 0.6},
                {"engine_measured_evaluations": 9, "checkpoint_best_validation_nrmse": 0.3},
            ]}},
        ]
        curve, total = _combined_curve(results)
        self.assertEqual(total, 21)
        self.assertEqual([item["engine_measured_evaluations"] for item in curve], [5, 12, 16, 21])
        self.assertEqual([item["best_so_far_validation_nrmse"] for item in curve], [0.8, 0.4, 0.4, 0.3])

    def test_selected_candidate_matches_simplified_equation(self) -> None:
        result = {
            "selected": {"simplified_equation": "x1 + x2"},
            "candidates": [
                {"simplified_equation": "x1"},
                {"simplified_equation": "x1 + x2", "ranking": {"scientific_score": 0.1}},
            ],
        }
        self.assertEqual(_selected_candidate(result)["ranking"]["scientific_score"], 0.1)


if __name__ == "__main__":
    unittest.main()
