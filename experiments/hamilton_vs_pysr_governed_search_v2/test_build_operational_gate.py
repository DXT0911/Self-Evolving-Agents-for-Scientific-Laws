import json
import tempfile
import unittest
from pathlib import Path

from experiments.hamilton_vs_pysr_governed_search_v2.build_operational_gate import build


class BuildOperationalGateTests(unittest.TestCase):
    def test_builds_two_tasks_four_arms_without_baseline_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = build(root)
            matrix = json.loads((root / "run_matrix.json").read_text(encoding="utf-8"))
            self.assertEqual(lock["job_count"], 8)
            self.assertEqual(len(matrix["jobs"]), 8)
            self.assertEqual(sum(j["state"] == "ready" for j in matrix["jobs"]), 2)
            for task in ("static_s02", "dynamic_d02"):
                h = root / "governed_hamilton" / task / "repeat_1/workspaces/task_0"
                self.assertTrue((h / "round1_baseline.json").is_file())
                self.assertTrue((h / "input/data.csv").is_file())
                for arm in ("ordinary_pysr", "fixed_schedule_pysr", "union_schedule_pysr"):
                    b = root / arm / task / "repeat_1/workspace"
                    self.assertTrue((b / "input/data.csv").is_file())
                    self.assertFalse((b / "experiment.json").exists())


if __name__ == "__main__":
    unittest.main()
