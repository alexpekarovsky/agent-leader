"""CORE-03 Lease Renewal Contract Tests.

Comprehensive tests for the renew_task_lease method covering:
- Happy path renewal of valid in_progress lease
- Expiry extension beyond current time
- renewed_at timestamp update
- lease_id preservation across renewals
- TTL consistency with policy configuration
- Double/successive renewal success
- Negative cases (non-existent task, owner mismatch, instance mismatch,
  wrong status, no lease)
- Event emission on the bus
- Persistence to disk after renewal

References: TASK-7a153253, TASK-79b3512e
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_policy(path: Path, ttl_seconds: int = 300) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {
            "backend": "claude_code",
            "frontend": "gemini",
            "default": "codex",
        },
        "decisions": {
            "architecture": {
                "mode": "consensus",
                "members": ["codex", "claude_code", "gemini"],
            }
        },
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "lease_ttl_seconds": ttl_seconds,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, ttl_seconds: int = 300) -> Orchestrator:
    policy = _make_policy(root / "policy.json", ttl_seconds=ttl_seconds)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _register(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.register_agent(agent, metadata={
        "client": "test",
        "model": "test",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": session_id,
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    })
    orch.heartbeat(agent, metadata={
        "client": "test",
        "model": "test",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": session_id,
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    })


def _create_and_claim(orch: Orchestrator, agent: str = "claude_code") -> dict:
    """Create a task owned by *agent*, claim it, and return the claimed task."""
    task = orch.create_task(
        title="lease-renewal-contract-task",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["passes"],
    )
    claimed = orch.claim_next_task(agent)
    assert claimed is not None, "claim_next_task returned None"
    return claimed


# ---------------------------------------------------------------------------
# 1. Happy-path renewal
# ---------------------------------------------------------------------------

class TestLeaseRenewalHappyPath(unittest.TestCase):
    """Renewal of a valid in_progress lease succeeds and returns expected keys."""

    def test_renewal_succeeds_returns_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertIn("task_id", result)
            self.assertEqual(task["id"], result["task_id"])
            self.assertIn("agent", result)
            self.assertEqual("claude_code", result["agent"])
            self.assertIn("lease", result)
            self.assertIsInstance(result["lease"], dict)


# ---------------------------------------------------------------------------
# 2. Expiry extension
# ---------------------------------------------------------------------------

class TestLeaseExpiryExtension(unittest.TestCase):
    """Renewal pushes expires_at beyond the current UTC time."""

    def test_expires_at_is_in_the_future(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            new_expires = datetime.fromisoformat(result["lease"]["expires_at"])
            now = datetime.now(timezone.utc)
            self.assertGreater(new_expires, now)

    def test_expires_at_extended_beyond_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]
            original_expires = task["lease"]["expires_at"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertGreaterEqual(result["lease"]["expires_at"], original_expires)


# ---------------------------------------------------------------------------
# 3. renewed_at update
# ---------------------------------------------------------------------------

class TestRenewedAtUpdate(unittest.TestCase):
    """renewed_at timestamp is refreshed on renewal."""

    def test_renewed_at_changes_after_renewal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]
            original_renewed = task["lease"]["renewed_at"]

            # Small pause so timestamp can differ
            time.sleep(0.01)
            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertIn("renewed_at", result["lease"])
            # renewed_at should be at or after the original
            self.assertGreaterEqual(result["lease"]["renewed_at"], original_renewed)


# ---------------------------------------------------------------------------
# 4. Lease-id preserved
# ---------------------------------------------------------------------------

class TestLeaseIdPreserved(unittest.TestCase):
    """lease_id must not change across renewals."""

    def test_lease_id_unchanged_after_renewal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertEqual(lease_id, result["lease"]["lease_id"])

    def test_lease_id_stable_across_multiple_renewals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            for _ in range(5):
                result = orch.renew_task_lease(task["id"], "claude_code", lease_id)
                self.assertEqual(lease_id, result["lease"]["lease_id"])


# ---------------------------------------------------------------------------
# 5. TTL consistency
# ---------------------------------------------------------------------------

class TestTTLConsistency(unittest.TestCase):
    """Renewed lease ttl_seconds must match policy/config."""

    def test_ttl_matches_policy_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, ttl_seconds=300)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertEqual(300, result["lease"]["ttl_seconds"])

    def test_ttl_matches_custom_policy_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, ttl_seconds=600)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertEqual(600, result["lease"]["ttl_seconds"])

    def test_ttl_clamped_to_minimum_30(self) -> None:
        """Even if policy says 5s, the floor is 30s."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, ttl_seconds=5)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertGreaterEqual(result["lease"]["ttl_seconds"], 30)


# ---------------------------------------------------------------------------
# 6. Double renewal
# ---------------------------------------------------------------------------

class TestDoubleRenewal(unittest.TestCase):
    """Calling renew twice in succession both succeed."""

    def test_two_successive_renewals_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            r1 = orch.renew_task_lease(task["id"], "claude_code", lease_id)
            r2 = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            self.assertEqual(task["id"], r1["task_id"])
            self.assertEqual(task["id"], r2["task_id"])
            self.assertEqual(lease_id, r1["lease"]["lease_id"])
            self.assertEqual(lease_id, r2["lease"]["lease_id"])
            # Second renewal should have equal or later expires_at
            self.assertGreaterEqual(
                r2["lease"]["expires_at"], r1["lease"]["expires_at"]
            )


# ---------------------------------------------------------------------------
# 7. Negative cases
# ---------------------------------------------------------------------------

class TestRenewalNegativeCases(unittest.TestCase):
    """Failure modes that must raise ValueError."""

    def test_renew_nonexistent_task_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease("TASK-does-not-exist", "claude_code", "LEASE-abc")
            self.assertIn("not found", str(ctx.exception).lower())

    def test_renew_task_owned_by_different_agent_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _register(orch, "gemini", session_id="sess-gemini")
            task = _create_and_claim(orch)  # owned by claude_code
            lease_id = task["lease"]["lease_id"]

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "gemini", lease_id)
            self.assertIn("lease_owner_mismatch", str(ctx.exception))

    def test_renew_task_with_wrong_instance_id_fails(self) -> None:
        """When the lease's owner_instance_id differs from the agent's current
        instance_id, renewal must raise lease_instance_mismatch.

        The normalize_agent_metadata function pins instance_id once set, so
        we simulate a mismatch by directly patching the lease on disk to have
        a different owner_instance_id than the agent's current instance.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-original")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            # Patch the lease's owner_instance_id on disk to something that
            # differs from the agent's current instance_id ("sess-original").
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == task["id"]:
                    t["lease"]["owner_instance_id"] = "sess-alien-instance"
            orch._write_json(orch.tasks_path, tasks)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", lease_id)
            self.assertIn("lease_instance_mismatch", str(ctx.exception))

    def test_renew_task_not_in_progress_fails(self) -> None:
        """A task in 'assigned' status (no lease from claim) cannot be renewed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            # Create task but do NOT claim it -- it stays in 'assigned'.
            task = orch.create_task(
                title="unclaimed-task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["passes"],
            )

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-fake")
            # Should fail with lease_missing because assigned tasks have no lease.
            self.assertIn("lease_missing", str(ctx.exception))

    def test_renew_task_with_no_lease_fails(self) -> None:
        """Task manually moved to in_progress without a lease cannot be renewed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = orch.create_task(
                title="no-lease-task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["passes"],
            )
            # Use the manager agent to set status to in_progress directly,
            # bypassing claim (so no lease is issued).
            orch.set_task_status(task["id"], "in_progress", "codex")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-fake")
            self.assertIn("lease_missing", str(ctx.exception))

    def test_renew_with_wrong_lease_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-wrong")
            self.assertIn("lease_id_mismatch", str(ctx.exception))

    def test_renew_expired_lease_fails(self) -> None:
        """An already-expired lease cannot be renewed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            # Manually expire the lease on disk
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == task["id"]:
                    t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", lease_id)
            self.assertIn("lease_expired", str(ctx.exception))


# ---------------------------------------------------------------------------
# 8. Event emission
# ---------------------------------------------------------------------------

class TestLeaseRenewalEventEmission(unittest.TestCase):
    """Successful renewal emits a task.lease_renewed event on the bus."""

    def test_renewal_emits_task_lease_renewed_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            # Flush existing events so we only see the renewal event
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.renew_task_lease(task["id"], "claude_code", lease_id)

            events = list(orch.bus.iter_events())
            renewed_events = [
                e for e in events if e.get("type") == "task.lease_renewed"
            ]
            self.assertEqual(1, len(renewed_events))
            payload = renewed_events[0]["payload"]
            self.assertEqual(task["id"], payload["task_id"])
            self.assertEqual("claude_code", payload["agent"])
            self.assertEqual(lease_id, payload["lease_id"])

    def test_double_renewal_emits_two_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.renew_task_lease(task["id"], "claude_code", lease_id)
            orch.renew_task_lease(task["id"], "claude_code", lease_id)

            events = list(orch.bus.iter_events())
            renewed_events = [
                e for e in events if e.get("type") == "task.lease_renewed"
            ]
            self.assertEqual(2, len(renewed_events))


# ---------------------------------------------------------------------------
# 9. Persistence to disk
# ---------------------------------------------------------------------------

class TestLeaseRenewalPersistence(unittest.TestCase):
    """Renewed lease data persists to tasks.json on disk."""

    def test_renewed_lease_persists_to_tasks_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]
            original_renewed = task["lease"]["renewed_at"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)
            new_renewed = result["lease"]["renewed_at"]

            # Read raw JSON from disk (not through the orchestrator cache)
            raw = json.loads(orch.tasks_path.read_text(encoding="utf-8"))
            persisted_task = next(t for t in raw if t["id"] == task["id"])

            self.assertIsNotNone(persisted_task.get("lease"))
            self.assertEqual(lease_id, persisted_task["lease"]["lease_id"])
            self.assertEqual(new_renewed, persisted_task["lease"]["renewed_at"])
            # expires_at on disk should match what was returned
            self.assertEqual(
                result["lease"]["expires_at"],
                persisted_task["lease"]["expires_at"],
            )

    def test_new_orchestrator_sees_renewed_lease(self) -> None:
        """A fresh Orchestrator instance reads the persisted renewal from disk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = _create_and_claim(orch)
            lease_id = task["lease"]["lease_id"]

            result = orch.renew_task_lease(task["id"], "claude_code", lease_id)

            # Create a brand-new Orchestrator pointed at the same root
            orch2 = Orchestrator(
                root=root,
                policy=_make_policy(root / "policy.json"),
            )
            tasks = orch2._read_json(orch2.tasks_path)
            persisted = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual(lease_id, persisted["lease"]["lease_id"])
            self.assertEqual(
                result["lease"]["renewed_at"],
                persisted["lease"]["renewed_at"],
            )


if __name__ == "__main__":
    unittest.main()
