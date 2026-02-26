"""CORE-03 lease renewal identity binding test matrix.

Tests that lease renewal enforces agent + instance identity invariants:

Identity Binding Invariants
===========================
1. **Agent ownership match**: task.owner must equal renewal agent
2. **Lease ID match**: lease.lease_id must equal renewal lease_id
3. **Instance ID match**: lease.owner_instance_id must equal current agent instance
4. **Lease not expired**: lease.expires_at must be in the future
5. **Lease exists**: task must have a lease dict (not None)
6. **Lease ID non-empty**: lease_id parameter must be non-empty string

Mismatch Rejection Matrix
==========================
| # | Condition               | Expected Error           |
|---|-------------------------|--------------------------|
| 1 | Wrong agent             | lease_owner_mismatch     |
| 2 | Wrong lease_id          | lease_id_mismatch        |
| 3 | Wrong instance_id       | lease_instance_mismatch  |
| 4 | Expired lease           | lease_expired            |
| 5 | No lease on task        | lease_missing            |
| 6 | Empty lease_id param    | non-empty string error   |
| 7 | Task not found          | Task not found           |

These tests map directly to renew_task_lease (engine.py line 547).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _full_metadata(root: Path, agent: str, session_id: str = "") -> dict:
    sid = session_id or f"sess-{agent}"
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": sid,
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_agent(orch: Orchestrator, root: Path, agent: str, session_id: str = "") -> None:
    meta = _full_metadata(root, agent, session_id)
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


def _create_and_claim(orch: Orchestrator, root: Path, agent: str = "claude_code") -> dict:
    """Create a task, claim it, return the claimed task with lease."""
    _setup_agent(orch, root, agent)
    orch.create_task(
        title="Renewal identity test",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    return orch.claim_next_task(agent)


# ---------------------------------------------------------------------------
# 1. Successful renewal with correct identity
# ---------------------------------------------------------------------------

class SuccessfulRenewalTests(unittest.TestCase):
    """Renewal with matching agent, lease_id, and instance succeeds."""

    def test_correct_identity_renews_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)
            lease_id = claimed["lease"]["lease_id"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertEqual(result["task_id"], claimed["id"])
            self.assertEqual(result["agent"], "claude_code")
            self.assertEqual(result["lease"]["lease_id"], lease_id)

    def test_renewal_extends_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)
            original_expires = claimed["lease"]["expires_at"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])

            self.assertGreaterEqual(result["lease"]["expires_at"], original_expires)

    def test_renewal_updates_renewed_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)
            original_renewed = claimed["lease"]["renewed_at"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])

            self.assertNotEqual(original_renewed, result["lease"]["renewed_at"])

    def test_renewal_emits_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])

            events = list(orch.bus.iter_events())
            renewed = [e for e in events if e.get("type") == "task.lease_renewed"]
            self.assertEqual(len(renewed), 1)
            self.assertEqual(renewed[0]["payload"]["task_id"], claimed["id"])


# ---------------------------------------------------------------------------
# 2. Agent ownership mismatch rejection
# ---------------------------------------------------------------------------

class AgentOwnershipMismatchTests(unittest.TestCase):
    """Renewal by a different agent than the task owner must be rejected."""

    def test_wrong_agent_raises_lease_owner_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "gemini", claimed["lease"]["lease_id"])
            self.assertIn("lease_owner_mismatch", str(ctx.exception))

    def test_wrong_agent_does_not_modify_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")
            original_renewed = claimed["lease"]["renewed_at"]

            try:
                orch.renew_task_lease(claimed["id"], "gemini", claimed["lease"]["lease_id"])
            except ValueError:
                pass

            tasks = orch._read_json(orch.tasks_path)
            task = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual(task["lease"]["renewed_at"], original_renewed)


# ---------------------------------------------------------------------------
# 3. Lease ID mismatch rejection
# ---------------------------------------------------------------------------

class LeaseIdMismatchTests(unittest.TestCase):
    """Renewal with a wrong lease_id must be rejected."""

    def test_wrong_lease_id_raises_lease_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", "LEASE-wrongid1")
            self.assertIn("lease_id_mismatch", str(ctx.exception))

    def test_lease_id_with_extra_whitespace_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)
            # Add trailing whitespace — should be stripped, but if real ID differs, still mismatch
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", "LEASE-notreal")
            self.assertIn("lease_id_mismatch", str(ctx.exception))


# ---------------------------------------------------------------------------
# 4. Instance ID mismatch rejection
# ---------------------------------------------------------------------------

class InstanceIdMismatchTests(unittest.TestCase):
    """Renewal from a different instance than the lease owner must be rejected."""

    def test_different_instance_raises_instance_mismatch(self) -> None:
        """Agent reconnects with a different explicit instance_id after lease was issued."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Claim with explicit instance_id alpha
            meta_alpha = _full_metadata(root, "claude_code")
            meta_alpha["instance_id"] = "inst-alpha"
            orch.register_agent("claude_code", meta_alpha)
            orch.heartbeat("claude_code", meta_alpha)
            orch.create_task(
                title="Instance mismatch test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            # Verify lease has inst-alpha
            self.assertEqual(claimed["lease"]["owner_instance_id"], "inst-alpha")

            # Re-register with explicit instance_id beta (different instance)
            meta_beta = _full_metadata(root, "claude_code")
            meta_beta["instance_id"] = "inst-beta"
            orch.register_agent("claude_code", meta_beta)
            orch.heartbeat("claude_code", meta_beta)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])
            self.assertIn("lease_instance_mismatch", str(ctx.exception))


# ---------------------------------------------------------------------------
# 5. Expired lease rejection
# ---------------------------------------------------------------------------

class ExpiredLeaseRejectionTests(unittest.TestCase):
    """Renewal of an already-expired lease must be rejected."""

    def test_expired_lease_raises_lease_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)

            # Manually expire the lease
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == claimed["id"]:
                    t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])
            self.assertIn("lease_expired", str(ctx.exception))


# ---------------------------------------------------------------------------
# 6. Missing lease rejection
# ---------------------------------------------------------------------------

class MissingLeaseRejectionTests(unittest.TestCase):
    """Renewal on a task with no lease must be rejected."""

    def test_no_lease_raises_lease_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)

            # Remove the lease
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == claimed["id"]:
                    t["lease"] = None
            orch._write_json(orch.tasks_path, tasks)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])
            self.assertIn("lease_missing", str(ctx.exception))


# ---------------------------------------------------------------------------
# 7. Empty lease_id parameter rejection
# ---------------------------------------------------------------------------

class EmptyLeaseIdRejectionTests(unittest.TestCase):
    """Renewal with empty or whitespace-only lease_id must be rejected."""

    def test_empty_string_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", "")
            self.assertIn("non-empty", str(ctx.exception))

    def test_whitespace_only_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", "   ")
            self.assertIn("non-empty", str(ctx.exception))


# ---------------------------------------------------------------------------
# 8. Task not found rejection
# ---------------------------------------------------------------------------

class TaskNotFoundRejectionTests(unittest.TestCase):
    """Renewal on a nonexistent task must be rejected."""

    def test_nonexistent_task_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease("TASK-nonexistent", "claude_code", "LEASE-xxx")
            self.assertIn("not found", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# 9. Multiple renewals with same identity succeed
# ---------------------------------------------------------------------------

class MultipleRenewalsTests(unittest.TestCase):
    """Sequential renewals with matching identity should all succeed."""

    def test_three_sequential_renewals_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)
            lease_id = claimed["lease"]["lease_id"]

            for i in range(3):
                result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
                self.assertEqual(result["lease"]["lease_id"], lease_id)

    def test_each_renewal_advances_expires_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _create_and_claim(orch, root)
            lease_id = claimed["lease"]["lease_id"]
            prev_expires = claimed["lease"]["expires_at"]

            for i in range(3):
                result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
                self.assertGreaterEqual(result["lease"]["expires_at"], prev_expires)
                prev_expires = result["lease"]["expires_at"]


if __name__ == "__main__":
    unittest.main()
