"""Consolidated shell-script tests for autopilot supervisor, worker, manager,
watchdog, and monitor loops.

Covers: argument validation, config/budget defaults, proc_cmd passthrough,
instance-ID propagation, lifecycle (start/stop/status), status format,
log naming/rotation, timeout handling, low-burn mode, and prompt content.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from orchestrator.supervisor import Supervisor, SupervisorConfig, build_config_from_args, proc_cmd
from orchestrator.engine import Orchestrator

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_SH = str(REPO_ROOT / "scripts" / "autopilot" / "supervisor.sh")
MANAGER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "manager_loop.sh")
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")
WATCHDOG_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "watchdog_loop.sh")
MONITOR_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "monitor_loop.sh")

_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_cfg(**overrides) -> SupervisorConfig:
    with tempfile.TemporaryDirectory() as tmp:
        defaults = {
            "project_root": tmp,
            "repo_root": tmp,
            "log_dir": f"{tmp}/logs",
            "leader_agent": "codex",
        }
        defaults.update(overrides)
        cfg = SupervisorConfig(**defaults)
        cfg.finalise()
        return cfg


def _make_stub_cli(stub_dir: Path, name: str, *, sleep: int = 0) -> None:
    stub = stub_dir / name
    body = f"sleep {sleep}" if sleep else "exit 0"
    stub.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    stub.chmod(0o755)


def _run_shell(cmd: list[str], *, env=None, timeout: int = _TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=timeout, env=env,
    )


def _touch(path: Path, mtime: int) -> None:
    path.write_text("old\n", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _supervisor_env(stub_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
    return env


def _run_supervisor(action, pid_dir, log_dir, env, extra=None):
    cmd = [
        "bash", SUPERVISOR_SH, action,
        "--pid-dir", pid_dir, "--log-dir", log_dir,
        "--manager-cli-timeout", "30", "--worker-cli-timeout", "30",
        "--manager-interval", "9999", "--worker-interval", "9999",
    ]
    if extra:
        cmd.extend(extra)
    return subprocess.run(
        cmd, cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=90,
    )


# ===========================================================================
# SupervisorTests
# ===========================================================================

class SupervisorTests(unittest.TestCase):
    """Config defaults, proc_cmd passthrough, instance-ID, lifecycle, status format."""

    # -- Config defaults ---------------------------------------------------

    def test_default_idle_backoff(self):
        self.assertEqual(_default_cfg().idle_backoff, "30,60,120,300,900")

    def test_default_max_idle_cycles(self):
        self.assertEqual(_default_cfg().max_idle_cycles, 30)

    def test_default_daily_call_budget(self):
        self.assertEqual(_default_cfg().daily_call_budget, 100)

    def test_default_low_burn_false(self):
        self.assertFalse(_default_cfg().low_burn)

    def test_parser_defaults_to_low_burn(self):
        _, cfg = build_config_from_args(["status"])
        self.assertTrue(cfg.low_burn)

    def test_high_throughput_disables_low_burn(self):
        _, cfg = build_config_from_args(["status", "--high-throughput"])
        self.assertFalse(cfg.low_burn)

    # -- Low-burn mode -----------------------------------------------------

    def test_low_burn_increases_intervals(self):
        cfg = _default_cfg(low_burn=True)
        self.assertGreaterEqual(cfg.manager_interval, 120)
        self.assertGreaterEqual(cfg.worker_interval, 180)

    def test_low_burn_preserves_custom_intervals(self):
        cfg = _default_cfg(low_burn=True, manager_interval=300, worker_interval=600)
        self.assertEqual(cfg.manager_interval, 300)
        self.assertEqual(cfg.worker_interval, 600)

    def test_low_burn_preserves_custom_max_idle(self):
        cfg = _default_cfg(low_burn=True, max_idle_cycles=5)
        self.assertEqual(cfg.max_idle_cycles, 5)

    def test_mcp_default_low_burn_false(self):
        cfg = SupervisorConfig(low_burn=False)
        cfg.finalise()
        self.assertEqual(cfg.manager_interval, 20)
        self.assertEqual(cfg.worker_interval, 25)

    def test_mcp_explicit_high_intervals_preserved(self):
        cfg = SupervisorConfig(low_burn=True, manager_interval=60, worker_interval=90)
        cfg.finalise()
        self.assertEqual(cfg.manager_interval, 60)
        self.assertEqual(cfg.worker_interval, 90)

    def test_mcp_schema_low_burn_default(self):
        import orchestrator_mcp_server as srv
        resp = srv.handle_tools_list(request_id=1)
        tools = resp["result"]["tools"]
        hs = next(t for t in tools if t["name"] == "orchestrator_headless_start")
        self.assertFalse(hs["inputSchema"]["properties"]["low_burn"]["default"])

    # -- proc_cmd passthrough ----------------------------------------------

    def test_manager_cmd_includes_idle_flags(self):
        cfg = _default_cfg(idle_backoff="10,20", max_idle_cycles=5, daily_call_budget=100)
        cmd = proc_cmd("manager", cfg)
        self.assertIn("--idle-backoff 10,20", cmd)
        self.assertIn("--max-idle-cycles 5", cmd)
        self.assertIn("--daily-call-budget 100", cmd)

    def test_worker_cmd_includes_idle_flags(self):
        cfg = _default_cfg(idle_backoff="60", max_idle_cycles=10, daily_call_budget=50)
        cmd = proc_cmd("claude", cfg)
        self.assertIn("--idle-backoff 60", cmd)
        self.assertIn("--max-idle-cycles 10", cmd)
        self.assertIn("--daily-call-budget 50", cmd)

    def test_watchdog_cmd_excludes_idle_flags(self):
        cfg = _default_cfg(idle_backoff="10,20", max_idle_cycles=5, daily_call_budget=100)
        cmd = proc_cmd("watchdog", cfg)
        self.assertNotIn("--idle-backoff", cmd)
        self.assertNotIn("--max-idle-cycles", cmd)
        self.assertNotIn("--daily-call-budget", cmd)

    def test_persistent_flag_in_proc_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = SupervisorConfig(project_root=tmp, log_dir=f"{tmp}/logs",
                                   pid_dir=f"{tmp}/pids")
            cfg.finalise()
            cfg.persistent_workers = True
            cfg.max_tasks_per_session = 10
            cmd = proc_cmd("gemini", cfg)

            self.assertIn(" --max-tasks-per-session 10", cmd)

    def test_persistent_flag_absent_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = SupervisorConfig(project_root=tmp, log_dir=f"{tmp}/logs",
                                   pid_dir=f"{tmp}/pids")
            cfg.finalise()
            cfg.persistent_workers = False
            cmd = proc_cmd("gemini", cfg)
            self.assertNotIn(" --persistent", cmd)

    # -- Instance-ID propagation -------------------------------------------

    def _make_supervisor(self, agents):
        tmpdir = tempfile.mkdtemp()
        cfg = SupervisorConfig(
            project_root=tmpdir,
            log_dir=str(Path(tmpdir) / "logs"),
            pid_dir=str(Path(tmpdir) / "pids"),
        )
        cfg.finalise()
        orch = MagicMock(spec=Orchestrator)
        orch.list_agents.return_value = agents
        return Supervisor(cfg, orch), tmpdir

    def test_instance_id_in_status_json(self):
        sv, tmp = self._make_supervisor([
            {"agent": "gemini", "instance_id": "gemini#test-1",
             "status": "active", "task_counts": {"in_progress": 1}},
        ])
        status = sv.status_json()
        gem = next(p for p in status if p["name"] == "gemini")
        self.assertEqual(gem["instance_id"], "gemini#test-1")
        import shutil; shutil.rmtree(tmp, True)

    def test_instance_id_fallback_when_missing(self):
        sv, tmp = self._make_supervisor([])
        status = sv.status_json()
        gem = next(p for p in status if p["name"] == "gemini")
        self.assertEqual(gem["instance_id"], "gemini#headless-default")
        import shutil; shutil.rmtree(tmp, True)

    def test_claude_lane_task_activity(self):
        sv, tmp = self._make_supervisor([
            {"agent": "claude_code", "instance_id": "claude_code#headless-default-1",
             "status": "active", "task_counts": {"in_progress": 1, "assigned": 0}},
            {"agent": "claude_code", "instance_id": "claude_code#headless-default-2",
             "status": "active", "task_counts": {"in_progress": 0, "assigned": 2}},
            {"agent": "claude_code", "instance_id": "claude_code#headless-default-3",
             "status": "active", "task_counts": {"in_progress": 0, "assigned": 0}},
        ])
        status = sv.status_json()
        c1 = next(p for p in status if p["name"] == "claude")
        c2 = next(p for p in status if p["name"] == "claude_2")
        c3 = next(p for p in status if p["name"] == "claude_3")
        self.assertEqual(c1["task_activity"], "working")
        self.assertEqual(c2["task_activity"], "working")
        self.assertEqual(c3["task_activity"], "idle")
        import shutil; shutil.rmtree(tmp, True)

    # -- Lifecycle (shell) -------------------------------------------------

    def _lifecycle_setup(self):
        tmp = tempfile.mkdtemp()
        pid_dir = os.path.join(tmp, "pids")
        log_dir = os.path.join(tmp, "logs")
        stub_dir = Path(tmp) / "stubs"
        stub_dir.mkdir()
        for cli in ("codex", "claude", "gemini"):
            _make_stub_cli(stub_dir, cli)
        env = _supervisor_env(stub_dir)
        return tmp, pid_dir, log_dir, env

    def _lifecycle_teardown(self, tmp, pid_dir, log_dir, env):
        _run_supervisor("stop", pid_dir, log_dir, env)
        import shutil; shutil.rmtree(tmp, True)

    def test_status_before_start_shows_stopped(self):
        tmp, pid_dir, log_dir, env = self._lifecycle_setup()
        try:
            proc = _run_supervisor("status", pid_dir, log_dir, env)
            self.assertEqual(0, proc.returncode)
            self.assertIn("stopped", proc.stdout)
        finally:
            self._lifecycle_teardown(tmp, pid_dir, log_dir, env)

    def test_start_creates_pid_files(self):
        tmp, pid_dir, log_dir, env = self._lifecycle_setup()
        try:
            proc = _run_supervisor("start", pid_dir, log_dir, env)
            self.assertEqual(0, proc.returncode)
            self.assertGreaterEqual(len(list(Path(pid_dir).glob("*.pid"))), 1)
        finally:
            self._lifecycle_teardown(tmp, pid_dir, log_dir, env)

    def test_stop_removes_pid_files(self):
        tmp, pid_dir, log_dir, env = self._lifecycle_setup()
        try:
            _run_supervisor("start", pid_dir, log_dir, env)
            _run_supervisor("stop", pid_dir, log_dir, env)
            if Path(pid_dir).exists():
                self.assertEqual(0, len(list(Path(pid_dir).glob("*.pid"))))
        finally:
            self._lifecycle_teardown(tmp, pid_dir, log_dir, env)

    def test_unknown_command_exits_nonzero(self):
        tmp, pid_dir, log_dir, env = self._lifecycle_setup()
        try:
            proc = _run_supervisor("bogus", pid_dir, log_dir, env)
            self.assertNotEqual(0, proc.returncode)
        finally:
            self._lifecycle_teardown(tmp, pid_dir, log_dir, env)

    # -- Status format -----------------------------------------------------

    def test_status_header_fields(self):
        tmp, pid_dir, log_dir, env = self._lifecycle_setup()
        try:
            proc = _run_supervisor("status", pid_dir, log_dir, env)
            for field in ("Autopilot supervisor status", "Project:", "PID dir:", "Log dir:"):
                self.assertIn(field, proc.stdout)
        finally:
            self._lifecycle_teardown(tmp, pid_dir, log_dir, env)

    def test_status_lists_all_processes(self):
        tmp, pid_dir, log_dir, env = self._lifecycle_setup()
        try:
            proc = _run_supervisor("status", pid_dir, log_dir, env)
            for name in ("manager", "wingman", "claude", "gemini", "watchdog"):
                self.assertIn(name, proc.stdout)
        finally:
            self._lifecycle_teardown(tmp, pid_dir, log_dir, env)

    def test_stopped_format_pid_dash_restarts_zero(self):
        tmp, pid_dir, log_dir, env = self._lifecycle_setup()
        try:
            proc = _run_supervisor("status", pid_dir, log_dir, env)
            self.assertRegex(proc.stdout, r"manager\s+stopped\s+-\s+0")
        finally:
            self._lifecycle_teardown(tmp, pid_dir, log_dir, env)


# ===========================================================================
# WorkerLoopTests
# ===========================================================================

class WorkerLoopTests(unittest.TestCase):
    """worker_loop.sh argument validation, unsupported CLI, prompt content."""

    def _run_worker(self, args, *, env=None):
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return _run_shell(["bash", WORKER_LOOP, *args], env=merged, timeout=10)

    # -- Argument validation -----------------------------------------------

    def test_unknown_arg_exits_1_with_error(self):
        proc = self._run_worker(["--bogus-flag"])
        self.assertEqual(1, proc.returncode)
        self.assertIn("[ERROR]", proc.stderr)
        self.assertIn("Unknown arg", proc.stderr)
        self.assertIn("--bogus-flag", proc.stderr)

    def test_multiple_unknown_args_rejects_first(self):
        proc = self._run_worker(["--aaa", "--bbb"])
        self.assertEqual(1, proc.returncode)
        self.assertIn("--aaa", proc.stderr)

    def test_missing_cli_and_agent_error(self):
        proc = self._run_worker([])
        self.assertEqual(1, proc.returncode)
        self.assertIn("[ERROR]", proc.stderr)
        self.assertIn("--cli and --agent are required", proc.stderr)

    def test_missing_agent_only_error(self):
        proc = self._run_worker(["--cli", "codex"])
        self.assertEqual(1, proc.returncode)
        self.assertIn("--cli and --agent are required", proc.stderr)

    def test_missing_cli_only_error(self):
        proc = self._run_worker(["--agent", "claude_code"])
        self.assertEqual(1, proc.returncode)
        self.assertIn("--cli and --agent are required", proc.stderr)

    # -- Unsupported CLI ---------------------------------------------------

    def _run_with_fake_cli(self, cli_name="fakecli", agent="test_agent"):
        tmp = tempfile.mkdtemp()
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        _make_stub_cli(bin_dir, cli_name)
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        proc = self._run_worker([
            "--cli", cli_name, "--agent", agent, "--once",
            "--project-root", tmp, "--log-dir", str(Path(tmp) / "logs"),
        ], env=env)
        return proc

    def test_unsupported_cli_exits_nonzero_with_error(self):
        proc = self._run_with_fake_cli()
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("Unsupported CLI: fakecli", proc.stderr)
        self.assertIn("worker cycle failed", proc.stderr)

    def test_unsupported_cli_includes_name(self):
        proc = self._run_with_fake_cli(cli_name="mycustomtool")
        self.assertIn("Unsupported CLI: mycustomtool", proc.stderr)

    def test_worker_info_log_before_failure(self):
        proc = self._run_with_fake_cli()
        self.assertIn("worker cycle=0", proc.stderr)
        self.assertIn("agent=test_agent", proc.stderr)

    # -- Prompt auto-claim content -----------------------------------------

    def test_prompt_auto_claim_no_redundant_poll_or_claim_in_setup(self):
        """Setup section should not contain poll_events or claim_next_task;
        connect_to_leader auto-claims, so those calls are redundant."""
        script = (REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh").read_text()
        match = re.search(r'cat\s*>"?\$prompt_file"?\s*<<EOF\n(.*?)\nEOF', script, re.DOTALL)
        self.assertIsNotNone(match, "prompt heredoc not found")
        prompt = match.group(1)
        # Setup section ends at "TASK LOOP" header
        setup_end = prompt.find("TASK LOOP")
        if setup_end == -1:
            # Legacy one-shot prompt has no TASK LOOP; setup is steps 1-3
            setup_section = prompt[:prompt.find("If a task is claimed")]
        else:
            setup_section = prompt[:setup_end]
        self.assertNotIn("poll_events", setup_section)
        self.assertNotIn("claim_next_task", setup_section)

    # -- Skip inter-cycle sleep detection ------------------------------------

    def test_auto_claim_next_regex_detects_task_id(self):
        """The regex in worker_loop.sh should detect TASK IDs near auto_claim_next."""
        # Simulated CLI output containing an auto_claim_next with a task ID
        output_with_task = (
            'Tool result: {"ok": true, "result": {"submitted": true, '
            '"auto_claim_next": {"id": "TASK-3c9ffcbc", "title": "Do stuff", '
            '"status": "in_progress"}}}\n'
        )
        result = subprocess.run(
            ["python3", "-c",
             'import re,sys; sys.exit(0 if re.search(r"auto_claim_next.*?TASK-[0-9a-f]+",sys.stdin.read(),re.DOTALL) else 1)'],
            input=output_with_task, capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, "Should detect TASK ID in auto_claim_next")

    def test_auto_claim_next_regex_rejects_null(self):
        """No false positive when auto_claim_next is null."""
        output_null = (
            'Tool result: {"ok": true, "result": {"submitted": true, '
            '"auto_claim_next": null}}\n'
        )
        result = subprocess.run(
            ["python3", "-c",
             'import re,sys; sys.exit(0 if re.search(r"auto_claim_next.*?TASK-[0-9a-f]+",sys.stdin.read(),re.DOTALL) else 1)'],
            input=output_null, capture_output=True, text=True,
        )
        self.assertNotEqual(0, result.returncode, "Should NOT detect task when auto_claim_next is null")

    def test_auto_claim_next_regex_rejects_no_match(self):
        """No false positive when auto_claim_next is absent."""
        output_no_claim = 'Task completed. All done.\n'
        result = subprocess.run(
            ["python3", "-c",
             'import re,sys; sys.exit(0 if re.search(r"auto_claim_next.*?TASK-[0-9a-f]+",sys.stdin.read(),re.DOTALL) else 1)'],
            input=output_no_claim, capture_output=True, text=True,
        )
        self.assertNotEqual(0, result.returncode, "Should NOT detect task when auto_claim_next absent")

    def test_skip_sleep_fallback_uses_claimable_work_check(self):
        """worker_loop.sh should have a worker_has_claimable_work fallback for skip_sleep."""
        script = (REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh").read_text()
        # Verify the fallback pattern exists: check claimable work after task completion
        self.assertIn("worker_has_claimable_work", script)
        # The skip_sleep fallback should appear in the post-cycle section (after run_cli_prompt)
        post_cycle = script[script.index("run_cli_prompt"):]
        self.assertRegex(
            post_cycle,
            r'skip_sleep.*false.*worker_has_claimable_work',
            "skip_sleep fallback should check worker_has_claimable_work",
        )

    # -- Max-logs pruning --------------------------------------------------

    def test_worker_max_logs_prunes_own_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"; bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"; log_dir.mkdir()
            _make_stub_cli(bin_dir, "codex", sleep=5)
            for i in range(3):
                _touch(log_dir / f"worker-claude_code-codex-20250101-00000{i}.log", 2000 + i)
            _touch(log_dir / "manager-codex-20250101-000000.log", 1999)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            subprocess.run(
                ["bash", WORKER_LOOP, "--cli", "codex", "--agent", "claude_code",
                 "--once", "--project-root", str(REPO_ROOT), "--log-dir", str(log_dir),
                 "--cli-timeout", "1", "--max-logs", "2"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=_TIMEOUT,
            )
            self.assertLessEqual(len(list(log_dir.glob("worker-claude_code-codex-*.log"))), 2)
            self.assertEqual(len(list(log_dir.glob("manager-codex-*.log"))), 1)


# ===========================================================================
# ManagerLoopTests
# ===========================================================================

class ManagerLoopTests(unittest.TestCase):
    """manager_loop.sh argument validation, --once failure, timeout naming."""

    def _run_manager(self, args, *, env=None):
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return _run_shell(["bash", MANAGER_LOOP, *args], env=merged, timeout=_TIMEOUT)

    # -- Argument validation -----------------------------------------------

    def test_unknown_arg_exits_1_with_error(self):
        proc = self._run_manager(["--bogus-flag"])
        self.assertEqual(1, proc.returncode)
        self.assertIn("[ERROR]", proc.stderr)
        self.assertIn("Unknown arg: --bogus-flag", proc.stderr)

    def test_multiple_unknown_args_rejects_first(self):
        proc = self._run_manager(["--aaa", "--bbb"])
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("--aaa", proc.stderr)

    def test_unknown_arg_exit_code_is_always_1(self):
        for flag in ("--xyz", "--does-not-exist", "--invalid"):
            with self.subTest(flag=flag):
                proc = self._run_manager([flag])
                self.assertEqual(1, proc.returncode)

    # -- --once failure propagation ----------------------------------------

    def _make_fake_cli_env(self, tmp):
        bin_dir = Path(tmp) / "bin"; bin_dir.mkdir()
        _make_stub_cli(bin_dir, "fakecli")
        return {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}

    def test_unsupported_cli_once_exits_nonzero_with_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._make_fake_cli_env(tmp)
            proc = self._run_manager([
                "--cli", "fakecli", "--once",
                "--project-root", tmp, "--log-dir", str(Path(tmp) / "logs"),
            ], env=env)
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("Unsupported CLI: fakecli", proc.stderr)
            self.assertIn("manager cycle failed", proc.stderr)

    def test_unsupported_cli_once_creates_log_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._make_fake_cli_env(tmp)
            log_dir = Path(tmp) / "logs"
            self._run_manager([
                "--cli", "fakecli", "--once",
                "--project-root", tmp, "--log-dir", str(log_dir),
            ], env=env)
            self.assertTrue(log_dir.exists())

    def test_missing_cli_command_once_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run_manager([
                "--cli", "nonexistent_cli_xyz", "--once",
                "--project-root", tmp, "--log-dir", str(Path(tmp) / "logs"),
            ])
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("Missing required command", proc.stderr)

    # -- Timeout naming ----------------------------------------------------

    def _run_timeout(self, cli_name="codex", cli_timeout=1):
        tmp = tempfile.mkdtemp()
        bin_dir = Path(tmp) / "bin"; bin_dir.mkdir()
        log_dir = Path(tmp) / "logs"
        _make_stub_cli(bin_dir, cli_name, sleep=5)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        proc = subprocess.run(
            ["bash", MANAGER_LOOP, "--cli", cli_name, "--once",
             "--project-root", str(REPO_ROOT), "--log-dir", str(log_dir),
             "--cli-timeout", str(cli_timeout)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=_TIMEOUT,
        )
        return proc, log_dir

    def test_timeout_stderr_message(self):
        proc, _ = self._run_timeout()
        self.assertIn("manager cycle timed out after 1s", proc.stderr)
        self.assertIn("[ERROR]", proc.stderr)

    def test_timeout_log_filename_pattern(self):
        _, log_dir = self._run_timeout()
        logs = list(log_dir.glob("manager-codex-*.log"))
        self.assertEqual(1, len(logs))
        self.assertRegex(logs[0].name, r"^manager-codex-\d{8}-\d{6}\.log$")

    def test_timeout_log_contains_marker(self):
        _, log_dir = self._run_timeout()
        logs = list(log_dir.glob("manager-codex-*.log"))
        self.assertTrue(logs)
        self.assertIn("[AUTOPILOT] CLI timeout after 1s for codex",
                       logs[0].read_text(encoding="utf-8"))

    def test_timeout_exits_nonzero(self):
        proc, _ = self._run_timeout()
        self.assertNotEqual(0, proc.returncode)

    # -- Max-logs pruning --------------------------------------------------

    def test_manager_max_logs_prunes_own_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"; bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"; log_dir.mkdir()
            _make_stub_cli(bin_dir, "codex", sleep=5)
            for i in range(3):
                _touch(log_dir / f"manager-codex-20250101-00000{i}.log", 1000 + i)
            _touch(log_dir / "worker-claude_code-codex-20250101-000000.log", 999)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            subprocess.run(
                ["bash", MANAGER_LOOP, "--cli", "codex", "--once",
                 "--project-root", str(REPO_ROOT), "--log-dir", str(log_dir),
                 "--cli-timeout", "1", "--max-logs", "2"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=_TIMEOUT,
            )
            self.assertLessEqual(len(list(log_dir.glob("manager-codex-*.log"))), 2)
            self.assertEqual(len(list(log_dir.glob("worker-claude_code-*.log"))), 1)


# ===========================================================================
# WatchdogTests
# ===========================================================================

class WatchdogTests(unittest.TestCase):
    """watchdog_loop.sh JSONL naming, rotation, and cycle output."""

    def _run_watchdog(self, project_root, log_dir, *, max_logs=200):
        return _run_shell([
            "bash", WATCHDOG_LOOP,
            "--project-root", project_root, "--log-dir", log_dir,
            "--max-logs", str(max_logs), "--once",
        ])

    def _setup_state(self, root: Path, *, stale=True):
        state = root / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "bugs.json").write_text("[]")
        (state / "blockers.json").write_text("[]")
        if stale:
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            tasks = [{"id": "TASK-stale", "owner": "test", "status": "assigned",
                       "title": "stale task", "updated_at": old_ts}]
            (state / "tasks.json").write_text(json.dumps(tasks))
        else:
            (state / "tasks.json").write_text("[]")

    def test_once_creates_jsonl_with_timestamp_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            self._run_watchdog(tmp, str(root / "logs"))
            jsonl = list((root / "logs").glob("watchdog-*.jsonl"))
            self.assertEqual(1, len(jsonl))
            self.assertRegex(jsonl[0].name, r"^watchdog-\d{8}-\d{6}\.jsonl$")

    def test_max_logs_prunes_old_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            log_dir = root / "logs"; log_dir.mkdir(parents=True)
            for i in range(3):
                f = log_dir / f"watchdog-20250101-00000{i}.jsonl"
                f.write_text("{}\n")
                os.utime(f, (1000000 + i, 1000000 + i))
            self._run_watchdog(tmp, str(log_dir), max_logs=2)
            self.assertLessEqual(len(list(log_dir.glob("watchdog-*.jsonl"))), 2)

    def test_stderr_contains_cycle_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            proc = self._run_watchdog(tmp, str(root / "logs"))
            self.assertIn("watchdog cycle=1", proc.stderr)


# ===========================================================================
# MonitorLoopTests
# ===========================================================================

class MonitorLoopTests(unittest.TestCase):
    """monitor_loop.sh output stability and project-path header."""

    def _run_monitor(self, project_root, *, extra_env=None):
        env = os.environ.copy()
        env["TERM"] = "dumb"
        if extra_env:
            env.update(extra_env)
        try:
            proc = subprocess.run(
                ["bash", MONITOR_LOOP, project_root, "1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=5, env=env,
            )
            return proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            return stdout, stderr

    def test_prints_project_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout, _ = self._run_monitor(tmp)
            self.assertIn(f"project={tmp}", stdout)

    def test_project_path_is_first_content_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout, _ = self._run_monitor(tmp)
            lines = [l for l in stdout.splitlines() if l.strip()]
            self.assertTrue(lines)
            self.assertEqual(f"project={tmp}", lines[0])

    def test_handles_missing_logs_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout, stderr = self._run_monitor(tmp)
            self.assertIn(f"project={tmp}", stdout)
            self.assertNotIn("No such file", stdout + stderr)

    def test_handles_empty_logs_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".autopilot-logs").mkdir()
            stdout, _ = self._run_monitor(tmp)
            self.assertIn(f"project={tmp}", stdout)

    def test_lists_log_files_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / ".autopilot-logs"; logs.mkdir()
            (logs / "manager-codex-20260101-000000.log").write_text("cycle\n")
            (logs / "worker-claude-20260101-000000.log").write_text("cycle\n")
            stdout, _ = self._run_monitor(tmp)
            self.assertIn("manager-codex", stdout)
            self.assertIn("worker-claude", stdout)

    def test_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "my project dir"; spaced.mkdir()
            stdout, _ = self._run_monitor(str(spaced))
            self.assertIn(f"project={spaced}", stdout)

    def test_codex_list_output_capped_to_five_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"; bin_dir.mkdir()
            fake = bin_dir / "codex"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                'if [ "${1:-}" = "mcp" ] && [ "${2:-}" = "list" ]; then\n'
                "  printf 'line1\\nline2\\nline3\\nline4\\nline5\\nline6\\nline7\\n'\n"
                "fi\n"
            )
            fake.chmod(0o755)
            stdout, _ = self._run_monitor(
                tmp, extra_env={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            for n in ("line1", "line2", "line3", "line4", "line5"):
                self.assertIn(n, stdout)
            self.assertNotIn("line6", stdout)


if __name__ == "__main__":
    unittest.main()
