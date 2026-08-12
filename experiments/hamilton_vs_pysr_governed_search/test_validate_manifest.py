"""Offline contract tests for the governed-search preparation manifest."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from .validate_manifest import load_manifest, validate_manifest


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "pilot_manifest.yaml"


class PilotManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = load_manifest(MANIFEST)

    def preparation_payload(self) -> dict:
        payload = copy.deepcopy(self.payload)
        payload["permissions"]["deepseek"] = False
        payload["permissions"]["pysr_julia"] = False
        payload["budget"]["authorization_state"] = (
            "frozen_pending_user_authorization"
        )
        payload["status"] = "configured_waiting_authorization"
        payload["launch_blocked"] = True
        payload["readiness_blockers"] = [
            "cumulative_evaluation_budget_not_authorized",
            "deepseek_not_authorized",
            "pysr_julia_not_authorized",
        ]
        return payload

    def test_current_manifest_is_launch_ready(self) -> None:
        self.assertEqual(validate_manifest(self.payload, mode="launch"), [])

    def test_manifest_is_launch_ready_after_token_extension(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["status"] = "frozen"
        payload["launch_blocked"] = False
        payload["readiness_blockers"] = []
        self.assertEqual(validate_manifest(payload, mode="launch"), [])

    def test_preparation_manifest_is_not_launch_ready(self) -> None:
        errors = validate_manifest(self.preparation_payload(), mode="launch")
        self.assertTrue(errors)
        self.assertTrue(any("launch" in error for error in errors))
        self.assertTrue(any("permission deepseek" in error for error in errors))
        self.assertTrue(any("evaluation-budget authorization" in error for error in errors))

    def test_rejects_any_external_execution_permission(self) -> None:
        for permission in ("deepseek", "pysr_julia", "private_ood"):
            with self.subTest(permission=permission):
                payload = self.preparation_payload()
                payload["permissions"][permission] = True
                errors = validate_manifest(payload, mode="preparation")
                self.assertTrue(any(permission in error for error in errors))

    def test_rejects_private_or_ood_dataset_paths(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["dataset_families"][-1]["tasks"][0]["input"] = (
            "playground/hamilton/benchmarks/viv/private/U248_test.csv"
        )
        errors = validate_manifest(payload, mode="launch")
        self.assertTrue(any("forbidden" in error for error in errors))

    def test_rejects_unpaired_episode_seed_plan(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["seed_plan"]["repeats"][0]["episode_seeds"] = [1101, 1102]
        errors = validate_manifest(payload, mode="launch")
        self.assertTrue(any("episode seeds" in error for error in errors))

    def test_rejects_missing_diagnostic_baseline(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["arms"] = [
            arm for arm in payload["arms"] if arm["id"] != "fixed_schedule_pysr"
        ]
        errors = validate_manifest(payload, mode="launch")
        self.assertTrue(any("three preregistered arms" in error for error in errors))

    def test_rejects_budget_allocation_that_does_not_reconcile(self) -> None:
        payload = self.preparation_payload()
        payload["budget"]["hamilton_dynamic_bounds"]["min_evals"] = 7000
        errors = validate_manifest(payload, mode="preparation")
        self.assertTrue(any("dynamic-budget bounds" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
