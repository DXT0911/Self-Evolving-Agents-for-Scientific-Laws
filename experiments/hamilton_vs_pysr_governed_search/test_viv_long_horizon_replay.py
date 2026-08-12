"""Offline contract tests for public VIV long-horizon replay."""

from __future__ import annotations

import unittest

from .viv_long_horizon_replay import PROFILES, frozen_result_paths, verifier_config


class VivLongHorizonReplayTests(unittest.TestCase):
    def test_replay_scope_is_exactly_completed_public_u248_gate(self) -> None:
        paths = frozen_result_paths()
        self.assertEqual(len(paths), 7)
        self.assertEqual({arm for arm, _, _ in paths}, {
            "governed_hamilton",
            "ordinary_pysr",
            "fixed_schedule_pysr",
        })
        self.assertTrue(all("viv_u248" in str(path) for _, _, path in paths))
        self.assertTrue(all(path.is_file() for _, _, path in paths))

    def test_profiles_change_one_numerical_dimension_at_a_time(self) -> None:
        primary = PROFILES["primary_40"]
        self.assertEqual(PROFILES["window_30"] | {"steady_state_fraction": 0.4}, primary)
        self.assertEqual(PROFILES["window_50"] | {"steady_state_fraction": 0.4}, primary)
        self.assertEqual(PROFILES["resolution_2x"] | {"points": 3000}, primary)

    def test_replay_scoring_is_diagnostic_only(self) -> None:
        config = verifier_config(PROFILES["primary_40"])
        self.assertNotIn("weights", config["verification"]["candidate_ranking"])
        self.assertEqual(
            config["verification"]["long_horizon_dynamics"]["zero_initial_policy"],
            "report_only",
        )


if __name__ == "__main__":
    unittest.main()
