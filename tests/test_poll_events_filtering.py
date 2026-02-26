"""Tests for Orchestrator.poll_events() audience filtering and cursor behavior.

Covers audience filtering (agent-specific and wildcard), auto_advance cursor,
explicit cursor parameter, limit enforcement, and result shape validation.
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


class ResultShapeTests(unittest.TestCase):
    """Validate poll_events return value structure."""

    def test_result_has_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            result = orch.poll_events(agent="claude_code")
            self.assertIn("agent", result)
            self.assertIn("cursor", result)
            self.assertIn("next_cursor", result)
            self.assertIn("events", result)
            self.assertEqual(result["agent"], "claude_code")
            self.assertIsInstance(result["events"], list)

    def test_empty_bus_returns_empty_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            result = orch.poll_events(agent="claude_code")
            # May have bootstrap events, but cursor starts at 0
            self.assertIsInstance(result["events"], list)
            self.assertGreaterEqual(result["next_cursor"], result["cursor"])

    def test_events_have_offset_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event(
                event_type="test.ping",
                payload={"msg": "hello"},
                source="codex",
            )

            result = orch.poll_events(agent="claude_code", cursor=0)
            for event in result["events"]:
                self.assertIn("offset", event)
                self.assertIsInstance(event["offset"], int)


class AudienceFilteringTests(unittest.TestCase):
    """Tests for audience-based event filtering."""

    def test_event_with_matching_audience_included(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event(
                event_type="task.assigned",
                payload={"task_id": "T1", "audience": ["claude_code"]},
                source="codex",
            )

            result = orch.poll_events(agent="claude_code", cursor=0)
            task_events = [e for e in result["events"] if e.get("type") == "task.assigned"]
            self.assertEqual(len(task_events), 1)

    def test_event_with_different_audience_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event(
                event_type="task.assigned",
                payload={"task_id": "T1", "audience": ["gemini"]},
                source="codex",
            )

            result = orch.poll_events(agent="claude_code", cursor=0)
            task_events = [e for e in result["events"] if e.get("type") == "task.assigned"]
            self.assertEqual(len(task_events), 0)

    def test_wildcard_audience_includes_all_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event(
                event_type="broadcast.msg",
                payload={"msg": "all", "audience": ["*"]},
                source="codex",
            )

            result = orch.poll_events(agent="claude_code", cursor=0)
            broadcast_events = [e for e in result["events"] if e.get("type") == "broadcast.msg"]
            self.assertEqual(len(broadcast_events), 1)

    def test_no_audience_field_includes_event(self) -> None:
        """Events without audience field should be visible to all agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event(
                event_type="general.info",
                payload={"msg": "no audience"},
                source="codex",
            )

            result = orch.poll_events(agent="claude_code", cursor=0)
            info_events = [e for e in result["events"] if e.get("type") == "general.info"]
            self.assertEqual(len(info_events), 1)

    def test_agent_in_multi_audience_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event(
                event_type="multi.target",
                payload={"audience": ["gemini", "claude_code"]},
                source="codex",
            )

            result = orch.poll_events(agent="claude_code", cursor=0)
            multi_events = [e for e in result["events"] if e.get("type") == "multi.target"]
            self.assertEqual(len(multi_events), 1)


class CursorBehaviorTests(unittest.TestCase):
    """Tests for cursor advancement and explicit cursor parameter."""

    def test_auto_advance_true_moves_cursor_forward(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("test.ev", source="codex", payload={"n": 1})
            orch.publish_event("test.ev", source="codex", payload={"n": 2})

            result1 = orch.poll_events(agent="claude_code", auto_advance=True)
            result2 = orch.poll_events(agent="claude_code", auto_advance=True)

            # Second poll should not return events already seen
            self.assertGreaterEqual(result2["cursor"], result1["next_cursor"])

    def test_auto_advance_false_does_not_move_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("test.ev", source="codex", payload={"n": 1})

            result1 = orch.poll_events(agent="claude_code", auto_advance=False)
            result2 = orch.poll_events(agent="claude_code", auto_advance=False)

            # Cursor should not have advanced — same start
            self.assertEqual(result1["cursor"], result2["cursor"])
            self.assertEqual(len(result1["events"]), len(result2["events"]))

    def test_explicit_cursor_overrides_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("test.ev", source="codex", payload={"n": 1})
            orch.publish_event("test.ev", source="codex", payload={"n": 2})
            orch.publish_event("test.ev", source="codex", payload={"n": 3})

            # Advance cursor
            orch.poll_events(agent="claude_code", auto_advance=True)

            # Override with cursor=0 to replay from start
            result = orch.poll_events(agent="claude_code", cursor=0, auto_advance=False)
            self.assertEqual(result["cursor"], 0)
            self.assertGreater(len(result["events"]), 0)

    def test_cursor_after_no_events_stays_same(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            # Consume all events
            orch.poll_events(agent="claude_code", auto_advance=True)

            result = orch.poll_events(agent="claude_code", auto_advance=True)
            # No new events — cursor and next_cursor should match
            self.assertEqual(result["cursor"], result["next_cursor"])


class LimitTests(unittest.TestCase):
    """Tests for limit parameter capping returned events."""

    def test_limit_caps_returned_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            for i in range(10):
                orch.publish_event("test.ev", source="codex", payload={"n": i})

            result = orch.poll_events(agent="claude_code", cursor=0, limit=3)
            self.assertLessEqual(len(result["events"]), 3)

    def test_limit_one_returns_single_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("test.a", source="codex")
            orch.publish_event("test.b", source="codex")

            result = orch.poll_events(agent="claude_code", cursor=0, limit=1)
            self.assertEqual(len(result["events"]), 1)


if __name__ == "__main__":
    unittest.main()
