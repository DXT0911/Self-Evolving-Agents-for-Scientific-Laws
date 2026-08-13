from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from .build_launch_bundle import HERE, build
from .validate_launch_bundle import validate


class LaunchBundleTests(unittest.TestCase):
    def test_materialized_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            bundle = Path(directory) / "bundle"
            build(bundle)
            self.assertEqual(validate(bundle), [])


if __name__ == "__main__":
    unittest.main()
