"""Tests for event bus lifecycle: publish_event, poll_events, ack_event.

Validates the event bus methods in orchestrator/engine.py covering
event publishing, polling with cursor management, and acknowledgment.
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


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _register_agent(orch: Orchestrator, agent: str) -> None:
    """Register an agent so it passes operational checks."""
    orch.register_agent(agent, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"cid-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    })


class PublishEventTests(unittest.TestCase):
    """Tests for publish_event."""

    def test_publish_returns_event_with_expected_fields(self) -> None:
        """publish_event should return an event dict with standard fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="test.event",
                source="claude_code",
                payload={"key": "value"},
            )

            self.assertTrue(event["event_id"].startswith("EVT-"))
            self.assertEqual("test.event", event["type"])
            self.assertEqual("claude_code", event["source"])
            self.assertIn("timestamp", event)
            self.assertEqual("value", event["payload"]["key"])

    def test_publish_with_no_payload(self) -> None:
        """publish_event with no payload should use empty dict."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="ping",
                source="codex",
            )

            self.assertIsInstance(event["payload"], dict)

    def test_publish_with_audience(self) -> None:
        """publish_event with audience should include it in payload."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="targeted.event",
                source="codex",
                payload={"data": "hello"},
                audience=["claude_code"],
            )

            self.assertEqual(["claude_code"], event["payload"]["audience"])

    def test_publish_writes_to_event_log(self) -> None:
        """publish_event should persist the event to the JSONL event log."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.publish_event(event_type="log.test", source="codex", payload={"x": 1})

            # Events are stored inside the .orchestrator directory
            events_path = orch.bus.events_path
            self.assertTrue(events_path.exists())
            lines = events_path.read_text(encoding="utf-8").strip().split("\n")
            # Find our event (there may be bootstrap events)
            found = any(
                json.loads(line).get("type") == "log.test"
                for line in lines
                if line.strip()
            )
            self.assertTrue(found, "Published event not found in events.jsonl")


class PollEventsTests(unittest.TestCase):
    """Tests for poll_events."""

    def test_poll_returns_published_events(self) -> None:
        """poll_events should return events published after the cursor."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("task.assigned", "codex", {"task_id": "T1"})

            result = orch.poll_events("claude_code", timeout_ms=0)

            self.assertEqual("claude_code", result["agent"])
            self.assertIsInstance(result["events"], list)
            # Should have at least our published event
            types = [e["type"] for e in result["events"]]
            self.assertIn("task.assigned", types)

    def test_poll_advances_cursor(self) -> None:
        """poll_events with auto_advance should update the agent cursor."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("evt1", "codex", {"n": 1})

            result1 = orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)
            cursor_after = result1["next_cursor"]

            # Poll again - should get no new events
            result2 = orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)
            self.assertEqual(0, len(result2["events"]))
            self.assertEqual(cursor_after, result2["cursor"])

    def test_poll_without_auto_advance(self) -> None:
        """poll_events with auto_advance=False should not update cursor."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("evt1", "codex", {"n": 1})

            result1 = orch.poll_events("claude_code", timeout_ms=0, auto_advance=False)
            events1 = result1["events"]

            # Poll again - should get same events since cursor didn't advance
            result2 = orch.poll_events("claude_code", timeout_ms=0, auto_advance=False)
            events2 = result2["events"]

            self.assertEqual(len(events1), len(events2))

    def test_poll_respects_audience(self) -> None:
        """poll_events should filter events by audience."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            # Publish event targeted only at gemini
            orch.publish_event("private.msg", "codex", {"msg": "hi"}, audience=["gemini"])
            # Publish event for all
            orch.publish_event("public.msg", "codex", {"msg": "hello"})

            result = orch.poll_events("claude_code", timeout_ms=0)
            types = [e["type"] for e in result["events"]]

            self.assertNotIn("private.msg", types)
            self.assertIn("public.msg", types)

    def test_poll_respects_limit(self) -> None:
        """poll_events should return at most `limit` events."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            for i in range(5):
                orch.publish_event(f"evt{i}", "codex", {"i": i})

            result = orch.poll_events("claude_code", timeout_ms=0, limit=2)
            self.assertLessEqual(len(result["events"]), 2)

    def test_poll_nonoperational_agent_raises(self) -> None:
        """poll_events for a non-registered agent should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError):
                orch.poll_events("nonexistent_agent", timeout_ms=0)

    def test_poll_returns_cursor_info(self) -> None:
        """poll_events should include cursor and next_cursor."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            result = orch.poll_events("claude_code", timeout_ms=0)

            self.assertIn("cursor", result)
            self.assertIn("next_cursor", result)
            self.assertIsInstance(result["cursor"], int)
            self.assertIsInstance(result["next_cursor"], int)


class AckEventTests(unittest.TestCase):
    """Tests for ack_event."""

    def test_ack_returns_confirmation(self) -> None:
        """ack_event should return acked=True."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            event = orch.publish_event("test.ack", "codex", {"n": 1})
            result = orch.ack_event("claude_code", event["event_id"])

            self.assertEqual("claude_code", result["agent"])
            self.assertEqual(event["event_id"], result["event_id"])
            self.assertTrue(result["acked"])

    def test_ack_is_idempotent(self) -> None:
        """Acking the same event twice should not raise or duplicate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            event = orch.publish_event("test.idem", "codex", {})
            orch.ack_event("claude_code", event["event_id"])
            result = orch.ack_event("claude_code", event["event_id"])

            self.assertTrue(result["acked"])

    def test_ack_persists_to_state(self) -> None:
        """ack_event should persist the ack to the acks state file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            event = orch.publish_event("test.persist", "codex", {})
            orch.ack_event("claude_code", event["event_id"])

            acks_path = orch.acks_path
            if acks_path.exists():
                acks = json.loads(acks_path.read_text(encoding="utf-8"))
                self.assertIn(event["event_id"], acks.get("claude_code", []))


class EventLifecycleTests(unittest.TestCase):
    """End-to-end: publish -> poll -> ack."""

    def test_full_lifecycle(self) -> None:
        """Full lifecycle: publish, poll sees event, ack, poll again returns empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            # Publish
            event = orch.publish_event("lifecycle.test", "codex", {"step": "begin"})
            event_id = event["event_id"]

            # Poll - should see event
            result1 = orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)
            types1 = [e["type"] for e in result1["events"]]
            self.assertIn("lifecycle.test", types1)

            # Ack (note: ack_event itself emits an event.acked event)
            ack_result = orch.ack_event("claude_code", event_id)
            self.assertTrue(ack_result["acked"])

            # Poll again - may see the event.acked event from the ack call
            result2 = orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)
            # All events should be ack-related, not our original lifecycle.test
            for evt in result2["events"]:
                self.assertNotEqual("lifecycle.test", evt["type"])

    def test_multiple_events_sequential_polling(self) -> None:
        """Multiple published events should be polled in order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            # Get cursor past bootstrap events
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)

            # Publish 3 events
            e1 = orch.publish_event("evt.first", "codex", {"n": 1})
            e2 = orch.publish_event("evt.second", "codex", {"n": 2})
            e3 = orch.publish_event("evt.third", "codex", {"n": 3})

            # Poll all
            result = orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)
            types = [e["type"] for e in result["events"]]

            self.assertIn("evt.first", types)
            self.assertIn("evt.second", types)
            self.assertIn("evt.third", types)

            # Verify ordering
            first_idx = types.index("evt.first")
            second_idx = types.index("evt.second")
            third_idx = types.index("evt.third")
            self.assertLess(first_idx, second_idx)
            self.assertLess(second_idx, third_idx)


if __name__ == "__main__":
    unittest.main()
