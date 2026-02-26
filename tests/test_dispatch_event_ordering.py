"""Dispatch telemetry event ordering validation tests (TASK-f30fc62a).

Verifies that events in the bus JSONL file maintain correct ordering:
- Events are stored in order
- Events have monotonically increasing offsets
- publish_event returns the event with an offset (via iter_events_from)
- Events from different sources maintain global ordering
- Reading events back preserves insertion order
- Audience-filtered events do not change ordering of remaining events
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
    """Register and heartbeat an agent so it is operational."""
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))


class EventStorageOrderTests(unittest.TestCase):
    """Events must be stored in the JSONL file in the order they were published."""

    def test_events_stored_in_order(self) -> None:
        """Events read back from the bus JSONL must match publication order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            published = []
            for i in range(5):
                event = orch.publish_event(
                    event_type=f"test.order.{i}",
                    source="codex",
                    payload={"seq": i},
                )
                published.append(event)

            stored = list(orch.bus.iter_events())

            self.assertEqual(len(published), len(stored))
            for i, (pub, stored_evt) in enumerate(zip(published, stored)):
                self.assertEqual(pub["event_id"], stored_evt["event_id"],
                                 f"Event {i} event_id mismatch")
                self.assertEqual(pub["type"], stored_evt["type"],
                                 f"Event {i} type mismatch")

    def test_events_have_monotonically_increasing_offsets(self) -> None:
        """When reading events via iter_events_from, offsets must be monotonically increasing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            for i in range(5):
                orch.publish_event(f"test.mono.{i}", "codex", {"seq": i})

            offsets = []
            for idx, event in orch.bus.iter_events_from(start=0):
                offsets.append(idx)

            self.assertEqual(5, len(offsets))
            for i in range(1, len(offsets)):
                self.assertGreater(offsets[i], offsets[i - 1],
                                   f"Offset {offsets[i]} should be greater than {offsets[i-1]}")


class PublishEventReturnsTests(unittest.TestCase):
    """publish_event must return a well-formed event dict."""

    def test_publish_event_returns_event_with_event_id(self) -> None:
        """Returned event must contain event_id and type."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event("test.return", "codex", {"data": "test"})

            self.assertIn("event_id", event)
            self.assertTrue(event["event_id"].startswith("EVT-"))
            self.assertEqual("test.return", event["type"])
            self.assertEqual("codex", event["source"])

    def test_publish_event_returns_timestamp(self) -> None:
        """Returned event must contain an ISO-format timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event("test.ts", "codex", {})

            self.assertIn("timestamp", event)
            self.assertIn("T", event["timestamp"])

    def test_published_event_retrievable_by_offset(self) -> None:
        """After publishing, the event must be retrievable via iter_events_from at correct offset."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            event = orch.publish_event("test.offset", "codex", {"marker": "find_me"})

            found = None
            for idx, evt in orch.bus.iter_events_from(start=0):
                if evt.get("event_id") == event["event_id"]:
                    found = (idx, evt)
                    break

            self.assertIsNotNone(found, "Published event must be found in the event stream")
            self.assertEqual(0, found[0], "First event after clear should be at offset 0")
            self.assertEqual("find_me", found[1]["payload"]["marker"])


class MultiSourceOrderingTests(unittest.TestCase):
    """Events from different sources must maintain global ordering."""

    def test_interleaved_sources_maintain_global_order(self) -> None:
        """Events from codex, claude_code, gemini must appear in publication order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            sources = ["codex", "claude_code", "gemini", "codex", "gemini", "claude_code"]
            published_ids = []
            for i, src in enumerate(sources):
                event = orch.publish_event(f"test.multi.{i}", src, {"index": i})
                published_ids.append(event["event_id"])

            stored = list(orch.bus.iter_events())
            stored_ids = [e["event_id"] for e in stored]

            self.assertEqual(published_ids, stored_ids)

    def test_different_sources_have_unique_event_ids(self) -> None:
        """Events from different sources must all have unique event_ids."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            ids = set()
            for src in ["codex", "claude_code", "gemini"]:
                event = orch.publish_event("test.unique", src, {})
                ids.add(event["event_id"])

            self.assertEqual(3, len(ids), "All event IDs must be unique across sources")


class EventReadbackPreservesOrderTests(unittest.TestCase):
    """Reading events back must preserve the original insertion order."""

    def test_iter_events_preserves_insertion_order(self) -> None:
        """iter_events must return events in the exact order they were appended."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            types_in_order = []
            for i in range(8):
                orch.publish_event(f"test.readback.{i}", "codex", {"seq": i})
                types_in_order.append(f"test.readback.{i}")

            stored = list(orch.bus.iter_events())
            stored_types = [e["type"] for e in stored]

            self.assertEqual(types_in_order, stored_types)

    def test_jsonl_lines_match_event_count(self) -> None:
        """The number of JSONL lines must match the number of events published."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            count = 6
            for i in range(count):
                orch.publish_event(f"test.count.{i}", "codex", {})

            raw_lines = orch.bus.events_path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(count, len(raw_lines))

            # Each line must be valid JSON
            for line in raw_lines:
                parsed = json.loads(line)
                self.assertIn("event_id", parsed)


class AudienceFilterDoesNotAffectOrderTests(unittest.TestCase):
    """Audience-filtered events must not change ordering of remaining events."""

    def test_audience_filtered_events_preserve_order_for_target(self) -> None:
        """Events filtered by audience must still appear in correct order for the target agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")

            # Advance cursors past bootstrap/registration events
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)

            # Publish a mix of targeted and broadcast events
            orch.publish_event("test.broadcast.1", "codex", {"seq": 1})
            orch.publish_event("test.targeted.gemini", "codex", {"seq": 2}, audience=["gemini"])
            orch.publish_event("test.broadcast.2", "codex", {"seq": 3})
            orch.publish_event("test.targeted.claude", "codex", {"seq": 4}, audience=["claude_code"])
            orch.publish_event("test.broadcast.3", "codex", {"seq": 5})

            result = orch.poll_events("claude_code", timeout_ms=0)
            types = [e["type"] for e in result["events"]]

            # claude_code should see broadcasts + its targeted event, but NOT gemini's
            self.assertIn("test.broadcast.1", types)
            self.assertNotIn("test.targeted.gemini", types)
            self.assertIn("test.broadcast.2", types)
            self.assertIn("test.targeted.claude", types)
            self.assertIn("test.broadcast.3", types)

            # Verify the relative order is maintained
            b1_idx = types.index("test.broadcast.1")
            b2_idx = types.index("test.broadcast.2")
            tc_idx = types.index("test.targeted.claude")
            b3_idx = types.index("test.broadcast.3")

            self.assertLess(b1_idx, b2_idx)
            self.assertLess(b2_idx, tc_idx)
            self.assertLess(tc_idx, b3_idx)

    def test_global_event_log_unaffected_by_audience(self) -> None:
        """The raw JSONL log must contain ALL events regardless of audience filtering."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.publish_event("test.all.1", "codex", {})
            orch.publish_event("test.private", "codex", {"secret": True}, audience=["gemini"])
            orch.publish_event("test.all.2", "codex", {})

            all_events = list(orch.bus.iter_events())
            types = [e["type"] for e in all_events]

            self.assertEqual(["test.all.1", "test.private", "test.all.2"], types)


if __name__ == "__main__":
    unittest.main()
