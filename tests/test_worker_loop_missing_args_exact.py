"""Tests for worker_loop missing --cli/--agent error strings exactness.

AL-CORE-27 (TASK-e35fb677): Validates that worker_loop.sh emits the
exact stable error message for missing required args and exits non-zero
immediately.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")

_TIMEOUT = 5


class WorkerLoopMissingArgsExactTests(unittest.TestCase):
    """Bounded tests for exact missing-arg error strings."""

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", WORKER_LOOP, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )

    def test_no_args_exits_nonzero(self) -> None:
        proc = self._run([])
        self.assertNotEqual(0, proc.returncode)

    def test_no_args_exact_error_string(self) -> None:
        proc = self._run([])
        self.assertIn("--cli and --agent are required", proc.stderr)

    def test_only_cli_exits_nonzero(self) -> None:
        proc = self._run(["--cli", "codex"])
        self.assertNotEqual(0, proc.returncode)

    def test_only_cli_exact_error_string(self) -> None:
        proc = self._run(["--cli", "codex"])
        self.assertIn("--cli and --agent are required", proc.stderr)

    def test_only_agent_exits_nonzero(self) -> None:
        proc = self._run(["--agent", "claude_code"])
        self.assertNotEqual(0, proc.returncode)

    def test_only_agent_exact_error_string(self) -> None:
        proc = self._run(["--agent", "claude_code"])
        self.assertIn("--cli and --agent are required", proc.stderr)

    def test_error_has_error_level(self) -> None:
        proc = self._run([])
        self.assertIn("[ERROR]", proc.stderr)


if __name__ == "__main__":
    unittest.main()
