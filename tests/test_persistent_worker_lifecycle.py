"""Tests for persistent worker lifecycle — session management, task chaining,
max_tasks_per_session, session metrics, and graceful shutdown."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest import TestCase, mock

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy
from orchestrator.persistent_worker import (
    PersistentWorker,
    PersistentWorkerConfig,
    _build_cli_cmd,
    _signal_file,
)


def _make_policy(root: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {},
        "triggers": {"heartbeat_timeout_minutes": 10, "claim_cooldown_seconds": 0},
    }
    policy_path = root / "config" / "policy.codex-manager.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(policy_path)


def _make_worker(root: Path, **overrides) -> tuple[PersistentWorker, Orchestrator]:
    """Create a PersistentWorker with mocked orchestrator internals."""
    policy = _make_policy(root)
    orch = Orchestrator(root=root, policy=policy)

    defaults = dict(
        cli="codex",
        agent="codex",
        lane="default",
        project_root=str(root),
        repo_root=str(root),
        log_dir=str(root / ".autopilot-logs"),
        max_idle_cycles=1,
        signal_max_wait=1,
        signal_poll_interval=1,
        daily_call_budget=0,  # disable budget limits for lifecycle tests
    )
    defaults.update(overrides)
    cfg = PersistentWorkerConfig(**defaults)
    cfg.finalise()

    worker = PersistentWorker(cfg)
    worker._orch = orch
    return worker, orch


class TestPersistentWorkerStartStop(TestCase):
    """Worker starts, connects, and shuts down cleanly."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exits_zero_when_no_work(self) -> None:
        """Worker exits cleanly (rc=0) when no tasks and max idle reached."""
        worker, _ = _make_worker(self.root, max_idle_cycles=1)
        worker._wait_for_signal = lambda: False
        rc = worker.run()
        self.assertEqual(rc, 0)

    def test_shutdown_via_flag(self) -> None:
        """Worker exits cleanly when _shutdown is set."""
        worker, _ = _make_worker(self.root, max_idle_cycles=100)

        call_count = [0]
        orig_has_work = worker._has_claimable_work

        def _no_work_then_shutdown():
            call_count[0] += 1
            if call_count[0] >= 2:
                worker._shutdown = True
            return False

        worker._has_claimable_work = _no_work_then_shutdown
        worker._wait_for_signal = lambda: False
        rc = worker.run()
        self.assertEqual(rc, 0)

    def test_connect_failure_exits_one(self) -> None:
        """Worker exits with rc=1 if initial connect fails."""
        worker, _ = _make_worker(self.root)
        worker._connect = mock.Mock(side_effect=RuntimeError("connection refused"))
        rc = worker.run()
        self.assertEqual(rc, 1)


class TestPersistentWorkerTaskChaining(TestCase):
    """Worker chains tasks immediately without inter-cycle sleep."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_chains_two_tasks_then_exits(self) -> None:
        """Worker claims and executes two tasks consecutively, then exits idle."""
        worker, orch = _make_worker(self.root, max_idle_cycles=1)

        task_a = {"id": "TASK-a", "title": "Task A", "description": "do A",
                  "owner": "codex", "status": "assigned"}
        task_b = {"id": "TASK-b", "title": "Task B", "description": "do B",
                  "owner": "codex", "status": "assigned"}

        # Write tasks to disk so _has_claimable_work() finds them.
        tasks_path = self.root / "state" / "tasks.json"
        tasks_path.write_text(json.dumps([task_a, task_b]), encoding="utf-8")

        cli_prompts: list[str] = []
        claim_queue = [task_a, task_b]

        def _mock_claim():
            if claim_queue:
                t = claim_queue.pop(0)
                # Mark as in_progress on disk so _has_claimable_work sees the change.
                current = json.loads(tasks_path.read_text(encoding="utf-8"))
                for ct in current:
                    if ct["id"] == t["id"]:
                        ct["status"] = "in_progress"
                tasks_path.write_text(json.dumps(current), encoding="utf-8")
                return t
            return None

        def _mock_run_cli(prompt: str) -> tuple:
            cli_prompts.append(prompt)
            # Mark the task as done on disk.
            for line in prompt.splitlines():
                if line.strip().startswith("Task ID:"):
                    tid = line.split(":", 1)[1].strip()
                    current = json.loads(tasks_path.read_text(encoding="utf-8"))
                    for ct in current:
                        if ct["id"] == tid:
                            ct["status"] = "done"
                    tasks_path.write_text(json.dumps(current), encoding="utf-8")
                    break
            return 0, "/dev/null"

        worker._claim_next_task = _mock_claim
        worker._run_cli = _mock_run_cli
        worker._wait_for_signal = lambda: False
        rc = worker.run()

        self.assertEqual(rc, 0)
        self.assertEqual(len(cli_prompts), 2)
        self.assertIn("Task A", cli_prompts[0])
        self.assertIn("Task B", cli_prompts[1])

    def test_consecutive_failure_exits_one(self) -> None:
        """Worker exits rc=1 after max consecutive failures."""
        worker, orch = _make_worker(self.root, max_idle_cycles=100,
                                     max_consecutive_failures=2)

        tasks = [{"id": f"TASK-{i}", "title": f"Fail {i}", "description": "",
                  "owner": "codex", "status": "assigned"} for i in range(5)]
        tasks_path = self.root / "state" / "tasks.json"
        tasks_path.write_text(json.dumps(tasks), encoding="utf-8")

        claim_idx = [0]

        def _mock_claim():
            if claim_idx[0] < len(tasks):
                t = tasks[claim_idx[0]]
                claim_idx[0] += 1
                return t
            return None

        worker._claim_next_task = _mock_claim
        worker._run_cli = lambda prompt: (1, "/dev/null")  # Always fail.
        worker._wait_for_signal = lambda: False
        rc = worker.run()

        self.assertEqual(rc, 1)
        self.assertEqual(worker._consecutive_failures, 2)

    def test_failure_counter_resets_on_success(self) -> None:
        """A successful task resets the consecutive failure counter."""
        worker, orch = _make_worker(self.root, max_idle_cycles=1,
                                     max_consecutive_failures=3)

        task_a = {"id": "TASK-fail", "title": "Fail", "description": "",
                  "owner": "codex", "status": "assigned"}
        task_b = {"id": "TASK-pass", "title": "Pass", "description": "",
                  "owner": "codex", "status": "assigned"}
        tasks_path = self.root / "state" / "tasks.json"
        tasks_path.write_text(json.dumps([task_a, task_b]), encoding="utf-8")

        claim_queue = [task_a, task_b]
        call_count = [0]

        def _mock_claim():
            if claim_queue:
                t = claim_queue.pop(0)
                # Mark done on disk so it's not re-found.
                current = json.loads(tasks_path.read_text(encoding="utf-8"))
                for ct in current:
                    if ct["id"] == t["id"]:
                        ct["status"] = "in_progress"
                tasks_path.write_text(json.dumps(current), encoding="utf-8")
                return t
            return None

        def _alternate_cli(prompt: str) -> tuple:
            call_count[0] += 1
            # Mark done on disk.
            for line in prompt.splitlines():
                if line.strip().startswith("Task ID:"):
                    tid = line.split(":", 1)[1].strip()
                    current = json.loads(tasks_path.read_text(encoding="utf-8"))
                    for ct in current:
                        if ct["id"] == tid:
                            ct["status"] = "done"
                    tasks_path.write_text(json.dumps(current), encoding="utf-8")
                    break
            return (1 if call_count[0] == 1 else 0), "/dev/null"

        worker._claim_next_task = _mock_claim
        worker._run_cli = _alternate_cli
        worker._wait_for_signal = lambda: False
        rc = worker.run()

        self.assertEqual(rc, 0)
        self.assertEqual(worker._consecutive_failures, 0)


class TestMaxTasksPerSession(TestCase):
    """Worker respects max_tasks_per_session limit."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exits_after_session_limit(self) -> None:
        """Worker exits cleanly after completing max_tasks_per_session tasks."""
        worker, orch = _make_worker(self.root, max_tasks_per_session=2,
                                     max_idle_cycles=100)

        tasks = [{"id": f"TASK-{i}", "title": f"Task {i}", "description": "",
                  "owner": "codex", "status": "assigned"} for i in range(5)]
        tasks_path = self.root / "state" / "tasks.json"
        tasks_path.write_text(json.dumps(tasks), encoding="utf-8")

        claim_idx = [0]

        def _mock_claim():
            if claim_idx[0] < len(tasks):
                t = tasks[claim_idx[0]]
                claim_idx[0] += 1
                return t
            return None

        worker._claim_next_task = _mock_claim
        worker._run_cli = lambda prompt: (0, "/dev/null")
        worker._wait_for_signal = lambda: False
        rc = worker.run()

        self.assertEqual(rc, 0)
        self.assertEqual(worker._tasks_completed, 2)

    def test_unlimited_when_zero(self) -> None:
        """max_tasks_per_session=0 means unlimited (no session restart)."""
        worker, orch = _make_worker(self.root, max_tasks_per_session=0,
                                     max_idle_cycles=1)

        tasks = [{"id": f"TASK-{i}", "title": f"Task {i}", "description": "",
                  "owner": "codex", "status": "assigned"} for i in range(3)]
        tasks_path = self.root / "state" / "tasks.json"
        tasks_path.write_text(json.dumps(tasks), encoding="utf-8")

        claim_idx = [0]

        def _mock_claim():
            if claim_idx[0] < len(tasks):
                t = tasks[claim_idx[0]]
                claim_idx[0] += 1
                # Mark as done on disk so _has_claimable_work doesn't find it again.
                current = json.loads(tasks_path.read_text(encoding="utf-8"))
                for ct in current:
                    if ct["id"] == t["id"]:
                        ct["status"] = "done"
                tasks_path.write_text(json.dumps(current), encoding="utf-8")
                return t
            return None

        worker._claim_next_task = _mock_claim
        worker._run_cli = lambda prompt: (0, "/dev/null")
        worker._wait_for_signal = lambda: False
        rc = worker.run()

        self.assertEqual(rc, 0)
        self.assertEqual(worker._tasks_completed, 3)


class TestSessionMetrics(TestCase):
    """Worker emits session metrics on exit."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_emits_session_end_event_on_idle_exit(self) -> None:
        """Session metrics event published on max-idle exit."""
        worker, orch = _make_worker(self.root, max_idle_cycles=1)
        worker._wait_for_signal = lambda: False
        rc = worker.run()
        self.assertEqual(rc, 0)

        events_path = self.root / "bus" / "events.jsonl"
        self.assertTrue(events_path.exists())
        lines = events_path.read_text(encoding="utf-8").strip().splitlines()
        session_events = [
            json.loads(line) for line in lines
            if json.loads(line).get("type") == "worker.session_end"
        ]
        self.assertEqual(len(session_events), 1)
        payload = session_events[0]["payload"]
        self.assertEqual(payload["agent"], "codex")
        self.assertEqual(payload["exit_reason"], "max_idle")
        self.assertEqual(payload["tasks_completed"], 0)
        self.assertGreater(payload["uptime_seconds"], -1)

    def test_emits_session_limit_event(self) -> None:
        """Session metrics event published with session_limit reason."""
        worker, orch = _make_worker(self.root, max_tasks_per_session=1,
                                     max_idle_cycles=100)

        task = {"id": "TASK-t1", "title": "T1", "description": "",
                "owner": "codex", "status": "assigned"}
        tasks_path = self.root / "state" / "tasks.json"
        tasks_path.write_text(json.dumps([task]), encoding="utf-8")

        worker._claim_next_task = lambda: task
        worker._run_cli = lambda prompt: (0, "/dev/null")
        worker._wait_for_signal = lambda: False
        rc = worker.run()
        self.assertEqual(rc, 0)

        events_path = self.root / "bus" / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().splitlines()
        session_events = [
            json.loads(line) for line in lines
            if json.loads(line).get("type") == "worker.session_end"
        ]
        self.assertEqual(len(session_events), 1)
        self.assertEqual(session_events[0]["payload"]["exit_reason"], "session_limit")
        self.assertEqual(session_events[0]["payload"]["tasks_completed"], 1)


class TestPromptBuilding(TestCase):
    """Task prompt includes expected content."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_prompt_contains_task_details(self) -> None:
        worker, _ = _make_worker(self.root)
        task = {
            "id": "TASK-abc123",
            "title": "Fix the widget",
            "description": "Widget is broken in production",
            "acceptance_criteria": ["Widget works", "Tests pass"],
        }
        prompt = worker._build_task_prompt(task)

        self.assertIn("TASK-abc123", prompt)
        self.assertIn("Fix the widget", prompt)
        self.assertIn("Widget is broken in production", prompt)
        self.assertIn("Widget works", prompt)
        self.assertIn("Tests pass", prompt)
        self.assertIn("orchestrator_submit_report", prompt)

    def test_prompt_wingman_lane_guard(self) -> None:
        worker, _ = _make_worker(self.root, lane="wingman", agent="ccm", cli="claude")
        task = {"id": "TASK-x", "title": "Review code", "description": ""}
        prompt = worker._build_task_prompt(task)
        self.assertIn("QA lane guard", prompt)

    def test_prompt_team_guard(self) -> None:
        worker, _ = _make_worker(self.root, team_id="team-alpha")
        task = {"id": "TASK-x", "title": "Do thing", "description": ""}
        prompt = worker._build_task_prompt(task)
        self.assertIn("Team lane guard", prompt)
        self.assertIn("team-alpha", prompt)


class TestSignalFile(TestCase):
    """Signal file path is correct."""

    def test_signal_file_path(self) -> None:
        p = _signal_file("/proj", "codex")
        self.assertEqual(str(p), "/proj/state/.wakeup-codex")


class TestBuildCliCmd(TestCase):
    """CLI command building for each tool."""

    def test_codex_cmd(self) -> None:
        cmd = _build_cli_cmd("codex", "/proj", {})
        self.assertEqual(cmd[0], "codex")
        self.assertIn("-C", cmd)

    def test_claude_cmd(self) -> None:
        cmd = _build_cli_cmd("claude", "/proj", {})
        self.assertEqual(cmd[0], "claude")

    def test_gemini_cmd(self) -> None:
        cmd = _build_cli_cmd("gemini", "/proj", {})
        self.assertEqual(cmd[0], "gemini")

    def test_gemini_with_model(self) -> None:
        cmd = _build_cli_cmd("gemini", "/proj", {"ORCHESTRATOR_GEMINI_MODEL": "gemini-2.0"})
        self.assertIn("-m", cmd)
        idx = cmd.index("-m")
        self.assertEqual(cmd[idx + 1], "gemini-2.0")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            _build_cli_cmd("unknown", "/proj", {})


class TestClaimableWorkFiltering(TestCase):
    """_has_claimable_work filters tasks correctly."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_finds_assigned_task_for_agent(self) -> None:
        worker, _ = _make_worker(self.root)
        tasks = [{"id": "TASK-1", "owner": "codex", "status": "assigned"}]
        (self.root / "state" / "tasks.json").write_text(json.dumps(tasks))
        self.assertTrue(worker._has_claimable_work())

    def test_ignores_other_agent(self) -> None:
        worker, _ = _make_worker(self.root)
        tasks = [{"id": "TASK-1", "owner": "gemini", "status": "assigned"}]
        (self.root / "state" / "tasks.json").write_text(json.dumps(tasks))
        self.assertFalse(worker._has_claimable_work())

    def test_ignores_done_tasks(self) -> None:
        worker, _ = _make_worker(self.root)
        tasks = [{"id": "TASK-1", "owner": "codex", "status": "done"}]
        (self.root / "state" / "tasks.json").write_text(json.dumps(tasks))
        self.assertFalse(worker._has_claimable_work())

    def test_wingman_filters_non_qa(self) -> None:
        worker, _ = _make_worker(self.root, lane="wingman", agent="ccm", cli="claude")
        tasks = [{"id": "TASK-1", "owner": "ccm", "status": "assigned",
                  "workstream": "backend", "title": "add feature", "description": ""}]
        (self.root / "state" / "tasks.json").write_text(json.dumps(tasks))
        self.assertFalse(worker._has_claimable_work())

    def test_wingman_accepts_qa_workstream(self) -> None:
        worker, _ = _make_worker(self.root, lane="wingman", agent="ccm", cli="claude")
        tasks = [{"id": "TASK-1", "owner": "ccm", "status": "assigned",
                  "workstream": "qa", "title": "review", "description": ""}]
        (self.root / "state" / "tasks.json").write_text(json.dumps(tasks))
        self.assertTrue(worker._has_claimable_work())

    def test_team_id_filter(self) -> None:
        worker, _ = _make_worker(self.root, team_id="alpha")
        tasks = [{"id": "TASK-1", "owner": "codex", "status": "assigned",
                  "team_id": "beta"}]
        (self.root / "state" / "tasks.json").write_text(json.dumps(tasks))
        self.assertFalse(worker._has_claimable_work())

    def test_team_id_matches(self) -> None:
        worker, _ = _make_worker(self.root, team_id="alpha")
        tasks = [{"id": "TASK-1", "owner": "codex", "status": "assigned",
                  "team_id": "alpha"}]
        (self.root / "state" / "tasks.json").write_text(json.dumps(tasks))
        self.assertTrue(worker._has_claimable_work())
