"""Lease expiry requeue state transition tests (TASK-9de55796).

Verifies that expired leases cause correct state transitions:
- expired lease requeues task to 'assigned'
- expired lease clears lease field to None
- requeued task gets lease_recovery_at timestamp
- requeued task can be claimed again
- non-expired leases are left untouched
- multiple expired tasks are all recovered
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
        "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str) -> dict:
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_agent(orch: Orchestrator, root: Path, agent: str) -> None:
    """Register and heartbeat an agent so it is operational."""
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))


def _make_expired_task(orch: Orchestrator, root: Path, agent: str = "claude_code", title: str = "Expire me") -> dict:
    """Create a task, claim it, then manually expire its lease."""
    task = orch.create_task(
        title=title,
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    claimed = orch.claim_next_task(agent)
    # Manually expire the lease by backdating expires_at
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == claimed["id"]:
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)
    return claimed


class ExpiredLeaseRequeuesToAssignedTests(unittest.TestCase):
    """Expired lease recovery must transition task back to assigned status."""

    def test_expired_lease_requeues_to_assigned(self) -> None:
        """Task with expired lease must be set back to 'assigned' after recovery."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = _make_expired_task(orch, root, "claude_code")
            # Keep agent active with fresh heartbeat
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("assigned", recovered["status"])

    def test_expired_lease_clears_lease_to_none(self) -> None:
        """After recovery, the lease field must be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = _make_expired_task(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(recovered.get("lease"))

    def test_expired_task_gets_lease_recovery_at(self) -> None:
        """Recovered task must have a lease_recovery_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = _make_expired_task(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIn("lease_recovery_at", recovered)
            self.assertIsNotNone(recovered["lease_recovery_at"])
            # Should be a parseable ISO timestamp
            self.assertIn("T", recovered["lease_recovery_at"])

    def test_requeued_task_can_be_claimed_again(self) -> None:
        """After recovery, the task must be claimable by the same agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = _make_expired_task(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(task["id"], reclaimed["id"])
            self.assertEqual("in_progress", reclaimed["status"])
            self.assertIsNotNone(reclaimed.get("lease"))
            self.assertTrue(reclaimed["lease"]["lease_id"].startswith("LEASE-"))

    def test_non_expired_lease_is_not_requeued(self) -> None:
        """A task with a valid (non-expired) lease must NOT be recovered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Active lease task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            # Do NOT expire the lease

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(0, result["recovered_count"])
            self.assertEqual([], result["recovered"])
            # Task should still be in_progress with its lease
            tasks = orch._read_json(orch.tasks_path)
            task = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("in_progress", task["status"])
            self.assertIsNotNone(task.get("lease"))

    def test_multiple_expired_tasks_all_requeued(self) -> None:
        """When multiple tasks have expired leases, all must be recovered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            expired_ids = []
            for i in range(3):
                task = _make_expired_task(orch, root, "claude_code", title=f"Expire task {i}")
                expired_ids.append(task["id"])

            # Keep agent active
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(3, result["recovered_count"])
            tasks = orch._read_json(orch.tasks_path)
            for task_id in expired_ids:
                recovered = next(t for t in tasks if t["id"] == task_id)
                self.assertEqual("assigned", recovered["status"])
                self.assertIsNone(recovered.get("lease"))
                self.assertIsNotNone(recovered.get("lease_recovery_at"))

    def test_recovery_result_contains_expected_fields(self) -> None:
        """Recovery result dict must contain recovered_count, recovered, active_agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _make_expired_task(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertIn("recovered_count", result)
            self.assertIn("recovered", result)
            self.assertIn("active_agents", result)
            self.assertIn("threshold_seconds", result)
            self.assertIsInstance(result["recovered"], list)
            self.assertIsInstance(result["active_agents"], list)


if __name__ == "__main__":
    unittest.main()
