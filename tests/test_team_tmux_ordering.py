"""Tests for team_tmux.sh --dry-run command ordering consistency.

AL-CORE-20 (TASK-6fab5022): Validates that dry-run output prints tmux
commands in the expected order for the current topology:
new-session (manager), new-window (workers), split-window x3
(gemini/wingman/watchdog), new-window (monitor), select-layout.
"""
from __future__ import annotations

import re
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


class TeamTmuxCommandOrderingTests(unittest.TestCase):
    """Deterministic tests for dry-run command ordering."""

    def _get_tmux_commands(self, log_dir: str) -> list[str]:
        proc = _dry_run(log_dir=log_dir)
        self.assertEqual(0, proc.returncode)
        return [
            line.strip()
            for line in proc.stdout.splitlines()
            if line.strip().startswith("tmux ")
        ]

    def test_new_session_comes_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmds = self._get_tmux_commands(tmp)
            self.assertTrue(cmds, "no tmux commands found")
            self.assertTrue(cmds[0].startswith("tmux new-session"))

    def test_split_windows_follow_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmds = self._get_tmux_commands(tmp)
            split_indices = [i for i, c in enumerate(cmds) if "split-window" in c]
            self.assertEqual(3, len(split_indices), "expected 3 split-window commands")
            # All splits should come after new-session (index 0)
            for idx in split_indices:
                self.assertGreater(idx, 0)

    def test_new_window_monitor_after_splits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmds = self._get_tmux_commands(tmp)
            split_indices = [i for i, c in enumerate(cmds) if "split-window" in c]
            monitor_window_indices = [i for i, c in enumerate(cmds) if "new-window" in c and " -n monitor " in c]
            self.assertEqual(1, len(monitor_window_indices))
            self.assertGreater(monitor_window_indices[0], max(split_indices))

    def test_select_layout_comes_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmds = self._get_tmux_commands(tmp)
            layout_indices = [i for i, c in enumerate(cmds) if "select-layout" in c]
            self.assertEqual(1, len(layout_indices))
            self.assertEqual(len(cmds) - 1, layout_indices[0])

    def test_total_tmux_command_count(self) -> None:
        """Should have 7 tmux commands in default topology."""
        with tempfile.TemporaryDirectory() as tmp:
            cmds = self._get_tmux_commands(tmp)
            self.assertEqual(7, len(cmds))

    def test_manager_in_first_split_context(self) -> None:
        """First split-window should reference manager pane context."""
        with tempfile.TemporaryDirectory() as tmp:
            cmds = self._get_tmux_commands(tmp)
            splits = [c for c in cmds if "split-window" in c]
            # First split should be for claude worker (split from manager)
            self.assertIn("worker_loop", splits[0])


if __name__ == "__main__":
    unittest.main()
