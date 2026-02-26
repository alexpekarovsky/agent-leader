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

    @staticmethod
    def _decode_stream(data: object) -> str:
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    def _run_and_capture_with_env(
        self,
        project_root: str,
        *,
        interval: str = _INTERVAL,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        """Run monitor_loop and return (stdout, stderr), tolerating timeout."""
        env = os.environ.copy()
        env["TERM"] = "dumb"
        if extra_env:
            env.update(extra_env)
        try:
            proc = subprocess.run(
                ["bash", MONITOR_LOOP, project_root, interval],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_TIMEOUT,
                env=env,
            )
            return proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            return self._decode_stream(exc.stdout), self._decode_stream(exc.stderr)

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

    def test_project_path_on_startup_is_first_content_line(self) -> None:
        """AL-CORE-32: project path must appear as the first non-empty output line."""
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_and_capture(tmp)
            # Filter out empty lines; first content line should be the project path
            content_lines = [l for l in output.splitlines() if l.strip()]
            self.assertTrue(content_lines, "no output from monitor_loop")
            self.assertEqual(f"project={tmp}", content_lines[0])

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

    def test_missing_logs_directory_does_not_emit_ls_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout, stderr = self._run_and_capture_with_env(tmp)
            self.assertIn(f"project={tmp}", stdout)
            self.assertNotIn("No such file", stdout)
            self.assertNotIn("No such file", stderr)

    def test_codex_list_output_is_capped_to_five_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake_codex = bin_dir / "codex"
            fake_codex.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"${1:-}\" = \"mcp\" ] && [ \"${2:-}\" = \"list\" ]; then\n"
                "  printf 'line1\\nline2\\nline3\\nline4\\nline5\\nline6\\nline7\\n'\n"
                "fi\n"
            )
            fake_codex.chmod(0o755)

            stdout, _ = self._run_and_capture_with_env(
                tmp,
                extra_env={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            for line in ("line1", "line2", "line3", "line4", "line5"):
                self.assertIn(line, stdout)
            self.assertNotIn("line6", stdout)
            self.assertNotIn("line7", stdout)

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
