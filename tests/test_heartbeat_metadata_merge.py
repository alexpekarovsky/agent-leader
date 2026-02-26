"""Tests for heartbeat metadata merge preserving prior instance_id.

Covers heartbeat updates that omit instance_id ensuring previously stored
instance_id is preserved, and that other metadata fields are not regressed.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    data = {
        "name": "test-policy",
        "manager": "codex",
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "architecture_mode": "solo",
        "triggers": {},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


class HeartbeatPreservesInstanceIdTests(unittest.TestCase):
    """Heartbeat without instance_id should preserve the stored one."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_heartbeat_no_metadata_preserves_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42"})
        entry = self.orch.heartbeat("claude_code")
        self.assertEqual(entry["metadata"]["instance_id"], "inst-42")

    def test_heartbeat_empty_metadata_preserves_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42"})
        entry = self.orch.heartbeat("claude_code", metadata={})
        self.assertEqual(entry["metadata"]["instance_id"], "inst-42")

    def test_heartbeat_metadata_without_instance_id_preserves_it(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42", "client": "cli"})
        entry = self.orch.heartbeat("claude_code", metadata={"model": "opus"})
        self.assertEqual(entry["metadata"]["instance_id"], "inst-42")

    def test_heartbeat_session_id_preserves_derived_instance_id(self) -> None:
        """If instance_id was derived from session_id, heartbeat without it should keep it."""
        self.orch.register_agent("claude_code", metadata={"session_id": "sess-99"})
        entry = self.orch.heartbeat("claude_code")
        self.assertEqual(entry["metadata"]["instance_id"], "sess-99")

    def test_heartbeat_connection_id_preserves_derived_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"connection_id": "conn-77"})
        entry = self.orch.heartbeat("claude_code")
        self.assertEqual(entry["metadata"]["instance_id"], "conn-77")

    def test_multiple_heartbeats_preserve_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "stable-id"})
        for _ in range(5):
            entry = self.orch.heartbeat("claude_code")
        self.assertEqual(entry["metadata"]["instance_id"], "stable-id")


class HeartbeatMetadataMergeTests(unittest.TestCase):
    """Heartbeat with partial metadata should merge without losing fields."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_heartbeat_adds_new_field_without_losing_existing(self) -> None:
        self.orch.register_agent("claude_code", metadata={"client": "cli", "instance_id": "id-1"})
        entry = self.orch.heartbeat("claude_code", metadata={"model": "opus"})
        self.assertEqual(entry["metadata"]["client"], "cli")
        self.assertEqual(entry["metadata"]["model"], "opus")
        self.assertEqual(entry["metadata"]["instance_id"], "id-1")

    def test_heartbeat_updates_existing_field(self) -> None:
        self.orch.register_agent("claude_code", metadata={"model": "sonnet", "instance_id": "id-1"})
        entry = self.orch.heartbeat("claude_code", metadata={"model": "opus"})
        self.assertEqual(entry["metadata"]["model"], "opus")
        self.assertEqual(entry["metadata"]["instance_id"], "id-1")

    def test_heartbeat_new_instance_id_overrides_old(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "old-id"})
        entry = self.orch.heartbeat("claude_code", metadata={"instance_id": "new-id"})
        self.assertEqual(entry["metadata"]["instance_id"], "new-id")

    def test_heartbeat_updates_last_seen(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "id-1"})
        entry1 = self.orch.heartbeat("claude_code")
        ts1 = entry1["last_seen"]
        entry2 = self.orch.heartbeat("claude_code")
        ts2 = entry2["last_seen"]
        self.assertTrue(ts2 >= ts1)

    def test_heartbeat_status_remains_active(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "id-1"})
        entry = self.orch.heartbeat("claude_code")
        self.assertEqual(entry["status"], "active")


class HeartbeatUnregisteredAgentTests(unittest.TestCase):
    """Heartbeat for an agent not yet registered."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_heartbeat_creates_entry_with_default_instance_id(self) -> None:
        entry = self.orch.heartbeat("new_agent")
        self.assertEqual(entry["metadata"]["instance_id"], "new_agent#default")

    def test_heartbeat_creates_entry_with_provided_instance_id(self) -> None:
        entry = self.orch.heartbeat("new_agent", metadata={"instance_id": "fresh-id"})
        self.assertEqual(entry["metadata"]["instance_id"], "fresh-id")

    def test_heartbeat_creates_active_entry(self) -> None:
        entry = self.orch.heartbeat("new_agent")
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["agent"], "new_agent")


if __name__ == "__main__":
    unittest.main()
