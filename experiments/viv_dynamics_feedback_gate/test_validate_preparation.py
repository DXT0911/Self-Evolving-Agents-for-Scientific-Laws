"""Offline safety tests for the preparation-only VIV dynamics-feedback gate."""

from __future__ import annotations

import copy
import unittest

from .validate_preparation import (
    DEFAULT_MANIFEST,
    DEFAULT_SPECS,
    load_yaml,
    validate,
)


class PreparationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_yaml(DEFAULT_MANIFEST)
        self.specs = load_yaml(DEFAULT_SPECS)

    def test_frozen_launch_state_passes(self) -> None:
        self.assertEqual(validate(self.manifest, self.specs, mode="launch"), [])

    def test_launch_requires_explicit_execution_permission(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["execution_permitted"] = False
        errors = validate(manifest, self.specs, mode="launch")
        self.assertIn("launch must explicitly permit execution", errors)

    def test_rejects_private_ood_permission(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["permissions"]["private_ood"] = True
        self.assertTrue(any("private/OOD" in error for error in validate(manifest, self.specs, mode="launch")))

    def test_rejects_fit_only_dynamics_leak(self) -> None:
        specs = copy.deepcopy(self.specs)
        specs["arms"]["fit_only_hamilton"]["evidence_withheld_until_endpoint_freeze"] = []
        self.assertIn("fit-only dynamics evidence must be withheld", validate(self.manifest, specs, mode="launch"))

    def test_rejects_budget_or_seed_drift(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["requested_evaluation_budget"]["maximum_per_arm"] = 13000
        manifest["seed_plan"]["hamilton_round_seeds"][2] = 2101
        errors = validate(manifest, self.specs, mode="launch")
        self.assertIn("per-arm ceiling must be 12000", errors)
        self.assertIn("three unique integer Hamilton round seeds are required", errors)

    def test_rejects_nonzero_fit_only_long_horizon_weight(self) -> None:
        specs = copy.deepcopy(self.specs)
        specs["arms"]["fit_only_hamilton"]["search_time_ranking_weights"][
            "long_horizon_penalty"
        ] = 1.0
        self.assertIn("fit-only long-horizon weight must be zero", validate(self.manifest, specs, mode="launch"))


if __name__ == "__main__":
    unittest.main()
