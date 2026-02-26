"""Tests for common.sh require_cmd missing command error path.

AL-CORE-35 (TASK-ccadc65d): Validates that require_cmd helper produces
expected error text and non-zero exit when the command is missing.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = str(REPO_ROOT / "scripts" / "autopilot" / "common.sh")

_TIMEOUT = 5


class CommonRequireCmdTests(unittest.TestCase):
    """Bounded tests for require_cmd helper."""

    def _run_require_cmd(self, cmd_name: str) -> subprocess.CompletedProcess[str]:
        """Source common.sh and call require_cmd."""
        script = f'source "{COMMON_SH}" && require_cmd "{cmd_name}"'
        return subprocess.run(
            ["bash", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )

    def test_missing_command_exits_nonzero(self) -> None:
        proc = self._run_require_cmd("nonexistent_cmd_xyz_12345")
        self.assertNotEqual(0, proc.returncode)

    def test_missing_command_error_text(self) -> None:
        proc = self._run_require_cmd("nonexistent_cmd_xyz_12345")
        self.assertIn("Missing required command", proc.stderr)
        self.assertIn("nonexistent_cmd_xyz_12345", proc.stderr)

    def test_missing_command_error_level(self) -> None:
        proc = self._run_require_cmd("nonexistent_cmd_xyz_12345")
        self.assertIn("[ERROR]", proc.stderr)

    def test_existing_command_exits_zero(self) -> None:
        proc = self._run_require_cmd("bash")
        self.assertEqual(0, proc.returncode)

    def test_existing_command_no_error_output(self) -> None:
        proc = self._run_require_cmd("bash")
        self.assertNotIn("Missing required command", proc.stderr)

    def test_empty_string_exits_nonzero(self) -> None:
        proc = self._run_require_cmd("")
        self.assertNotEqual(0, proc.returncode)


if __name__ == "__main__":
    unittest.main()
