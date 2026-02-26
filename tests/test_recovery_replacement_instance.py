"""CORE-04 lease expiry recovery for replacement same-family instance.

Tests that when an agent re-registers with a new session (replacement instance),
expired leases are recovered and the new instance can claim the requeued task.
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


def _register(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.register_agent(agent, metadata={
        "client": "test", "model": "test", "cwd": str(orch.root),
        "project_root": str(orch.root), "permissions_mode": "default",
        "sandbox_mode": "workspace-write", "session_id": session_id,
        "connection_id": f"conn-{agent}-{session_id}", "server_version": "0.1.0",
        "verification_source": "test",
        "instance_id": session_id,
    })


def _heartbeat(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.heartbeat(agent, metadata={
        "client": "test", "model": "test", "cwd": str(orch.root),
        "project_root": str(orch.root), "permissions_mode": "default",
        "sandbox_mode": "workspace-write", "session_id": session_id,
        "connection_id": f"conn-{agent}-{session_id}", "server_version": "0.1.0",
        "verification_source": "test",
        "instance_id": session_id,
    })


def _expire_lease(orch: Orchestrator, task_id: str) -> None:
    """Manually set lease expiry in the past to simulate expiration."""
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == task_id and isinstance(t.get("lease"), dict):
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)


class RecoveryReplacementInstanceTests(unittest.TestCase):
    """CORE-04: lease expiry recovery for replacement same-family instance."""

    def test_agent_registers_with_session1_claims_task_lease_issued(self) -> None:
        """Agent registers with session-1, claims task, and a lease is issued."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-1")
            task = orch.create_task(
                title="Test task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])
            lease = claimed.get("lease")
            self.assertIsNotNone(lease)
            self.assertIn("lease_id", lease)
            self.assertEqual("claude_code", lease["owner"])
            self.assertEqual("sess-1", lease["owner_instance_id"])

    def test_reregister_with_session2_updates_instance(self) -> None:
        """Agent re-registering with session-2 updates the active instance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-1")
            _register(orch, "claude_code", session_id="sess-2")

            agents = orch._read_json(orch.agents_path)
            instance_id = agents["claude_code"]["metadata"]["instance_id"]
            self.assertEqual("sess-2", instance_id)

    def test_expired_lease_recovered_and_requeued(self) -> None:
        """Expired lease is recovered and the task is requeued to assigned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-1")
            task = orch.create_task(
                title="Recovery target",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")

            # Re-register with new session (replacement instance)
            _register(orch, "claude_code", session_id="sess-2")
            _heartbeat(orch, "claude_code", session_id="sess-2")

            # Expire the lease
            _expire_lease(orch, claimed["id"])

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual("requeued", result["recovered"][0]["action"])

            # Task should be back to assigned
            tasks = orch.list_tasks()
            recovered = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("assigned", recovered["status"])

    def test_new_instance_can_claim_requeued_task(self) -> None:
        """The new session-2 instance can claim the requeued task."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-1")
            task = orch.create_task(
                title="Reclaimable task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            task_id = claimed["id"]

            # Replacement instance
            _register(orch, "claude_code", session_id="sess-2")
            _heartbeat(orch, "claude_code", session_id="sess-2")

            # Expire and recover
            _expire_lease(orch, task_id)
            orch.recover_expired_task_leases(source="codex")

            # New instance claims
            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(task_id, reclaimed["id"])
            self.assertEqual("in_progress", reclaimed["status"])

    def test_new_lease_has_session2_instance_id(self) -> None:
        """After reclaim, the new lease should carry the session-2 instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-1")
            task = orch.create_task(
                title="Instance check task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            task_id = claimed["id"]

            # Replacement instance
            _register(orch, "claude_code", session_id="sess-2")
            _heartbeat(orch, "claude_code", session_id="sess-2")

            # Expire and recover
            _expire_lease(orch, task_id)
            orch.recover_expired_task_leases(source="codex")

            # Reclaim with new instance
            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            new_lease = reclaimed["lease"]
            self.assertIsNotNone(new_lease)
            self.assertEqual("sess-2", new_lease["owner_instance_id"])

    def test_old_instance_lease_fully_cleared(self) -> None:
        """After recovery, the old instance's lease is fully cleared (None)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-1")
            task = orch.create_task(
                title="Clearance task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            task_id = claimed["id"]

            # Replacement
            _register(orch, "claude_code", session_id="sess-2")
            _heartbeat(orch, "claude_code", session_id="sess-2")

            # Expire
            _expire_lease(orch, task_id)

            # Recovery clears lease
            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task_id)
            self.assertIsNone(recovered.get("lease"))
            self.assertIn("lease_recovery_at", recovered)

    def test_full_replacement_lifecycle(self) -> None:
        """Full lifecycle: register sess-1, claim, re-register sess-2, expire, recover, reclaim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Step 1: Agent registers with session-1 and claims a task
            _register(orch, "claude_code", session_id="sess-1")
            task = orch.create_task(
                title="Full lifecycle task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            task_id = claimed["id"]
            original_lease_id = claimed["lease"]["lease_id"]
            self.assertEqual("sess-1", claimed["lease"]["owner_instance_id"])

            # Step 2: Agent re-registers with session-2 (new instance)
            _register(orch, "claude_code", session_id="sess-2")
            _heartbeat(orch, "claude_code", session_id="sess-2")

            # Step 3: Lease expires
            _expire_lease(orch, task_id)

            # Step 4: Recovery requeues the task
            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(1, result["recovered_count"])

            # Step 5: New instance claims the requeued task
            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(task_id, reclaimed["id"])
            self.assertEqual("in_progress", reclaimed["status"])

            # Step 6: New lease has session-2's instance_id
            new_lease = reclaimed["lease"]
            self.assertEqual("sess-2", new_lease["owner_instance_id"])
            self.assertNotEqual(original_lease_id, new_lease["lease_id"])

            # Step 7: Verify old lease is gone (task has new lease)
            tasks = orch._read_json(orch.tasks_path)
            task_record = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("sess-2", task_record["lease"]["owner_instance_id"])


if __name__ == "__main__":
    unittest.main()
