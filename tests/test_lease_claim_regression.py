"""Lease issuance on claim regression tests (TASK-4f233bf5).

Verifies that claim_next_task correctly issues lease records with all
required fields, correct ownership, instance tracking, timestamps,
status transitions, and idempotent claim behavior.
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
        "connection_id": f"conn-{agent}-{sid}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_agent(orch: Orchestrator, root: Path, agent: str, session_id: str = "") -> None:
    """Register and heartbeat an agent so it is operational."""
    meta = _full_metadata(root, agent, session_id)
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


class ClaimSetsLeaseFieldsTests(unittest.TestCase):
    """claim_next_task must populate lease fields on the task record."""

    def test_claim_sets_lease_on_task(self) -> None:
        """After claiming, the returned task must contain a non-None lease dict."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Lease presence test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            self.assertIn("lease", claimed)
            self.assertIsNotNone(claimed["lease"])
            self.assertIsInstance(claimed["lease"], dict)

    def test_lease_has_required_fields(self) -> None:
        """Lease must contain lease_id, owner, issued_at, expires_at, ttl_seconds, owner_instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Required fields test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            lease = claimed["lease"]
            required = {"lease_id", "owner", "issued_at", "expires_at", "ttl_seconds", "owner_instance_id"}
            for field in required:
                self.assertIn(field, lease, f"Missing required lease field: {field}")
                self.assertIsNotNone(lease[field], f"Lease field {field} should not be None")

    def test_lease_id_starts_with_prefix(self) -> None:
        """lease_id must start with 'LEASE-'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Lease prefix test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertTrue(
                claimed["lease"]["lease_id"].startswith("LEASE-"),
                f"Expected lease_id to start with 'LEASE-', got: {claimed['lease']['lease_id']}",
            )

    def test_lease_owner_matches_claiming_agent(self) -> None:
        """Lease owner must match the agent that performed the claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Lease owner test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertEqual("claude_code", claimed["lease"]["owner"])

    def test_lease_owner_instance_id_matches_agent_instance(self) -> None:
        """Lease owner_instance_id must match the agent's current instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Instance id match test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            lease = claimed["lease"]
            # The instance_id is derived from session_id by _normalize_agent_metadata
            self.assertIn("owner_instance_id", lease)
            self.assertTrue(len(lease["owner_instance_id"]) > 0)
            # Verify it matches the agent's registered instance
            agents = orch._read_json(orch.agents_path)
            agent_entry = agents.get("claude_code", {})
            agent_instance = agent_entry.get("metadata", {}).get("instance_id", "")
            self.assertEqual(agent_instance, lease["owner_instance_id"])

    def test_claimed_at_timestamp_is_set(self) -> None:
        """Claimed task must have a claimed_at timestamp after claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Claimed at test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertIn("claimed_at", claimed)
            self.assertIsNotNone(claimed["claimed_at"])
            # Should be an ISO format string containing 'T'
            self.assertIn("T", claimed["claimed_at"])

    def test_task_status_becomes_in_progress(self) -> None:
        """After claim, task status must be 'in_progress'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Status transition test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertEqual("in_progress", claimed["status"])
            # Verify persisted state
            tasks = orch._read_json(orch.tasks_path)
            persisted = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("in_progress", persisted["status"])

    def test_second_claim_by_same_agent_returns_none(self) -> None:
        """After claiming the only task, second claim should return None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Double claim test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            first = orch.claim_next_task("claude_code")
            second = orch.claim_next_task("claude_code")

            self.assertIsNotNone(first)
            self.assertIsNone(second)

    def test_different_agent_claims_frontend_task(self) -> None:
        """gemini claiming a frontend task should get a lease with gemini as owner."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "gemini")
            orch.create_task(
                title="Frontend claim test",
                workstream="frontend",
                owner="gemini",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("gemini")

            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])
            lease = claimed["lease"]
            self.assertEqual("gemini", lease["owner"])
            self.assertTrue(lease["lease_id"].startswith("LEASE-"))

    def test_lease_ttl_matches_policy(self) -> None:
        """Lease ttl_seconds should match the policy trigger value (300)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="TTL check test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertEqual(300, claimed["lease"]["ttl_seconds"])


if __name__ == "__main__":
    unittest.main()
