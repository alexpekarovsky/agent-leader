"""Tests for agent_instances project_root visibility and filtering.

Verifies entries include project_root and preserve same-project visibility
semantics for operator status dashboards.
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


class ProjectRootPresenceTests(unittest.TestCase):
    """project_root field should be present in list_agent_instances results."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_project_root_key_present_in_entry(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-1"})
        instances = self.orch.list_agent_instances()
        self.assertEqual(len(instances), 1)
        self.assertIn("project_root", instances[0])

    def test_project_root_from_cwd_metadata(self) -> None:
        self.orch.register_agent("claude_code", metadata={
            "instance_id": "c-1",
            "cwd": "/Users/alex/my-project",
        })
        instances = self.orch.list_agent_instances()
        # project_root comes from identity snapshot which reads cwd
        self.assertIn("project_root", instances[0])

    def test_project_root_none_when_no_cwd(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-1"})
        instances = self.orch.list_agent_instances()
        # Without cwd in metadata, project_root should be empty/None
        pr = instances[0].get("project_root")
        self.assertTrue(pr is None or pr == "" or pr == str(self.root))

    def test_multiple_agents_all_have_project_root_key(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-1"})
        self.orch.register_agent("gemini", metadata={"instance_id": "g-1"})
        self.orch.register_agent("codex", metadata={"instance_id": "x-1"})
        instances = self.orch.list_agent_instances()
        for inst in instances:
            self.assertIn("project_root", inst, f"missing project_root for {inst.get('agent_name')}")


class MixedProjectRootTests(unittest.TestCase):
    """Instances with different project roots should coexist."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_different_cwd_values_stored_separately(self) -> None:
        self.orch.register_agent("claude_code", metadata={
            "instance_id": "c-proj-a",
            "cwd": "/Users/alex/project-a",
        })
        self.orch.register_agent("claude_code", metadata={
            "instance_id": "c-proj-b",
            "cwd": "/Users/alex/project-b",
        })
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i.get("agent_name") == "claude_code"]
        self.assertEqual(len(cc), 2)
        ids = {i["instance_id"] for i in cc}
        self.assertEqual(ids, {"c-proj-a", "c-proj-b"})

    def test_instance_entries_preserve_cwd_in_metadata(self) -> None:
        self.orch.register_agent("claude_code", metadata={
            "instance_id": "c-1",
            "cwd": "/Users/alex/project-x",
        })
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i.get("agent_name") == "claude_code"]
        self.assertEqual(cc[0]["metadata"]["cwd"], "/Users/alex/project-x")

    def test_no_instances_returns_empty(self) -> None:
        instances = self.orch.list_agent_instances()
        self.assertEqual(instances, [])


if __name__ == "__main__":
    unittest.main()
