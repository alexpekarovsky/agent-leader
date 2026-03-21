"""Tests for event bus compaction with cursor safety.

Validates that:
- Events beyond retention limit are archived to rotated file
- Agent cursors are adjusted during compaction to remain valid
- No event loss for connected agents during compaction
- Configurable retention limit via policy
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bus import EventBus
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, event_retention_limit: int = 500) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code"]}},
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "event_retention_limit": event_retention_limit,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(tmpdir: Path, event_retention_limit: int = 500) -> Orchestrator:
    policy = _make_policy(tmpdir / "policy.json", event_retention_limit)
    return Orchestrator(root=tmpdir, policy=policy)


def _register_agent(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": False,
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })


class EventBusCompactTests(unittest.TestCase):
    """Low-level EventBus.compact_events() tests."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.bus = EventBus(self.tmpdir / "bus")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_compaction_below_limit(self) -> None:
        for i in range(5):
            self.bus.emit("test.evt", {"n": i}, source="codex")
        result = self.bus.compact_events(retention_limit=10)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 5)
        self.assertEqual(result["offset_adjustment"], 0)

    def test_compaction_archives_oldest_events(self) -> None:
        for i in range(20):
            self.bus.emit("test.evt", {"n": i}, source="codex")
        result = self.bus.compact_events(retention_limit=10)
        self.assertEqual(result["archived"], 10)
        self.assertEqual(result["retained"], 10)
        self.assertEqual(result["offset_adjustment"], 10)

        # Verify retained events are the newest 10
        remaining = list(self.bus.iter_events())
        self.assertEqual(len(remaining), 10)
        payloads = [e["payload"]["n"] for e in remaining]
        self.assertEqual(payloads, list(range(10, 20)))

    def test_archive_file_created(self) -> None:
        for i in range(15):
            self.bus.emit("test.evt", {"n": i}, source="codex")
        result = self.bus.compact_events(retention_limit=5)
        archive_path = Path(result["archive_path"])
        self.assertTrue(archive_path.exists())
        # Archive should contain the 10 oldest events
        with archive_path.open("r") as fh:
            lines = [l for l in fh if l.strip()]
        self.assertEqual(len(lines), 10)

    def test_compaction_on_empty_bus(self) -> None:
        result = self.bus.compact_events(retention_limit=100)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 0)

    def test_compaction_exact_limit(self) -> None:
        for i in range(10):
            self.bus.emit("test.evt", {"n": i}, source="codex")
        result = self.bus.compact_events(retention_limit=10)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 10)


class OrchestratorCompactTests(unittest.TestCase):
    """Orchestrator.compact_events() with cursor adjustment."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.orch = _make_orch(self.tmpdir, event_retention_limit=10)
        _register_agent(self.orch, "claude_code")
        _register_agent(self.orch, "gemini")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cursors_adjusted_after_compaction(self) -> None:
        # Emit enough events to exceed limit (registration already adds some)
        for i in range(20):
            self.orch.publish_event(f"test.bulk.{i}", source="codex")
        # Advance cursors by polling
        self.orch.poll_events(agent="claude_code")
        self.orch.poll_events(agent="gemini")

        cursor_before_cc = self.orch.get_agent_cursor("claude_code")
        cursor_before_gem = self.orch.get_agent_cursor("gemini")
        self.assertGreater(cursor_before_cc, 0)

        result = self.orch.compact_events()
        offset_adj = result["offset_adjustment"]
        self.assertGreater(offset_adj, 0)

        cursor_after_cc = self.orch.get_agent_cursor("claude_code")
        cursor_after_gem = self.orch.get_agent_cursor("gemini")
        self.assertEqual(cursor_after_cc, max(0, cursor_before_cc - offset_adj))
        self.assertEqual(cursor_after_gem, max(0, cursor_before_gem - offset_adj))

    def test_no_event_loss_for_agent_mid_stream(self) -> None:
        """Agent that hasn't polled yet should still see retained events after compaction."""
        # Emit events but don't advance gemini's cursor
        for i in range(20):
            self.orch.publish_event(f"test.seq.{i}", source="codex")

        # Only advance claude_code cursor
        self.orch.poll_events(agent="claude_code")

        # Compact
        result = self.orch.compact_events()
        self.assertGreater(result["archived"], 0)

        # gemini's cursor was 0, after adjustment it should be 0 (clamped)
        cursor_gem = self.orch.get_agent_cursor("gemini")
        self.assertEqual(cursor_gem, 0)

        # gemini can still poll and get the retained events
        poll_result = self.orch.poll_events(agent="gemini")
        self.assertGreater(len(poll_result["events"]), 0)

    def test_policy_configures_retention_limit(self) -> None:
        """Retention limit comes from policy triggers."""
        subdir = self.tmpdir / "sub"
        subdir.mkdir()
        orch5 = _make_orch(subdir, event_retention_limit=5)
        _register_agent(orch5, "codex")
        for i in range(12):
            orch5.publish_event(f"test.pol.{i}", source="codex")
        result = orch5.compact_events()
        # 1 registration event + 12 published = 13 total, retain 5
        self.assertEqual(result["retained"], 5)
        remaining = list(orch5.bus.iter_events())
        # 5 retained + 1 events.compacted event emitted after compaction
        self.assertEqual(len(remaining), 6)

    def test_compaction_emits_events_compacted_event(self) -> None:
        for i in range(20):
            self.orch.publish_event(f"test.emit.{i}", source="codex")
        self.orch.compact_events()
        # The events.compacted event is emitted after compaction
        all_events = list(self.orch.bus.iter_events())
        compacted_events = [e for e in all_events if e["type"] == "events.compacted"]
        self.assertEqual(len(compacted_events), 1)
        payload = compacted_events[0]["payload"]
        self.assertIn("archived", payload)
        self.assertIn("retained", payload)
        self.assertIn("offset_adjustment", payload)

    def test_explicit_retention_limit_overrides_policy(self) -> None:
        for i in range(20):
            self.orch.publish_event(f"test.override.{i}", source="codex")
        result = self.orch.compact_events(retention_limit=5)
        self.assertEqual(result["retained"], 5)

    def test_poll_after_compaction_returns_correct_events(self) -> None:
        """After compaction, polling should continue seamlessly."""
        # Emit events and advance cursor partway
        for i in range(15):
            self.orch.publish_event(f"test.pre.{i}", source="codex")
        self.orch.poll_events(agent="claude_code", limit=10)

        # Emit more
        for i in range(5):
            self.orch.publish_event(f"test.post.{i}", source="codex")

        # Compact
        self.orch.compact_events()

        # Poll should return remaining unread events without duplicates or gaps
        result = self.orch.poll_events(agent="claude_code")
        types = [e["type"] for e in result["events"]]
        # Should see the post events (and possibly some pre events still in retention window)
        post_types = [t for t in types if t.startswith("test.post.")]
        self.assertGreater(len(post_types), 0)

    def test_requeue_stale_triggers_compaction(self) -> None:
        """requeue_stale_in_progress_tasks should call compact_events."""
        for i in range(20):
            self.orch.publish_event(f"test.stale.{i}", source="codex")
        # Count events before
        before = len(list(self.orch.bus.iter_events()))
        self.assertGreater(before, 10)

        self.orch.requeue_stale_in_progress_tasks()

        # After requeue (which triggers compaction), events should be trimmed
        after = len(list(self.orch.bus.iter_events()))
        # retained <= limit (10) + any events emitted during compaction/requeue
        self.assertLessEqual(after, 15)


if __name__ == "__main__":
    unittest.main()
