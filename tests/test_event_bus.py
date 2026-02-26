"""Unit tests for event bus: publish_event, poll_events, ack_event.

Tests the Orchestrator-level methods that wrap EventBus operations,
including cursor management, audience filtering, and ack tracking.
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
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(tmpdir: Path) -> Orchestrator:
    policy = _make_policy(tmpdir / "policy.json")
    return Orchestrator(root=tmpdir, policy=policy)


def _register_agent(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": False,
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })


class PublishEventTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.orch = _make_orch(self.tmpdir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_publish_event_returns_event_with_id(self) -> None:
        event = self.orch.publish_event("test.ping", source="codex", payload={"msg": "hello"})
        self.assertIn("event_id", event)
        self.assertTrue(event["event_id"].startswith("EVT-"))
        self.assertEqual(event["type"], "test.ping")
        self.assertEqual(event["source"], "codex")
        self.assertEqual(event["payload"]["msg"], "hello")

    def test_publish_event_with_audience(self) -> None:
        event = self.orch.publish_event(
            "manager.sync", source="codex",
            payload={"action": "resync"}, audience=["claude_code"],
        )
        self.assertIn("audience", event["payload"])
        self.assertEqual(event["payload"]["audience"], ["claude_code"])

    def test_publish_event_empty_payload(self) -> None:
        event = self.orch.publish_event("test.empty", source="codex")
        self.assertEqual(event["payload"], {})

    def test_publish_event_persists_to_bus(self) -> None:
        self.orch.publish_event("test.persist", source="codex", payload={"x": 1})
        events = list(self.orch.bus.iter_events())
        matching = [e for e in events if e["type"] == "test.persist"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["payload"]["x"], 1)


class PollEventsTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.orch = _make_orch(self.tmpdir)
        _register_agent(self.orch, "claude_code")
        _register_agent(self.orch, "gemini")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_poll_after_registration_returns_registration_events(self) -> None:
        """Registering agents emits events; poll should return them."""
        result = self.orch.poll_events(agent="claude_code")
        self.assertEqual(result["agent"], "claude_code")
        # Registration emits agent.registered events, so bus is not empty
        self.assertGreater(len(result["events"]), 0)
        types = {e["type"] for e in result["events"]}
        self.assertIn("agent.registered", types)

    def test_poll_returns_published_events(self) -> None:
        self.orch.publish_event("test.a", source="codex", payload={"n": 1})
        self.orch.publish_event("test.b", source="codex", payload={"n": 2})
        result = self.orch.poll_events(agent="claude_code")
        types = [e["type"] for e in result["events"]]
        self.assertIn("test.a", types)
        self.assertIn("test.b", types)

    def test_poll_advances_cursor(self) -> None:
        self.orch.publish_event("test.x", source="codex")
        result1 = self.orch.poll_events(agent="claude_code")
        self.assertGreater(result1["next_cursor"], result1["cursor"])

        # Second poll with auto-advanced cursor should return no old events
        result2 = self.orch.poll_events(agent="claude_code")
        old_types = {e["type"] for e in result1["events"]}
        new_types = {e["type"] for e in result2["events"]}
        self.assertTrue(old_types.isdisjoint(new_types) or len(result2["events"]) == 0)

    def test_poll_filters_by_audience(self) -> None:
        self.orch.publish_event(
            "targeted.msg", source="codex",
            payload={"data": "for-claude"}, audience=["claude_code"],
        )
        # claude_code should see it
        result_cc = self.orch.poll_events(agent="claude_code")
        cc_types = [e["type"] for e in result_cc["events"]]
        self.assertIn("targeted.msg", cc_types)

        # gemini should NOT see it
        result_gem = self.orch.poll_events(agent="gemini")
        gem_types = [e["type"] for e in result_gem["events"]]
        self.assertNotIn("targeted.msg", gem_types)

    def test_poll_wildcard_audience(self) -> None:
        self.orch.publish_event(
            "broadcast.msg", source="codex",
            payload={}, audience=["*"],
        )
        result = self.orch.poll_events(agent="gemini")
        types = [e["type"] for e in result["events"]]
        self.assertIn("broadcast.msg", types)

    def test_poll_respects_limit(self) -> None:
        for i in range(10):
            self.orch.publish_event(f"test.bulk.{i}", source="codex")
        result = self.orch.poll_events(agent="claude_code", limit=3)
        self.assertLessEqual(len(result["events"]), 3)

    def test_poll_no_auto_advance(self) -> None:
        self.orch.publish_event("test.noadvance", source="codex")
        result1 = self.orch.poll_events(agent="claude_code", auto_advance=False)
        result2 = self.orch.poll_events(agent="claude_code", auto_advance=False)
        # Same cursor means same events returned
        self.assertEqual(result1["cursor"], result2["cursor"])


class AckEventTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.orch = _make_orch(self.tmpdir)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ack_event_returns_confirmation(self) -> None:
        event = self.orch.publish_event("test.ack", source="codex")
        result = self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        self.assertTrue(result["acked"])
        self.assertEqual(result["agent"], "claude_code")
        self.assertEqual(result["event_id"], event["event_id"])

    def test_ack_is_idempotent(self) -> None:
        event = self.orch.publish_event("test.idem", source="codex")
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        result = self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        self.assertTrue(result["acked"])
        # Should not duplicate in acks list
        acks_data = json.loads(self.orch.acks_path.read_text(encoding="utf-8"))
        cc_acks = acks_data.get("claude_code", [])
        count = cc_acks.count(event["event_id"])
        self.assertEqual(count, 1)

    def test_ack_emits_event_acked_event(self) -> None:
        event = self.orch.publish_event("test.ackemit", source="codex")
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        all_events = list(self.orch.bus.iter_events())
        ack_events = [e for e in all_events if e["type"] == "event.acked"]
        self.assertGreater(len(ack_events), 0)
        latest_ack = ack_events[-1]
        self.assertEqual(latest_ack["payload"]["agent"], "claude_code")
        self.assertEqual(latest_ack["payload"]["event_id"], event["event_id"])

    def test_ack_per_agent_isolation(self) -> None:
        _register_agent(self.orch, "gemini")
        event = self.orch.publish_event("test.isolation", source="codex")
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        # gemini has not acked
        acks_data = json.loads(self.orch.acks_path.read_text(encoding="utf-8"))
        self.assertNotIn(event["event_id"], acks_data.get("gemini", []))
        self.assertIn(event["event_id"], acks_data.get("claude_code", []))


class EventLifecycleTests(unittest.TestCase):
    """End-to-end: publish -> poll -> ack -> poll returns empty."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.orch = _make_orch(self.tmpdir)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_full_lifecycle(self) -> None:
        # Publish
        event = self.orch.publish_event("lifecycle.test", source="codex", payload={"step": 1})

        # Poll — should see the event
        result1 = self.orch.poll_events(agent="claude_code")
        event_ids = [e["event_id"] for e in result1["events"]]
        self.assertIn(event["event_id"], event_ids)

        # Ack
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])

        # Poll again — cursor advanced, so old events not returned
        result2 = self.orch.poll_events(agent="claude_code")
        event_ids2 = [e["event_id"] for e in result2["events"]]
        # The original lifecycle event should not reappear (cursor advanced past it)
        self.assertNotIn(event["event_id"], event_ids2)


if __name__ == "__main__":
    unittest.main()
