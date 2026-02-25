"""Smoke tests for monitor_loop.sh output stability.

Validates that monitor_loop.sh starts, prints the project header, and
handles missing or empty log directories without crashing.  Uses
subprocess timeout to keep every test bounded.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MONITOR_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "monitor_loop.sh")

# Short interval so the loop iterates quickly; timeout kills it.
_INTERVAL = "1"
_TIMEOUT = 5


def _run_monitor(
    project_root: str,
    interval: str = _INTERVAL,
    timeout: int = _TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run monitor_loop.sh with a timeout, expecting it to be killed."""
    env = os.environ.copy()
    # Ensure 'clear' is a no-op so it doesn't emit terminal escapes.
    env["TERM"] = "dumb"
    proc = subprocess.run(
        ["bash", MONITOR_LOOP, project_root, interval],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env=env,
    )
    return proc


class MonitorLoopSmokeTests(unittest.TestCase):
    """Bounded smoke tests — no live codex MCP dependency."""

    def _run_and_capture(
        self, project_root: str, interval: str = _INTERVAL
    ) -> str:
        """Run monitor_loop and return stdout, tolerating timeout."""
        try:
            proc = _run_monitor(project_root, interval)
            return proc.stdout
        except subprocess.TimeoutExpired as exc:
            # Expected: the loop runs forever until killed.
            return exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""

    def test_prints_project_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_and_capture(tmp)
            self.assertIn(f"project={tmp}", output)

    def test_handles_missing_logs_directory(self) -> None:
        """No .autopilot-logs dir — should not crash."""
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / ".autopilot-logs"
            self.assertFalse(logs_dir.exists())
            output = self._run_and_capture(tmp)
            # Script should still print project header without crashing
            self.assertIn(f"project={tmp}", output)

    def test_handles_empty_logs_directory(self) -> None:
        """Empty .autopilot-logs dir — should not crash."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".autopilot-logs").mkdir()
            output = self._run_and_capture(tmp)
            self.assertIn(f"project={tmp}", output)

    def test_lists_log_files_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / ".autopilot-logs"
            logs_dir.mkdir()
            (logs_dir / "manager-codex-20260101-000000.log").write_text("cycle\n")
            (logs_dir / "worker-claude-20260101-000000.log").write_text("cycle\n")
            output = self._run_and_capture(tmp)
            self.assertIn("manager-codex", output)
            self.assertIn("worker-claude", output)

    def test_bounded_runtime(self) -> None:
        """Verify the loop is killed within the timeout window."""
        with tempfile.TemporaryDirectory() as tmp:
            import time

            start = time.time()
            self._run_and_capture(tmp, interval="1")
            elapsed = time.time() - start
            self.assertLess(elapsed, _TIMEOUT + 2)


if __name__ == "__main__":
    unittest.main()
