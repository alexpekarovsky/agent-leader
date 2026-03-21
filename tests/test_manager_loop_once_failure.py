"""Tests for manager_loop.sh --once failure exit-code propagation.

AL-CORE-16 (TASK-53733337): Validates that manager_loop.sh propagates
non-zero exit codes when using --once mode with an unsupported CLI,
mirroring the worker_loop regression class.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "manager_loop.sh")

_TIMEOUT = 10


class ManagerLoopOnceFailureTests(unittest.TestCase):
    """Bounded tests for --once exit-code propagation on CLI failure."""

    def _run_manager(
        self, args: list[str], *, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        return subprocess.run(
            ["bash", MANAGER_LOOP, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
            env=merged_env,
        )

    def test_unsupported_cli_once_exits_nonzero(self) -> None:
        """--once with unsupported CLI should exit non-zero."""
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake_cli = bin_dir / "fakecli"
            fake_cli.write_text("#!/usr/bin/env bash\nexit 0\n")
            fake_cli.chmod(0o755)

            proc = self._run_manager(
                [
                    "--cli", "fakecli",
                    "--once",
                    "--project-root", tmp,
                    "--log-dir", str(Path(tmp) / "logs"),
                ],
                env={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            self.assertNotEqual(0, proc.returncode)

    def test_unsupported_cli_once_stderr_has_error_text(self) -> None:
        """Unsupported CLI error message should appear in stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake_cli = bin_dir / "fakecli"
            fake_cli.write_text("#!/usr/bin/env bash\nexit 0\n")
            fake_cli.chmod(0o755)

            proc = self._run_manager(
                [
                    "--cli", "fakecli",
                    "--once",
                    "--project-root", tmp,
                    "--log-dir", str(Path(tmp) / "logs"),
                ],
                env={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            self.assertIn("Unsupported CLI: fakecli", proc.stderr)

    def test_unsupported_cli_once_stderr_has_cycle_failed(self) -> None:
        """manager cycle failed message should appear in stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake_cli = bin_dir / "fakecli"
            fake_cli.write_text("#!/usr/bin/env bash\nexit 0\n")
            fake_cli.chmod(0o755)

            proc = self._run_manager(
                [
                    "--cli", "fakecli",
                    "--once",
                    "--project-root", tmp,
                    "--log-dir", str(Path(tmp) / "logs"),
                ],
                env={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            self.assertIn("manager cycle failed", proc.stderr)

    def test_unsupported_cli_once_log_dir_created(self) -> None:
        """Log directory should be created even on failure."""
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake_cli = bin_dir / "fakecli"
            fake_cli.write_text("#!/usr/bin/env bash\nexit 0\n")
            fake_cli.chmod(0o755)
            log_dir = Path(tmp) / "logs"

            self._run_manager(
                [
                    "--cli", "fakecli",
                    "--once",
                    "--project-root", tmp,
                    "--log-dir", str(log_dir),
                ],
                env={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            self.assertTrue(log_dir.exists(), "log directory should be created")

    def test_missing_cli_command_once_exits_nonzero(self) -> None:
        """--once with a CLI not on PATH should exit non-zero via require_cmd."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run_manager(
                [
                    "--cli", "nonexistent_cli_xyz",
                    "--once",
                    "--project-root", tmp,
                    "--log-dir", str(Path(tmp) / "logs"),
                ],
            )
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("Missing required command", proc.stderr)



