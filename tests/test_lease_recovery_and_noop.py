"""Tests for recover_expired_task_leases and emit_stale_claim_override_noops.

Covers recovery edge cases (no expired, active owner requeue, no eligible
worker blocker creation) and dispatch noop diagnostics (non-leader rejection,
empty overrides, suppression when task advanced).
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
    """Register and heartbeat an agent."""
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))


def _make_expired_lease_task(orch: Orchestrator, root: Path, agent: str = "claude_code") -> dict:
    """Create, claim a task, then expire its lease."""
    _setup_agent(orch, root, agent)
    task = orch.create_task(
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


class RecoverExpiredLeaseBasicTests(unittest.TestCase):
    """Basic tests for recover_expired_task_leases."""

    def test_no_expired_leases_returns_zero(self) -> None:
        """When no leases are expired, recovered_count should be 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Active lease task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.claim_next_task("claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(0, result["recovered_count"])
            self.assertEqual([], result["recovered"])

    def test_no_in_progress_tasks_returns_zero(self) -> None:
        """With only assigned tasks, nothing to recover."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.create_task(
                title="Assigned only",
                workstream="backend",
                acceptance_criteria=["test"],
            )

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(0, result["recovered_count"])


class RecoverExpiredLeaseRequeueTests(unittest.TestCase):
    """Tests for expired lease requeue behavior."""

    def test_active_owner_gets_task_requeued(self) -> None:
        """Expired lease with active owner should requeue to same owner."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            # Keep agent active with fresh heartbeat
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual("requeued", result["recovered"][0]["action"])
            # Task should be assigned again
            tasks = orch.list_tasks()
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("assigned", recovered["status"])
            self.assertIsNone(recovered.get("lease"))

    def test_requeue_clears_lease(self) -> None:
        """After recovery, the task's lease should be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(recovered.get("lease"))

    def test_recovery_emits_requeue_event(self) -> None:
        """Requeue should emit a task.requeued_lease_expired event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            requeue_events = [
                e for e in events
                if e.get("type") in {"task.requeued_lease_expired", "task.reassigned_lease_expired"}
            ]
            self.assertGreaterEqual(len(requeue_events), 1)

    def test_multiple_expired_all_recovered(self) -> None:
        """Multiple expired leases should all be recovered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            task_ids = []
            for i in range(3):
                task = orch.create_task(
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

            # Keep agent active
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(3, result["recovered_count"])


class RecoverExpiredLeaseBlockerTests(unittest.TestCase):
    """Tests for blocker creation when no eligible worker."""

    def test_no_eligible_worker_creates_blocker(self) -> None:
        """When no active worker is eligible, task should be blocked with blocker."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            # Make the agent stale so it's not eligible
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual("blocked", result["recovered"][0]["action"])
            self.assertIn("blocker_id", result["recovered"][0])

    def test_blocked_recovery_sets_task_status(self) -> None:
        """When blocked, task status should be 'blocked'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            orch.recover_expired_task_leases(source="codex")

            tasks = orch.list_tasks()
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("blocked", recovered["status"])

    def test_blocked_recovery_emits_event(self) -> None:
        """Blocked recovery should emit task.lease_expired_blocked event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root, "claude_code")
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            blocked_events = [e for e in events if e.get("type") == "task.lease_expired_blocked"]
            self.assertEqual(1, len(blocked_events))

    def test_recovery_returns_active_agents(self) -> None:
        """Result should include list of active agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertIn("active_agents", result)
            self.assertIsInstance(result["active_agents"], list)


class EmitStaleClaimOverrideNoopsTests(unittest.TestCase):
    """Tests for emit_stale_claim_override_noops."""

    def test_non_leader_rejected(self) -> None:
        """Non-leader source should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError) as ctx:
                orch.emit_stale_claim_override_noops(source="claude_code")
            self.assertIn("leader_mismatch", str(ctx.exception))

    def test_empty_overrides_returns_zero(self) -> None:
        """With no claim overrides, emitted_count should be 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.emit_stale_claim_override_noops(source="codex")

            self.assertEqual(0, result["emitted_count"])
            self.assertEqual([], result["emitted"])

    def test_recent_override_not_emitted(self) -> None:
        """Override created recently (within timeout) should not emit noop."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override target",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.set_claim_override(
                agent="claude_code",
                task_id=task["id"],
                source="codex",
            )

            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=3600)

            self.assertEqual(0, result["emitted_count"])

    def test_stale_override_emits_noop(self) -> None:
        """Override older than timeout should emit a dispatch.noop event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override stale target",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.set_claim_override(
                agent="claude_code",
                task_id=task["id"],
                source="codex",
            )
            # Backdate the override
            overrides = orch._read_json(orch.claim_overrides_path)
            overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.claim_overrides_path, overrides)
            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)

            self.assertEqual(1, result["emitted_count"])
            events = list(orch.bus.iter_events())
            noop_events = [e for e in events if e.get("type") == "dispatch.noop"]
            self.assertEqual(1, len(noop_events))
            self.assertEqual("claim_override_timeout", noop_events[0]["payload"]["reason"])

    def test_suppression_when_task_advanced(self) -> None:
        """Override should be suppressed if task status is no longer assigned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Override suppress target",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.set_claim_override(
                agent="claude_code",
                task_id=task["id"],
                source="codex",
            )
            # Claim the task (advancing it to in_progress, consuming the override)
            orch.claim_next_task("claude_code")
            # Re-create override for same agent but with a new task
            task2 = orch.create_task(
                title="Second override target",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.set_claim_override(
                agent="claude_code",
                task_id=task2["id"],
                source="codex",
            )
            # Advance the second task via manager
            orch.set_task_status(task2["id"], "in_progress", "codex")
            # Backdate the override
            overrides = orch._read_json(orch.claim_overrides_path)
            if "claude_code" in overrides:
                overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
                orch._write_json(orch.claim_overrides_path, overrides)

            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)

            self.assertEqual(0, result["emitted_count"])

    def test_already_emitted_noop_not_repeated(self) -> None:
        """Once noop_emitted_at is set, should not emit again."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="No repeat noop",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.set_claim_override(
                agent="claude_code",
                task_id=task["id"],
                source="codex",
            )
            # Backdate and emit once
            overrides = orch._read_json(orch.claim_overrides_path)
            overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.claim_overrides_path, overrides)
            orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)

            # Second call should not emit again
            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)

            self.assertEqual(0, result["emitted_count"])

    def test_timeout_minimum_is_5(self) -> None:
        """Timeout should be at least 5 seconds."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=1)

            self.assertEqual(5, result["timeout_seconds"])


if __name__ == "__main__":
    unittest.main()
