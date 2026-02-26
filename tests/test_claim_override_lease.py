"""CORE-03 lease issuance invariants for claim override path.

Verifies that set_claim_override + claim_next_task correctly issues leases
on the overridden task, with proper fields, status requirements, override
consumption, and instance_id matching.
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


def _full_metadata(root: Path, agent: str, instance_id: str = "") -> dict:
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
    if instance_id:
        meta["instance_id"] = instance_id
    return meta


def _setup_agent(orch: Orchestrator, root: Path, agent: str, instance_id: str = "") -> None:
    meta = _full_metadata(root, agent, instance_id=instance_id)
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


class ClaimOverrideLeaseIssuanceTests(unittest.TestCase):
    """set_claim_override then claim_next_task should issue a lease on the overridden task."""

    def test_override_claim_issues_lease(self) -> None:
        """Setting override then claiming should return task with lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override lease test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            self.assertEqual(task["id"], claimed["id"])
            self.assertIn("lease", claimed)
            self.assertIsNotNone(claimed["lease"])

    def test_override_lease_has_correct_fields(self) -> None:
        """Lease from override claim must have all required fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override lease fields test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")

            lease = claimed["lease"]
            required = {"lease_id", "owner", "issued_at", "expires_at", "ttl_seconds", "owner_instance_id"}
            for field in required:
                self.assertIn(field, lease, f"Missing required lease field: {field}")
                self.assertIsNotNone(lease[field], f"Lease field {field} should not be None")
            self.assertTrue(lease["lease_id"].startswith("LEASE-"))
            self.assertEqual("claude_code", lease["owner"])
            self.assertEqual(300, lease["ttl_seconds"])

    def test_override_task_must_be_assigned(self) -> None:
        """Override task must be in assigned status to be claimed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override status test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            # Advance task to in_progress (no longer assigned)
            orch.set_task_status(task["id"], "in_progress", "codex")

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            # The override should be ignored since task is not assigned
            claimed = orch.claim_next_task("claude_code")

            # No assigned tasks left, so claim returns None
            self.assertIsNone(claimed)

    def test_override_consumed_after_claim(self) -> None:
        """After override claim, the override should be consumed (removed)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override consumed test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            # Verify override exists before claim
            overrides = orch._read_json(orch.claim_overrides_path)
            self.assertIn("claude_code", overrides)

            orch.claim_next_task("claude_code")

            # Override should be consumed
            overrides = orch._read_json(orch.claim_overrides_path)
            self.assertNotIn("claude_code", overrides)

    def test_lease_instance_id_matches_agent(self) -> None:
        """Lease owner_instance_id must match the claiming agent's instance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code", instance_id="cc#worker-42")
            task = orch.create_task(
                title="Override instance test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")

            lease = claimed["lease"]
            self.assertEqual("cc#worker-42", lease["owner_instance_id"])

    def test_set_claim_override_requires_leader(self) -> None:
        """set_claim_override must reject non-leader source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override leader test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            with self.assertRaises(ValueError) as ctx:
                orch.set_claim_override(agent="claude_code", task_id=task["id"], source="claude_code")
            self.assertIn("leader_mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
