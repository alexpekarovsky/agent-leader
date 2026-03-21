"""Tests for comprehend_project task type lifecycle.

Covers: task_type field, comprehension_summary artifact validation,
parent/sub-task relationships, and full lifecycle.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator, TASK_TYPES
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {
            "backend": "claude_code",
            "frontend": "gemini",
            "comprehension": "claude_code",
            "default": "codex",
        },
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


class TestTaskTypeField(unittest.TestCase):
    """Tests for the task_type field on task creation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_default_task_type_is_standard(self) -> None:
        task = self.orch.create_task(
            title="Normal task",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        self.assertEqual(task["task_type"], "standard")

    def test_explicit_standard_task_type(self) -> None:
        task = self.orch.create_task(
            title="Explicit standard",
            workstream="backend",
            acceptance_criteria=["Done"],
            task_type="standard",
        )
        self.assertEqual(task["task_type"], "standard")

    def test_comprehend_project_task_type(self) -> None:
        task = self.orch.create_task(
            title="Comprehend Project: my-app",
            workstream="comprehension",
            acceptance_criteria=["Modules identified", "Patterns documented"],
            task_type="comprehend_project",
        )
        self.assertEqual(task["task_type"], "comprehend_project")
        self.assertEqual(task["workstream"], "comprehension")

    def test_invalid_task_type_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.orch.create_task(
                title="Bad type",
                workstream="backend",
                acceptance_criteria=["Done"],
                task_type="invalid_type",
            )
        self.assertIn("task_type must be one of", str(ctx.exception))

    def test_task_type_case_insensitive(self) -> None:
        task = self.orch.create_task(
            title="Case test",
            workstream="backend",
            acceptance_criteria=["Done"],
            task_type="COMPREHEND_PROJECT",
        )
        self.assertEqual(task["task_type"], "comprehend_project")

    def test_task_types_constant(self) -> None:
        self.assertIn("standard", TASK_TYPES)
        self.assertIn("comprehend_project", TASK_TYPES)


class TestParentSubTaskRelationship(unittest.TestCase):
    """Tests for parent_task_id sub-task support."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")
        _register_agent(self.orch, "gemini")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_sub_task(self) -> None:
        parent = self.orch.create_task(
            title="Comprehend Project: my-app",
            workstream="comprehension",
            acceptance_criteria=["Summary produced"],
            task_type="comprehend_project",
        )
        child = self.orch.create_task(
            title="Comprehend API Surface",
            workstream="backend",
            acceptance_criteria=["API endpoints documented"],
            parent_task_id=parent["id"],
        )
        self.assertEqual(child["parent_task_id"], parent["id"])
        self.assertEqual(child["task_type"], "standard")

    def test_invalid_parent_task_id_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.orch.create_task(
                title="Orphan sub-task",
                workstream="backend",
                acceptance_criteria=["Done"],
                parent_task_id="TASK-nonexist",
            )
        self.assertIn("Parent task not found", str(ctx.exception))

    def test_list_sub_tasks(self) -> None:
        parent = self.orch.create_task(
            title="Comprehend Project: my-app",
            workstream="comprehension",
            acceptance_criteria=["Summary produced"],
            task_type="comprehend_project",
        )
        child1 = self.orch.create_task(
            title="Comprehend DB Schema",
            workstream="backend",
            acceptance_criteria=["DB schema documented"],
            parent_task_id=parent["id"],
        )
        child2 = self.orch.create_task(
            title="Comprehend Frontend Components",
            workstream="frontend",
            acceptance_criteria=["Components listed"],
            parent_task_id=parent["id"],
            owner="gemini",
        )
        # Unrelated task
        self.orch.create_task(
            title="Fix bug",
            workstream="backend",
            acceptance_criteria=["Bug fixed"],
        )

        subs = self.orch.list_sub_tasks(parent["id"])
        self.assertEqual(len(subs), 2)
        sub_ids = {s["id"] for s in subs}
        self.assertIn(child1["id"], sub_ids)
        self.assertIn(child2["id"], sub_ids)

    def test_no_parent_returns_none(self) -> None:
        task = self.orch.create_task(
            title="Standalone task",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        self.assertIsNone(task["parent_task_id"])


class TestComprehensionSummaryValidation(unittest.TestCase):
    """Tests for comprehension_summary artifact validation in reports."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _create_and_claim(self) -> str:
        task = self.orch.create_task(
            title="Comprehend Project: test",
            workstream="comprehension",
            acceptance_criteria=["Modules identified"],
            task_type="comprehend_project",
        )
        self.orch.claim_next_task(owner="claude_code")
        return task["id"]

    def test_valid_comprehension_summary(self) -> None:
        task_id = self._create_and_claim()
        report = self.orch.ingest_report({
            "task_id": task_id,
            "agent": "claude_code",
            "commit_sha": "abc123",
            "status": "done",
            "test_summary": {"command": "python3 -m pytest", "passed": 10, "failed": 0},
            "comprehension_summary": {
                "modules": [
                    {"name": "orchestrator", "responsibility": "Core task orchestration engine"},
                    {"name": "bus", "responsibility": "Event bus for inter-agent communication"},
                ],
                "patterns": ["event-driven", "file-based state persistence"],
                "dependencies": ["fcntl", "json", "pathlib"],
            },
        })
        self.assertEqual(report["task_id"], task_id)
        self.assertIn("comprehension_summary", report)

    def test_missing_required_fields(self) -> None:
        task_id = self._create_and_claim()
        with self.assertRaises(ValueError) as ctx:
            self.orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
                "comprehension_summary": {
                    "modules": [],
                    # missing patterns and dependencies
                },
            })
        self.assertIn("comprehension_summary missing required fields", str(ctx.exception))

    def test_modules_must_be_array(self) -> None:
        task_id = self._create_and_claim()
        with self.assertRaises(ValueError) as ctx:
            self.orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
                "comprehension_summary": {
                    "modules": "not-an-array",
                    "patterns": [],
                    "dependencies": [],
                },
            })
        self.assertIn("comprehension_summary.modules must be an array", str(ctx.exception))

    def test_module_entry_validation(self) -> None:
        task_id = self._create_and_claim()
        with self.assertRaises(ValueError) as ctx:
            self.orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
                "comprehension_summary": {
                    "modules": [{"name": "", "responsibility": "something"}],
                    "patterns": [],
                    "dependencies": [],
                },
            })
        self.assertIn("modules[0].name must be a non-empty string", str(ctx.exception))

    def test_comprehension_summary_must_be_object(self) -> None:
        task_id = self._create_and_claim()
        with self.assertRaises(ValueError) as ctx:
            self.orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
                "comprehension_summary": "not-an-object",
            })
        self.assertIn("comprehension_summary must be an object", str(ctx.exception))

    def test_report_without_summary_still_works(self) -> None:
        """Standard reports without comprehension_summary remain valid."""
        task_id = self._create_and_claim()
        report = self.orch.ingest_report({
            "task_id": task_id,
            "agent": "claude_code",
            "commit_sha": "abc123",
            "status": "done",
            "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
        })
        self.assertEqual(report["task_id"], task_id)
        self.assertNotIn("comprehension_summary", report)


class TestComprehendProjectFullLifecycle(unittest.TestCase):
    """Full lifecycle: create parent -> create sub-tasks -> claim -> report with summary -> validate."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")
        _register_agent(self.orch, "codex")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_full_comprehend_lifecycle(self) -> None:
        # 1. Create parent comprehend_project task
        parent = self.orch.create_task(
            title="Comprehend Project: agent-leader",
            workstream="comprehension",
            acceptance_criteria=[
                "Key modules identified",
                "Architectural patterns documented",
                "Dependencies mapped",
            ],
            task_type="comprehend_project",
            description="Analyze the agent-leader codebase before planning phase.",
        )
        self.assertEqual(parent["task_type"], "comprehend_project")
        self.assertEqual(parent["status"], "assigned")

        # 2. Create sub-task for backend comprehension
        sub_task = self.orch.create_task(
            title="Comprehend Backend: orchestrator engine",
            workstream="backend",
            acceptance_criteria=["Engine modules documented"],
            parent_task_id=parent["id"],
        )
        self.assertEqual(sub_task["parent_task_id"], parent["id"])

        # 3. Claim the sub-task
        claimed = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNotNone(claimed)
        # Should claim either parent or sub-task (both assigned to claude_code)
        claimed_id = claimed["id"]

        # 4. Submit report with comprehension summary
        report = self.orch.ingest_report({
            "task_id": claimed_id,
            "agent": "claude_code",
            "commit_sha": "def456",
            "status": "done",
            "test_summary": {"command": "python3 -m pytest tests/", "passed": 15, "failed": 0},
            "comprehension_summary": {
                "modules": [
                    {
                        "name": "orchestrator.engine",
                        "responsibility": "Core task orchestration and state management",
                        "key_files": ["orchestrator/engine.py"],
                    },
                    {
                        "name": "orchestrator.bus",
                        "responsibility": "Event bus for agent communication",
                        "key_files": ["orchestrator/bus.py"],
                    },
                ],
                "patterns": [
                    "file-based state persistence with atomic writes",
                    "event-driven inter-agent communication",
                    "lease-based task concurrency control",
                ],
                "dependencies": ["fcntl", "json", "pathlib", "uuid"],
                "entry_points": ["orchestrator_mcp_server.py"],
                "notes": "Single-process design with file locking for multi-session safety.",
            },
        })
        self.assertEqual(report["task_id"], claimed_id)
        self.assertIn("comprehension_summary", report)
        self.assertEqual(len(report["comprehension_summary"]["modules"]), 2)

        # 5. Verify task is now reported
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == claimed_id)
        self.assertEqual(found["status"], "reported")

        # 6. Manager validates
        result = self.orch.validate_task(
            task_id=claimed_id,
            passed=True,
            notes="Comprehensive analysis accepted.",
            source="codex",
        )
        self.assertEqual(result["task_id"], claimed_id)

        # Verify task status is now done
        tasks = self.orch.list_tasks()
        done_task = next(t for t in tasks if t["id"] == claimed_id)
        self.assertEqual(done_task["status"], "done")

        # 7. Verify sub-tasks are trackable
        subs = self.orch.list_sub_tasks(parent["id"])
        self.assertTrue(len(subs) >= 1)


if __name__ == "__main__":
    unittest.main()
