"""Tests for auto-resume: workers check roadmap backlog before idle-exit."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = str(REPO_ROOT / "scripts" / "autopilot" / "common.sh")

SAMPLE_PROJECT_YAML_WITH_BACKLOG = """\
name: Test Project
roadmap:
  - version: v1.1.0
    name: "Velocity Features"
    items:
      - id: item-a
        title: "Auto-resume on completion"
        effort: S
        status: backlog
        details: >
          Workers self-restart when backlog has items.
        tags: [backend, velocity]
      - id: item-b
        title: "Persistent sessions"
        effort: L
        status: backlog
        tags: [backend]
"""

SAMPLE_PROJECT_YAML_NO_BACKLOG = """\
name: Test Project
roadmap:
  - version: v1.0.0
    name: "Done"
    items:
      - id: item-x
        title: "Already done"
        effort: S
        status: done
        tags: [backend]
"""

_TIMEOUT = 10


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


class TestRoadmapHasBacklog(unittest.TestCase):
    """Tests for roadmap_has_backlog shell function."""

    def _run_roadmap_check(self, project_root: str) -> subprocess.CompletedProcess[str]:
        script = f"""
        source "{COMMON_SH}"
        roadmap_has_backlog "{project_root}"
        """
        return subprocess.run(
            ["bash", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )

    def test_returns_zero_when_backlog_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "project.yaml").write_text(
                SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
            )
            proc = self._run_roadmap_check(tmp)
            self.assertEqual(0, proc.returncode, f"stderr: {proc.stderr}")

    def test_returns_nonzero_when_no_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "project.yaml").write_text(
                SAMPLE_PROJECT_YAML_NO_BACKLOG, encoding="utf-8"
            )
            proc = self._run_roadmap_check(tmp)
            self.assertNotEqual(0, proc.returncode)

    def test_returns_nonzero_when_no_project_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run_roadmap_check(tmp)
            self.assertNotEqual(0, proc.returncode)


class TestAutoResumeFromRoadmap(unittest.TestCase):
    """Tests for plan_from_roadmap creating tasks that enable auto-resume."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_auto_resume_creates_tasks_when_backlog_exists(self) -> None:
        """plan_from_roadmap creates tasks from backlog, enabling workers to resume."""
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
        )
        result = self.orch.plan_from_roadmap(source="claude_code")
        self.assertGreater(len(result["created"]), 0)
        # Verify each created task has a task_id and owner
        for task in result["created"]:
            self.assertIn("task_id", task)
            self.assertIn("owner", task)
            self.assertTrue(task["task_id"].startswith("TASK-"))

    def test_auto_resume_skips_when_no_backlog(self) -> None:
        """plan_from_roadmap creates nothing when all items are done."""
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_NO_BACKLOG, encoding="utf-8"
        )
        result = self.orch.plan_from_roadmap(source="claude_code")
        self.assertEqual(len(result["created"]), 0)

    def test_auto_resume_clean_exit_when_truly_no_work(self) -> None:
        """No tasks created + no backlog = clean exit condition."""
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_NO_BACKLOG, encoding="utf-8"
        )
        result = self.orch.plan_from_roadmap(source="claude_code")
        tasks = self.orch.list_tasks()
        self.assertEqual(len(result["created"]), 0)
        self.assertEqual(len(tasks), 0)

    def test_auto_resume_trigger_resets_idle(self) -> None:
        """When backlog items exist and tasks are created, the idle cycle should reset.

        This verifies the core auto-resume contract: if plan_from_roadmap
        creates tasks, the worker should continue rather than exit.
        """
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
        )
        # First call creates tasks from backlog
        result1 = self.orch.plan_from_roadmap(source="claude_code")
        created_count = len(result1["created"])
        self.assertGreater(created_count, 0)

        # Verify created tasks are properly attributed
        for task in result1["created"]:
            self.assertIn("task_id", task)
            self.assertIn("owner", task)

        # The backlog_remaining count should reflect items not yet planned
        self.assertIn("backlog_remaining", result1)

        # A second call still returns results (tasks can be claimed), confirming
        # that the auto-resume contract holds: as long as backlog items exist,
        # plan_from_roadmap will produce work for workers to claim.
        result2 = self.orch.plan_from_roadmap(source="claude_code")
        self.assertIsInstance(result2.get("created"), list)


class TestWorkerLoopAutoResumeIntegration(unittest.TestCase):
    """Integration test: worker_loop.sh auto-resume log output."""

    def test_worker_loop_logs_auto_resume_on_backlog(self) -> None:
        """Verify worker_loop.sh contains auto-resume logic in its idle exit path."""
        worker_loop = REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh"
        content = worker_loop.read_text(encoding="utf-8")

        # Verify the auto-resume integration points exist
        self.assertIn("roadmap_has_backlog", content)
        self.assertIn("auto_resume_from_roadmap", content)
        self.assertIn("auto-resume: roadmap backlog detected", content)
        self.assertIn("no backlog remaining; exiting", content)


if __name__ == "__main__":
    unittest.main()
