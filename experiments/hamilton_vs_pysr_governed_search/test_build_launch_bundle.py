import json
import tempfile
import unittest
from pathlib import Path

from experiments.hamilton_vs_pysr_governed_search.build_launch_bundle import (
    build_bundle,
    sha256,
    write_json,
)
from experiments.hamilton_vs_pysr_governed_search.freeze_paired_budget import (
    freeze_paired_budget,
)

HERE = Path(__file__).resolve().parent


class BuildLaunchBundleTests(unittest.TestCase):
    def test_exact_matrix_is_frozen_but_not_enabled(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory) / "bundle"
            lock = build_bundle(root)
            self.assertEqual(lock["task_count"], 11)
            self.assertEqual(lock["repeat_count"], 3)
            self.assertEqual(lock["job_count"], 99)
            self.assertEqual(
                lock["episode_evaluations"],
                "realized_from_paired_hamilton_ledger",
            )
            matrix = json.loads((root / "run_matrix.json").read_text(encoding="utf-8"))
            self.assertFalse(matrix["execution_permitted"])
            self.assertFalse(matrix["private_ood_permitted"])
            self.assertEqual(matrix["ready_job_count"], 33)

    def test_baselines_wait_for_hamilton_and_round_one_is_frozen(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory) / "bundle"
            build_bundle(root)
            task = "static_s01"
            self.assertFalse(
                (root / "ordinary_pysr" / task / "repeat_1/workspace/experiment.json")
                .exists()
            )
            self.assertEqual(
                list(
                    (
                        root / "fixed_schedule_pysr" / task / "repeat_1/workspace"
                    ).glob("episodes/*.json")
                ),
                [],
            )

            baseline = json.loads(
                (
                    root
                    / "governed_hamilton"
                    / task
                    / "repeat_1/workspaces/task_0/round1_baseline.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(baseline["search"]["max_evals"], 4000)
            self.assertEqual(baseline["search"]["random_state"], 1101)
            task_text = (
                root
                / "governed_hamilton"
                / task
                / "repeat_1/workspaces/task_0/task.md"
            ).read_text(encoding="utf-8")
            self.assertIn("base=4000", task_text)
            self.assertIn("min=2000", task_text)
            self.assertIn("[1101, 1102, 1103]", task_text)

    def test_freezes_realized_hamilton_budget_before_materializing_pysr(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory) / "bundle"
            build_bundle(root)
            task = "dynamic_d01"
            workspace = (
                root / "governed_hamilton" / task / "repeat_1/workspaces/task_0"
            )
            baseline = json.loads(
                (workspace / "round1_baseline.json").read_text(encoding="utf-8")
            )
            attempts = []
            for index, (budget, seed) in enumerate(
                zip([3000, 5000, 3500], [1101, 1102, 1103]), start=1
            ):
                config = json.loads(json.dumps(baseline))
                config["experiment_id"] = f"fake-round-{index}"
                config["search"]["max_evals"] = budget
                config["search"]["random_state"] = seed
                config["output"]["result_file"] = (
                    f"history/round{index}/results/result.json"
                )
                config["output"]["run_directory"] = (
                    f"history/round{index}/results/pysr"
                )
                config_path = workspace / f"history/round{index}/experiment.json"
                write_json(config_path, config)
                attempts.append(
                    {
                        "requested_evals": budget,
                        "status": "completed",
                        "result_file": config["output"]["result_file"],
                        "config_sha256": sha256(config_path),
                    }
                )
            write_json(
                workspace / ".hamilton_evaluation_ledger.json",
                {
                    "schema_version": 1,
                    "max_total_evals": 12000,
                    "attempts": attempts,
                },
            )
            trace = freeze_paired_budget(task, "repeat_1", root)
            self.assertEqual(trace["actual_total_evals"], 11500)
            ordinary = json.loads(
                (
                    root
                    / "ordinary_pysr"
                    / task
                    / "repeat_1/workspace/experiment.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(ordinary["search"]["max_evals"], 11500)
            fixed = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(
                    (
                        root
                        / "fixed_schedule_pysr"
                        / task
                        / "repeat_1/workspace/episodes"
                    ).glob("*.json")
                )
            ]
            self.assertEqual(
                [config["search"]["max_evals"] for config in fixed],
                [3000, 5000, 3500],
            )


if __name__ == "__main__":
    unittest.main()
