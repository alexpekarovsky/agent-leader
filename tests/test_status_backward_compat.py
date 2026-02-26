"""Status regression test for backward compatibility without instance_id.

Verifies orchestrator remains backward compatible when agents connect
without instance_id metadata and fallback derivation is used. Ensures
stable payload keys for older clients that don't send identity fields.
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


class NoInstanceIdBackwardCompatTests(unittest.TestCase):
    """Agents connecting without instance_id should get fallback derivation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_without_metadata_succeeds(self) -> None:
        entry = self.orch.register_agent("claude_code")
        self.assertEqual(entry["agent"], "claude_code")
        self.assertEqual(entry["status"], "active")

    def test_register_without_metadata_has_instance_id(self) -> None:
        entry = self.orch.register_agent("claude_code")
        self.assertIn("instance_id", entry["metadata"])
        self.assertEqual(entry["metadata"]["instance_id"], "claude_code#default")

    def test_heartbeat_without_metadata_succeeds(self) -> None:
        self.orch.register_agent("claude_code")
        entry = self.orch.heartbeat("claude_code")
        self.assertEqual(entry["agent"], "claude_code")
        self.assertEqual(entry["status"], "active")

    def test_list_agents_includes_no_metadata_agent(self) -> None:
        self.orch.register_agent("claude_code")
        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(len(cc), 1)
        self.assertIn("metadata", cc[0])

    def test_list_agent_instances_includes_no_metadata_agent(self) -> None:
        self.orch.register_agent("claude_code")
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i.get("agent_name") == "claude_code"]
        self.assertEqual(len(cc), 1)
        self.assertEqual(cc[0]["instance_id"], "claude_code#default")

    def test_instance_id_in_agent_instances_without_metadata(self) -> None:
        """Agent instances should derive instance_id even with no metadata."""
        self.orch.register_agent("claude_code")
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i.get("agent_name") == "claude_code"]
        self.assertEqual(len(cc), 1)
        self.assertIn("instance_id", cc[0])
        self.assertEqual(cc[0]["instance_id"], "claude_code#default")

    def test_heartbeat_then_list_agents_stable_keys(self) -> None:
        """Heartbeat + list_agents should produce stable keys for old client."""
        self.orch.register_agent("claude_code")
        self.orch.heartbeat("claude_code")
        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        self.assertEqual(len(cc), 1)
        for key in ("agent", "status", "metadata", "last_seen"):
            self.assertIn(key, cc[0])


class MixedClientsCompatTests(unittest.TestCase):
    """Old clients (no instance_id) and new clients (with) should coexist."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_old_and_new_client_coexist_in_list_agents(self) -> None:
        self.orch.register_agent("claude_code")  # old client
        self.orch.register_agent("gemini", metadata={"instance_id": "gem-v2"})  # new client
        agents = self.orch.list_agents(active_only=False)
        cc = [a for a in agents if a.get("agent") == "claude_code"]
        gem = [a for a in agents if a.get("agent") == "gemini"]
        self.assertEqual(len(cc), 1)
        self.assertEqual(len(gem), 1)
        self.assertEqual(cc[0]["metadata"]["instance_id"], "claude_code#default")
        self.assertEqual(gem[0]["metadata"]["instance_id"], "gem-v2")

    def test_old_client_can_upgrade_to_instance_id(self) -> None:
        self.orch.register_agent("claude_code")
        entry1 = self.orch.heartbeat("claude_code")
        self.assertEqual(entry1["metadata"]["instance_id"], "claude_code#default")
        # Now send heartbeat with instance_id (client upgraded)
        entry2 = self.orch.heartbeat("claude_code", metadata={"instance_id": "new-inst"})
        self.assertEqual(entry2["metadata"]["instance_id"], "new-inst")

    def test_stable_payload_keys_for_old_client(self) -> None:
        """Verify all expected keys are present even without identity metadata."""
        self.orch.register_agent("claude_code")
        agents = self.orch.list_agents(active_only=False)
        cc = agents[0]
        for key in ("agent", "status", "metadata", "last_seen"):
            self.assertIn(key, cc, f"missing key: {key}")
        self.assertIn("instance_id", cc["metadata"])


if __name__ == "__main__":
    unittest.main()
