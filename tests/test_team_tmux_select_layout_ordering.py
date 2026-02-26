"""Tests for team_tmux dry-run select-layout ordering.

AL-CORE-34 (TASK-6e227e1a): Validates that select-layout command appears
after all session/window/split commands in dry-run output.
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


class TeamTmuxSelectLayoutOrderingTests(unittest.TestCase):
    """Deterministic tests for select-layout command position."""

    def _get_tmux_lines(self) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            return [l for l in proc.stdout.splitlines() if l.startswith("tmux ")]

    def test_select_layout_is_last_tmux_command(self) -> None:
        lines = self._get_tmux_lines()
        self.assertTrue(lines, "no tmux commands found")
        self.assertIn("select-layout", lines[-1])

    def test_select_layout_after_new_session(self) -> None:
        lines = self._get_tmux_lines()
        session_idx = next(i for i, l in enumerate(lines) if "new-session" in l)
        layout_idx = next(i for i, l in enumerate(lines) if "select-layout" in l)
        self.assertGreater(layout_idx, session_idx)

    def test_select_layout_after_all_splits(self) -> None:
        lines = self._get_tmux_lines()
        split_indices = [i for i, l in enumerate(lines) if "split-window" in l]
        layout_idx = next(i for i, l in enumerate(lines) if "select-layout" in l)
        for si in split_indices:
            self.assertGreater(layout_idx, si)

    def test_select_layout_after_new_window(self) -> None:
        lines = self._get_tmux_lines()
        window_idx = next(i for i, l in enumerate(lines) if "new-window" in l)
        layout_idx = next(i for i, l in enumerate(lines) if "select-layout" in l)
        self.assertGreater(layout_idx, window_idx)

    def test_select_layout_uses_tiled(self) -> None:
        lines = self._get_tmux_lines()
        layout_line = next(l for l in lines if "select-layout" in l)
        self.assertIn("tiled", layout_line)


if __name__ == "__main__":
    unittest.main()
