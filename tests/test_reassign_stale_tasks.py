"""Tests for reassign_stale_tasks_to_active_workers.

Validates stale agent detection, task reassignment to active workers,
blocked task handling, diagnostics output, and edge cases.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _register_agent(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"cid-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    })


def _make_agent_stale(orch: Orchestrator, agent: str) -> None:
    """Set an agent's last_seen to a very old timestamp so it appears stale."""
    agents = orch._read_json(orch.agents_path)
    if agent in agents:
        agents[agent]["last_seen"] = "2020-01-01T00:00:00+00:00"
        orch._write_json(orch.agents_path, agents)


def _create_and_claim(orch: Orchestrator, title: str, owner: str) -> str:
    task = orch.create_task(
        title=title,
        workstream="backend",
        acceptance_criteria=["done"],
        owner=owner,
    )
    orch.claim_next_task(owner)
    return task["id"]


class ReassignStaleBasicTests(unittest.TestCase):
    """Basic stale task reassignment tests."""

    def test_no_stale_agents_no_reassignment(self) -> None:
        """When all owners are active, no tasks should be reassigned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            task_id = _create_and_claim(orch, "Active owner task", "claude_code")

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertEqual(0, result["reassigned_count"])
            self.assertEqual([], result["reassigned"])

    def test_stale_owner_task_reassigned(self) -> None:
        """A task owned by a stale agent should be reassigned to an active agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task_id = _create_and_claim(orch, "Stale owner task", "claude_code")

            # Make claude_code stale, keep gemini active
            _make_agent_stale(orch, "claude_code")
            # Refresh gemini's heartbeat
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertEqual(1, result["reassigned_count"])
            self.assertEqual("claude_code", result["reassigned"][0]["from_owner"])

    def test_reassigned_task_status_becomes_assigned(self) -> None:
        """After reassignment, the task status should be 'assigned'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task_id = _create_and_claim(orch, "Status check task", "claude_code")

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            tasks = orch.list_tasks()
            task = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("assigned", task["status"])

    def test_reassigned_task_has_metadata(self) -> None:
        """Reassigned task should have reassigned_from, reason, and degraded_comm fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task_id = _create_and_claim(orch, "Metadata check", "claude_code")

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            tasks = orch.list_tasks()
            task = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("claude_code", task["reassigned_from"])
            self.assertTrue(task["degraded_comm"])
            self.assertIn("stale", task.get("reassigned_reason", ""))


class ReassignBlockedTests(unittest.TestCase):
    """Tests for blocked task handling in reassignment."""

    def test_blocked_task_reassigned_by_default(self) -> None:
        """include_blocked=True (default) should reassign blocked tasks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task_id = _create_and_claim(orch, "Blocked task", "claude_code")

            # Block the task
            orch.raise_blocker(task_id, "claude_code", "Need spec")

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertEqual(1, result["reassigned_count"])

    def test_blocked_task_not_reassigned_when_excluded(self) -> None:
        """include_blocked=False should skip blocked tasks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task_id = _create_and_claim(orch, "Blocked excluded", "claude_code")

            orch.raise_blocker(task_id, "claude_code", "Need spec")

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
                include_blocked=False,
            )

            self.assertEqual(0, result["reassigned_count"])


class ReassignEdgeCaseTests(unittest.TestCase):
    """Edge case tests for reassignment."""

    def test_no_active_workers_no_reassignment(self) -> None:
        """When no active workers exist, tasks should not be reassigned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            task_id = _create_and_claim(orch, "No workers task", "claude_code")

            _make_agent_stale(orch, "claude_code")

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertEqual(0, result["reassigned_count"])

    def test_no_tasks_returns_empty(self) -> None:
        """With no tasks, result should show zero reassignments."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertEqual(0, result["reassigned_count"])
            self.assertEqual([], result["reassigned"])

    def test_reported_tasks_not_reassigned(self) -> None:
        """Reported tasks should never be reassigned (manager validation first)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task_id = _create_and_claim(orch, "Reported task", "claude_code")

            # Submit report to move to reported
            orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "test", "passed": 1, "failed": 0},
            })

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertEqual(0, result["reassigned_count"])

    def test_assigned_tasks_not_reassigned(self) -> None:
        """Tasks in 'assigned' status should not be reassigned (not in_progress)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            # Create but don't claim
            orch.create_task(
                title="Assigned task",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
            )

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertEqual(0, result["reassigned_count"])


class ReassignResultStructureTests(unittest.TestCase):
    """Tests for the result structure of reassignment."""

    def test_result_has_required_keys(self) -> None:
        """Result should contain reassigned_count, threshold_seconds, reassigned, active_agents, timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            self.assertIn("reassigned_count", result)
            self.assertIn("threshold_seconds", result)
            self.assertIn("reassigned", result)
            self.assertIn("active_agents", result)
            self.assertIn("timestamp", result)

    def test_threshold_matches_input(self) -> None:
        """threshold_seconds should match the input stale_after_seconds."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=42,
            )

            self.assertEqual(42, result["threshold_seconds"])

    def test_reassignment_payload_has_diagnostics(self) -> None:
        """Each reassignment entry should contain task_id, from/to owner, reason, and diagnostic."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task_id = _create_and_claim(orch, "Diag check", "claude_code")

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            entry = result["reassigned"][0]
            self.assertEqual(task_id, entry["task_id"])
            self.assertEqual("claude_code", entry["from_owner"])
            self.assertEqual("owner_stale", entry["reason"])
            self.assertIn("owner_diagnostic", entry)

    def test_emits_reassignment_event(self) -> None:
        """Each reassignment should emit a task.reassigned_stale event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            _create_and_claim(orch, "Event task", "claude_code")

            _make_agent_stale(orch, "claude_code")
            orch.heartbeat("gemini", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gemini", "connection_id": "cid-gemini",
                "server_version": "0.1.0", "verification_source": "test",
            })

            orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600,
            )

            events = list(orch.bus.iter_events())
            reassign_events = [e for e in events if e["type"] == "task.reassigned_stale"]
            self.assertGreaterEqual(len(reassign_events), 1)


if __name__ == "__main__":
    unittest.main()
