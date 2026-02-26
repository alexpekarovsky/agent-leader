"""CORE-06 manager execute-timeout noop diagnostic payload tests.

Tests that _recover_expired_task_leases emits events with proper
diagnostic payloads including task_id, owner, status, reason fields,
and that the event bus contains task.lease_recovered-type events.
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


def _register(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.register_agent(agent, metadata={
        "client": "test", "model": "test", "cwd": str(orch.root),
        "project_root": str(orch.root), "permissions_mode": "default",
        "sandbox_mode": "workspace-write", "session_id": session_id,
        "connection_id": f"conn-{agent}", "server_version": "0.1.0",
        "verification_source": "test",
    })


def _heartbeat(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.heartbeat(agent, metadata={
        "client": "test", "model": "test", "cwd": str(orch.root),
        "project_root": str(orch.root), "permissions_mode": "default",
        "sandbox_mode": "workspace-write", "session_id": session_id,
        "connection_id": f"conn-{agent}", "server_version": "0.1.0",
        "verification_source": "test",
    })


def _create_and_expire_task(orch: Orchestrator, agent: str = "claude_code") -> dict:
    """Create, claim, and expire a task for the given agent."""
    task = orch.create_task(
        title="Expiring task",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    claimed = orch.claim_next_task(agent)
    # Expire the lease
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == claimed["id"] and isinstance(t.get("lease"), dict):
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)
    return claimed


class NoopDiagnosticPayloadTests(unittest.TestCase):
    """CORE-06: manager execute-timeout noop diagnostic payload tests."""

    def test_recovery_emits_event_on_expired_lease(self) -> None:
        """When recover_expired_task_leases finds expired leases, it emits events."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            claimed = _create_and_expire_task(orch, "claude_code")

            # Clear events to isolate recovery events
            orch.bus.events_path.write_text("", encoding="utf-8")
            _heartbeat(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in {
                    "task.requeued_lease_expired",
                    "task.reassigned_lease_expired",
                    "task.lease_expired_blocked",
                }
            ]
            self.assertGreaterEqual(len(recovery_events), 1)

    def test_recovery_event_contains_task_id_and_owner(self) -> None:
        """Recovery events contain task_id, owner, and status info."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            claimed = _create_and_expire_task(orch, "claude_code")

            orch.bus.events_path.write_text("", encoding="utf-8")
            _heartbeat(orch, "claude_code")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in {
                    "task.requeued_lease_expired",
                    "task.reassigned_lease_expired",
                    "task.lease_expired_blocked",
                }
            ]
            self.assertGreaterEqual(len(recovery_events), 1)
            payload = recovery_events[0]["payload"]
            self.assertEqual(claimed["id"], payload["task_id"])
            self.assertEqual("claude_code", payload["owner"])

    def test_recovery_event_has_reason_field(self) -> None:
        """Recovery events have descriptive reason fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            _create_and_expire_task(orch, "claude_code")

            orch.bus.events_path.write_text("", encoding="utf-8")
            _heartbeat(orch, "claude_code")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in {
                    "task.requeued_lease_expired",
                    "task.reassigned_lease_expired",
                    "task.lease_expired_blocked",
                }
            ]
            self.assertGreaterEqual(len(recovery_events), 1)
            payload = recovery_events[0]["payload"]
            self.assertEqual("lease_expired", payload.get("reason"))

    def test_recovery_result_includes_recovered_count(self) -> None:
        """The result payload includes recovered_count and task details."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            claimed = _create_and_expire_task(orch, "claude_code")
            _heartbeat(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertIn("recovered_count", result)
            self.assertEqual(1, result["recovered_count"])
            self.assertIn("recovered", result)
            self.assertEqual(1, len(result["recovered"]))
            detail = result["recovered"][0]
            self.assertEqual(claimed["id"], detail["task_id"])
            self.assertEqual("claude_code", detail["owner"])
            self.assertIn("action", detail)

    def test_recovery_event_includes_lease_id(self) -> None:
        """Recovery event payload includes the expired lease_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            claimed = _create_and_expire_task(orch, "claude_code")
            original_lease_id = claimed["lease"]["lease_id"]

            orch.bus.events_path.write_text("", encoding="utf-8")
            _heartbeat(orch, "claude_code")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in {
                    "task.requeued_lease_expired",
                    "task.reassigned_lease_expired",
                    "task.lease_expired_blocked",
                }
            ]
            self.assertGreaterEqual(len(recovery_events), 1)
            payload = recovery_events[0]["payload"]
            self.assertEqual(original_lease_id, payload.get("lease_id"))

    def test_no_expired_leases_emits_no_recovery_events(self) -> None:
        """When no leases are expired, no recovery events should be emitted."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            # Create and claim but do NOT expire
            task = orch.create_task(
                title="Active task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.claim_next_task("claude_code")

            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(0, result["recovered_count"])
            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in {
                    "task.requeued_lease_expired",
                    "task.reassigned_lease_expired",
                    "task.lease_expired_blocked",
                }
            ]
            self.assertEqual(0, len(recovery_events))


if __name__ == "__main__":
    unittest.main()
