"""CORE-03 lease issuance invariant and compatibility tests.

Covers:
- TASK-313fd107: Lease issuance invariants for claim override path
- TASK-f80bae8b: Lease ownership mismatch and stale-instance renewal rejection
- TASK-f6529999: Lease issuance response compatibility (legacy + new fields)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, **trigger_overrides: int) -> Policy:
    triggers = {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300}
    triggers.update(trigger_overrides)
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": triggers,
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, **trigger_overrides: int) -> Orchestrator:
    policy = _make_policy(root / "policy.json", **trigger_overrides)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str, **overrides: str) -> dict:
    meta = {
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
    meta.update(overrides)
    return meta


def _connect(orch: Orchestrator, root: Path, agent: str, **overrides: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent, **overrides), source=agent)


EXPECTED_LEASE_FIELDS = {"lease_id", "owner", "owner_instance_id", "issued_at", "renewed_at", "expires_at", "ttl_seconds"}


# ── TASK-313fd107: Claim override path lease invariants ──────────────


class ClaimOverrideLeaseInvariantTests(unittest.TestCase):
    """Lease must be issued on claim override path, same as normal claim."""

    def test_override_claim_issues_lease(self) -> None:
        """Claiming via override should issue a lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Override lease", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsInstance(t.get("lease"), dict)

    def test_override_lease_has_all_fields(self) -> None:
        """Override-path lease should contain all standard fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Override fields", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            lease = t["lease"]
            for field in EXPECTED_LEASE_FIELDS:
                self.assertIn(field, lease, f"Missing override lease field: {field}")

    def test_override_lease_id_prefix(self) -> None:
        """Override lease should have LEASE- prefix like normal claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Override prefix", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertTrue(t["lease"]["lease_id"].startswith("LEASE-"))

    def test_override_lease_owner_matches_agent(self) -> None:
        """Override lease owner should match the claiming agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Override owner", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("claude_code", t["lease"]["owner"])

    def test_override_lease_ttl_matches_policy(self) -> None:
        """Override lease TTL should use configured policy value."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, lease_ttl_seconds=180)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Override TTL", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual(180, t["lease"]["ttl_seconds"])

    def test_normal_and_override_lease_structure_identical(self) -> None:
        """Normal and override claim should produce same lease structure."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            # Normal claim
            t1 = orch.create_task("Normal", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            # Override claim
            t2 = orch.create_task("Override", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=t2["id"], source="codex")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            l1 = next(t for t in tasks if t["id"] == t1["id"])["lease"]
            l2 = next(t for t in tasks if t["id"] == t2["id"])["lease"]

            # Same set of keys
            self.assertEqual(set(l1.keys()), set(l2.keys()))


# ── TASK-f80bae8b: Lease mismatch and stale-instance rejection ───────


class LeaseOwnershipMismatchTests(unittest.TestCase):
    """Lease renewal rejection for ownership and instance mismatches."""

    def test_wrong_agent_rejected(self) -> None:
        """Agent B cannot renew agent A's lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            _connect(orch, root, "gemini")
            task = orch.create_task("Mismatch", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            lease_id = next(t for t in tasks if t["id"] == task["id"])["lease"]["lease_id"]

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "gemini", lease_id)
            self.assertIn("lease_owner_mismatch", str(ctx.exception))

    def test_wrong_lease_id_rejected(self) -> None:
        """Renewal with wrong lease_id should be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Wrong ID", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-fake")
            self.assertIn("lease_id_mismatch", str(ctx.exception))

    def test_expired_lease_renewal_rejected(self) -> None:
        """Cannot renew an already-expired lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Expired", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            tasks = orch._read_json(orch.tasks_path)
            t = next(t for t in tasks if t["id"] == task["id"])
            lease_id = t["lease"]["lease_id"]
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", lease_id)
            self.assertIn("lease_expired", str(ctx.exception))

    def test_instance_mismatch_rejected(self) -> None:
        """Renewal from different instance should be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code", instance_id="cc#w1")
            task = orch.create_task("Instance mismatch", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            lease_id = next(t for t in tasks if t["id"] == task["id"])["lease"]["lease_id"]

            # Switch instance
            orch.heartbeat("claude_code", {
                **_full_metadata(root, "claude_code"),
                "instance_id": "cc#w2",
                "session_id": "sess-w2",
                "connection_id": "conn-w2",
            })

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", lease_id)
            self.assertIn("lease_instance_mismatch", str(ctx.exception))

    def test_empty_lease_id_rejected(self) -> None:
        """Empty lease_id string should be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Empty ID", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            with self.assertRaises(ValueError):
                orch.renew_task_lease(task["id"], "claude_code", "")


# ── TASK-f6529999: Lease in claim response compatibility ─────────────


class LeaseResponseCompatibilityTests(unittest.TestCase):
    """Claim response compatibility with lease metadata fields."""

    def test_claim_response_contains_lease_key(self) -> None:
        """claim_next_task return value should include lease data."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            orch.create_task("Response test", "backend", ["done"], owner="claude_code")
            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            self.assertIn("lease", claimed)
            self.assertIsInstance(claimed["lease"], dict)

    def test_claim_response_lease_has_standard_fields(self) -> None:
        """Lease in claim response should have all standard fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            orch.create_task("Fields test", "backend", ["done"], owner="claude_code")
            claimed = orch.claim_next_task("claude_code")

            for field in EXPECTED_LEASE_FIELDS:
                self.assertIn(field, claimed["lease"], f"Missing: {field}")

    def test_claim_response_backward_compat_fields(self) -> None:
        """Legacy fields (id, status, owner, title) should still be present."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            orch.create_task("Compat test", "backend", ["done"], owner="claude_code")
            claimed = orch.claim_next_task("claude_code")

            for field in ("id", "status", "owner", "title"):
                self.assertIn(field, claimed, f"Missing legacy field: {field}")

    def test_lease_fields_json_serializable(self) -> None:
        """Claim response including lease should be JSON-serializable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            orch.create_task("Serial test", "backend", ["done"], owner="claude_code")
            claimed = orch.claim_next_task("claude_code")

            serialized = json.dumps(claimed)
            deserialized = json.loads(serialized)
            self.assertIn("lease", deserialized)
            self.assertEqual(claimed["lease"]["lease_id"], deserialized["lease"]["lease_id"])

    def test_no_task_returns_none(self) -> None:
        """When no tasks available, claim returns None (not error)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            result = orch.claim_next_task("claude_code")
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
