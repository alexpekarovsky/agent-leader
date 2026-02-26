"""Tests for Orchestrator.poll_events() engine method.

Covers: audience filtering, auto_advance cursor, explicit cursor parameter,
limit enforcement, result shape, and timeout behavior.
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


class PollEventsResultShapeTests(unittest.TestCase):
    """Tests for poll_events result structure."""

    def test_result_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            result = orch.poll_events(agent="claude_code", timeout_ms=0)

            self.assertIn("agent", result)
            self.assertIn("cursor", result)
            self.assertIn("next_cursor", result)
            self.assertIn("events", result)
            self.assertEqual("claude_code", result["agent"])

    def test_events_have_offset_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            # Bootstrap emits events, so there should be some
            result = orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)

            if result["events"]:
                for event in result["events"]:
                    self.assertIn("offset", event)
                    self.assertIsInstance(event["offset"], int)

    def test_empty_bus_returns_empty_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            # Clear all events
            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.poll_events(agent="claude_code", timeout_ms=0)

            self.assertEqual([], result["events"])
            self.assertEqual(0, result["cursor"])


class PollEventsCursorTests(unittest.TestCase):
    """Tests for cursor tracking in poll_events."""

    def test_auto_advance_true_moves_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            # Emit some events from cursor 0
            orch.bus.events_path.write_text("", encoding="utf-8")
            for i in range(5):
                orch.bus.emit(f"test.event.{i}", {"n": i}, source="test")

            result1 = orch.poll_events(agent="claude_code", cursor=0, auto_advance=True, timeout_ms=0)
            self.assertEqual(5, len(result1["events"]))
            self.assertGreater(result1["next_cursor"], 0)

            # Second poll from stored cursor should return nothing
            result2 = orch.poll_events(agent="claude_code", auto_advance=True, timeout_ms=0)
            self.assertEqual([], result2["events"])
            self.assertEqual(result1["next_cursor"], result2["cursor"])

    def test_auto_advance_false_keeps_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            for i in range(3):
                orch.bus.emit(f"test.event.{i}", {"n": i}, source="test")

            result1 = orch.poll_events(agent="claude_code", cursor=0, auto_advance=False, timeout_ms=0)
            self.assertEqual(3, len(result1["events"]))

            # Same events should be returned again since cursor didn't advance
            result2 = orch.poll_events(agent="claude_code", cursor=0, auto_advance=False, timeout_ms=0)
            self.assertEqual(3, len(result2["events"]))

    def test_explicit_cursor_overrides_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            for i in range(10):
                orch.bus.emit(f"test.event.{i}", {"n": i}, source="test")

            # First advance cursor to end
            orch.poll_events(agent="claude_code", cursor=0, auto_advance=True, timeout_ms=0)

            # Use explicit cursor=0 to re-read from beginning
            result = orch.poll_events(agent="claude_code", cursor=0, auto_advance=False, timeout_ms=0)
            self.assertEqual(10, len(result["events"]))
            self.assertEqual(0, result["cursor"])

    def test_cursor_starts_at_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            cursor = orch.get_agent_cursor("claude_code")
            self.assertEqual(0, cursor)


class PollEventsLimitTests(unittest.TestCase):
    """Tests for limit parameter."""

    def test_limit_caps_returned_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            for i in range(20):
                orch.bus.emit(f"test.event.{i}", {"n": i}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, limit=5, timeout_ms=0)

            self.assertEqual(5, len(result["events"]))

    def test_limit_larger_than_available_returns_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            for i in range(3):
                orch.bus.emit(f"test.event.{i}", {"n": i}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, limit=100, timeout_ms=0)

            self.assertEqual(3, len(result["events"]))

    def test_next_cursor_advances_past_limit(self) -> None:
        """After limit-capped poll, next_cursor should point past returned events."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            for i in range(10):
                orch.bus.emit(f"test.event.{i}", {"n": i}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, limit=3, auto_advance=True, timeout_ms=0)

            self.assertEqual(3, len(result["events"]))
            # next_cursor should be > cursor and allow fetching remaining events
            result2 = orch.poll_events(agent="claude_code", auto_advance=True, timeout_ms=0)
            self.assertEqual(7, len(result2["events"]))


class PollEventsAudienceFilterTests(unittest.TestCase):
    """Tests for audience-based event filtering."""

    def test_events_without_audience_visible_to_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.bus.emit("broadcast.event", {"msg": "hello"}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)

            self.assertEqual(1, len(result["events"]))

    def test_targeted_event_visible_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.bus.emit("targeted.event", {"audience": ["claude_code"], "msg": "for you"}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)

            targeted = [e for e in result["events"] if e.get("type") == "targeted.event"]
            self.assertEqual(1, len(targeted))

    def test_targeted_event_hidden_from_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.bus.emit("targeted.event", {"audience": ["gemini"], "msg": "not for claude"}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)

            targeted = [e for e in result["events"] if e.get("type") == "targeted.event"]
            self.assertEqual(0, len(targeted))

    def test_wildcard_audience_visible_to_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.bus.emit("wildcard.event", {"audience": ["*"], "msg": "for everyone"}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)

            wildcard = [e for e in result["events"] if e.get("type") == "wildcard.event"]
            self.assertEqual(1, len(wildcard))

    def test_skipped_audience_events_advance_cursor(self) -> None:
        """Events filtered by audience should still advance cursor past them."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")
            orch.bus.events_path.write_text("", encoding="utf-8")
            # 3 events: first for gemini, second for all, third for gemini
            orch.bus.emit("e1", {"audience": ["gemini"]}, source="test")
            orch.bus.emit("e2", {"msg": "for all"}, source="test")
            orch.bus.emit("e3", {"audience": ["gemini"]}, source="test")

            result = orch.poll_events(agent="claude_code", cursor=0, auto_advance=True, timeout_ms=0)

            # claude_code sees only e2 (no audience restriction)
            visible = [e for e in result["events"] if e.get("type") == "e2"]
            self.assertEqual(1, len(visible))
            # next_cursor should be past all 3 events
            self.assertEqual(3, result["next_cursor"])


class PollEventsTimeoutTests(unittest.TestCase):
    """Tests for timeout behavior."""

    def test_zero_timeout_returns_immediately(self) -> None:
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")

            start = time.time()
            result = orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)
            elapsed = time.time() - start

            self.assertLess(elapsed, 1.0)
            self.assertEqual([], result["events"])


if __name__ == "__main__":
    unittest.main()
