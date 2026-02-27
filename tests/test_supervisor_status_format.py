"""Tests for supervisor.sh status output format contract.

Validates that status output contains expected fields: process names,
status values (running/stopped/dead), pid, and restart count columns.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = str(REPO_ROOT / "scripts" / "autopilot" / "supervisor.sh")

_TIMEOUT = 30
_PROCS = ("manager", "wingman", "claude", "gemini", "codex_worker", "watchdog")


def _make_stub_cli(stub_dir: Path, name: str) -> None:
    stub = stub_dir / name
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)


def _run(action: str, pid_dir: str, log_dir: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", SUPERVISOR, action,
         "--pid-dir", pid_dir, "--log-dir", log_dir,
         "--manager-cli-timeout", "2", "--worker-cli-timeout", "2",
         "--manager-interval", "9999", "--worker-interval", "9999"],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=_TIMEOUT,
    )


class SupervisorStatusFormatTests(unittest.TestCase):
    """Validate status output structure."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.pid_dir = os.path.join(self.tmp, "pids")
        self.log_dir = os.path.join(self.tmp, "logs")
        self.stub_dir = Path(self.tmp) / "stubs"
        self.stub_dir.mkdir()
        for cli in ("codex", "claude", "gemini"):
            _make_stub_cli(self.stub_dir, cli)
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.stub_dir}:{self.env.get('PATH', '')}"

    def tearDown(self) -> None:
        _run("stop", self.pid_dir, self.log_dir, self.env)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_status_header_contains_project_and_dirs(self) -> None:
        proc = _run("status", self.pid_dir, self.log_dir, self.env)
        self.assertIn("Autopilot supervisor status", proc.stdout)
        self.assertIn("Project:", proc.stdout)
        self.assertIn("PID dir:", proc.stdout)
        self.assertIn("Log dir:", proc.stdout)

    def test_status_lists_all_four_processes(self) -> None:
        proc = _run("status", self.pid_dir, self.log_dir, self.env)
        for name in _PROCS:
            self.assertIn(name, proc.stdout)

    def test_stopped_status_format(self) -> None:
        """Before start, all should show 'stopped' with pid='-'."""
        proc = _run("status", self.pid_dir, self.log_dir, self.env)
        for name in _PROCS:
            # Match: name  stopped  pid=-  restarts=N
            expected_status = "disabled" if name == "codex_worker" else "stopped"
            pattern = rf"{name}\s+{expected_status}\s+pid=-"
            self.assertRegex(proc.stdout, pattern, f"expected stopped format for {name}")

    def test_running_status_has_numeric_pid(self) -> None:
        _run("start", self.pid_dir, self.log_dir, self.env)
        time.sleep(0.5)
        proc = _run("status", self.pid_dir, self.log_dir, self.env)
        # At least some processes should show running with numeric pid
        running_pids = re.findall(r"(\w+)\s+running\s+pid=(\d+)", proc.stdout)
        self.assertGreaterEqual(len(running_pids), 1, "expected at least one running process with pid")

    def test_status_includes_restart_count(self) -> None:
        proc = _run("status", self.pid_dir, self.log_dir, self.env)
        restart_fields = re.findall(r"restarts=(\d+)", proc.stdout)
        self.assertEqual(len(restart_fields), len(_PROCS),
                         f"expected restarts field for each of {len(_PROCS)} processes")

    def test_dead_status_after_kill(self) -> None:
        """Killing a process should result in 'dead' status."""
        _run("start", self.pid_dir, self.log_dir, self.env)
        time.sleep(0.5)
        # Find a running pid and kill it
        status = _run("status", self.pid_dir, self.log_dir, self.env)
        match = re.search(r"(\w+)\s+running\s+pid=(\d+)", status.stdout)
        if match:
            pid = int(match.group(2))
            os.kill(pid, 9)
            time.sleep(0.5)
            status2 = _run("status", self.pid_dir, self.log_dir, self.env)
            self.assertIn("dead", status2.stdout)


if __name__ == "__main__":
    unittest.main()
