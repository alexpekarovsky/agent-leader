"""Tests for manager_loop timeout log naming and stderr message consistency.

AL-CORE-22 (TASK-f028e203): Validates that manager_loop timeout path emits
consistent stderr message format and writes a manager-{cli}-{ts}.log file
name matching documented patterns.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "manager_loop.sh")

_TIMEOUT = 15


def _make_sleeping_stub(bin_dir: Path, name: str, sleep_seconds: int = 5) -> None:
    """Create a fake CLI that sleeps longer than the configured timeout."""
    stub = bin_dir / name
    stub.write_text(
        f"#!/usr/bin/env bash\nsleep {sleep_seconds}\n"
    )
    stub.chmod(0o755)


class ManagerLoopTimeoutNamingTests(unittest.TestCase):
    """Bounded tests for timeout log naming and stderr messages."""

    def _run_manager_timeout(
        self, cli_name: str = "codex", cli_timeout: int = 1
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        tmp = tempfile.mkdtemp()
        tmp_path = Path(tmp)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log_dir = tmp_path / "logs"

        _make_sleeping_stub(bin_dir, cli_name, sleep_seconds=5)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

        proc = subprocess.run(
            [
                "bash", MANAGER_LOOP,
                "--cli", cli_name,
                "--once",
                "--project-root", str(REPO_ROOT),
                "--log-dir", str(log_dir),
                "--cli-timeout", str(cli_timeout),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )
        return proc, log_dir

    def test_timeout_stderr_message_format(self) -> None:
        """Stderr should contain 'manager cycle timed out after Ns'."""
        proc, _ = self._run_manager_timeout()
        self.assertIn("manager cycle timed out after 1s", proc.stderr)

    def test_timeout_stderr_has_error_level(self) -> None:
        proc, _ = self._run_manager_timeout()
        self.assertIn("[ERROR]", proc.stderr)

    def test_timeout_stderr_references_log_file(self) -> None:
        proc, _ = self._run_manager_timeout()
        self.assertIn("see ", proc.stderr)
        self.assertIn("manager-codex-", proc.stderr)

    def test_timeout_log_filename_pattern(self) -> None:
        """Log file should match manager-{cli}-YYYYMMDD-HHMMSS.log."""
        _, log_dir = self._run_manager_timeout()
        log_files = list(log_dir.glob("manager-codex-*.log"))
        self.assertEqual(1, len(log_files), f"expected 1 log file, got {len(log_files)}")
        name = log_files[0].name
        pattern = r"^manager-codex-\d{8}-\d{6}\.log$"
        self.assertRegex(name, pattern)

    def test_timeout_log_contains_marker(self) -> None:
        """Log file should contain the [AUTOPILOT] CLI timeout marker."""
        _, log_dir = self._run_manager_timeout()
        log_files = list(log_dir.glob("manager-codex-*.log"))
        self.assertTrue(log_files, "no log file created")
        content = log_files[0].read_text(encoding="utf-8")
        self.assertIn("[AUTOPILOT] CLI timeout after 1s for codex", content)

    def test_timeout_exits_nonzero_in_once_mode(self) -> None:
        proc, _ = self._run_manager_timeout()
        self.assertNotEqual(0, proc.returncode)


if __name__ == "__main__":
    unittest.main()
