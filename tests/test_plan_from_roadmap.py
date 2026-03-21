"""Tests for plan_from_roadmap: manager generates tasks from project.yaml roadmap."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


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
        for skip in result2["skipped"]:
            self.assertEqual(skip["reason"], "duplicate")

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


if __name__ == "__main__":
    unittest.main()
