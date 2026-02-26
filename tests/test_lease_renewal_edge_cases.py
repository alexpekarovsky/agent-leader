"""Tests for renew_task_lease edge cases.

Covers: empty lease_id, task not found, owner mismatch, lease missing,
lease_id mismatch, instance mismatch, expired lease, successful renewal,
and event emission.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
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


def _setup_claimed_task(orch: Orchestrator, root: Path, agent: str = "claude_code") -> dict:
    """Create a task, register agent, claim it, return the task with lease."""
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))
    task = orch.create_task(
        title="Lease renewal test task",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    claimed = orch.claim_next_task(agent)
    return claimed


class RenewLeaseValidationTests(unittest.TestCase):
    """Tests for renew_task_lease input validation."""

    def test_empty_lease_id_rejected(self) -> None:
        """Empty lease_id should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "")
            self.assertIn("non-empty", str(ctx.exception))

    def test_whitespace_only_lease_id_rejected(self) -> None:
        """Whitespace-only lease_id should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "   ")
            self.assertIn("non-empty", str(ctx.exception))

    def test_task_not_found_rejected(self) -> None:
        """Nonexistent task_id should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.register_agent("claude_code", _full_metadata(root, "claude_code"))
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease("TASK-nonexistent", "claude_code", "LEASE-abc")
            self.assertIn("not found", str(ctx.exception).lower())

    def test_owner_mismatch_rejected(self) -> None:
        """Agent that doesn't own the task should be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root, "claude_code")
            lease_id = task.get("lease", {}).get("lease_id", "")
            # Register gemini as well
            orch.register_agent("gemini", _full_metadata(root, "gemini"))
            orch.heartbeat("gemini", _full_metadata(root, "gemini"))
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "gemini", lease_id)
            self.assertIn("lease_owner_mismatch", str(ctx.exception))

    def test_lease_missing_rejected(self) -> None:
        """Task without lease should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.register_agent("claude_code", _full_metadata(root, "claude_code"))
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            task = orch.create_task(
                title="No lease task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            # Manually set status to in_progress without a lease
            orch.set_task_status(task["id"], "in_progress", "codex")
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-fake")
            self.assertIn("lease_missing", str(ctx.exception))

    def test_lease_id_mismatch_rejected(self) -> None:
        """Wrong lease_id should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-wrong-id")
            self.assertIn("lease_id_mismatch", str(ctx.exception))

    def test_expired_lease_rejected(self) -> None:
        """Expired lease should raise ValueError on renewal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task.get("lease", {}).get("lease_id", "")
            # Manually expire the lease
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == task["id"]:
                    t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", lease_id)
            self.assertIn("lease_expired", str(ctx.exception))


class RenewLeaseSuccessTests(unittest.TestCase):
    """Tests for successful lease renewal."""

    def test_successful_renewal_returns_updated_lease(self) -> None:
        """Successful renewal should return dict with updated lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertEqual(task["id"], result["task_id"])
            self.assertEqual("claude_code", result["agent"])
            self.assertIn("lease", result)
            self.assertEqual(lease_id, result["lease"]["lease_id"])

    def test_renewal_updates_renewed_at(self) -> None:
        """renewed_at should change after renewal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]
            original_renewed_at = task["lease"]["renewed_at"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertNotEqual(original_renewed_at, result["lease"]["renewed_at"])

    def test_renewal_extends_expires_at(self) -> None:
        """expires_at should be pushed forward after renewal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]
            original_expires = task["lease"]["expires_at"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            new_expires = result["lease"]["expires_at"]
            # New expires should be >= original (renewal extends it)
            self.assertGreaterEqual(new_expires, original_expires)

    def test_renewal_emits_event(self) -> None:
        """Successful renewal should emit a task.lease_renewed event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]
            # Clear events
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.renew_task_lease(task["id"], "claude_code", lease_id)

            events = list(orch.bus.iter_events())
            renewal_events = [e for e in events if e.get("type") == "task.lease_renewed"]
            self.assertEqual(1, len(renewal_events))
            self.assertEqual(task["id"], renewal_events[0]["payload"]["task_id"])
            self.assertEqual("claude_code", renewal_events[0]["payload"]["agent"])

    def test_renewal_persists_to_disk(self) -> None:
        """After renewal, reloading tasks should show updated lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]

            orch.renew_task_lease(task["id"], "claude_code", lease_id)

            # Re-read tasks from disk
            tasks = orch._read_json(orch.tasks_path)
            persisted = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNotNone(persisted["lease"])
            self.assertEqual(lease_id, persisted["lease"]["lease_id"])

    def test_multiple_renewals_succeed(self) -> None:
        """Multiple consecutive renewals should all succeed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]

            for _ in range(3):
                result = orch.renew_task_lease(task["id"], "claude_code", lease_id)
                self.assertEqual(lease_id, result["lease"]["lease_id"])


class RenewLeaseTTLTests(unittest.TestCase):
    """Tests for lease TTL configuration on renewal."""

    def test_renewal_uses_configured_ttl(self) -> None:
        """Renewal should use lease_ttl_seconds from policy triggers."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertEqual(300, result["lease"]["ttl_seconds"])

    def test_ttl_minimum_is_30(self) -> None:
        """Even with TTL < 30 configured, minimum should be 30 seconds."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = {
                "name": "test-policy",
                "roles": {"manager": "codex"},
                "routing": {"default": "codex"},
                "decisions": {"architecture": {"mode": "consensus", "members": []}},
                "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 5},
            }
            (root / "policy.json").write_text(json.dumps(raw), encoding="utf-8")
            policy = Policy.load(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = _setup_claimed_task(orch, root)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertGreaterEqual(result["lease"]["ttl_seconds"], 30)


if __name__ == "__main__":
    unittest.main()
