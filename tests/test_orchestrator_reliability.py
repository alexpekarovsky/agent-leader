from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bus import EventBus
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


class EventBusReliabilityTests(unittest.TestCase):
    def test_iter_events_skips_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bus"
            bus = EventBus(root)
            bus.emit("ok.event", {"x": 1}, source="tester")
            with bus.events_path.open("a", encoding="utf-8") as fh:
                fh.write("{this is malformed json\n")
                fh.write("\n")
            bus.emit("ok.event2", {"x": 2}, source="tester")

            events = list(bus.iter_events())
            self.assertEqual(2, len(events))
            self.assertEqual("ok.event", events[0]["type"])
            self.assertEqual("ok.event2", events[1]["type"])


class ListAgentsSideEffectTests(unittest.TestCase):
    def test_list_agents_default_does_not_emit_stale_notice_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            # Reset emitted bootstrap event so this test checks list_agents side effects only.
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.register_agent(
                "gemini",
                {
                    "client": "gemini-cli",
                    "model": "gemini-2.5-pro",
                    "cwd": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "default",
                    "session_id": "sess-1",
                    "connection_id": "conn-1",
                    "server_version": "0.1.0",
                    "verification_source": "test",
                },
            )
            # Force offline without invoking stale notice emission.
            agents = orch._read_json(orch.agents_path)
            agents["gemini"]["last_seen"] = "2000-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)
            orch.bus.events_path.write_text("", encoding="utf-8")

            listed = orch.list_agents(active_only=False)
            self.assertTrue(any(a.get("agent") == "gemini" for a in listed))
            self.assertEqual([], list(orch.bus.iter_events()))


class TaskStatusGuardTests(unittest.TestCase):
    def test_non_manager_cannot_set_done_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = orch.create_task(
                title="Guarded completion",
                workstream="backend",
                acceptance_criteria=["Use submit_report"],
            )

            with self.assertRaises(ValueError):
                orch.set_task_status(task_id=task["id"], status="done", source="claude_code")

    def test_manager_can_set_done_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = orch.create_task(
                title="Manager override",
                workstream="backend",
                acceptance_criteria=["Manager can override"],
            )

            updated = orch.set_task_status(task_id=task["id"], status="done", source="codex")
            self.assertEqual("done", updated.get("status"))


class ConnectBehaviorTests(unittest.TestCase):
    def test_manager_connect_does_not_auto_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.create_task(
                title="Manager should not auto-claim",
                workstream="default",
                acceptance_criteria=["Remain assigned"],
                owner="codex",
            )

            result = orch.connect_to_leader(
                agent="codex",
                metadata={
                    "role": "manager",
                    "client": "codex-cli",
                    "model": "gpt-5",
                    "cwd": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "workspace-write",
                    "session_id": "manager-test",
                    "connection_id": "manager-conn-test",
                    "server_version": "0.1.0",
                    "verification_source": "test",
                },
                source="codex",
            )

            self.assertTrue(result.get("connected"))
            self.assertIsNone(result.get("auto_claimed_task"))
            assigned = orch.list_tasks_for_owner("codex")
            self.assertEqual("assigned", assigned[0].get("status"))


if __name__ == "__main__":
    unittest.main()
