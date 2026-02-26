"""Tests for team_tmux dry-run watchdog command and interval flag.

AL-CORE-33 (TASK-873f4b92): Validates that dry-run output contains the
watchdog_loop command and the expected --interval 15 argument in the
printed tmux split command.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEAM_TMUX = str(REPO_ROOT / "scripts" / "autopilot" / "team_tmux.sh")

_TIMEOUT = 10


def _dry_run(*, log_dir: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", TEAM_TMUX, "--dry-run", "--log-dir", log_dir],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_TIMEOUT,
    )


class TeamTmuxWatchdogCommandTests(unittest.TestCase):
    """Deterministic dry-run tests for watchdog command presence."""

    def test_watchdog_command_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            self.assertIn("watchdog_loop", proc.stdout)

    def test_watchdog_interval_is_15(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            watchdog_lines = [l for l in lines if "watchdog_loop" in l]
            self.assertTrue(watchdog_lines, "no watchdog_loop line found")
            self.assertIn("--interval 15", watchdog_lines[0])

    def test_watchdog_in_split_window_command(self) -> None:
        """Watchdog should be in a tmux split-window command."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            watchdog_lines = [l for l in lines if "watchdog_loop" in l]
            self.assertTrue(watchdog_lines)
            self.assertIn("tmux split-window", watchdog_lines[0])

    def test_watchdog_uses_log_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            watchdog_lines = [l for l in lines if "watchdog_loop" in l]
            self.assertTrue(watchdog_lines)
            self.assertIn(tmp, watchdog_lines[0])

    def test_watchdog_uses_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            watchdog_lines = [l for l in lines if "watchdog_loop" in l]
            self.assertTrue(watchdog_lines)
            self.assertIn("--project-root", watchdog_lines[0])


if __name__ == "__main__":
    unittest.main()
