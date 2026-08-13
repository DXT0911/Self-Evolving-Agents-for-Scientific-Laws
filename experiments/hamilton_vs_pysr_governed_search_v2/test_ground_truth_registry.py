import unittest
from pathlib import Path

import yaml

from experiments.hamilton_vs_pysr_governed_search.ground_truth_equivalence import (
    verify_equivalence,
)


HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "controller_ground_truth.yaml"


class V2GroundTruthRegistryTests(unittest.TestCase):
    def test_every_registered_truth_is_self_equivalent(self) -> None:
        registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(len(registry["tasks"]), 10)
        for task_id, task in registry["tasks"].items():
            with self.subTest(task_id=task_id):
                result = verify_equivalence(
                    task_id, task["expression"], registry_path=REGISTRY
                )
                self.assertTrue(result["equivalent_ground_truth"])
                self.assertEqual(result["variable_selection"]["precision"], 1.0)
                self.assertEqual(result["variable_selection"]["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
