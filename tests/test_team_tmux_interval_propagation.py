"""Tests for team_tmux.sh --dry-run custom interval propagation.

AL-CORE-18 (TASK-1aa2ea52): Validates that team_tmux.sh --dry-run propagates
custom --manager-interval and --worker-interval values into generated commands.
No tmux dependency required.
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
    manager_interval: int | None = None,
    worker_interval: int | None = None,
    log_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd: list[str] = ["bash", TEAM_TMUX, "--dry-run"]
    if manager_interval is not None:
        cmd += ["--manager-interval", str(manager_interval)]
    if worker_interval is not None:
        cmd += ["--worker-interval", str(worker_interval)]
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


class TeamTmuxIntervalPropagationTests(unittest.TestCase):
    """Deterministic dry-run tests for interval propagation."""

    def test_custom_manager_interval_in_manager_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_interval=45, log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            self.assertTrue(manager_lines, "no manager_loop line in output")
            self.assertIn("--interval '45'", manager_lines[0])

    def test_custom_worker_interval_in_worker_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(worker_interval=60, log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            lines = proc.stdout.splitlines()
            worker_lines = [l for l in lines if "worker_loop" in l]
            self.assertEqual(3, len(worker_lines), f"expected 3 worker lines, got {len(worker_lines)}")
            for wl in worker_lines:
                self.assertIn("--interval '60'", wl)

    def test_manager_and_worker_intervals_are_independent(self) -> None:
        """Manager interval should not appear in worker commands and vice versa."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_interval=45, worker_interval=60, log_dir=tmp)
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            worker_lines = [l for l in lines if "worker_loop" in l]

            self.assertTrue(manager_lines)
            self.assertTrue(worker_lines)

            # Manager gets 45
            self.assertIn("--interval '45'", manager_lines[0])
            # Workers get 60
            for wl in worker_lines:
                self.assertIn("--interval '60'", wl)

    def test_default_intervals_in_output(self) -> None:
        """Default values (manager=20, worker=25) appear when no overrides given."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            worker_lines = [l for l in lines if "worker_loop" in l]

            self.assertIn("--interval '20'", manager_lines[0])
            for wl in worker_lines:
                self.assertIn("--interval '25'", wl)

    def test_watchdog_interval_is_fixed(self) -> None:
        """Watchdog interval is hardcoded to 15 regardless of manager/worker overrides."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_interval=99, worker_interval=99, log_dir=tmp)
            lines = proc.stdout.splitlines()
            watchdog_lines = [l for l in lines if "watchdog_loop" in l]
            self.assertTrue(watchdog_lines, "no watchdog_loop line in output")
            self.assertIn("--interval 15", watchdog_lines[0])


if __name__ == "__main__":
    unittest.main()
