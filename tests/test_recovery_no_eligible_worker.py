"""CORE-04 lease expiry recovery when no eligible same-project worker.

Covers: expired lease with no registered agents, expired lease with only
offline agents, requeued task sits in assigned until claimed, recovery
count correctness, and lease field clearing.
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
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))


def _make_expired_lease_task(orch: Orchestrator, root: Path, agent: str = "claude_code") -> dict:
    """Create, claim a task, then expire its lease."""
    _setup_agent(orch, root, agent)
    orch.create_task(
        title="Expire me",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    claimed = orch.claim_next_task(agent)
    # Manually expire the lease
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == claimed["id"]:
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)
    return claimed


class NoRegisteredAgentRecoveryTests(unittest.TestCase):
    """Expired lease with no registered (or no active) agents."""

    def test_expired_no_agents_still_recovers(self) -> None:
        """Expired lease with agent made stale should still recover (block)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")

            # Make the agent stale so no active agents exist
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            # Since no active agent, should be blocked
            self.assertEqual("blocked", result["recovered"][0]["action"])

    def test_expired_only_offline_agents_recovers(self) -> None:
        """Expired lease with only offline agents should still be recovered (blocked)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Register two agents, create task, expire lease
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")
            orch.create_task(
                title="Expire with offline agents",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")

            # Expire the lease
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == claimed["id"]:
                    t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            # Make both agents offline
            agents = orch._read_json(orch.agents_path)
            for a in agents:
                agents[a]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual("blocked", result["recovered"][0]["action"])


class RequeuedTaskWaitsTests(unittest.TestCase):
    """Requeued task sits in assigned until a worker registers and claims."""

    def test_requeued_task_in_assigned_until_claimed(self) -> None:
        """After blocked recovery (no workers), new agent can register and claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            task_id = task["id"]

            # Make agent stale - triggers blocked recovery
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            orch.recover_expired_task_leases(source="codex")

            # Task should be blocked
            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("blocked", recovered["status"])

            # Now register a fresh agent, manually move task to assigned, and claim
            _setup_agent(orch, root, "claude_code")
            orch.set_task_status(task_id, "assigned", "codex")

            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(task_id, reclaimed["id"])
            self.assertEqual("in_progress", reclaimed["status"])


class RecoveryCountTests(unittest.TestCase):
    """Recovery count should be correct regardless of worker availability."""

    def test_recovery_count_with_no_active_workers(self) -> None:
        """Multiple expired leases with no active workers should all be counted."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            task_ids = []
            for i in range(3):
                orch.create_task(
                    title=f"Expire task {i}",
                    workstream="backend",
                    owner="claude_code",
                    acceptance_criteria=["test"],
                )
                claimed = orch.claim_next_task("claude_code")
                task_ids.append(claimed["id"])

            # Expire all leases
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] in task_ids and t.get("lease"):
                    t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            # Make agent offline
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(3, result["recovered_count"])
            self.assertEqual(3, len(result["recovered"]))
            for rec in result["recovered"]:
                self.assertEqual("blocked", rec["action"])


class LeaseClearedOnRecoveryTests(unittest.TestCase):
    """Lease field must be cleared regardless of worker availability."""

    def test_lease_cleared_when_blocked(self) -> None:
        """Even when recovery results in blocked, lease should be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")

            # Make agent stale
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(recovered.get("lease"))

    def test_lease_cleared_when_requeued(self) -> None:
        """When recovery results in requeue (active worker), lease should be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            # Keep agent active
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(recovered.get("lease"))


if __name__ == "__main__":
    unittest.main()
