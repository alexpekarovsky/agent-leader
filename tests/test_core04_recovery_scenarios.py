"""CORE-04 lease expiry recovery scenario tests.

Covers:
- TASK-fd36c022: No eligible same-project worker recovery
- TASK-be0d220f: Replacement same-family instance recovery
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


def _expire_lease(orch: Orchestrator, task_id: str) -> None:
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == task_id and t.get("lease"):
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)


def _make_agent_stale(orch: Orchestrator, agent: str) -> None:
    agents = orch._read_json(orch.agents_path)
    if agent in agents:
        agents[agent]["last_seen"] = "2020-01-01T00:00:00+00:00"
        orch._write_json(orch.agents_path, agents)


# ── TASK-fd36c022: No eligible worker recovery ──────────────────────


class NoEligibleWorkerRecoveryTests(unittest.TestCase):
    """Recovery when no same-project eligible worker is available."""

    def test_no_active_workers_blocks_task(self) -> None:
        """When no active worker exists, expired lease should block task."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Block me", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])
            _make_agent_stale(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(1, result["recovered_count"])
            recovery = result["recovered"][0]
            self.assertEqual("blocked", recovery["action"])

    def test_blocked_task_has_blocker_created(self) -> None:
        """Blocked recovery should create a blocker entry."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Blocker test", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])
            _make_agent_stale(orch, "claude_code")

            orch.recover_expired_task_leases(source="codex")

            blockers = orch.list_blockers(status="open")
            task_blockers = [b for b in blockers if b["task_id"] == task["id"]]
            self.assertEqual(1, len(task_blockers))
            self.assertIn("no eligible", task_blockers[0]["question"].lower())

    def test_blocked_task_status_set(self) -> None:
        """Blocked task should have status=blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Status check", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])
            _make_agent_stale(orch, "claude_code")

            orch.recover_expired_task_leases(source="codex")
            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("blocked", t["status"])

    def test_blocked_emits_lease_expired_blocked_event(self) -> None:
        """Should emit task.lease_expired_blocked event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Event check", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])
            _make_agent_stale(orch, "claude_code")

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            blocked_events = [e for e in events if e["type"] == "task.lease_expired_blocked"]
            self.assertEqual(1, len(blocked_events))
            self.assertEqual(task["id"], blocked_events[0]["payload"]["task_id"])

    def test_recovery_returns_empty_active_agents(self) -> None:
        """Result should show no active agents when all stale."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("No agents", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])
            _make_agent_stale(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual([], result["active_agents"])


# ── TASK-be0d220f: Same-family replacement instance recovery ─────────


class ReplacementInstanceRecoveryTests(unittest.TestCase):
    """Recovery when owner is still active (same family)."""

    def test_active_owner_gets_task_requeued(self) -> None:
        """If owner is still active, task requeued to same owner."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Requeue", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])
            # Keep claude_code active (don't make stale)

            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(1, result["recovered_count"])
            recovery = result["recovered"][0]
            self.assertEqual("requeued", recovery["action"])
            self.assertEqual("claude_code", recovery["to_owner"])

    def test_requeued_task_gets_assigned_status(self) -> None:
        """Requeued task should be set to assigned status."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Assigned", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])

            orch.recover_expired_task_leases(source="codex")
            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("assigned", t["status"])

    def test_requeued_task_lease_cleared(self) -> None:
        """Requeued task should have lease cleared."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Clear lease", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])

            orch.recover_expired_task_leases(source="codex")
            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(t.get("lease"))

    def test_requeued_emits_requeued_event(self) -> None:
        """Should emit task.requeued_lease_expired event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Requeue event", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")
            _expire_lease(orch, task["id"])

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            requeued = [e for e in events if e["type"] == "task.requeued_lease_expired"]
            self.assertEqual(1, len(requeued))

    def test_requeued_task_is_reclaimable(self) -> None:
        """After requeue, task should be claimable again with new lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Reclaim", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            tasks = orch.list_tasks()
            old_lease_id = next(t for t in tasks if t["id"] == task["id"])["lease"]["lease_id"]
            _expire_lease(orch, task["id"])
            orch.recover_expired_task_leases(source="codex")

            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(task["id"], reclaimed["id"])
            self.assertNotEqual(old_lease_id, reclaimed["lease"]["lease_id"])

    def test_multiple_expired_all_recovered(self) -> None:
        """Multiple expired leases should all be recovered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            task_ids = []
            for i in range(3):
                t = orch.create_task(f"Multi {i}", "backend", ["done"], owner="claude_code")
                orch.claim_next_task("claude_code")
                _expire_lease(orch, t["id"])
                task_ids.append(t["id"])

            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(3, result["recovered_count"])


if __name__ == "__main__":
    unittest.main()
