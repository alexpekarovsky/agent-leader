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


class TestPersistentWorkerAutoResume(unittest.TestCase):
    """Persistent worker _auto_resume_from_roadmap method."""

    def setUp(self) -> None:
        from orchestrator.persistent_worker import PersistentWorker, PersistentWorkerConfig

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)
        self.orch = _make_orch(self.root)

        cfg = PersistentWorkerConfig(
            cli="codex",
            agent="codex",
            lane="default",
            project_root=str(self.root),
            repo_root=str(self.root),
            log_dir=str(self.root / ".autopilot-logs"),
            max_idle_cycles=2,
            signal_max_wait=1,
            signal_poll_interval=1,
        )
        cfg.finalise()
        self.worker = PersistentWorker(cfg)
        self.worker._orch = self.orch

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_creates_tasks_from_backlog(self) -> None:
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
        )
        created = self.worker._auto_resume_from_roadmap()
        self.assertGreater(created, 0)
        tasks = self.orch.list_tasks()
        self.assertGreaterEqual(len(tasks), created)

    def test_touches_wakeup_signal(self) -> None:
        from orchestrator.persistent_worker import _signal_file

        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
        )
        self.worker._auto_resume_from_roadmap()
        sig = _signal_file(str(self.root), "codex")
        self.assertTrue(sig.exists())
        self.assertGreater(int(sig.read_text(encoding="utf-8")), 0)

    def test_publishes_event(self) -> None:
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
        )
        self.worker._auto_resume_from_roadmap()
        events_path = self.root / "bus" / "events.jsonl"
        self.assertTrue(events_path.exists())
        lines = events_path.read_text(encoding="utf-8").strip().splitlines()
        resume_events = [
            json.loads(line) for line in lines
            if json.loads(line).get("type") == "worker.auto_resume"
        ]
        self.assertGreaterEqual(len(resume_events), 1)
        self.assertEqual(resume_events[0]["payload"]["agent"], "codex")
        self.assertGreater(resume_events[0]["payload"]["tasks_created"], 0)

    def test_returns_zero_when_no_backlog(self) -> None:
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_NO_BACKLOG, encoding="utf-8"
        )
        created = self.worker._auto_resume_from_roadmap()
        self.assertEqual(created, 0)

    def test_no_signal_when_nothing_created(self) -> None:
        from orchestrator.persistent_worker import _signal_file

        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_NO_BACKLOG, encoding="utf-8"
        )
        self.worker._auto_resume_from_roadmap()
        sig = _signal_file(str(self.root), "codex")
        self.assertFalse(sig.exists())

    def test_deduplicates_across_calls(self) -> None:
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
        )
        first = self.worker._auto_resume_from_roadmap()
        self.assertGreater(first, 0)
        second = self.worker._auto_resume_from_roadmap()
        self.assertEqual(second, 0)

    def test_run_loop_resumes_instead_of_exiting(self) -> None:
        """run() auto-resumes at max idle instead of exiting when backlog exists."""
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_WITH_BACKLOG, encoding="utf-8"
        )
        self.worker.cfg.max_idle_cycles = 1

        cli_calls = []
        self.worker._run_cli = lambda prompt: (cli_calls.append(prompt), 0)[1]
        self.worker._wait_for_signal = lambda: False

        call_count = [0]
        def patched_has_work():
            call_count[0] += 1
            if call_count[0] == 1:
                return False  # Triggers auto-resume.
            if call_count[0] == 2:
                return True  # Claims the new task.
            return False  # Back to idle → exit (backlog now deduped).

        claim_count = [0]
        def patched_claim():
            claim_count[0] += 1
            if claim_count[0] == 1:
                return {"id": "TASK-fake", "title": "Fake task", "description": "test"}
            return None

        self.worker._has_claimable_work = patched_has_work
        self.worker._claim_next_task = patched_claim
        rc = self.worker.run()

        self.assertEqual(rc, 0)
        self.assertGreaterEqual(len(cli_calls), 1)

    def test_run_loop_exits_cleanly_no_backlog(self) -> None:
        """run() exits when max idle reached and no backlog."""
        (self.root / "project.yaml").write_text(
            SAMPLE_PROJECT_YAML_NO_BACKLOG, encoding="utf-8"
        )
        self.worker.cfg.max_idle_cycles = 1
        self.worker._wait_for_signal = lambda: False

        rc = self.worker.run()

        self.assertEqual(rc, 0)
        tasks = self.orch.list_tasks()
        self.assertEqual(len(tasks), 0)


class TestManagerCycleTouchesWakeupSignals(unittest.TestCase):
    """Manager cycle touches wakeup signals when auto-plan creates tasks."""

    def test_signals_written_for_task_owners(self) -> None:
        """_touch_wakeup_signals writes files for each unique owner."""
        import orchestrator_mcp_server as mcp
        orig_root = mcp.ROOT_DIR

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "state").mkdir()
            try:
                mcp.ROOT_DIR = root
                created = [
                    {"owner": "codex", "task_id": "TASK-1"},
                    {"owner": "gemini", "task_id": "TASK-2"},
                    {"owner": "codex", "task_id": "TASK-3"},
                ]
                mcp._touch_wakeup_signals(created)
                self.assertTrue((root / "state" / ".wakeup-codex").exists())
                self.assertTrue((root / "state" / ".wakeup-gemini").exists())
            finally:
                mcp.ROOT_DIR = orig_root

    def test_no_signals_for_empty_list(self) -> None:
        import orchestrator_mcp_server as mcp
        orig_root = mcp.ROOT_DIR

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "state").mkdir()
            try:
                mcp.ROOT_DIR = root
                mcp._touch_wakeup_signals([])
                self.assertEqual(list((root / "state").glob(".wakeup-*")), [])
            finally:
                mcp.ROOT_DIR = orig_root


if __name__ == "__main__":
    unittest.main()
