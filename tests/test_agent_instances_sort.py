"""Tests for list_agent_instances sort order (agent_name, instance_id).

Ensures stable presentation for dashboards and status tooling.
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


class AgentInstancesSortOrderTests(unittest.TestCase):
    """Sort order is (agent_name, instance_id) ascending."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_single_agent_single_instance(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-1"})
        instances = self.orch.list_agent_instances()
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0]["agent_name"], "claude_code")

    def test_two_agents_sorted_by_name(self) -> None:
        self.orch.register_agent("gemini", metadata={"instance_id": "g-1"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-1"})
        instances = self.orch.list_agent_instances()
        names = [i["agent_name"] for i in instances]
        self.assertEqual(names, ["claude_code", "gemini"])

    def test_three_agents_alphabetical(self) -> None:
        self.orch.register_agent("gemini", metadata={"instance_id": "g-1"})
        self.orch.register_agent("codex", metadata={"instance_id": "x-1"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-1"})
        instances = self.orch.list_agent_instances()
        names = [i["agent_name"] for i in instances]
        self.assertEqual(names, ["claude_code", "codex", "gemini"])

    def test_same_agent_multiple_instances_sorted_by_instance_id(self) -> None:
        """Multiple instances of the same agent sorted by instance_id."""
        self.orch.register_agent("claude_code", metadata={"instance_id": "cc-beta"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "cc-alpha"})
        instances = self.orch.list_agent_instances()
        cc_instances = [i for i in instances if i["agent_name"] == "claude_code"]
        ids = [i["instance_id"] for i in cc_instances]
        self.assertEqual(ids, sorted(ids))

    def test_mixed_agents_and_instances_fully_sorted(self) -> None:
        """Multiple agents with multiple instances, all sorted correctly."""
        self.orch.register_agent("gemini", metadata={"instance_id": "g-2"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "cc-2"})
        self.orch.register_agent("gemini", metadata={"instance_id": "g-1"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "cc-1"})
        instances = self.orch.list_agent_instances()
        pairs = [(i["agent_name"], i["instance_id"]) for i in instances]
        self.assertEqual(pairs, sorted(pairs))

    def test_sort_is_stable_across_calls(self) -> None:
        self.orch.register_agent("gemini", metadata={"instance_id": "g-1"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-1"})
        self.orch.register_agent("codex", metadata={"instance_id": "x-1"})
        first = [(i["agent_name"], i.get("instance_id")) for i in self.orch.list_agent_instances()]
        second = [(i["agent_name"], i.get("instance_id")) for i in self.orch.list_agent_instances()]
        self.assertEqual(first, second)

    def test_sort_with_default_instance_ids(self) -> None:
        """Agents registered without explicit instance_id get agent#default."""
        self.orch.register_agent("gemini")
        self.orch.register_agent("claude_code")
        instances = self.orch.list_agent_instances()
        names = [i["agent_name"] for i in instances]
        self.assertEqual(names, ["claude_code", "gemini"])

    def test_empty_instances_returns_empty_list(self) -> None:
        instances = self.orch.list_agent_instances()
        self.assertEqual(instances, [])


if __name__ == "__main__":
    unittest.main()
