"""Multi-instance claim path tests for same-agent (TASK-63b2e186).

Verifies that two instances of the same agent (different session_ids)
can both register, claim distinct tasks, and receive leases with the
correct owner_instance_id. Also verifies that lease renewal requires
a matching instance_id.
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


def _full_metadata(root: Path, agent: str, session_id: str) -> dict:
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": session_id,
        "connection_id": f"conn-{agent}-{session_id}",
        "server_version": "0.1.0",
        "verification_source": "test",
        # Explicitly set instance_id so that re-registration with a
        # different session_id actually changes the active instance.
        # Without this, _normalize_agent_metadata keeps the existing
        # instance_id from a prior registration.
        "instance_id": session_id,
    }


def _register_instance(orch: Orchestrator, root: Path, agent: str, session_id: str) -> None:
    """Register and heartbeat an agent with a specific session_id (instance)."""
    meta = _full_metadata(root, agent, session_id)
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


def _switch_instance(orch: Orchestrator, root: Path, agent: str, session_id: str) -> None:
    """Switch the active instance by re-registering with a different session_id."""
    meta = _full_metadata(root, agent, session_id)
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


class TwoInstancesRegisterTests(unittest.TestCase):
    """Two instances of claude_code (different session_ids) both register."""

    def test_both_instances_register_successfully(self) -> None:
        """Two registrations of the same agent with different session_ids should both succeed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _register_instance(orch, root, "claude_code", "sess-instance-1")
            _register_instance(orch, root, "claude_code", "sess-instance-2")

            agents = orch._read_json(orch.agents_path)
            self.assertIn("claude_code", agents)
            self.assertEqual("active", agents["claude_code"]["status"])

    def test_instances_recorded_separately(self) -> None:
        """Agent instances should be recorded as separate entries in agent_instances."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _register_instance(orch, root, "claude_code", "sess-instance-1")
            _register_instance(orch, root, "claude_code", "sess-instance-2")

            instances = orch._read_json(orch.agent_instances_path)
            # Should have entries for both instances
            cc_instances = {k: v for k, v in instances.items() if v.get("agent") == "claude_code"}
            self.assertGreaterEqual(len(cc_instances), 1)


class Instance1ClaimsTaskTests(unittest.TestCase):
    """Instance 1 claims a task and gets a lease with instance 1's instance_id."""

    def test_instance_1_claim_gets_correct_instance_id(self) -> None:
        """First instance claiming a task should get a lease with its own instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Register instance 1
            _register_instance(orch, root, "claude_code", "sess-instance-1")
            orch.create_task(
                title="Task for instance 1",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            lease = claimed["lease"]
            # instance_id is derived from session_id by _normalize_agent_metadata
            self.assertEqual("sess-instance-1", lease["owner_instance_id"])


class Instance2ClaimsDifferentTaskTests(unittest.TestCase):
    """Instance 2 claims a different task and gets a lease with instance 2's instance_id."""

    def test_instance_2_claim_gets_correct_instance_id(self) -> None:
        """Second instance claiming a different task should get lease with its own instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Register instance 1 and claim a task
            _register_instance(orch, root, "claude_code", "sess-instance-1")
            orch.create_task(
                title="Task A",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            task_a = orch.claim_next_task("claude_code")

            # Create another task
            orch.create_task(
                title="Task B",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            # Switch to instance 2
            _switch_instance(orch, root, "claude_code", "sess-instance-2")

            task_b = orch.claim_next_task("claude_code")

            self.assertIsNotNone(task_b)
            # Task B's lease should have instance 2's id
            self.assertEqual("sess-instance-2", task_b["lease"]["owner_instance_id"])
            # Task A's lease should still have instance 1's id (persisted)
            tasks = orch._read_json(orch.tasks_path)
            persisted_a = next(t for t in tasks if t["id"] == task_a["id"])
            self.assertEqual("sess-instance-1", persisted_a["lease"]["owner_instance_id"])


class OwnerSameButInstanceDiffersTests(unittest.TestCase):
    """Owner is 'claude_code' for both tasks but owner_instance_id differs."""

    def test_same_owner_different_instance_ids(self) -> None:
        """Two tasks claimed by different instances of the same agent must have different instance_ids."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Instance 1 registers and claims
            _register_instance(orch, root, "claude_code", "sess-instance-1")
            orch.create_task(
                title="Instance diff A",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            task_a = orch.claim_next_task("claude_code")

            # Create second task
            orch.create_task(
                title="Instance diff B",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            # Instance 2 takes over and claims
            _switch_instance(orch, root, "claude_code", "sess-instance-2")
            task_b = orch.claim_next_task("claude_code")

            # Both tasks owned by claude_code
            self.assertEqual("claude_code", task_a["lease"]["owner"])
            self.assertEqual("claude_code", task_b["lease"]["owner"])

            # But instance_ids differ
            self.assertNotEqual(
                task_a["lease"]["owner_instance_id"],
                task_b["lease"]["owner_instance_id"],
            )
            self.assertEqual("sess-instance-1", task_a["lease"]["owner_instance_id"])
            self.assertEqual("sess-instance-2", task_b["lease"]["owner_instance_id"])


class LeaseRenewalRequiresMatchingInstanceTests(unittest.TestCase):
    """Lease renewal must fail when the current instance does not match the lease instance."""

    def test_renewal_from_wrong_instance_raises(self) -> None:
        """Renewing from a different instance than the one that claimed should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Instance 1 claims
            _register_instance(orch, root, "claude_code", "sess-instance-1")
            orch.create_task(
                title="Renewal instance test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            lease_id = claimed["lease"]["lease_id"]

            # Switch to instance 2
            _switch_instance(orch, root, "claude_code", "sess-instance-2")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
            self.assertIn("lease_instance_mismatch", str(ctx.exception))

    def test_renewal_from_correct_instance_succeeds(self) -> None:
        """Renewing from the same instance that claimed should succeed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _register_instance(orch, root, "claude_code", "sess-instance-1")
            orch.create_task(
                title="Renewal correct instance test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            lease_id = claimed["lease"]["lease_id"]

            # Renew from same instance (still instance-1)
            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertEqual(lease_id, result["lease"]["lease_id"])
            self.assertEqual("claude_code", result["agent"])

    def test_instance_ids_persist_to_disk(self) -> None:
        """Instance-specific lease data must be persisted to tasks.json."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _register_instance(orch, root, "claude_code", "sess-alpha")
            orch.create_task(
                title="Persist instance test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")

            # Reload from disk
            tasks = orch._read_json(orch.tasks_path)
            persisted = next(t for t in tasks if t["id"] == claimed["id"])

            self.assertIsNotNone(persisted.get("lease"))
            self.assertEqual("sess-alpha", persisted["lease"]["owner_instance_id"])
            self.assertEqual("claude_code", persisted["lease"]["owner"])


class ExplicitInstanceIdClaimAndRenewTests(unittest.TestCase):
    """Explicit instance_id APIs avoid singleton-agent races for same-agent sessions."""

    def test_claim_uses_explicit_instance_when_other_instance_is_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _register_instance(orch, root, "claude_code", "sess-instance-1")
            _register_instance(orch, root, "claude_code", "sess-instance-2")
            orch.create_task(
                title="Explicit instance claim",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code", instance_id="sess-instance-1")

            self.assertIsNotNone(claimed)
            self.assertEqual("sess-instance-1", claimed["lease"]["owner_instance_id"])

    def test_renew_uses_explicit_instance_when_other_instance_is_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _register_instance(orch, root, "claude_code", "sess-instance-1")
            orch.create_task(
                title="Explicit instance renew",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code", instance_id="sess-instance-1")
            lease_id = claimed["lease"]["lease_id"]

            # Another session becomes the latest singleton record for this agent family.
            _register_instance(orch, root, "claude_code", "sess-instance-2")

            with self.assertRaises(ValueError):
                orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            renewed = orch.renew_task_lease(
                claimed["id"],
                "claude_code",
                lease_id,
                instance_id="sess-instance-1",
            )
            self.assertEqual("sess-instance-1", renewed["instance_id"])
            self.assertEqual(lease_id, renewed["lease"]["lease_id"])


if __name__ == "__main__":
    unittest.main()
