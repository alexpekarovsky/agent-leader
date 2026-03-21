"""Tests for manager_loop/worker_loop --max-logs propagation to pruning.

AL-CORE-08 (TASK-10d71ac2): verifies both loops honor --max-logs by
running one bounded timeout cycle and asserting prefixed logs are pruned.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "manager_loop.sh")
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")

_TIMEOUT = 15


def _make_sleeping_stub(bin_dir: Path, name: str, sleep_seconds: int = 5) -> None:
    stub = bin_dir / name
    stub.write_text(f"#!/usr/bin/env bash\nsleep {sleep_seconds}\n")
    stub.chmod(0o755)


def _touch(path: Path, mtime: int) -> None:
    path.write_text("old\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))


class LoopMaxLogsPropagationTests(unittest.TestCase):
    def test_manager_loop_max_logs_prunes_manager_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            log_dir = tmp_path / "logs"
            bin_dir.mkdir()
            log_dir.mkdir()
            _make_sleeping_stub(bin_dir, "codex")

            # Seed 3 older manager logs; run should create one more then prune to <=2.
            for i in range(3):
                _touch(log_dir / f"manager-codex-20250101-00000{i}.log", 1000 + i)
            _touch(log_dir / "worker-claude_code-codex-20250101-000000.log", 999)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            proc = subprocess.run(
                [
                    "bash",
                    MANAGER_LOOP,
                    "--cli",
                    "codex",
                    "--once",
                    "--project-root",
                    str(REPO_ROOT),
                    "--log-dir",
                    str(log_dir),
                    "--cli-timeout",
                    "1",
                    "--max-logs",
                    "2",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_TIMEOUT,
            )
            self.assertNotEqual(0, proc.returncode)  # timeout path is expected in --once
            manager_logs = list(log_dir.glob("manager-codex-*.log"))
            worker_logs = list(log_dir.glob("worker-claude_code-*.log"))
            self.assertLessEqual(len(manager_logs), 2)
            self.assertEqual(1, len(worker_logs), "unrelated prefixed logs should be untouched")

    def test_worker_loop_max_logs_prunes_worker_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            log_dir = tmp_path / "logs"
            bin_dir.mkdir()
            log_dir.mkdir()
            _make_sleeping_stub(bin_dir, "codex")

            for i in range(3):
                _touch(log_dir / f"worker-claude_code-codex-20250101-00000{i}.log", 2000 + i)
            _touch(log_dir / "manager-codex-20250101-000000.log", 1999)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            proc = subprocess.run(
                [
                    "bash",
                    WORKER_LOOP,
                    "--cli",
                    "codex",
                    "--agent",
                    "claude_code",
                    "--once",
                    "--project-root",
                    str(REPO_ROOT),
                    "--log-dir",
                    str(log_dir),
                    "--cli-timeout",
                    "1",
                    "--max-logs",
                    "2",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_TIMEOUT,
            )
            self.assertNotEqual(0, proc.returncode)
            worker_logs = list(log_dir.glob("worker-claude_code-codex-*.log"))
            manager_logs = list(log_dir.glob("manager-codex-*.log"))
            self.assertLessEqual(len(worker_logs), 2)
            self.assertEqual(1, len(manager_logs), "unrelated prefixed logs should be untouched")



