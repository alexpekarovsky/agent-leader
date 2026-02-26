"""CORE-04 lease expiry recovery event + audit correlation regression tests.

Ensures lease expiry recovery emits correlatable task/event/audit records
for operator debugging. Documents the correlation field chain:

Correlation Fields (CORE-04)
=============================
Recovery operations produce three categories of correlatable records:

1. **Bus Events** (events.jsonl via bus.emit):
   - event_id:    str — Unique event ID (EVT-{hex})
   - timestamp:   str — ISO-8601 when event was emitted
   - type:        str — Event type (task.requeued_lease_expired, etc.)
   - source:      str — Agent that triggered recovery (usually manager)
   - payload:     dict — Contains task_id, owner, lease_id, lease_owner_instance_id

2. **Task State** (tasks.json):
   - id:                str — Task ID linking to event payload.task_id
   - status:            str — "assigned" (requeued) or "blocked" (no worker)
   - lease:             None — Cleared after recovery
   - lease_recovery_at: str — ISO-8601 timestamp of recovery
   - owner:             str — Current owner after recovery
   - reassigned_from:   str — Previous owner (if reassigned to different agent)
   - reassigned_reason: str — "lease_expired_recovery" (if reassigned)

3. **Blockers** (blockers.json, only for blocked recoveries):
   - id:        str — Blocker ID (BLK-{hex}) linking to event payload.blocker_id
   - task_id:   str — Links back to task
   - agent:     str — Original task owner
   - status:    str — "open"
   - severity:  str — "high"

Task → Event Linkage:
  task["id"] == event["payload"]["task_id"]
  task["lease_recovery_at"] correlates temporally with event["timestamp"]

Event → Blocker Linkage (blocked path only):
  event["payload"]["blocker_id"] == blocker["id"]
  event["payload"]["task_id"] == blocker["task_id"]
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
    _setup_agent(orch, root, agent)
    task = orch.create_task(
        title="Correlation test task",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    claimed = orch.claim_next_task(agent)
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == claimed["id"]:
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)
    return claimed


# ---------------------------------------------------------------------------
# 1. Requeue event ↔ task correlation
# ---------------------------------------------------------------------------

class RequeueEventTaskCorrelationTests(unittest.TestCase):
    """Requeue recovery events must link back to the task via shared fields."""

    def test_event_payload_contains_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertGreaterEqual(len(recovery_events), 1)
            self.assertEqual(recovery_events[0]["payload"]["task_id"], task["id"])

    def test_event_payload_contains_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertEqual(recovery_events[0]["payload"]["owner"], "claude_code")

    def test_event_payload_contains_lease_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            original_lease_id = task["lease"]["lease_id"]
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertEqual(recovery_events[0]["payload"]["lease_id"], original_lease_id)

    def test_event_payload_contains_lease_owner_instance_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertIn("lease_owner_instance_id", recovery_events[0]["payload"])

    def test_event_has_event_id(self) -> None:
        """Every event must have a unique event_id for audit correlation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertTrue(recovery_events[0]["event_id"].startswith("EVT-"))

    def test_event_source_is_recovery_caller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertEqual(recovery_events[0]["source"], "codex")

    def test_task_lease_recovery_at_set_after_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIn("lease_recovery_at", recovered)
            self.assertIsNotNone(recovered["lease_recovery_at"])


# ---------------------------------------------------------------------------
# 2. Blocked event ↔ blocker correlation
# ---------------------------------------------------------------------------

class BlockedEventBlockerCorrelationTests(unittest.TestCase):
    """Blocked recovery events must link to the created blocker."""

    def _make_blocked_recovery(self, orch: Orchestrator, root: Path) -> tuple:
        """Create an expired task with stale owner, run recovery, return (task, events, blockers)."""
        task = _make_expired_lease_task(orch, root)
        agents = orch._read_json(orch.agents_path)
        agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
        orch._write_json(orch.agents_path, agents)
        orch.bus.events_path.write_text("", encoding="utf-8")

        orch.recover_expired_task_leases(source="codex")

        events = list(orch.bus.iter_events())
        blockers = orch._read_json_list(orch.blockers_path)
        return task, events, blockers

    def test_blocked_event_contains_blocker_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task, events, blockers = self._make_blocked_recovery(orch, root)

            blocked_events = [e for e in events if e.get("type") == "task.lease_expired_blocked"]
            self.assertEqual(len(blocked_events), 1)
            self.assertIn("blocker_id", blocked_events[0]["payload"])

    def test_blocker_id_matches_event_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task, events, blockers = self._make_blocked_recovery(orch, root)

            blocked_events = [e for e in events if e.get("type") == "task.lease_expired_blocked"]
            event_blocker_id = blocked_events[0]["payload"]["blocker_id"]
            blocker_ids = [b["id"] for b in blockers]
            self.assertIn(event_blocker_id, blocker_ids)

    def test_blocker_task_id_matches_event_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task, events, blockers = self._make_blocked_recovery(orch, root)

            blocked_events = [e for e in events if e.get("type") == "task.lease_expired_blocked"]
            event_task_id = blocked_events[0]["payload"]["task_id"]
            matching_blockers = [b for b in blockers if b["id"] == blocked_events[0]["payload"]["blocker_id"]]
            self.assertEqual(len(matching_blockers), 1)
            self.assertEqual(matching_blockers[0]["task_id"], event_task_id)

    def test_blocker_agent_matches_original_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task, events, blockers = self._make_blocked_recovery(orch, root)

            blocked_events = [e for e in events if e.get("type") == "task.lease_expired_blocked"]
            matching_blockers = [b for b in blockers if b["id"] == blocked_events[0]["payload"]["blocker_id"]]
            self.assertEqual(matching_blockers[0]["agent"], "claude_code")

    def test_blocker_severity_is_high(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _, _, blockers = self._make_blocked_recovery(orch, root)

            self.assertEqual(len(blockers), 1)
            self.assertEqual(blockers[0]["severity"], "high")

    def test_blocker_status_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _, _, blockers = self._make_blocked_recovery(orch, root)

            self.assertEqual(blockers[0]["status"], "open")


# ---------------------------------------------------------------------------
# 3. Recovery return value ↔ event correlation
# ---------------------------------------------------------------------------

class RecoveryReturnEventCorrelationTests(unittest.TestCase):
    """recover_expired_task_leases return value must match emitted events."""

    def test_requeue_return_matches_event_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertEqual(result["recovered_count"], len(recovery_events))

    def test_return_task_ids_match_event_task_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.recover_expired_task_leases(source="codex")

            return_task_ids = {r["task_id"] for r in result["recovered"]}
            events = list(orch.bus.iter_events())
            event_task_ids = {e["payload"]["task_id"] for e in events if "lease_expired" in e.get("type", "")}
            self.assertEqual(return_task_ids, event_task_ids)

    def test_return_lease_ids_match_event_lease_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.recover_expired_task_leases(source="codex")

            return_lease_ids = {r["lease_id"] for r in result["recovered"]}
            events = list(orch.bus.iter_events())
            event_lease_ids = {e["payload"]["lease_id"] for e in events if "lease_expired" in e.get("type", "")}
            self.assertEqual(return_lease_ids, event_lease_ids)


# ---------------------------------------------------------------------------
# 4. Multiple recoveries produce distinct events
# ---------------------------------------------------------------------------

class MultipleRecoveryCorrelationTests(unittest.TestCase):
    """Multiple expired tasks should each get their own correlatable event."""

    def test_multiple_expired_produce_distinct_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            task_ids = []
            for i in range(3):
                task = orch.create_task(
                    title=f"Multi-recover {i}",
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
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(3, result["recovered_count"])
            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            self.assertEqual(3, len(recovery_events))

            # Each event should have a distinct event_id
            event_ids = {e["event_id"] for e in recovery_events}
            self.assertEqual(3, len(event_ids))

            # Each event should reference a distinct task_id
            event_task_ids = {e["payload"]["task_id"] for e in recovery_events}
            self.assertEqual(set(task_ids), event_task_ids)

    def test_multiple_events_share_same_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            for i in range(2):
                orch.create_task(
                    title=f"Source check {i}",
                    workstream="backend",
                    owner="claude_code",
                    acceptance_criteria=["test"],
                )
                orch.claim_next_task("claude_code")

            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t.get("lease"):
                    t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [e for e in events if "lease_expired" in e.get("type", "")]
            sources = {e["source"] for e in recovery_events}
            self.assertEqual(sources, {"codex"})


if __name__ == "__main__":
    unittest.main()
