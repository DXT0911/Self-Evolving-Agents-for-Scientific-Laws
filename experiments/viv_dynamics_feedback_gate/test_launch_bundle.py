from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from .build_launch_bundle import HERE, build
from .validate_launch_bundle import validate


class LaunchBundleTests(unittest.TestCase):
    def test_materialized_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            bundle = Path(directory) / "bundle"
            build(bundle)
            self.assertEqual(validate(bundle), [])
            script = (bundle / "run_authorized.ps1").read_text(encoding="utf-8")
            self.assertIn("ForEach-Object { Write-Host $_ }", script)
            self.assertIn("return [int]$Code", script)
            self.assertGreaterEqual(script.count("if ($Code -ne 0) { exit $Code }"), 5)
            config = yaml.safe_load((bundle / "configs/hamilton.yaml").read_text(encoding="utf-8"))
            prompt = Path(config["agents"]["hamilton"]["system_prompt_file"])
            self.assertTrue(prompt.is_absolute())
            self.assertTrue(prompt.is_file())


if __name__ == "__main__":
    unittest.main()
