"""Tests for team_tmux.sh --dry-run output: session name and CLI timeout propagation.

Verifies that custom --session, --manager-cli-timeout, and --worker-cli-timeout
values appear in the rendered dry-run plan.  Runs without tmux installed and
completes in bounded time (subprocess timeout).
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEAM_TMUX = str(REPO_ROOT / "scripts" / "autopilot" / "team_tmux.sh")

# Subprocess timeout – keeps every test bounded even if the script hangs.
_TIMEOUT = 10


def _dry_run(
    *,
    session: str | None = None,
    manager_cli_timeout: int | None = None,
    worker_cli_timeout: int | None = None,
    log_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke team_tmux.sh --dry-run with optional overrides."""
    cmd: list[str] = ["bash", TEAM_TMUX, "--dry-run"]
    if session is not None:
        cmd += ["--session", session]
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


class TeamTmuxDryRunTests(unittest.TestCase):
    """Deterministic tests that need no tmux binary."""

    def test_dry_run_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertEqual(0, proc.returncode)

    def test_default_session_name_in_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertIn("Session: agents-autopilot", proc.stdout)
            self.assertIn("agents-autopilot", proc.stdout)

    def test_custom_session_name_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(session="my-custom-session", log_dir=tmp)
            self.assertIn("Session: my-custom-session", proc.stdout)
            # Session name should appear in tmux new-session command
            self.assertIn("tmux new-session -d -s my-custom-session", proc.stdout)

    def test_custom_manager_cli_timeout_in_manager_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_cli_timeout=42, log_dir=tmp)
            # Extract manager_loop line and verify timeout
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            self.assertTrue(manager_lines, "no manager_loop line in dry-run output")
            self.assertIn("--cli-timeout '42'", manager_lines[0])

    def test_custom_worker_cli_timeout_in_worker_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(worker_cli_timeout=99, log_dir=tmp)
            lines = proc.stdout.splitlines()
            worker_lines = [l for l in lines if "worker_loop" in l]
            # Should have 2 worker lines (claude + gemini)
            self.assertEqual(2, len(worker_lines), f"expected 2 worker lines, got {len(worker_lines)}")
            for wl in worker_lines:
                self.assertIn("--cli-timeout '99'", wl)

    def test_manager_and_worker_timeouts_are_independent(self) -> None:
        """Manager timeout should not leak into worker commands and vice versa."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(
                manager_cli_timeout=111,
                worker_cli_timeout=222,
                log_dir=tmp,
            )
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            worker_lines = [l for l in lines if "worker_loop" in l]

            self.assertTrue(manager_lines)
            self.assertTrue(worker_lines)

            # Manager gets 111, not 222
            self.assertIn("--cli-timeout '111'", manager_lines[0])
            self.assertNotIn("222", manager_lines[0])

            # Workers get 222, not 111
            for wl in worker_lines:
                self.assertIn("--cli-timeout '222'", wl)
                self.assertNotIn("111", wl)

    def test_default_timeouts_in_output(self) -> None:
        """Default values (manager=300, worker=600) appear when no overrides given."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            worker_lines = [l for l in lines if "worker_loop" in l]

            self.assertIn("--cli-timeout '300'", manager_lines[0])
            for wl in worker_lines:
                self.assertIn("--cli-timeout '600'", wl)

    def test_all_tmux_commands_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertIn("tmux new-session", proc.stdout)
            self.assertIn("tmux split-window", proc.stdout)
            self.assertIn("tmux new-window", proc.stdout)
            self.assertIn("tmux select-layout", proc.stdout)

    def test_log_dir_propagated_to_loop_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            # manager, claude worker, gemini worker, watchdog use --log-dir;
            # monitor_loop does not, so exclude it.
            loop_lines = [
                l for l in lines
                if "_loop" in l and "tmux" in l and "monitor_loop" not in l
            ]
            self.assertEqual(4, len(loop_lines), f"expected 4 loop commands, got {len(loop_lines)}")
            for ll in loop_lines:
                self.assertIn(tmp, ll, f"log dir not in command: {ll}")


if __name__ == "__main__":
    unittest.main()
