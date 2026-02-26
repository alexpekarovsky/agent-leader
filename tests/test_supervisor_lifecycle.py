"""Smoke tests for supervisor.sh start/status/stop lifecycle.

Uses stub CLIs that exit immediately so no real agents are invoked.
All tests are bounded and clean up pid/log artifacts.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = str(REPO_ROOT / "scripts" / "autopilot" / "supervisor.sh")

_TIMEOUT = 30


def _make_stub_cli(stub_dir: Path, name: str) -> None:
    """Create a stub CLI that exits immediately."""
    stub = stub_dir / name
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)


def _run_supervisor(
    action: str,
    *,
    pid_dir: str,
    log_dir: str,
    env: dict[str, str],
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "bash", SUPERVISOR, action,
        "--pid-dir", pid_dir,
        "--log-dir", log_dir,
        "--manager-cli-timeout", "2",
        "--worker-cli-timeout", "2",
        "--manager-interval", "9999",
        "--worker-interval", "9999",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_TIMEOUT,
    )


class SupervisorLifecycleTests(unittest.TestCase):
    """Bounded lifecycle tests with stub CLIs."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.pid_dir = os.path.join(self.tmp, "pids")
        self.log_dir = os.path.join(self.tmp, "logs")
        self.stub_dir = Path(self.tmp) / "stubs"
        self.stub_dir.mkdir()

        # Create stub CLIs so loop scripts pass require_cmd
        for cli in ("codex", "claude", "gemini"):
            _make_stub_cli(self.stub_dir, cli)

        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.stub_dir}:{self.env.get('PATH', '')}"

    def tearDown(self) -> None:
        # Always stop processes to prevent orphans
        _run_supervisor("stop", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_status_before_start_shows_stopped(self) -> None:
        proc = _run_supervisor("status", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        self.assertEqual(0, proc.returncode)
        self.assertIn("stopped", proc.stdout)

    def test_start_creates_pid_files(self) -> None:
        proc = _run_supervisor("start", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        self.assertEqual(0, proc.returncode)
        self.assertIn("Supervisor started", proc.stdout)

        pid_path = Path(self.pid_dir)
        # Should have pid files for managed processes
        pid_files = list(pid_path.glob("*.pid"))
        self.assertGreaterEqual(len(pid_files), 1, "expected at least one pid file")

    def test_start_then_status_shows_info(self) -> None:
        _run_supervisor("start", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        # Brief pause for processes to register
        time.sleep(0.5)
        proc = _run_supervisor("status", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        self.assertEqual(0, proc.returncode)
        self.assertIn("Autopilot supervisor status", proc.stdout)
        # Should show process names
        for name in ("manager", "claude", "gemini", "watchdog"):
            self.assertIn(name, proc.stdout)

    def test_stop_removes_pid_files(self) -> None:
        _run_supervisor("start", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        proc = _run_supervisor("stop", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        self.assertEqual(0, proc.returncode)
        self.assertIn("stopped", proc.stdout.lower() + proc.stderr.lower())

        pid_path = Path(self.pid_dir)
        if pid_path.exists():
            remaining = list(pid_path.glob("*.pid"))
            self.assertEqual(0, len(remaining), f"pid files remain after stop: {remaining}")

    def test_clean_removes_supervisor_logs(self) -> None:
        _run_supervisor("start", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        time.sleep(0.5)
        _run_supervisor("stop", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)

        # Supervisor logs should exist after start
        log_path = Path(self.log_dir)
        sv_logs = list(log_path.glob("supervisor-*.log"))

        proc = _run_supervisor("clean", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        self.assertEqual(0, proc.returncode)

        # After clean, supervisor logs should be gone
        remaining = list(log_path.glob("supervisor-*.log"))
        self.assertEqual(0, len(remaining), f"supervisor logs remain after clean: {remaining}")

    def test_unknown_command_exits_nonzero(self) -> None:
        proc = _run_supervisor("bogus", pid_dir=self.pid_dir, log_dir=self.log_dir, env=self.env)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("Usage", proc.stdout)


if __name__ == "__main__":
    unittest.main()
