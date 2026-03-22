"""Tests for spec-kit integration: spec file generation from task descriptions."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy
from orchestrator.spec_kit import generate_spec, read_spec


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
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": False,
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })


class TestSpecKitGeneration(unittest.TestCase):
    """Test spec file generation from task descriptions."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_spec_generated_on_task_create(self) -> None:
        """Spec file is auto-generated when a task is created."""
        task = self.orch.create_task(
            title="Implement feature X",
            workstream="backend",
            acceptance_criteria=["Unit tests pass", "API endpoint responds 200"],
            description="Build the new feature X with REST endpoints.",
        )
        task_id = task["id"]
        spec = self.orch.get_spec(task_id)
        self.assertIsNotNone(spec)
        self.assertEqual(spec["task_id"], task_id)
        self.assertEqual(spec["title"], "Implement feature X")
        self.assertEqual(spec["description"], "Build the new feature X with REST endpoints.")

    def test_spec_includes_acceptance_criteria(self) -> None:
        """Spec file includes acceptance criteria from the task."""
        criteria = ["All tests green", "Documentation updated", "No regressions"]
        task = self.orch.create_task(
            title="Add docs",
            workstream="backend",
            acceptance_criteria=criteria,
        )
        spec = self.orch.get_spec(task["id"])
        self.assertEqual(spec["acceptance_criteria"], criteria)

    def test_spec_includes_constraints(self) -> None:
        """Spec file includes delivery profile as constraints."""
        task = self.orch.create_task(
            title="High risk task",
            workstream="backend",
            acceptance_criteria=["Done"],
            risk="high",
            test_plan="full",
            doc_impact="runbook",
        )
        spec = self.orch.get_spec(task["id"])
        self.assertEqual(spec["constraints"]["risk"], "high")
        self.assertEqual(spec["constraints"]["test_plan"], "full")
        self.assertEqual(spec["constraints"]["doc_impact"], "runbook")

    def test_spec_includes_references(self) -> None:
        """Spec file includes project references and tags."""
        task = self.orch.create_task(
            title="Ref task",
            workstream="backend",
            acceptance_criteria=["Done"],
            tags=["infra", "v2"],
            team_id="team-core",
        )
        spec = self.orch.get_spec(task["id"])
        refs = spec["references"]
        self.assertEqual(refs["team_id"], "team-core")
        self.assertIn("infra", refs["tags"])
        self.assertIn("v2", refs["tags"])

    def test_spec_includes_parent_task_reference(self) -> None:
        """Spec file references parent task when present."""
        parent = self.orch.create_task(
            title="Parent task",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        child = self.orch.create_task(
            title="Child task",
            workstream="backend",
            acceptance_criteria=["Done"],
            parent_task_id=parent["id"],
        )
        spec = self.orch.get_spec(child["id"])
        self.assertEqual(spec["references"]["parent_task_id"], parent["id"])

    def test_read_spec_returns_none_for_missing(self) -> None:
        """read_spec returns None when no spec file exists."""
        result = read_spec("TASK-nonexistent", self.root / "bus")
        self.assertIsNone(result)

    def test_spec_file_written_to_disk(self) -> None:
        """Spec file is written as JSON to bus/specs/ directory."""
        task = self.orch.create_task(
            title="Disk check",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        spec_path = self.root / "bus" / "specs" / f"{task['id']}.json"
        self.assertTrue(spec_path.exists())
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        self.assertEqual(data["task_id"], task["id"])

    def test_spec_has_generated_at_timestamp(self) -> None:
        """Spec file includes a generated_at ISO timestamp."""
        task = self.orch.create_task(
            title="Timestamp check",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        spec = self.orch.get_spec(task["id"])
        self.assertIn("generated_at", spec)
        self.assertIsInstance(spec["generated_at"], str)

    def test_deduplicated_task_does_not_generate_spec(self) -> None:
        """Deduplicated tasks should not generate a new spec file."""
        task1 = self.orch.create_task(
            title="Unique task",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        task2 = self.orch.create_task(
            title="Unique task",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        self.assertTrue(task2.get("deduplicated"))
        # Only the original task should have a spec
        self.assertIsNotNone(self.orch.get_spec(task1["id"]))


class TestSpecKitStandalone(unittest.TestCase):
    """Test spec_kit functions directly without Orchestrator."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bus_root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generate_and_read_roundtrip(self) -> None:
        """generate_spec followed by read_spec returns the same data."""
        task = {
            "id": "TASK-abc12345",
            "title": "Sample task",
            "description": "A sample for testing.",
            "workstream": "backend",
            "owner": "claude_code",
            "status": "assigned",
            "acceptance_criteria": ["Criterion A", "Criterion B"],
            "delivery_profile": {"risk": "low", "test_plan": "smoke", "doc_impact": "none"},
            "parent_task_id": None,
            "project_name": "test-project",
            "project_root": "/tmp/test",
            "team_id": "team-alpha",
            "tags": ["backend", "test"],
        }
        path = generate_spec(task, self.bus_root)
        self.assertTrue(path.exists())

        spec = read_spec("TASK-abc12345", self.bus_root)
        self.assertIsNotNone(spec)
        self.assertEqual(spec["task_id"], "TASK-abc12345")
        self.assertEqual(spec["title"], "Sample task")
        self.assertEqual(spec["acceptance_criteria"], ["Criterion A", "Criterion B"])
        self.assertEqual(spec["constraints"]["risk"], "low")
        self.assertEqual(spec["references"]["team_id"], "team-alpha")


if __name__ == "__main__":
    unittest.main()
