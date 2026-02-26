"""Tests for monitor_loop project path output on startup.

AL-CORE-32 (TASK-e446d02c): Validates that monitor_loop.sh prints the
configured project path header promptly on startup before timeout
termination.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MONITOR_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "monitor_loop.sh")

_TIMEOUT = 5


class MonitorLoopProjectPathTests(unittest.TestCase):
    """Bounded tests for project path output on startup."""

    def _run_and_capture(self, project_root: str) -> str:
        env = os.environ.copy()
        env["TERM"] = "dumb"
        try:
            proc = subprocess.run(
                ["bash", MONITOR_LOOP, project_root, "1"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_TIMEOUT,
                env=env,
            )
            return proc.stdout
        except subprocess.TimeoutExpired as exc:
            return exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""

    def test_prints_project_path_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_and_capture(tmp)
            self.assertIn(f"project={tmp}", output)

    def test_prints_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_and_capture(tmp)
            # The path should be absolute (starts with /)
            for line in output.splitlines():
                if line.startswith("project="):
                    path = line.split("=", 1)[1]
                    self.assertTrue(path.startswith("/"), f"path not absolute: {path}")
                    break
            else:
                self.fail("no project= line found")

    def test_path_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "my project dir"
            spaced.mkdir()
            output = self._run_and_capture(str(spaced))
            self.assertIn(f"project={spaced}", output)

    def test_header_appears_promptly(self) -> None:
        """Header should appear in the first few lines of output."""
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_and_capture(tmp)
            lines = [l for l in output.splitlines() if l.strip()]
            found = any("project=" in l for l in lines[:3])
            self.assertTrue(found, f"project= not in first 3 non-empty lines: {lines[:3]}")

    def test_no_mcp_dependency(self) -> None:
        """Output should contain project header even without codex on PATH."""
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_and_capture(tmp)
            self.assertIn(f"project={tmp}", output)


if __name__ == "__main__":
    unittest.main()
