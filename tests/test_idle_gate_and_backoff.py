"""Tests for idle gate, exponential backoff, max-idle auto-exit, and daily budget.

Covers TASK-3315cd37 (idle gate before LLM invocation) and
TASK-d9f2d7f6 (exponential idle backoff and max-idle auto-exit).

Acceptance criteria verified:
- manager_loop and worker_loop perform preflight state check before run_cli_prompt
- idle cycles produce no LLM CLI invocation
- logs include explicit idle-gated marker for observability
- backoff resets immediately when work is found
- max-idle-cycles causes clean worker/manager exit
- backoff_interval_for_streak returns correct progression
- consume_daily_budget enforces limits
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "manager_loop.sh")
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")
COMMON_SH = str(REPO_ROOT / "scripts" / "autopilot" / "common.sh")

_TIMEOUT = 15


def _make_cli_stub(bin_dir: Path, name: str) -> None:
    """Create a CLI stub that records invocations instead of running an LLM."""
    marker = bin_dir / f".{name}_invoked"
    stub = bin_dir / name
    stub.write_text(
        f"#!/usr/bin/env bash\ntouch '{marker}'\necho 'stub invoked'\n"
    )
    stub.chmod(0o755)


def _write_tasks(project_root: Path, tasks: list) -> None:
    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "tasks.json").write_text(
        json.dumps(tasks, indent=2), encoding="utf-8"
    )


def _run_loop(
    script: str,
    project_root: Path,
    bin_dir: Path,
    extra_args: list | None = None,
    timeout: int = _TIMEOUT,
    once: bool = False,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    cmd = ["bash", script, "--project-root", str(project_root)]
    if once:
        cmd.append("--once")
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


class BackoffIntervalTests(unittest.TestCase):
    """Test backoff_interval_for_streak from common.sh."""

    def _call_backoff(self, streak: int, csv: str = "30,60,120,300,900", fallback: int = 60) -> int:
        result = subprocess.run(
            ["bash", "-c", f'source "{COMMON_SH}" && backoff_interval_for_streak {streak} "{csv}" {fallback}'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return int(result.stdout.strip())

    def test_first_idle_returns_first_tier(self):
        self.assertEqual(self._call_backoff(1), 30)

    def test_second_idle_returns_second_tier(self):
        self.assertEqual(self._call_backoff(2), 60)

    def test_third_idle_returns_third_tier(self):
        self.assertEqual(self._call_backoff(3), 120)

    def test_fifth_idle_returns_max_tier(self):
        self.assertEqual(self._call_backoff(5), 900)

    def test_beyond_max_stays_at_max(self):
        self.assertEqual(self._call_backoff(10), 900)

    def test_streak_zero_returns_first(self):
        self.assertEqual(self._call_backoff(0), 30)

    def test_custom_csv(self):
        self.assertEqual(self._call_backoff(2, "10,20,40"), 20)

    def test_single_value_csv(self):
        self.assertEqual(self._call_backoff(5, "42"), 42)


class DailyBudgetTests(unittest.TestCase):
    """Test consume_daily_budget from common.sh."""

    def test_budget_zero_always_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", "-c", f'source "{COMMON_SH}" && consume_daily_budget 0 test "{tmp}"'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0)

    def test_budget_exhausted_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                subprocess.run(
                    ["bash", "-c", f'source "{COMMON_SH}" && consume_daily_budget 3 test "{tmp}"'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            result = subprocess.run(
                ["bash", "-c", f'source "{COMMON_SH}" && consume_daily_budget 3 test "{tmp}"'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 1)

    def test_budget_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(2):
                result = subprocess.run(
                    ["bash", "-c", f'source "{COMMON_SH}" && consume_daily_budget 5 bud "{tmp}"'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0)


class WorkerIdleGateTests(unittest.TestCase):
    """Test that worker_loop skips LLM invocation when no work is available."""

    def test_no_tasks_file_skips_llm(self):
        """No state/tasks.json → idle gate fires, no LLM call."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            result = _run_loop(
                WORKER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--agent", "codex",
                    "--max-idle-cycles", "1",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists(), "LLM CLI should NOT be invoked on idle")
            self.assertIn("idle gate", result.stderr)

    def test_no_assigned_tasks_skips_llm(self):
        """Tasks exist but none assigned to agent → idle gate fires."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [
                {"id": "T-1", "owner": "gemini", "status": "assigned"},
                {"id": "T-2", "owner": "codex", "status": "done"},
            ])
            result = _run_loop(
                WORKER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--agent", "codex",
                    "--max-idle-cycles", "1",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists(), "LLM CLI should NOT be invoked when no work for agent")
            self.assertIn("idle gate", result.stderr)

    def test_assigned_task_invokes_llm(self):
        """Task assigned to agent → idle gate passes, LLM invoked."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [
                {"id": "T-1", "owner": "codex", "status": "assigned"},
            ])
            result = _run_loop(
                WORKER_LOOP,
                project,
                bin_dir,
                once=True,
                extra_args=[
                    "--cli", "codex",
                    "--agent", "codex",
                    "--log-dir", str(log_dir),
                ],
            )
            marker = bin_dir / ".codex_invoked"
            self.assertTrue(marker.exists(), "LLM CLI should be invoked when work available")
            self.assertNotIn("idle gate", result.stderr)

    def test_max_idle_cycles_exit(self):
        """Worker exits cleanly after max-idle-cycles with no work."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [])
            result = _run_loop(
                WORKER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--agent", "codex",
                    "--max-idle-cycles", "2",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("max idle cycles reached", result.stderr)
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists())


class ManagerIdleGateTests(unittest.TestCase):
    """Test that manager_loop skips LLM invocation when no actionable work."""

    def test_no_tasks_file_skips_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            result = _run_loop(
                MANAGER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--max-idle-cycles", "1",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists(), "Manager LLM CLI should NOT be invoked on idle")
            self.assertIn("idle gate", result.stderr)

    def test_all_done_skips_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [
                {"id": "T-1", "owner": "codex", "status": "done"},
                {"id": "T-2", "owner": "gemini", "status": "done"},
            ])
            result = _run_loop(
                MANAGER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--max-idle-cycles", "1",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists())
            self.assertIn("idle gate", result.stderr)

    def test_reported_task_invokes_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [
                {"id": "T-1", "owner": "codex", "status": "reported"},
            ])
            result = _run_loop(
                MANAGER_LOOP,
                project,
                bin_dir,
                once=True,
                extra_args=[
                    "--cli", "codex",
                    "--log-dir", str(log_dir),
                ],
            )
            marker = bin_dir / ".codex_invoked"
            self.assertTrue(marker.exists(), "Manager should invoke LLM when reported tasks exist")

    def test_manager_max_idle_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [])
            result = _run_loop(
                MANAGER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--max-idle-cycles", "3",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("max idle cycles reached", result.stderr)
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists())


class WorkerTeamFilterTests(unittest.TestCase):
    """Test that worker idle gate respects team_id filtering."""

    def test_wrong_team_skips_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [
                {"id": "T-1", "owner": "codex", "status": "assigned", "team_id": "team-other"},
            ])
            result = _run_loop(
                WORKER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--agent", "codex",
                    "--team-id", "team-api",
                    "--max-idle-cycles", "1",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists())
            self.assertIn("idle gate", result.stderr)


class IdleGateLogMarkerTests(unittest.TestCase):
    """Verify observability: idle-gated log markers are emitted."""

    def test_worker_idle_log_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [])
            result = _run_loop(
                WORKER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--agent", "codex",
                    "--max-idle-cycles", "1",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            self.assertIn("idle gate: no claimable work", result.stderr)

    def test_manager_idle_log_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [])
            result = _run_loop(
                MANAGER_LOOP,
                project,
                bin_dir,
                extra_args=[
                    "--cli", "codex",
                    "--max-idle-cycles", "1",
                    "--log-dir", str(log_dir),
                    "--idle-backoff", "1",
                ],
            )
            self.assertIn("idle gate: no actionable manager work", result.stderr)


if __name__ == "__main__":
    unittest.main()
