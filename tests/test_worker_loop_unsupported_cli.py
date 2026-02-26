"""Tests for worker_loop unsupported CLI error propagation through helper.

AL-CORE-21 (TASK-65d537e4): Validates that worker_loop with an unsupported
CLI value propagates the helper error to logs/stderr and exits cleanly
without hanging.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")

_TIMEOUT = 10


class WorkerLoopUnsupportedCliTests(unittest.TestCase):
    """Bounded tests for unsupported CLI error propagation."""

    def _run_with_fake_cli(
        self, cli_name: str = "fakecli", agent: str = "test_agent"
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        tmp = tempfile.mkdtemp()
        tmp_path = Path(tmp)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log_dir = tmp_path / "logs"

        # Create a fake CLI that exists on PATH but isn't codex/claude/gemini
        fake_cli = bin_dir / cli_name
        fake_cli.write_text("#!/usr/bin/env bash\nexit 0\n")
        fake_cli.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

        proc = subprocess.run(
            [
                "bash", WORKER_LOOP,
                "--cli", cli_name,
                "--agent", agent,
                "--once",
                "--project-root", tmp,
                "--log-dir", str(log_dir),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )
        return proc, log_dir

    def test_unsupported_cli_exits_nonzero(self) -> None:
        proc, _ = self._run_with_fake_cli()
        self.assertNotEqual(0, proc.returncode)

    def test_unsupported_cli_error_in_stderr(self) -> None:
        """Helper error 'Unsupported CLI: ...' should appear in stderr."""
        proc, _ = self._run_with_fake_cli()
        self.assertIn("Unsupported CLI: fakecli", proc.stderr)

    def test_worker_cycle_failed_in_stderr(self) -> None:
        """Worker cycle failed message should appear in stderr."""
        proc, _ = self._run_with_fake_cli()
        self.assertIn("worker cycle failed", proc.stderr)

    def test_error_level_in_stderr(self) -> None:
        proc, _ = self._run_with_fake_cli()
        self.assertIn("[ERROR]", proc.stderr)

    def test_does_not_hang(self) -> None:
        """Process should complete well within timeout."""
        import time
        start = time.time()
        self._run_with_fake_cli()
        elapsed = time.time() - start
        self.assertLess(elapsed, _TIMEOUT - 1, "process took too long, may be hanging")

    def test_different_unsupported_cli_name(self) -> None:
        """Error message should include the actual CLI name."""
        proc, _ = self._run_with_fake_cli(cli_name="mycustomtool")
        self.assertIn("Unsupported CLI: mycustomtool", proc.stderr)
        self.assertNotEqual(0, proc.returncode)

    def test_worker_info_log_before_failure(self) -> None:
        """Worker cycle info log should appear before the error."""
        proc, _ = self._run_with_fake_cli()
        self.assertIn("worker cycle=1", proc.stderr)
        self.assertIn("agent=test_agent", proc.stderr)


if __name__ == "__main__":
    unittest.main()
