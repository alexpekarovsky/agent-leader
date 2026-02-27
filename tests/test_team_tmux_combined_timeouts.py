"""Tests for team_tmux dry-run combined manager/worker CLI timeout propagation.

AL-CORE-29 (TASK-6da0c805): Validates that team_tmux.sh --dry-run propagates
custom manager and worker CLI timeout values simultaneously into generated
commands for manager and both workers.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEAM_TMUX = str(REPO_ROOT / "scripts" / "autopilot" / "team_tmux.sh")

_TIMEOUT = 10


def _dry_run(
    *,
    manager_cli_timeout: int | None = None,
    worker_cli_timeout: int | None = None,
    log_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd: list[str] = ["bash", TEAM_TMUX, "--dry-run"]
    if manager_cli_timeout is not None:
        cmd += ["--manager-cli-timeout", str(manager_cli_timeout)]
    if worker_cli_timeout is not None:
        cmd += ["--worker-cli-timeout", str(worker_cli_timeout)]
    if log_dir is not None:
        cmd += ["--log-dir", log_dir]
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_TIMEOUT,
    )


class TeamTmuxCombinedTimeoutsTests(unittest.TestCase):
    """Deterministic dry-run tests for combined timeout propagation."""

    def test_combined_manager_timeout_in_manager_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_cli_timeout=120, worker_cli_timeout=900, log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            self.assertTrue(manager_lines)
            self.assertIn("--cli-timeout '120'", manager_lines[0])

    def test_combined_worker_timeout_in_claude_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_cli_timeout=120, worker_cli_timeout=900, log_dir=tmp)
            lines = proc.stdout.splitlines()
            claude_lines = [l for l in lines if "worker_loop" in l and "claude" in l]
            self.assertTrue(claude_lines, "no claude worker line found")
            self.assertIn("--cli-timeout '900'", claude_lines[0])

    def test_combined_worker_timeout_in_gemini_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_cli_timeout=120, worker_cli_timeout=900, log_dir=tmp)
            lines = proc.stdout.splitlines()
            gemini_lines = [l for l in lines if "worker_loop" in l and "gemini" in l]
            self.assertTrue(gemini_lines, "no gemini worker line found")
            self.assertIn("--cli-timeout '900'", gemini_lines[0])

    def test_manager_timeout_does_not_leak_to_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_cli_timeout=120, worker_cli_timeout=900, log_dir=tmp)
            lines = proc.stdout.splitlines()
            worker_lines = [l for l in lines if "worker_loop" in l]
            for wl in worker_lines:
                self.assertNotIn("'120'", wl)

    def test_worker_timeout_does_not_leak_to_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_cli_timeout=120, worker_cli_timeout=900, log_dir=tmp)
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            self.assertTrue(manager_lines)
            self.assertNotIn("'900'", manager_lines[0])

    def test_both_workers_have_same_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(worker_cli_timeout=777, log_dir=tmp)
            lines = proc.stdout.splitlines()
            worker_lines = [l for l in lines if "worker_loop" in l]
            self.assertEqual(3, len(worker_lines))
            for wl in worker_lines:
                self.assertIn("--cli-timeout '777'", wl)


if __name__ == "__main__":
    unittest.main()
