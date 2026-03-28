"""Tests for plan_from_roadmap: manager generates tasks from project.yaml roadmap."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy
import orchestrator_mcp_server
from orchestrator_mcp_server import _manager_cycle


SAMPLE_PROJECT_YAML = """\
name: Test Project
version:
  current: v1.0.0
  milestones:
    - id: done-milestone
      title: Already done milestone
      effort: S
      status: done
      tags: [backend]

roadmap:
  - version: v1.1.0
    name: "Test Velocity"
    items:
      - id: item-a
        title: "Persistent worker sessions"
        effort: L
        status: backlog
        details: >
          Keep a long-running CLI session per worker.
        tags: [velocity, backend]

      - id: item-b
        title: "Skip inter-cycle sleep"
        effort: S
        status: backlog
        details: >
          After successful task completion, skip the sleep.
        tags: [velocity, headless]

      - id: item-c
        title: "Already done item"
        effort: XS
        status: done
        tags: [bug]

      - id: item-d
        title: "Frontend dashboard upgrade"
        effort: M
        status: backlog
        tags: [frontend, ux]

  - version: v1.2.0
    name: "Hygiene"
    items:
      - id: item-e
        title: "Token budget guardrails"
        effort: M
        status: backlog
        tags: [cost-control]
"""


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {
            "backend": "claude_code",
            "frontend": "gemini",
            "default": "codex",
        },
        "decisions": {},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


class TestPlanFromRoadmap(unittest.TestCase):
    """Tests for Orchestrator.plan_from_roadmap."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_project_yaml(self, content: str = SAMPLE_PROJECT_YAML) -> None:
        (self.root / "project.yaml").write_text(content, encoding="utf-8")

    def test_creates_tasks_from_backlog_items(self):
        """Manager reads roadmap backlog items and creates tasks."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex")

        self.assertEqual(result["version"], "v1.1.0")
        self.assertEqual(len(result["created"]), 3)  # item-a, item-b, item-d (item-c is done)
        self.assertEqual(len(result["skipped"]), 0)

        # Verify tasks were actually created in state.
        tasks = self.orch.list_tasks()
        self.assertEqual(len(tasks), 3)

        # Verify policy routing: backend -> claude_code, frontend -> gemini.
        by_title = {t["title"]: t for t in tasks}
        self.assertEqual(by_title["Persistent worker sessions"]["owner"], "claude_code")
        self.assertEqual(by_title["Frontend dashboard upgrade"]["owner"], "gemini")

    def test_filters_by_version(self):
        """Specifying a version filters to that roadmap block."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex", version="v1.2.0")

        self.assertEqual(result["version"], "v1.2.0")
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(result["created"][0]["roadmap_id"], "item-e")

    def test_respects_limit(self):
        """Limit caps the number of tasks created."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex", limit=1)

        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(result["backlog_remaining"], 2)

    def test_deduplicates_existing_tasks(self):
        """Running plan twice skips already-created tasks."""
        self._write_project_yaml()
        result1 = self.orch.plan_from_roadmap(source="codex")
        self.assertEqual(len(result1["created"]), 3)

        result2 = self.orch.plan_from_roadmap(source="codex")
        self.assertEqual(len(result2["created"]), 0)
        self.assertEqual(len(result2["skipped"]), 3)
        valid_reasons = {"duplicate", "roadmap_tag_exists"}
        for skip in result2["skipped"]:
            self.assertIn(skip["reason"], valid_reasons)

    def test_deduplicates_across_statuses(self):
        """Tasks in non-open statuses (done, superseded) still block re-planning."""
        self._write_project_yaml()
        result1 = self.orch.plan_from_roadmap(source="codex", limit=1)
        self.assertEqual(len(result1["created"]), 1)
        task_id = result1["created"][0]["task_id"]

        # Move task to done — title-based dedup would miss this, but roadmap
        # tag dedup should still catch it.
        tasks = self.orch._read_json(self.orch.tasks_path, make_copy=True)
        for t in tasks:
            if t["id"] == task_id:
                t["status"] = "done"
        self.orch._write_tasks_json(tasks)

        result2 = self.orch.plan_from_roadmap(source="codex", limit=1)
        # The first roadmap item should be skipped (roadmap_tag_exists),
        # and the second item should be created instead.
        created_ids = [c["roadmap_id"] for c in result2["created"]]
        skipped_ids = [s["roadmap_id"] for s in result2["skipped"]]
        self.assertIn("item-a", skipped_ids)
        self.assertNotIn("item-a", created_ids)

    def test_assigns_team_id(self):
        """team_id is passed through to created tasks."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex", team_id="team-parity", limit=1)

        tasks = self.orch.list_tasks()
        self.assertEqual(tasks[0]["team_id"], "team-parity")
        self.assertEqual(len(result["created"]), 1)

    def test_missing_project_yaml(self):
        """Returns error when project.yaml doesn't exist."""
        result = self.orch.plan_from_roadmap(source="codex")
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    def test_no_backlog_items(self):
        """Returns empty created list when all items are done."""
        yaml_content = """\
name: Test
roadmap:
  - version: v1.0.0
    items:
      - id: x
        title: Done item
        status: done
        tags: [backend]
"""
        self._write_project_yaml(yaml_content)
        result = self.orch.plan_from_roadmap(source="codex")
        self.assertEqual(len(result["created"]), 0)
        self.assertIn("message", result)

    def test_version_not_found(self):
        """Returns error for non-existent version."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex", version="v99.0.0")
        self.assertIn("error", result)

    def test_roadmap_tags_include_provenance(self):
        """Created tasks include roadmap provenance tags."""
        self._write_project_yaml()
        self.orch.plan_from_roadmap(source="codex", limit=1)
        tasks = self.orch.list_tasks()
        tags = tasks[0]["tags"]
        self.assertTrue(any(t.startswith("roadmap:") for t in tags))
        self.assertTrue(any(t.startswith("version:") for t in tags))

    def test_emits_roadmap_planned_event(self):
        """plan_from_roadmap emits a manager.roadmap_planned event."""
        self._write_project_yaml()
        self.orch.plan_from_roadmap(source="codex", limit=1)

        events = list(self.orch.bus.iter_events())
        roadmap_events = [e for e in events if e.get("type") == "manager.roadmap_planned"]
        self.assertGreaterEqual(len(roadmap_events), 1)
        payload = roadmap_events[-1]["payload"]
        self.assertEqual(payload["version"], "v1.1.0")
        self.assertEqual(payload["created_count"], 1)

    def test_auto_plan_triggers_daily(self):
        """Manager auto-plans daily or on first cycle when policy is enabled."""
        self._write_project_yaml()

        # Save original globals and set test values
        original_orch = orchestrator_mcp_server.ORCH
        original_policy = orchestrator_mcp_server.POLICY
        try:
            orchestrator_mcp_server.ORCH = self.orch
            orchestrator_mcp_server.POLICY = self.orch.policy

            # Configure the policy instance that the mock will return
            self.orch.policy.triggers["auto_plan_from_roadmap"] = True
            self.orch.policy.triggers["auto_plan_limit"] = 5  # Ensure all backlog items are created

            # --- First cycle: Should plan ---
            cycle1_result = _manager_cycle(strict=True)
            self.assertTrue(cycle1_result["auto_plan"]["attempted"])
            self.assertGreater(len(cycle1_result["auto_plan"]["created"]), 0)
            self.assertIsNotNone(self.orch.last_auto_plan_timestamp)

            first_plan_time = self.orch.last_auto_plan_timestamp
            initial_tasks = self.orch.list_tasks()
            self.assertEqual(len(initial_tasks), 3) # item-a, item-b, item-d

            # --- Second cycle: Within 24 hours, should NOT plan ---
            # Manually set timestamp to be just under 24 hours ago
            self.orch.last_auto_plan_timestamp = first_plan_time # No need to subtract, just set to the first plan time
            cycle2_result = _manager_cycle(strict=True)
            self.assertFalse(cycle2_result["auto_plan"]["attempted"]) # Should not attempt to plan
            self.assertEqual(len(cycle2_result["auto_plan"]["created"]), 0)
            self.assertEqual(self.orch.last_auto_plan_timestamp, first_plan_time) # Should not have updated timestamp
            # Verify no new tasks were created
            self.assertEqual(len(self.orch.list_tasks()), 3)

            # --- Third cycle: After 24 hours, should plan again ---
            # Manually set timestamp to be > 24 hours ago
            self.orch.last_auto_plan_timestamp = first_plan_time.replace(year=first_plan_time.year - 1) # Set to a year ago
            cycle3_result = _manager_cycle(strict=True)
            self.assertTrue(cycle3_result["auto_plan"]["attempted"])
            self.assertGreater(len(cycle3_result["auto_plan"]["skipped"]), 0) # Should skip existing tasks
            self.assertEqual(len(cycle3_result["auto_plan"]["created"]), 0) # No new tasks should be created due to deduplication
            self.assertNotEqual(self.orch.last_auto_plan_timestamp, first_plan_time) # Should have updated timestamp
            # Verify new tasks were created (it should re-plan and try to create the same tasks,
            # which will then be skipped by deduplication. To actually see new tasks, we'd need
            # more unique backlog items. For this test, we verify it *attempts* to plan again.)
            self.assertGreaterEqual(len(self.orch.list_tasks()), 3)
            # Check that it still attempts to plan.
            self.assertIn("roadmap_id", cycle3_result["auto_plan"]["skipped"][0])

        finally:
            # Restore original globals
            orchestrator_mcp_server.ORCH = original_orch
            orchestrator_mcp_server.POLICY = original_policy


class TestAutoMarkBacklogDone(unittest.TestCase):
    """Tests for auto-marking project.yaml roadmap items as done on validation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_project_yaml(self, content: str = SAMPLE_PROJECT_YAML) -> None:
        (self.root / "project.yaml").write_text(content, encoding="utf-8")

    def _read_project_yaml(self):
        import yaml
        return yaml.safe_load((self.root / "project.yaml").read_text(encoding="utf-8"))

    def test_validate_done_marks_roadmap_item_done(self):
        """When validate_task passes, the matching roadmap item should be marked done."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex", limit=1)
        self.assertEqual(len(result["created"]), 1)
        task_id = result["created"][0]["task_id"]
        roadmap_id = result["created"][0]["roadmap_id"]

        # Validate task as passed (source must be the manager agent).
        self.orch.validate_task(
            task_id=task_id,
            passed=True,
            notes="All criteria met",
            source="codex",
        )

        # Verify project.yaml was updated.
        data = self._read_project_yaml()
        items = data["roadmap"][0]["items"]
        item = next(i for i in items if i["id"] == roadmap_id)
        self.assertEqual(item["status"], "done")

    def test_validate_fail_does_not_mark_done(self):
        """When validate_task fails, the roadmap item should NOT be marked done."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex", limit=1)
        task_id = result["created"][0]["task_id"]
        roadmap_id = result["created"][0]["roadmap_id"]

        self.orch.validate_task(
            task_id=task_id,
            passed=False,
            notes="Failing test",
            source="codex",
        )

        data = self._read_project_yaml()
        items = data["roadmap"][0]["items"]
        item = next(i for i in items if i["id"] == roadmap_id)
        self.assertEqual(item["status"], "backlog")

    def test_no_roadmap_tag_no_update(self):
        """A task without roadmap: tag should not touch project.yaml."""
        self._write_project_yaml()
        task = self.orch.create_task(
            title="No roadmap tag task",
            workstream="backend",
            acceptance_criteria=["done"],
        )
        # Manually move to reported so validation works.
        tasks = self.orch._read_json(self.orch.tasks_path, make_copy=True)
        for t in tasks:
            if t["id"] == task["id"]:
                t["status"] = "reported"
        self.orch._write_tasks_json(tasks)

        self.orch.validate_task(
            task_id=task["id"],
            passed=True,
            notes="OK",
            source="codex",
        )

        data = self._read_project_yaml()
        # All backlog items should still be backlog.
        items = data["roadmap"][0]["items"]
        backlog_items = [i for i in items if isinstance(i, dict) and i.get("status") == "backlog"]
        self.assertEqual(len(backlog_items), 3)  # item-a, item-b, item-d

    def test_emits_roadmap_item_done_event(self):
        """Marking a roadmap item done should emit a roadmap.item_done event."""
        self._write_project_yaml()
        result = self.orch.plan_from_roadmap(source="codex", limit=1)
        task_id = result["created"][0]["task_id"]

        self.orch.validate_task(
            task_id=task_id,
            passed=True,
            notes="All done",
            source="codex",
        )

        events = list(self.orch.bus.iter_events())
        done_events = [e for e in events if e.get("type") == "roadmap.item_done"]
        self.assertGreaterEqual(len(done_events), 1)


if __name__ == "__main__":
    unittest.main()
