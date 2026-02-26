"""Dispatch telemetry event contract tests (TASK-d9264c54).

Covers the publish_event contract and dispatch telemetry events:
- publish_event produces event with correct type, source, payload
- events have required fields (type, source, timestamp, offset/event_id)
- audience filtering works correctly
- correlation_id propagation through payload
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


class PublishEventContractTests(unittest.TestCase):
    """Verify publish_event produces events with correct structure."""

    def test_event_has_correct_type(self) -> None:
        """Published event must have the specified type."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="dispatch.command",
                source="codex",
                payload={"task_id": "TASK-001"},
            )

            self.assertEqual("dispatch.command", event["type"])

    def test_event_has_correct_source(self) -> None:
        """Published event must have the specified source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="test.source",
                source="claude_code",
                payload={},
            )

            self.assertEqual("claude_code", event["source"])

    def test_event_has_payload(self) -> None:
        """Published event must carry the provided payload."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="test.payload",
                source="codex",
                payload={"key1": "value1", "key2": 42},
            )

            self.assertEqual("value1", event["payload"]["key1"])
            self.assertEqual(42, event["payload"]["key2"])

    def test_event_with_none_payload_defaults_to_empty_dict(self) -> None:
        """publish_event with no payload should default to empty dict."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="test.nopayload",
                source="codex",
            )

            self.assertIsInstance(event["payload"], dict)


class EventRequiredFieldsTests(unittest.TestCase):
    """Verify all required fields are present on published events."""

    def test_event_has_event_id(self) -> None:
        """Event must have an event_id starting with EVT-."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event("test.id", "codex", {})

            self.assertIn("event_id", event)
            self.assertTrue(event["event_id"].startswith("EVT-"))

    def test_event_has_timestamp(self) -> None:
        """Event must have an ISO-format timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event("test.ts", "codex", {})

            self.assertIn("timestamp", event)
            self.assertIsInstance(event["timestamp"], str)
            # Should be parseable as ISO format (contains T separator)
            self.assertIn("T", event["timestamp"])

    def test_event_has_type_field(self) -> None:
        """Event must have a type field."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event("test.type", "codex", {})

            self.assertIn("type", event)
            self.assertEqual("test.type", event["type"])

    def test_event_has_source_field(self) -> None:
        """Event must have a source field."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event("test.src", "claude_code", {})

            self.assertIn("source", event)
            self.assertEqual("claude_code", event["source"])

    def test_unique_event_ids(self) -> None:
        """Each published event must have a unique event_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            e1 = orch.publish_event("test.uniq1", "codex", {})
            e2 = orch.publish_event("test.uniq2", "codex", {})
            e3 = orch.publish_event("test.uniq3", "codex", {})

            ids = {e1["event_id"], e2["event_id"], e3["event_id"]}
            self.assertEqual(3, len(ids), "Event IDs must be unique")

    def test_event_persisted_to_jsonl(self) -> None:
        """Event must be persisted in the JSONL event log with all fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            event = orch.publish_event("test.persist", "codex", {"flag": True})

            lines = orch.bus.events_path.read_text(encoding="utf-8").strip().split("\n")
            persisted = json.loads(lines[0])
            self.assertEqual(event["event_id"], persisted["event_id"])
            self.assertEqual("test.persist", persisted["type"])
            self.assertEqual("codex", persisted["source"])
            self.assertIn("timestamp", persisted)
            self.assertTrue(persisted["payload"]["flag"])


class AudienceFilteringTests(unittest.TestCase):
    """Verify audience filtering on publish and poll."""

    def test_audience_embedded_in_payload(self) -> None:
        """When audience is specified, it must appear in the event payload."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="test.audience",
                source="codex",
                payload={"data": "hello"},
                audience=["claude_code"],
            )

            self.assertIn("audience", event["payload"])
            self.assertEqual(["claude_code"], event["payload"]["audience"])

    def test_no_audience_means_broadcast(self) -> None:
        """Event without audience should not have audience key in payload."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="test.broadcast",
                source="codex",
                payload={"msg": "hi"},
            )

            self.assertNotIn("audience", event["payload"])

    def test_audience_filtering_excludes_non_target(self) -> None:
        """poll_events must exclude events targeted at other agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")

            # Advance cursor past bootstrap/registration events
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)

            # Publish event targeted only at gemini
            orch.publish_event(
                "private.msg",
                "codex",
                {"secret": "for-gemini"},
                audience=["gemini"],
            )
            # Publish broadcast event
            orch.publish_event(
                "public.msg",
                "codex",
                {"msg": "for-all"},
            )

            result = orch.poll_events("claude_code", timeout_ms=0)
            types = [e["type"] for e in result["events"]]

            self.assertNotIn("private.msg", types)
            self.assertIn("public.msg", types)

    def test_audience_filtering_includes_target(self) -> None:
        """poll_events must include events targeted at the polling agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            # Advance cursor past bootstrap/registration events
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)

            orch.publish_event(
                "targeted.msg",
                "codex",
                {"data": "for-claude"},
                audience=["claude_code"],
            )

            result = orch.poll_events("claude_code", timeout_ms=0)
            types = [e["type"] for e in result["events"]]

            self.assertIn("targeted.msg", types)

    def test_multi_agent_audience(self) -> None:
        """Event with multiple audience members should reach all of them."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")

            # Advance cursors
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)
            orch.poll_events("gemini", timeout_ms=0, auto_advance=True)

            orch.publish_event(
                "multi.target",
                "codex",
                {"info": "shared"},
                audience=["claude_code", "gemini"],
            )

            cc_result = orch.poll_events("claude_code", timeout_ms=0)
            gm_result = orch.poll_events("gemini", timeout_ms=0)

            cc_types = [e["type"] for e in cc_result["events"]]
            gm_types = [e["type"] for e in gm_result["events"]]

            self.assertIn("multi.target", cc_types)
            self.assertIn("multi.target", gm_types)


class CorrelationIdPropagationTests(unittest.TestCase):
    """Verify correlation_id propagation through dispatch payloads."""

    def test_correlation_id_in_payload(self) -> None:
        """correlation_id placed in payload should be preserved."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            event = orch.publish_event(
                event_type="dispatch.command",
                source="codex",
                payload={
                    "correlation_id": "CMD-abc123",
                    "task_id": "TASK-001",
                    "agent": "claude_code",
                },
            )

            self.assertEqual("CMD-abc123", event["payload"]["correlation_id"])

    def test_correlation_id_survives_poll(self) -> None:
        """correlation_id should be available when event is polled."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            # Advance cursor past bootstrap events
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=True)

            orch.publish_event(
                "dispatch.command",
                "codex",
                {"correlation_id": "CMD-xyz789", "task_id": "TASK-002"},
            )

            result = orch.poll_events("claude_code", timeout_ms=0)
            dispatch_events = [
                e for e in result["events"] if e["type"] == "dispatch.command"
            ]
            self.assertEqual(1, len(dispatch_events))
            self.assertEqual("CMD-xyz789", dispatch_events[0]["payload"]["correlation_id"])

    def test_claim_override_propagates_correlation_id(self) -> None:
        """Claiming via override should emit dispatch.ack with correlation_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            task = orch.create_task(
                title="Correlation test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.set_claim_override(
                agent="claude_code",
                task_id=task["id"],
                source="codex",
            )

            # Clear events to isolate claim events
            orch.bus.events_path.write_text("", encoding="utf-8")

            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            events = list(orch.bus.iter_events())
            ack_events = [e for e in events if e["type"] == "dispatch.ack"]
            self.assertGreaterEqual(len(ack_events), 1)
            ack = ack_events[0]
            self.assertIn("correlation_id", ack["payload"])
            self.assertTrue(ack["payload"]["correlation_id"].startswith("CMD-"))
            self.assertEqual("claim_override_consumed", ack["payload"]["ack_type"])

    def test_dispatch_events_in_jsonl_preserve_correlation(self) -> None:
        """correlation_id must be preserved when reading back from JSONL log."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Clear bootstrap events
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.publish_event(
                "dispatch.result",
                "claude_code",
                {"correlation_id": "CMD-persist", "result": "ok"},
            )

            events = list(orch.bus.iter_events())
            result_events = [e for e in events if e["type"] == "dispatch.result"]
            self.assertEqual(1, len(result_events))
            self.assertEqual("CMD-persist", result_events[0]["payload"]["correlation_id"])


class DispatchEventTypeTests(unittest.TestCase):
    """Verify dispatch-specific event types are properly formed."""

    def test_task_claimed_event_on_claim(self) -> None:
        """claim_next_task must emit a task.claimed event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Claim event test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            # Clear events
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.claim_next_task("claude_code")

            events = list(orch.bus.iter_events())
            claimed_events = [e for e in events if e["type"] == "task.claimed"]
            self.assertEqual(1, len(claimed_events))
            self.assertEqual("claude_code", claimed_events[0]["source"])
            self.assertIn("task_id", claimed_events[0]["payload"])
            self.assertIn("owner", claimed_events[0]["payload"])

    def test_task_reported_event_on_report(self) -> None:
        """ingest_report must emit a task.reported event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Report event test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.claim_next_task("claude_code")

            # Clear events
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "evt123",
                "status": "done",
                "test_summary": {"command": "test", "passed": 1, "failed": 0},
            })

            events = list(orch.bus.iter_events())
            reported_events = [e for e in events if e["type"] == "task.reported"]
            self.assertEqual(1, len(reported_events))
            self.assertEqual(task["id"], reported_events[0]["payload"]["task_id"])

    def test_lease_renewed_event_on_renew(self) -> None:
        """renew_task_lease must emit a task.lease_renewed event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Renew event test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            lease_id = claimed["lease"]["lease_id"]

            # Clear events
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            events = list(orch.bus.iter_events())
            renewed_events = [e for e in events if e["type"] == "task.lease_renewed"]
            self.assertEqual(1, len(renewed_events))
            self.assertEqual(claimed["id"], renewed_events[0]["payload"]["task_id"])
            self.assertEqual(lease_id, renewed_events[0]["payload"]["lease_id"])


if __name__ == "__main__":
    unittest.main()
