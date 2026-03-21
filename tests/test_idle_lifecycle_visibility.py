"""Tests for idle lifecycle visibility semantics.

Verifies that supervisor _status_proc() correctly maps process names to
heartbeat agent names and provides meaningful status for all process types
including leader (manager), workers, and watchdog.

Acceptance criteria covered:
- Leader heartbeat is represented correctly in status output.
- Watchdog classifies its state explicitly instead of showing 'unknown'.
- Idle lifecycle visibility is tested for leader/worker/watchdog.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy
from orchestrator.supervisor import ProcessStatus, Supervisor, SupervisorConfig


def _make_policy(path: Path) -> Policy:
    data = {
        "name": "test-policy",
        "manager": "codex",
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "architecture_mode": "solo",
        "triggers": {},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _make_supervisor(root: Path, orch: Orchestrator, **overrides) -> Supervisor:
    cfg = SupervisorConfig(
        project_root=str(root),
        log_dir=str(root / "logs"),
        pid_dir=str(root / "pids"),
        **overrides,
    )
    return Supervisor(cfg, orch)


def _agent_metadata(root: Path, **extra) -> dict:
    """Minimal metadata for a verified heartbeat in tests."""
    base = {
        "project_root": str(root),
        "cwd": str(root),
        "client": "test",
        "model": "test-model",
        "instance_id": "test#1",
        "session_id": "test-session",
        "connection_id": "test-conn",
        "server_version": "test",
        "verification_source": "test",
        "permissions_mode": "default",
        "sandbox_mode": False,
    }
    base.update(extra)
    return base


class LeaderHeartbeatVisibilityTests(unittest.TestCase):
    """Leader (manager process) heartbeat maps to the leader agent."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_manager_queries_leader_agent_codex(self) -> None:
        """When leader_agent=codex, manager status queries 'codex' heartbeat."""
        self.orch.heartbeat("codex", metadata=_agent_metadata(self.root, role="leader"))
        sv = _make_supervisor(self.root, self.orch, leader_agent="codex")
        ps = sv._status_proc("manager")
        self.assertEqual(ps.heartbeat_status, "active",
                         "manager should reflect codex leader heartbeat as active")

    def test_manager_queries_leader_agent_claude(self) -> None:
        """When leader_agent=claude_code, manager status queries 'claude_code'."""
        self.orch.heartbeat("claude_code", metadata=_agent_metadata(self.root, role="leader"))
        sv = _make_supervisor(self.root, self.orch, leader_agent="claude_code")
        ps = sv._status_proc("manager")
        self.assertEqual(ps.heartbeat_status, "active",
                         "manager should reflect claude_code leader heartbeat as active")

    def test_manager_unknown_when_no_leader_heartbeat(self) -> None:
        """Without a leader heartbeat, manager status should be 'unknown'."""
        sv = _make_supervisor(self.root, self.orch, leader_agent="codex")
        ps = sv._status_proc("manager")
        self.assertEqual(ps.heartbeat_status, "unknown")

    def test_manager_idle_when_leader_has_no_tasks(self) -> None:
        """Leader with heartbeat but no tasks → task_activity='idle'."""
        self.orch.heartbeat("codex", metadata=_agent_metadata(self.root, role="leader"))
        sv = _make_supervisor(self.root, self.orch, leader_agent="codex")
        ps = sv._status_proc("manager")
        self.assertEqual(ps.task_activity, "idle")


class WorkerHeartbeatMappingTests(unittest.TestCase):
    """Worker processes map to correct agent names for heartbeat queries."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_claude_process_maps_to_claude_code_agent(self) -> None:
        """Process 'claude' should query agent 'claude_code'."""
        self.orch.heartbeat("claude_code", metadata=_agent_metadata(self.root, role="team_member"))
        sv = _make_supervisor(self.root, self.orch, leader_agent="codex")
        ps = sv._status_proc("claude")
        self.assertEqual(ps.heartbeat_status, "active")

    def test_wingman_process_maps_to_wingman_agent(self) -> None:
        """Process 'wingman' should query agent configured as wingman_agent."""
        self.orch.heartbeat("ccm", metadata=_agent_metadata(self.root, role="team_member"))
        sv = _make_supervisor(self.root, self.orch, wingman_agent="ccm")
        ps = sv._status_proc("wingman")
        self.assertEqual(ps.heartbeat_status, "active")

    def test_codex_worker_maps_to_codex_agent(self) -> None:
        """Process 'codex_worker' should query agent 'codex'."""
        self.orch.heartbeat("codex", metadata=_agent_metadata(self.root, role="team_member"))
        # codex_worker is disabled when leader_agent=codex, use claude_code leader
        sv = _make_supervisor(self.root, self.orch, leader_agent="claude_code")
        ps = sv._status_proc("codex_worker")
        self.assertEqual(ps.heartbeat_status, "active")

    def test_gemini_process_maps_to_gemini_agent(self) -> None:
        """Process 'gemini' should query agent 'gemini'."""
        self.orch.heartbeat("gemini", metadata=_agent_metadata(self.root, role="team_member"))
        sv = _make_supervisor(self.root, self.orch, leader_agent="codex")
        ps = sv._status_proc("gemini")
        self.assertEqual(ps.heartbeat_status, "active")

    def test_worker_working_when_task_in_progress(self) -> None:
        """Worker with in_progress task shows task_activity='working'."""
        meta = _agent_metadata(self.root)
        self.orch.register_agent("claude_code", metadata=meta)
        self.orch.heartbeat("claude_code", metadata=meta)
        resolved_root = str(self.root.resolve())
        task = self.orch.create_task(
            title="test task", workstream="test",
            acceptance_criteria=["done"], owner="claude_code",
            project_root=resolved_root, project_name=self.root.resolve().name,
        )
        # Directly transition task to in_progress to test status visibility.
        self.orch.set_task_status(task["id"], "in_progress", source="claude_code")
        sv = _make_supervisor(self.root, self.orch, leader_agent="codex")
        ps = sv._status_proc("claude")
        self.assertEqual(ps.task_activity, "working")


class WatchdogVisibilityTests(unittest.TestCase):
    """Watchdog process shows meaningful status instead of 'unknown'."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        self.pid_dir = self.root / "pids"
        self.pid_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_watchdog_stopped_shows_na_heartbeat(self) -> None:
        """Watchdog with no PID file → heartbeat='n/a', activity='idle'."""
        sv = _make_supervisor(self.root, self.orch)
        ps = sv._status_proc("watchdog")
        self.assertEqual(ps.heartbeat_status, "n/a",
                         "stopped watchdog should show 'n/a' not 'unknown'")
        self.assertEqual(ps.task_activity, "idle")

    def test_watchdog_running_shows_active_monitoring(self) -> None:
        """Watchdog with live PID → heartbeat='active', activity='monitoring'."""
        # Write our own PID as a fake alive watchdog
        pid_file = self.pid_dir / "watchdog.pid"
        pid_file.write_text(str(os.getpid()))
        sv = _make_supervisor(self.root, self.orch)
        ps = sv._status_proc("watchdog")
        self.assertEqual(ps.heartbeat_status, "active",
                         "running watchdog should show 'active'")
        self.assertEqual(ps.task_activity, "monitoring",
                         "running watchdog should show 'monitoring'")

    def test_watchdog_dead_shows_na_idle(self) -> None:
        """Watchdog with stale PID (dead process) → heartbeat='n/a', state='dead'."""
        pid_file = self.pid_dir / "watchdog.pid"
        pid_file.write_text("999999")  # likely dead PID
        sv = _make_supervisor(self.root, self.orch)
        ps = sv._status_proc("watchdog")
        self.assertEqual(ps.heartbeat_status, "n/a")
        self.assertEqual(ps.task_activity, "idle")
        self.assertEqual(ps.state, "dead")

    def test_watchdog_never_disabled(self) -> None:
        """Watchdog should always be enabled regardless of leader_agent."""
        from orchestrator.supervisor import proc_enabled
        for leader in ("codex", "claude_code", "gemini"):
            self.assertTrue(proc_enabled("watchdog", leader),
                            f"watchdog should be enabled with leader_agent={leader}")


class StatusJsonVisibilityTests(unittest.TestCase):
    """status_json() includes correct heartbeat/activity for all processes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_status_json_watchdog_not_unknown(self) -> None:
        """Watchdog entry in status_json should not have heartbeat='unknown'."""
        sv = _make_supervisor(self.root, self.orch)
        entries = sv.status_json()
        watchdog = next(e for e in entries if e["name"] == "watchdog")
        self.assertNotEqual(watchdog["heartbeat_status"], "unknown",
                            "watchdog heartbeat should be classified, not 'unknown'")

    def test_status_json_manager_reflects_leader_heartbeat(self) -> None:
        """Manager entry picks up leader agent heartbeat."""
        self.orch.heartbeat("codex", metadata=_agent_metadata(self.root, role="leader"))
        sv = _make_supervisor(self.root, self.orch, leader_agent="codex")
        entries = sv.status_json()
        manager = next(e for e in entries if e["name"] == "manager")
        self.assertEqual(manager["heartbeat_status"], "active")
        self.assertEqual(manager["task_activity"], "idle")


if __name__ == "__main__":
    unittest.main()
