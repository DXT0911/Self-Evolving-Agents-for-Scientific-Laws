"""Tests for the controller-side Julia/PySR preflight."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playground.hamilton.core.pysr_preflight import (
    PySRPreflightError,
    probe_juliapkg_lock,
    warm_pysr,
)


class PySRPreflightTests(unittest.TestCase):
    def test_missing_lock_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = probe_juliapkg_lock(Path(directory))
        self.assertEqual(result["status"], "clear")
        self.assertFalse(result["existed"])

    def test_active_lock_fails_fast(self) -> None:
        from filelock import FileLock

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            held = FileLock(str(project / "lock.pid"))
            held.acquire()
            try:
                with self.assertRaisesRegex(PySRPreflightError, "actively locked"):
                    probe_juliapkg_lock(project)
            finally:
                held.release()

    @patch("playground.hamilton.core.pysr_preflight.subprocess.run")
    def test_warmup_returns_versions(self, run_mock) -> None:
        payload = {
            "status": "ready",
            "pysr_version": "1.5.9",
            "julia_version": "1.11.9",
            "elapsed_seconds": 1.2,
        }
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload) + "\n", stderr=""
        )
        result = warm_pysr(timeout_seconds=30)
        self.assertEqual(result["pysr_version"], "1.5.9")
        self.assertIn("controller_elapsed_seconds", result)

    @patch("playground.hamilton.core.pysr_preflight.subprocess.run")
    def test_warmup_timeout_has_actionable_error(self, run_mock) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=5)
        with self.assertRaisesRegex(PySRPreflightError, "exceeded 5s"):
            warm_pysr(timeout_seconds=5)


if __name__ == "__main__":
    unittest.main()
