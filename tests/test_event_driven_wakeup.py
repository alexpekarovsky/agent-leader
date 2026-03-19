"""Tests for event-driven worker wakeup (TASK-4ce1b61c).

Verifies:
- idle worker performs no periodic LLM calls in event-driven mode
- assignment event (wakeup signal file) triggers immediate wakeup
- fallback polling remains available when --event-driven is not set
- wait_for_task_signal detects mtime changes
- _touch_wakeup_signals writes signal files for agents with work
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")
COMMON_SH = str(REPO_ROOT / "scripts" / "autopilot" / "common.sh")

_TIMEOUT = 20


def _make_cli_stub(bin_dir: Path, name: str) -> None:
    marker = bin_dir / f".{name}_invoked"
    stub = bin_dir / name
    stub.write_text(
        f"#!/usr/bin/env bash\ntouch '{marker}'\necho 'stub invoked'\n"
    )
    stub.chmod(0o755)


def _write_tasks(project_root: Path, tasks: list) -> None:
    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "tasks.json").write_text(
        json.dumps(tasks, indent=2), encoding="utf-8"
    )


def _bootstrap_orchestrator_root(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    policy = {
        "name": "codex-manager",
        "roles": {"manager": "codex"},
        "routing": {"default": "codex"},
        "decisions": {},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    (root / "config" / "policy.codex-manager.json").write_text(
        json.dumps(policy), encoding="utf-8"
    )
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in {
        "agents.json": {},
        "roles.json": {"leader": "codex", "leader_instance_id": "codex#default", "team_members": []},
        "blockers.json": [],
        "bugs.json": [],
    }.items():
        (state_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    (root / "bus").mkdir(parents=True, exist_ok=True)


class WaitForTaskSignalTests(unittest.TestCase):
    """Test wait_for_task_signal from common.sh."""

    def test_no_signal_returns_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    "bash", "-c",
                    f'source "{COMMON_SH}" && wait_for_task_signal "{tmp}" testbot 2 1',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_signal_file_change_returns_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            signal = Path(tmp) / "state" / ".wakeup-testbot"
            signal.parent.mkdir(parents=True, exist_ok=True)
            signal.write_text("baseline", encoding="utf-8")

            def _touch_after_delay():
                time.sleep(1)
                signal.write_text("updated", encoding="utf-8")

            t = threading.Thread(target=_touch_after_delay)
            t.start()

            result = subprocess.run(
                [
                    "bash", "-c",
                    f'source "{COMMON_SH}" && wait_for_task_signal "{tmp}" testbot 5 1',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            t.join()
            self.assertEqual(result.returncode, 0)


class EventDrivenWorkerTests(unittest.TestCase):
    """Test worker_loop.sh with --event-driven flag."""

    def test_event_driven_idle_no_llm(self):
        """Event-driven worker waits for signal, no LLM call when idle."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            _bootstrap_orchestrator_root(project)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [])

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["ORCHESTRATOR_ROOT"] = str(project)
            result = subprocess.run(
                [
                    "bash", WORKER_LOOP,
                    "--cli", "codex",
                    "--agent", "codex",
                    "--project-root", str(project),
                    "--log-dir", str(log_dir),
                    "--max-idle-cycles", "2",
                    "--event-driven",
                    "--event-max-wait", "2",
                    "--event-poll-interval", "1",
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                env=env,
            )
            marker = bin_dir / ".codex_invoked"
            self.assertFalse(marker.exists(), "LLM should NOT be invoked in event-driven idle")
            self.assertIn("waiting for wakeup signal", result.stderr)
            agents = json.loads((project / "state" / "agents.json").read_text(encoding="utf-8"))
            self.assertIn("codex", agents)
            self.assertEqual(agents["codex"]["status"], "active")

    def test_event_driven_wakeup_triggers_recheck(self):
        """Signal file change wakes up event-driven worker to recheck."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            _bootstrap_orchestrator_root(project)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [])

            # Touch signal after delay to simulate task assignment
            signal_path = project / "state" / ".wakeup-codex"

            def _touch_signal():
                time.sleep(2)
                signal_path.write_text("wakeup", encoding="utf-8")

            t = threading.Thread(target=_touch_signal)
            t.start()

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["ORCHESTRATOR_ROOT"] = str(project)
            result = subprocess.run(
                [
                    "bash", WORKER_LOOP,
                    "--cli", "codex",
                    "--agent", "codex",
                    "--project-root", str(project),
                    "--log-dir", str(log_dir),
                    "--max-idle-cycles", "2",
                    "--event-driven",
                    "--event-max-wait", "5",
                    "--event-poll-interval", "1",
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                env=env,
            )
            t.join()
            self.assertIn("wakeup signal received", result.stderr)

    def test_fallback_polling_without_flag(self):
        """Without --event-driven, worker uses backoff polling (fallback)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            _bootstrap_orchestrator_root(project)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")
            _write_tasks(project, [])

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["ORCHESTRATOR_ROOT"] = str(project)
            result = subprocess.run(
                [
                    "bash", WORKER_LOOP,
                    "--cli", "codex",
                    "--agent", "codex",
                    "--project-root", str(project),
                    "--log-dir", str(log_dir),
                    "--max-idle-cycles", "1",
                    "--idle-backoff", "1",
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                env=env,
            )
            # Should use polling, not event-driven
            self.assertNotIn("waiting for wakeup signal", result.stderr)
            self.assertIn("idle gate: no claimable work", result.stderr)


class TouchWakeupSignalTests(unittest.TestCase):
    """Test _touch_wakeup_signals in orchestrator engine."""

    def test_wakeup_signal_created_on_task_write(self):
        """Writing tasks with assigned status creates wakeup signal files."""
        # Import engine and create orchestrator
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from orchestrator.engine import Orchestrator
        from orchestrator.policy import Policy

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bus").mkdir()
            (root / "state").mkdir()
            policy = Policy(name="test", roles={}, routing={}, decisions={}, triggers={})
            orch = Orchestrator(root=root, policy=policy)

            tasks = [
                {"id": "T-1", "owner": "claude_code", "status": "assigned"},
                {"id": "T-2", "owner": "gemini", "status": "done"},
                {"id": "T-3", "owner": "codex", "status": "bug_open"},
            ]
            orch._write_json(orch.tasks_path, tasks)
            orch._touch_wakeup_signals()

            # claude_code and codex should have signals (assigned, bug_open)
            self.assertTrue((root / "state" / ".wakeup-claude_code").exists())
            self.assertTrue((root / "state" / ".wakeup-codex").exists())
            # gemini has no active work
            self.assertFalse((root / "state" / ".wakeup-gemini").exists())


class SupervisorEventDrivenTests(unittest.TestCase):
    """Test that supervisor passes --event-driven flag to workers."""

    def test_event_driven_flag_in_worker_cmd(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from orchestrator.supervisor import SupervisorConfig, proc_cmd

        cfg = SupervisorConfig(event_driven=True)
        cfg.finalise()
        for name in ("claude", "gemini", "codex_worker", "wingman"):
            cmd = proc_cmd(name, cfg)
            self.assertIn("--event-driven", cmd, f"{name} should include --event-driven")

    def test_no_event_driven_flag_by_default(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from orchestrator.supervisor import SupervisorConfig, proc_cmd

        cfg = SupervisorConfig(event_driven=False)
        cfg.finalise()
        for name in ("claude", "gemini", "codex_worker", "wingman"):
            cmd = proc_cmd(name, cfg)
            self.assertNotIn("--event-driven", cmd, f"{name} should NOT include --event-driven")

    def test_manager_never_gets_event_driven(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from orchestrator.supervisor import SupervisorConfig, proc_cmd

        cfg = SupervisorConfig(event_driven=True)
        cfg.finalise()
        cmd = proc_cmd("manager", cfg)
        self.assertNotIn("--event-driven", cmd)


if __name__ == "__main__":
    unittest.main()
