"""Tests for list_agents exposing instance_id in active/offline entries.

Covers instance_id presence in list_agents results for active agents,
offline/stale agents, and transitions between states.
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


class ListAgentsActiveInstanceIdTests(unittest.TestCase):
    """instance_id should be present in agent entries returned by list_agents."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_agent_has_instance_id_in_metadata(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42"})
        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(len(cc), 1)
        self.assertEqual(cc[0]["metadata"]["instance_id"], "inst-42")

    def test_agent_session_derived_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"session_id": "sess-99"})
        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(len(cc), 1)
        self.assertEqual(cc[0]["metadata"]["instance_id"], "sess-99")

    def test_agent_default_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={})
        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(len(cc), 1)
        self.assertEqual(cc[0]["metadata"]["instance_id"], "claude_code#default")

    def test_multiple_agents_each_have_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "cc-1"})
        self.orch.register_agent("gemini", metadata={"instance_id": "gem-1"})
        agents = self.orch.list_agents(active_only=False)
        by_name = {a["agent"]: a for a in agents}
        self.assertEqual(by_name["claude_code"]["metadata"]["instance_id"], "cc-1")
        self.assertEqual(by_name["gemini"]["metadata"]["instance_id"], "gem-1")


class ListAgentsOfflineInstanceIdTests(unittest.TestCase):
    """instance_id should survive stale/offline transitions."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_offline_agent_still_has_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42"})
        # Make agent stale by setting last_seen far in the past
        agents_data = json.loads(self.orch.agents_path.read_text(encoding="utf-8"))
        agents_data["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch.agents_path.write_text(json.dumps(agents_data), encoding="utf-8")

        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(len(cc), 1)
        self.assertEqual(cc[0]["metadata"]["instance_id"], "inst-42")
        self.assertEqual(cc[0]["status"], "offline")

    def test_stale_transition_preserves_metadata_fields(self) -> None:
        self.orch.register_agent("claude_code", metadata={
            "instance_id": "inst-42", "client": "cli", "model": "opus"
        })
        agents_data = json.loads(self.orch.agents_path.read_text(encoding="utf-8"))
        agents_data["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch.agents_path.write_text(json.dumps(agents_data), encoding="utf-8")

        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(cc[0]["metadata"]["instance_id"], "inst-42")
        self.assertEqual(cc[0]["metadata"]["client"], "cli")
        self.assertEqual(cc[0]["metadata"]["model"], "opus")

    def test_active_only_excludes_offline(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42"})
        agents_data = json.loads(self.orch.agents_path.read_text(encoding="utf-8"))
        agents_data["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch.agents_path.write_text(json.dumps(agents_data), encoding="utf-8")

        agents = self.orch.list_agents(active_only=True)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(len(cc), 0)

    def test_instance_id_key_always_present(self) -> None:
        """Even with minimal registration, instance_id key must exist."""
        self.orch.register_agent("claude_code")
        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertIn("instance_id", cc[0]["metadata"])


if __name__ == "__main__":
    unittest.main()
