"""Smoke tests for manager_loop.sh argument handling.

Validates that manager_loop.sh rejects unknown arguments with a non-zero
exit code and expected error text on stderr.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "manager_loop.sh")

_TIMEOUT = 5


class ManagerLoopArgTests(unittest.TestCase):
    """Bounded tests for CLI argument validation."""

    def test_unknown_arg_exits_nonzero(self) -> None:
        proc = subprocess.run(
            ["bash", MANAGER_LOOP, "--bogus-flag"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )
        self.assertNotEqual(0, proc.returncode)

    def test_unknown_arg_stderr_contains_error_text(self) -> None:
        proc = subprocess.run(
            ["bash", MANAGER_LOOP, "--bogus-flag"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )
        self.assertIn("Unknown arg", proc.stderr)
        self.assertIn("--bogus-flag", proc.stderr)

    def test_unknown_arg_stderr_contains_error_level(self) -> None:
        proc = subprocess.run(
            ["bash", MANAGER_LOOP, "--not-a-real-option"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )
        self.assertIn("[ERROR]", proc.stderr)

    def test_multiple_unknown_args_rejects_first(self) -> None:
        """Script should fail on the first unrecognized arg."""
        proc = subprocess.run(
            ["bash", MANAGER_LOOP, "--aaa", "--bbb"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("--aaa", proc.stderr)


if __name__ == "__main__":
    unittest.main()
