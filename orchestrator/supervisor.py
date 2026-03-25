"""Process supervisor for headless autopilot loops.

Manages background agent processes (manager, workers, watchdog) with PID-file
tracking, topology-aware enablement, and graceful shutdown.  Designed to be
called from the thin shell wrapper ``scripts/autopilot/supervisor.sh`` or
directly via ``python3 -m orchestrator.supervisor``.
"""
from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

# Default process names in canonical order.
_BASE_PROCS = ("manager", "wingman", "claude", "claude_2", "claude_3", "gemini", "codex_worker", "watchdog")

STOP_WAIT_SECONDS = 10


@dataclass
class ExtraWorker:
    """Parsed ``--extra-worker name:cli:agent:team_id:project_root[:lane]``."""

    name: str
    cli: str
    agent: str
    team_id: str
    project_root: str
    lane: str = "default"


@dataclass
class SupervisorConfig:
    """All tunables consumed by the supervisor."""

    project_root: str = ""
    log_dir: str = ""
    pid_dir: str = ""
    manager_cli_timeout: int = 300
    worker_cli_timeout: int = 600
    manager_interval: int = 20
    worker_interval: int = 25
    idle_backoff: str = "30,60,120,300,900"
    max_idle_cycles: int = 200
    daily_call_budget: int = 100
    daily_token_budget: int = 1000000     # Hard daily token ceiling. 0 = disabled.
    hourly_token_budget: int = 100000     # Hard hourly token ceiling. 0 = disabled.
    tokens_per_call: int = 10000     # Estimated tokens consumed per CLI call.
    event_driven: bool = True
    low_burn: bool = False
    leader_agent: str = "codex"
    leader_cli: str = ""
    wingman_agent: str = "ccm"
    wingman_cli: str = "claude"
    claude_project_root: str = ""
    gemini_project_root: str = ""
    codex_project_root: str = ""
    wingman_project_root: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_model: str = ""
    gemini_capacity_retries: int = 2
    gemini_capacity_backoff: int = 15
    claude_team_id: str = ""
    gemini_team_id: str = ""
    codex_team_id: str = ""
    wingman_team_id: str = ""
    claude_lanes: int = 3  # Number of parallel Claude workers (1-3).
    persistent_workers: bool = True  # Use persistent worker sessions (no cold-start).
    max_tasks_per_session: int = 5    # Max tasks per persistent CLI session.
    extra_workers: List[ExtraWorker] = field(default_factory=list)
    mcp_auto_manager_active: bool = False  # When True, suppress shell manager_loop (MCP handles it).
    max_restarts: int = 5
    backoff_base: int = 10
    backoff_max: int = 120
    # Resolved at finalise time.
    repo_root: str = ""
    scripts: Path = field(init=False)

    # ------------------------------------------------------------------
    def finalise(self) -> None:
        """Fill in derived defaults that depend on other fields."""
        if not self.repo_root:
            self.repo_root = str(REPO_ROOT)
        if not self.project_root:
            self.project_root = self.repo_root
        if not self.log_dir:
            self.log_dir = os.path.join(self.project_root, ".autopilot-logs")
        if not self.pid_dir:
            self.pid_dir = os.path.join(self.project_root, ".autopilot-pids")
        self.scripts = Path(self.repo_root) / "scripts" / "autopilot"
        for attr in ("claude_project_root", "gemini_project_root",
                      "codex_project_root", "wingman_project_root"):
            if not getattr(self, attr):
                setattr(self, attr, self.project_root)
        if not self.leader_cli:
            self.leader_cli = {
                "codex": "codex",
                "claude_code": "claude",
                "gemini": "gemini",
            }.get(self.leader_agent, "codex")
        if self.low_burn:
            # Conservative low-burn defaults: fewer wakeups, bounded idle life.
            if self.manager_interval <= 20:
                self.manager_interval = 120
            if self.worker_interval <= 25:
                self.worker_interval = 180
            if self.max_idle_cycles <= 0:
                self.max_idle_cycles = 30

    def _token_budget_args(self) -> str:
        parts = ""
        if self.daily_token_budget > 0:
            parts += f" --daily-token-budget {shlex.quote(str(self.daily_token_budget))}"
        if self.hourly_token_budget > 0:
            parts += f" --hourly-token-budget {shlex.quote(str(self.hourly_token_budget))}"
        if self.tokens_per_call != 10000:
            parts += f" --tokens-per-call {shlex.quote(str(self.tokens_per_call))}"
        return parts

    def _persistent_worker_args(self, name: str, lane: str, cli: str, agent: str, team_id: str, project_root: str) -> str:
        instance_id = _get_instance_id(name, lane)
        session_arg = f" --max-tasks-per-session {shlex.quote(str(self.max_tasks_per_session))}" if self.max_tasks_per_session > 0 else ""
        return (
            f" --cli {shlex.quote(cli)}"
            f" --agent {shlex.quote(agent)}"
            f" --lane {shlex.quote(lane)}{_team_arg(team_id)}"
            f" --instance-id {shlex.quote(instance_id)}"
            f" --project-root {shlex.quote(project_root)}"
            f" --repo-root {shlex.quote(self.repo_root)}"
            f" --log-dir {shlex.quote(self.log_dir)}"
            f" --pid-dir {shlex.quote(self.pid_dir)}"
            f" --process-name {shlex.quote(name)}"
            f" --cli-timeout {shlex.quote(str(self.worker_cli_timeout))}"
            f" --heartbeat-interval {shlex.quote(str(self.worker_interval))}"
            f" --idle-backoff {shlex.quote(str(self.idle_backoff))}"
            f" --max-idle-cycles {shlex.quote(str(self.max_idle_cycles))}"
            f" --daily-call-budget {shlex.quote(str(self.daily_call_budget))}"
            f"{session_arg}"
            f"{self._token_budget_args()}"
        )

    def _worker_loop_args(self, name: str, lane: str, cli: str, agent: str, team_id: str, project_root: str) -> str:
        instance_id = _get_instance_id(name, lane)
        return (
            f" --cli {shlex.quote(cli)}"
            f" --agent {shlex.quote(agent)}"
            f" --lane {shlex.quote(lane)}{_team_arg(team_id)}"
            f" --instance-id {shlex.quote(instance_id)}"
            f" --project-root {shlex.quote(project_root)}"
            f" --interval {shlex.quote(str(self.worker_interval))}"
            f" --cli-timeout {shlex.quote(str(self.worker_cli_timeout))}"
            f" --log-dir {shlex.quote(self.log_dir)}"
            f" --idle-backoff {shlex.quote(str(self.idle_backoff))}"
            f" --max-idle-cycles {shlex.quote(str(self.max_idle_cycles))}"
            f" --daily-call-budget {shlex.quote(str(self.daily_call_budget))}"
            f"{self._token_budget_args()}"
            f"{_event_driven_arg(self)}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(level: str, msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"[{ts}] [{level}] {msg}", file=sys.stderr)


def _pid_file(pid_dir: str, name: str) -> Path:
    return Path(pid_dir) / f"{name}.pid"


def _restart_count_file(pid_dir: str, name: str) -> Path:
    return Path(pid_dir) / f"{name}.restarts"


def _proc_log_file(log_dir: str, name: str) -> Path:
    return Path(log_dir) / f"supervisor-{name}.log"


def _read_pid(pid_dir: str, name: str) -> Optional[int]:
    pf = _pid_file(pid_dir, name)
    if not pf.exists():
        return None
    try:
        text = pf.read_text().strip()
        return int(text) if text else None
    except (ValueError, OSError):
        return None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

def proc_enabled(name: str, leader_agent: str, claude_lanes: int = 3,
                  mcp_auto_manager_active: bool = False) -> bool:
    """Return whether *name* should run given *leader_agent*.

    *claude_lanes* controls how many parallel Claude workers are active (1-3).
    ``claude`` is always enabled (when leader permits), ``claude_2`` requires
    ``claude_lanes >= 2``, and ``claude_3`` requires ``claude_lanes >= 3``.

    When *mcp_auto_manager_active* is True the MCP in-process auto_manager_loop
    handles all manager duties, so the shell ``manager_loop.sh`` is disabled to
    avoid redundant (10K+ token) CLI spawns.
    """
    if name == "manager" and mcp_auto_manager_active:
        return False
    if name in ("claude", "claude_2", "claude_3"):
        # Claude workers run alongside claude_code leader — leader is manager-only,
        # workers are separate headless processes with their own instance IDs.
        if name == "claude_2":
            return claude_lanes >= 2
        if name == "claude_3":
            return claude_lanes >= 3
        return True
    if name == "gemini":
        return leader_agent != "gemini"
    if name == "codex_worker":
        return leader_agent != "codex"
    return True


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

def _get_instance_id(name: str, lane: str = "default") -> str:
    """Generate a consistent instance ID for a process name and lane."""
    if name in ("manager", "watchdog"):
        return f"{name}#headless-{lane}"
    if name.startswith("claude"):
        lane_num = name.split("_")[1] if "_" in name else "1"
        return f"claude_code#headless-{lane}-{lane_num}"
    return f"{name}#headless-{lane}"

def _team_arg(tid: str) -> str:
    return f" --team-id {shlex.quote(tid)}" if tid else ""

def _event_driven_arg(cfg: SupervisorConfig) -> str:
    return " --event-driven" if cfg.event_driven else ""

def proc_cmd(name: str, cfg: SupervisorConfig,
             extra_names: Sequence[str] = (),
             extra_cmds: Sequence[str] = ()) -> str:
    """Return the shell command string for *name*."""
    # Check extras first.
    for i, ename in enumerate(extra_names):
        if ename == name:
            return extra_cmds[i]

    # ------------------------------------------------------------------

    if name == "manager":
        return (
            f"{shlex.quote(str(cfg.scripts))}/manager_loop.sh"
            f" --cli {shlex.quote(cfg.leader_cli)}"
            f" --leader-agent {shlex.quote(cfg.leader_agent)}"
            f" --project-root {shlex.quote(cfg.project_root)}"
            f" --interval {shlex.quote(str(cfg.manager_interval))}"
            f" --cli-timeout {shlex.quote(str(cfg.manager_cli_timeout))}"
            f" --log-dir {shlex.quote(cfg.log_dir)}"
            f" --idle-backoff {shlex.quote(str(cfg.idle_backoff))}"
            f" --max-idle-cycles {shlex.quote(str(cfg.max_idle_cycles))}"
            f" --daily-call-budget {shlex.quote(str(cfg.daily_call_budget))}"
            f"{cfg._token_budget_args()}"
        )
    if name == "wingman":
        if cfg.persistent_workers:
            return (
                f"python3 -m orchestrator.persistent_worker"
                f"{cfg._persistent_worker_args(name, 'wingman', cfg.wingman_cli, cfg.wingman_agent, cfg.wingman_team_id, cfg.wingman_project_root)}"
            )
        else:
            return (
                f"{shlex.quote(str(cfg.scripts))}/worker_loop.sh"
                f"{cfg._worker_loop_args(name, 'wingman', cfg.wingman_cli, cfg.wingman_agent, cfg.wingman_team_id, cfg.wingman_project_root)}"
            )
    if name in ("claude", "claude_2", "claude_3"):
        if cfg.persistent_workers:
            return (
                f"python3 -m orchestrator.persistent_worker"
                f"{cfg._persistent_worker_args(name, 'default', 'claude', 'claude_code', cfg.claude_team_id, cfg.claude_project_root)}"
            )
        else:
            return (
                f"{shlex.quote(str(cfg.scripts))}/worker_loop.sh"
                f"{cfg._worker_loop_args(name, 'default', 'claude', 'claude_code', cfg.claude_team_id, cfg.claude_project_root)}"
            )
    if name == "gemini":
        env_parts = []
        if cfg.gemini_model:
            env_parts.append(f"ORCHESTRATOR_GEMINI_MODEL={shlex.quote(cfg.gemini_model)}")
        if cfg.gemini_fallback_model:
            env_parts.append(f"ORCHESTRATOR_GEMINI_FALLBACK_MODEL={shlex.quote(cfg.gemini_fallback_model)}")
        env_parts.append(f"ORCHESTRATOR_GEMINI_CAPACITY_RETRIES={shlex.quote(str(cfg.gemini_capacity_retries))}")
        env_parts.append(f"ORCHESTRATOR_GEMINI_CAPACITY_BACKOFF_SECONDS={shlex.quote(str(cfg.gemini_capacity_backoff))}")
        env_prefix = " ".join(env_parts) + " " if env_parts else ""
        if cfg.persistent_workers:
            return (
                f"{env_prefix}python3 -m orchestrator.persistent_worker"
                f"{cfg._persistent_worker_args(name, 'default', 'gemini', 'gemini', cfg.gemini_team_id, cfg.gemini_project_root)}"
            )
        else:
            return (
                f"{env_prefix}{shlex.quote(str(cfg.scripts))}/worker_loop.sh"
                f"{cfg._worker_loop_args(name, 'default', 'gemini', 'gemini', cfg.gemini_team_id, cfg.gemini_project_root)}"
            )
    if name == "codex_worker":
        if cfg.persistent_workers:
            return (
                f"python3 -m orchestrator.persistent_worker"
                f"{cfg._persistent_worker_args(name, 'default', 'codex', 'codex', cfg.codex_team_id, cfg.codex_project_root)}"
            )
        else:
            return (
                f"{shlex.quote(str(cfg.scripts))}/worker_loop.sh"
                f"{cfg._worker_loop_args(name, 'default', 'codex', 'codex', cfg.codex_team_id, cfg.codex_project_root)}"
            )
    if name == "watchdog":
        return (
            f"{shlex.quote(str(cfg.scripts))}/watchdog_loop.sh"
            f" --project-root {shlex.quote(cfg.project_root)}"
            f" --interval 15"
            f" --log-dir {shlex.quote(cfg.log_dir)}"
        )
    raise ValueError(f"unknown process name: {name}")


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

def _capacity_error_file(pid_dir: str, name: str) -> Path:
    return Path(pid_dir) / f"{name}.capacity_errors"


def _budget_exhaustion_file(pid_dir: str, name: str) -> Path:
    return Path(pid_dir) / f"{name}.token_budget_exhausted"


def _is_budget_window_active(pid_dir: str, name: str) -> bool:
    """Return True if a budget-exhaustion marker exists and has not expired."""
    marker = _budget_exhaustion_file(pid_dir, name)
    if not marker.exists():
        return False
    try:
        import json
        from datetime import datetime, timezone
        data = json.loads(marker.read_text().strip())
        next_window = data.get("next_window_at", "")
        if not next_window:
            return False
        # Parse ISO timestamp and compare to now.
        nw = datetime.fromisoformat(next_window.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < nw
    except Exception:
        return False


@dataclass
class ProcessStatus:
    name: str
    state: str  # running | stopped | dead | disabled
    pid: Optional[int]
    restarts: int
    heartbeat_status: str # active | stale | unknown | n/a
    task_activity: str # idle | working | blocked | reporting | no_tasks | expected_stopped
    capacity_errors: int = 0  # gemini capacity error streak count
    leader_heartbeat_stale: bool = False  # True when leader process is up but heartbeat is stale/unknown


class Supervisor:
    """Headless process supervisor — Python equivalent of supervisor.sh."""

    def __init__(self, cfg: SupervisorConfig, orchestrator: Orchestrator) -> None:
        cfg.finalise()
        self.cfg = cfg
        self.orchestrator = orchestrator
        # Register extra workers.
        self._extra_names: List[str] = []
        self._extra_cmds: List[str] = []
        self._procs: List[str] = list(_BASE_PROCS)
        self._register_extras()

    # -- extra worker registration ------------------------------------------

    def _register_extras(self) -> None:
        for ew in self.cfg.extra_workers:
            if ew.name in self._extra_names or ew.name in _BASE_PROCS:
                raise ValueError(f"duplicate process name: {ew.name}")
            if ew.lane not in ("default", "wingman"):
                raise ValueError(f"invalid lane '{ew.lane}' for extra worker '{ew.name}'")
            if self.cfg.persistent_workers:
                cmd = (
                    f"python3 -m orchestrator.persistent_worker"
                    f"{self.cfg._persistent_worker_args(ew.name, ew.lane, ew.cli, ew.agent, ew.team_id, ew.project_root)}"
                )
            else:
                cmd = (
                    f"{self.cfg.scripts}/worker_loop.sh"
                    f"{self.cfg._worker_loop_args(ew.name, ew.lane, ew.cli, ew.agent, ew.team_id, ew.project_root)}"
                )
            self._extra_names.append(ew.name)
            self._extra_cmds.append(cmd)
            self._procs.append(ew.name)

    # -- low-level helpers --------------------------------------------------

    def _is_running(self, name: str) -> bool:
        pid = _read_pid(self.cfg.pid_dir, name)
        if pid is None:
            return False
        return _is_alive(pid)

    def _start_proc(self, name: str) -> None:
        if not proc_enabled(name, self.cfg.leader_agent, self.cfg.claude_lanes, self.cfg.mcp_auto_manager_active):
            _log("INFO", f"skipping disabled process {name} (leader_agent={self.cfg.leader_agent})")
            return
        if self._is_running(name):
            pid = _read_pid(self.cfg.pid_dir, name)
            _log("INFO", f"{name} already running (pid={pid})")
            return

        cmd = proc_cmd(name, self.cfg, self._extra_names, self._extra_cmds)
        logf = _proc_log_file(self.cfg.log_dir, name)

        with open(logf, "a") as lf:
            proc = subprocess.Popen(
                ["bash", "-c", cmd],
                stdout=lf,
                stderr=lf,
                start_new_session=True,
            )

        _pid_file(self.cfg.pid_dir, name).write_text(str(proc.pid))
        _restart_count_file(self.cfg.pid_dir, name).write_text("0")
        _log("INFO", f"started {name} pid={proc.pid} log={logf}")

    def _stop_proc(self, name: str) -> None:
        pf = _pid_file(self.cfg.pid_dir, name)
        if not pf.exists():
            _log("INFO", f"{name} not running (no pidfile)")
            return
        pid = _read_pid(self.cfg.pid_dir, name)
        if pid is None:
            pf.unlink(missing_ok=True)
            return

        if _is_alive(pid):
            _log("INFO", f"stopping {name} pid={pid}")
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            waited = 0
            while _is_alive(pid) and waited < STOP_WAIT_SECONDS:
                time.sleep(1)
                waited += 1
            if _is_alive(pid):
                _log("WARN", f"{name} pid={pid} did not exit after {STOP_WAIT_SECONDS}s, sending SIGKILL")
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            _log("INFO", f"stopped {name} pid={pid}")
        else:
            _log("INFO", f"{name} pid={pid} already exited")

        pf.unlink(missing_ok=True)
        _restart_count_file(self.cfg.pid_dir, name).unlink(missing_ok=True)

    def _status_proc(self, name: str) -> ProcessStatus:
        rcf = _restart_count_file(self.cfg.pid_dir, name)
        restarts = 0
        if rcf.exists():
            try:
                restarts = int(rcf.read_text().strip())
            except (ValueError, OSError):
                pass

        if not proc_enabled(name, self.cfg.leader_agent, self.cfg.claude_lanes, self.cfg.mcp_auto_manager_active):
            return ProcessStatus(name, "disabled", None, restarts, "unknown", "no_tasks")

        pid = _read_pid(self.cfg.pid_dir, name)

        heartbeat_status = "unknown"
        task_activity = "no_tasks"

        # Query orchestrator for heartbeat and task activity if it's an agent process.
        _proc_to_agent_base_name = {
            "manager": self.cfg.leader_agent,
            "claude": "claude_code",
            "claude_2": "claude_code",
            "claude_3": "claude_code",
            "codex_worker": "codex",
            "wingman": self.cfg.wingman_agent,
            "gemini": "gemini",
        }

        agent_base_name = _proc_to_agent_base_name.get(name)
        if agent_base_name: # Only proceed if it's a known agent process
            # Determine the specific instance_id for this process
            lane = "wingman" if name == "wingman" else "default"
            target_instance_id = _get_instance_id(name, lane)

            agent_info = next(
                (a for a in self.orchestrator.list_agents(active_only=False)
                 if a.get("agent") == agent_base_name and a.get("instance_id") == target_instance_id),
                None,
            )
            if agent_info:
                heartbeat_status = "active" if agent_info.get("status") == "active" else "stale"
                task_counts = agent_info.get("task_counts", {})
                if (task_counts.get("in_progress", 0) > 0 or
                    task_counts.get("assigned", 0) > 0 or
                    task_counts.get("blocked", 0) > 0 or
                    task_counts.get("reported", 0) > 0):
                    task_activity = "working"
                else:
                    task_activity = "idle"
        elif name == "watchdog":
            # Watchdog is a monitoring process, not an agent — derive status
            # from process liveness rather than orchestrator heartbeat.
            watchdog_pid = _read_pid(self.cfg.pid_dir, name)
            if watchdog_pid is not None and _is_alive(watchdog_pid):
                heartbeat_status = "active"
                task_activity = "monitoring"
            else:
                heartbeat_status = "n/a"
                task_activity = "idle"


        # Detect stale leader heartbeat: process alive but agent heartbeat not active.
        leader_heartbeat_stale = False
        if name == "manager" and heartbeat_status in ("stale", "unknown"):
            # The leader process may be running but its orchestrator heartbeat
            # can lag between manager cycles.  Flag this explicitly so status
            # consumers can surface a remediation hint.
            if pid is not None and _is_alive(pid):
                leader_heartbeat_stale = True

        # Read capacity error streak for gemini workers
        capacity_errors = 0
        if name == "gemini":
            cef = _capacity_error_file(self.cfg.pid_dir, name)
            if cef.exists():
                try:
                    capacity_errors = int(cef.read_text().strip())
                except (ValueError, OSError):
                    pass
            if capacity_errors > 0 and task_activity not in ("working", "blocked"):
                task_activity = "capacity_degraded"

        if pid is None:
            return ProcessStatus(name, "stopped", None, restarts, heartbeat_status, task_activity, capacity_errors)
        if _is_alive(pid):
            return ProcessStatus(name, "running", pid, restarts, heartbeat_status, task_activity, capacity_errors, leader_heartbeat_stale)
        return ProcessStatus(name, "dead", pid, restarts, heartbeat_status, task_activity, capacity_errors)

    def _get_agent_display_info(self, name: str) -> Dict[str, str]:
        info: Dict[str, str] = {"role": "N/A", "type": "N/A", "model": "N/A"}

        if name == "manager":
            info["role"] = "Leader/Manager"
            info["type"] = self.cfg.leader_agent
        elif name in ("claude", "claude_2", "claude_3"):
            lane_label = name.replace("claude_", "lane ") if "_" in name else "lane 1"
            info["role"] = f"Claude worker ({lane_label})"
            info["type"] = "claude"
            info["model"] = "claude-v3"
        elif name == "gemini":
            info["role"] = "Gemini worker"
            info["type"] = "gemini"
            info["model"] = self.cfg.gemini_model
        elif name == "wingman":
            info["role"] = "Claude-backed wingman/reviewer"
            info["type"] = self.cfg.wingman_agent
            info["model"] = "claude-v3"
        elif name == "codex_worker":
            info["role"] = "Codex worker"
            info["type"] = "codex"
        else:
            # Check for extra workers
            for ew in self.cfg.extra_workers:
                if ew.name == name:
                    info["role"] = f"Extra worker (lane: {ew.lane}, cli: {ew.cli})"
                    info["type"] = ew.agent
                    break
        return info

    # -- public actions -----------------------------------------------------

    def start(self) -> None:
        """Start all enabled processes, tearing down disabled ones."""
        os.makedirs(self.cfg.log_dir, exist_ok=True)
        os.makedirs(self.cfg.pid_dir, exist_ok=True)
        _log("INFO", f"starting all processes (project={self.cfg.project_root})")
        for name in self._procs:
            if proc_enabled(name, self.cfg.leader_agent, self.cfg.claude_lanes, self.cfg.mcp_auto_manager_active):
                self._start_proc(name)
            else:
                self._stop_proc(name)
        print(f"Supervisor started. PID dir: {self.cfg.pid_dir}")
        print("Check status: supervisor.sh status")

    def stop(self) -> None:
        """Stop all processes."""
        _log("INFO", "stopping all processes")
        for name in self._procs:
            self._stop_proc(name)
        print("All processes stopped.")

    def status(self) -> List[ProcessStatus]:
        """Return status for every managed process and print a table."""
        print("Autopilot supervisor status")
        print(f"Project: {self.cfg.project_root}")
        print(f"PID dir: {self.cfg.pid_dir}")
        print(f"Log dir: {self.cfg.log_dir}")
        print()
        print(
            f"{'Process':<15} {'State':<10} {'PID':<8} {'Restarts':<10} {'Heartbeat':<10} {'Activity':<18} "
            f"{'CapErr':<7} {'Role':<30} {'Type':<15} {'Model':<20}"
        )
        print("-" * 150) # Separator line
        results = []
        for name in self._procs:
            ps = self._status_proc(name)
            display_info = self._get_agent_display_info(name)
            results.append(ps)
            pid_str = str(ps.pid) if ps.pid is not None else "-"
            cap_str = str(ps.capacity_errors) if ps.capacity_errors > 0 else "-"
            print(
                f"{ps.name:<15} {ps.state:<10} {pid_str:<8} {ps.restarts:<10} {ps.heartbeat_status:<10} {ps.task_activity:<18} "
                f"{cap_str:<7} {display_info['role']:<30} {display_info['type']:<15} {display_info['model']:<20}"
            )
        return results

    def restart(self) -> None:
        """Stop then start."""
        self.stop()
        time.sleep(1)
        self.start()

    def clean(self) -> None:
        """Remove stale PID files and supervisor logs."""
        cleaned = 0
        pid_path = Path(self.cfg.pid_dir)
        if pid_path.is_dir():
            for name in self._procs:
                pf = _pid_file(self.cfg.pid_dir, name)
                if pf.exists():
                    pid = _read_pid(self.cfg.pid_dir, name)
                    if pid is None or not _is_alive(pid):
                        pf.unlink(missing_ok=True)
                        _restart_count_file(self.cfg.pid_dir, name).unlink(missing_ok=True)
                        _log("INFO", f"removed stale pidfile for {name} (pid={pid})")
                        cleaned += 1
                    else:
                        _log("WARN", f"{name} is still running (pid={pid}) -- stop it first")
            # Remove dir if empty.
            try:
                pid_path.rmdir()
            except OSError:
                pass

        log_path = Path(self.cfg.log_dir)
        if log_path.is_dir():
            sv_logs = list(log_path.glob("supervisor-*.log"))
            if sv_logs:
                for lf in sv_logs:
                    lf.unlink(missing_ok=True)
                _log("INFO", f"removed {len(sv_logs)} supervisor log file(s)")
                cleaned += len(sv_logs)

        if cleaned == 0:
            print("Nothing to clean.")
        else:
            print(f"Cleaned {cleaned} file(s).")

    def monitor(self, interval: int = 30) -> None:
        """Continuously check for dead processes and restart them.

        Includes a circuit breaker: if total restarts across ALL processes
        exceed ``max_restarts * num_enabled_processes`` within a 10-minute
        rolling window, the supervisor stops all processes and emits a
        ``swarm.circuit_breaker`` event to prevent infinite restart loops.
        """

        _log("INFO", f"Starting supervisor monitor loop (interval={interval}s)")

        # Circuit breaker state: list of (timestamp, process_name) for recent restarts.
        _circuit_breaker_window: list = []
        _CIRCUIT_BREAKER_WINDOW_SECONDS = 600  # 10 minutes

        # Health checkpoint state
        _last_health_checkpoint: float = time.time()
        _HEALTH_CHECKPOINT_INTERVAL = 900  # 15 minutes

        try:
            while True:
                now = time.time()

                # -- Health checkpoint (Fix 15) --------------------------------
                if now - _last_health_checkpoint >= _HEALTH_CHECKPOINT_INTERVAL:
                    self._emit_health_checkpoint(_circuit_breaker_window)
                    _last_health_checkpoint = now

                # -- Prune stale circuit breaker entries ------------------------
                _circuit_breaker_window = [
                    (ts, pname) for ts, pname in _circuit_breaker_window
                    if now - ts < _CIRCUIT_BREAKER_WINDOW_SECONDS
                ]

                for name in self._procs:
                    if not proc_enabled(name, self.cfg.leader_agent, self.cfg.claude_lanes, self.cfg.mcp_auto_manager_active):
                        continue

                    ps = self._status_proc(name)
                    if ps.state == "dead":
                        # Skip restart if token budget is exhausted and window is still active.
                        if _is_budget_window_active(self.cfg.pid_dir, name):
                            _log("INFO", f"Skipping restart of {name}: token budget exhausted, waiting for next window")
                            continue
                        # Clear any expired budget marker before restarting.
                        bef = _budget_exhaustion_file(self.cfg.pid_dir, name)
                        if bef.exists():
                            bef.unlink(missing_ok=True)
                            _log("INFO", f"Budget window expired for {name}, cleared marker — allowing restart")
                        _log("WARN", f"Detected dead process: {name} (pid={ps.pid})")
                        if ps.restarts < self.cfg.max_restarts:
                            # -- Circuit breaker check -------------------------
                            num_enabled = sum(
                                1 for p in self._procs
                                if proc_enabled(p, self.cfg.leader_agent, self.cfg.claude_lanes, self.cfg.mcp_auto_manager_active)
                            )
                            cb_threshold = self.cfg.max_restarts * num_enabled
                            if len(_circuit_breaker_window) >= cb_threshold:
                                _log("ERROR",
                                     f"CIRCUIT BREAKER: {len(_circuit_breaker_window)} total restarts "
                                     f"in {_CIRCUIT_BREAKER_WINDOW_SECONDS}s (threshold={cb_threshold}). "
                                     f"Stopping all processes.")
                                try:
                                    self.orchestrator.publish_event(
                                        event_type="swarm.circuit_breaker",
                                        source="supervisor",
                                        payload={
                                            "total_restarts": len(_circuit_breaker_window),
                                            "threshold": cb_threshold,
                                            "window_seconds": _CIRCUIT_BREAKER_WINDOW_SECONDS,
                                            "recent_restarts": [
                                                {"timestamp": ts, "process": pn}
                                                for ts, pn in _circuit_breaker_window[-10:]
                                            ],
                                        },
                                    )
                                except Exception:
                                    pass
                                self.stop()
                                return

                            # Calculate backoff: base * (2 ^ restarts)
                            delay = min(self.cfg.backoff_base * (2 ** ps.restarts), self.cfg.backoff_max)
                            _log("INFO", f"Restarting {name} in {delay}s (restart count={ps.restarts + 1}/{self.cfg.max_restarts})")
                            time.sleep(delay)

                            self._start_proc(name)
                            # Increment restart count
                            new_count = ps.restarts + 1
                            _restart_count_file(self.cfg.pid_dir, name).write_text(str(new_count))
                            _circuit_breaker_window.append((time.time(), name))
                        else:
                            _log(
                                "ERROR",
                                f"Process {name} reached max restarts ({self.cfg.max_restarts}). Manual intervention required."
                            )

                time.sleep(interval)
        except KeyboardInterrupt:
            _log("INFO", "Monitor loop stopped by user.")

    # -- health checkpoint --------------------------------------------------

    def _emit_health_checkpoint(self, recent_restarts: list = None) -> None:
        """Emit a ``swarm.health_checkpoint`` event with current swarm health summary.

        Called every 15 minutes from the monitor loop for overnight diagnostics.
        """
        if recent_restarts is None:
            recent_restarts = []
        try:
            processes_alive = 0
            processes_dead = 0
            total_restarts = 0
            for name in self._procs:
                if not proc_enabled(name, self.cfg.leader_agent, self.cfg.claude_lanes, self.cfg.mcp_auto_manager_active):
                    continue
                ps = self._status_proc(name)
                if ps.state == "running":
                    processes_alive += 1
                elif ps.state in ("dead", "stopped"):
                    processes_dead += 1
                total_restarts += ps.restarts

            # Gather task status counts from orchestrator.
            tasks_by_status: Dict[str, int] = {}
            try:
                tasks = self.orchestrator.list_tasks()
                for t in tasks:
                    status = str(t.get("status", "unknown"))
                    tasks_by_status[status] = tasks_by_status.get(status, 0) + 1
            except Exception:
                pass

            # Budget remaining: check if any budget markers exist.
            budget_remaining = True
            for name in self._procs:
                if _is_budget_window_active(self.cfg.pid_dir, name):
                    budget_remaining = False
                    break

            uptime_seconds = 0
            supervisor_pid_file = _pid_file(self.cfg.pid_dir, "supervisor")
            if supervisor_pid_file.exists():
                try:
                    uptime_seconds = int(time.time() - supervisor_pid_file.stat().st_mtime)
                except OSError:
                    pass

            payload = {
                "processes_alive": processes_alive,
                "processes_dead": processes_dead,
                "tasks_by_status": tasks_by_status,
                "budget_remaining": budget_remaining,
                "uptime_seconds": uptime_seconds,
                "total_restarts": total_restarts,
                "recent_restart_count": len(recent_restarts),
            }
            self.orchestrator.publish_event(
                event_type="swarm.health_checkpoint",
                source="supervisor",
                payload=payload,
            )
            _log("INFO",
                 f"health checkpoint: alive={processes_alive} dead={processes_dead} "
                 f"restarts={total_restarts} tasks={tasks_by_status}")
        except Exception as e:
            _log("WARN", f"health checkpoint failed: {e}")

    # -- JSON-friendly status for MCP tools ---------------------------------

    def status_json(self) -> List[Dict]:
        """Return status as a list of dicts (no stdout side effects)."""
        results = []
        for name in self._procs:
            ps = self._status_proc(name)
            display = self._get_agent_display_info(name)
            entry = {
                "name": ps.name,
                "state": ps.state,
                "pid": ps.pid,
                "restarts": ps.restarts,
                "heartbeat_status": ps.heartbeat_status,
                "task_activity": ps.task_activity,
                "role": display["role"],
                "model": display["model"],
            }
            # Derive the agent name used for orchestrator lookups.
            agent_name_for_orch = None
            if name == "manager":
                agent_name_for_orch = self.cfg.leader_agent
            elif name in ("claude", "claude_2", "claude_3"):
                agent_name_for_orch = "claude_code"
            elif name == "wingman":
                agent_name_for_orch = self.cfg.wingman_agent
            elif name == "gemini":
                agent_name_for_orch = name
            elif name == "codex_worker":
                agent_name_for_orch = "codex"
            else:
                # Check for extra workers
                for ew in self.cfg.extra_workers:
                    if ew.name == name:
                        agent_name_for_orch = ew.agent
                        break

            # If an agent name is determined, try to get instance_id from orchestrator.
            if agent_name_for_orch:
                agent_info = next(
                    (a for a in self.orchestrator.list_agents(active_only=False) if a.get("agent") == agent_name_for_orch),
                    None,
                )
                if agent_info and agent_info.get("instance_id"):
                    entry["instance_id"] = agent_info["instance_id"]
                else:
                    # Fallback if orchestrator doesn't have it or for non-agent processes
                    entry["instance_id"] = _get_instance_id(name)
            else:
                # Fallback for processes that are not agents (e.g. watchdog)
                entry["instance_id"] = _get_instance_id(name)

            if ps.capacity_errors > 0:
                entry["capacity_errors"] = ps.capacity_errors
            if ps.leader_heartbeat_stale:
                entry["leader_heartbeat_stale"] = True
            if agent_name_for_orch: # Add this line
                entry["agent"] = agent_name_for_orch # Add this line
            results.append(entry)
        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_extra_worker(spec: str) -> ExtraWorker:
    parts = spec.split(":")
    if len(parts) < 5:
        raise argparse.ArgumentTypeError(
            f"invalid --extra-worker spec '{spec}': expected name:cli:agent:team_id:project_root[:lane]"
        )
    lane = parts[5] if len(parts) > 5 else "default"
    return ExtraWorker(
        name=parts[0], cli=parts[1], agent=parts[2],
        team_id=parts[3], project_root=parts[4], lane=lane,
    )


_VALID_ACTIONS = ("start", "stop", "status", "restart", "clean", "monitor")


def build_config_from_args(argv: Sequence[str] | None = None) -> Tuple[str, SupervisorConfig]:
    """Parse CLI args and return ``(action, config)``."""
    parser = argparse.ArgumentParser(
        description="Autopilot process supervisor",
        usage="%(prog)s {start|stop|status|restart|clean|monitor} [options]",
    )
    parser.add_argument("action", nargs="?")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--log-dir", default="")
    parser.add_argument("--pid-dir", default="")
    parser.add_argument("--manager-cli-timeout", type=int, default=300)
    parser.add_argument("--worker-cli-timeout", type=int, default=600)
    parser.add_argument("--manager-interval", type=int, default=20)
    parser.add_argument("--worker-interval", type=int, default=25)
    parser.add_argument("--idle-backoff", default="30,60,120,300,900")
    parser.add_argument("--max-idle-cycles", type=int, default=0)
    parser.add_argument("--daily-call-budget", type=int, default=0)
    parser.add_argument("--event-driven", action="store_true")
    parser.add_argument("--low-burn", dest="low_burn", action="store_true")
    parser.add_argument("--high-throughput", dest="low_burn", action="store_false")
    parser.set_defaults(low_burn=True)
    parser.add_argument("--leader-agent", default="codex")
    parser.add_argument("--leader-cli", default="")
    parser.add_argument("--wingman-agent", default="ccm")
    parser.add_argument("--wingman-cli", default="claude")
    parser.add_argument("--claude-project-root", default="")
    parser.add_argument("--gemini-project-root", default="")
    parser.add_argument("--codex-project-root", default="")
    parser.add_argument("--wingman-project-root", default="")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash")
    parser.add_argument("--gemini-fallback-model", default="")
    parser.add_argument("--gemini-capacity-retries", type=int, default=2)
    parser.add_argument("--gemini-capacity-backoff", type=int, default=15)
    parser.add_argument("--claude-lanes", type=int, default=3,
                        help="Number of parallel Claude worker lanes (1-3)")
    parser.add_argument("--claude-team-id", default="")
    parser.add_argument("--gemini-team-id", default="")
    parser.add_argument("--codex-team-id", default="")
    parser.add_argument("--wingman-team-id", default="")
    parser.add_argument("--extra-worker", action="append", default=[], type=_parse_extra_worker)
    parser.add_argument("--daily-token-budget", type=int, default=0,
                        help="Hard daily token ceiling. 0 disables.")
    parser.add_argument("--hourly-token-budget", type=int, default=0,
                        help="Hard hourly token ceiling. 0 disables.")
    parser.add_argument("--tokens-per-call", type=int, default=10000,
                        help="Estimated tokens per CLI call (default: 10000).")
    parser.add_argument("--max-restarts", type=int, default=5)
    parser.add_argument("--backoff-base", type=int, default=10)
    parser.add_argument("--backoff-max", type=int, default=120)
    parser.add_argument("--monitor-interval", type=int, default=30)

    args = parser.parse_args(argv)
    cfg = SupervisorConfig(
        project_root=args.project_root,
        log_dir=args.log_dir,
        pid_dir=args.pid_dir,
        manager_cli_timeout=args.manager_cli_timeout,
        worker_cli_timeout=args.worker_cli_timeout,
        manager_interval=args.manager_interval,
        worker_interval=args.worker_interval,
        idle_backoff=args.idle_backoff,
        max_idle_cycles=args.max_idle_cycles,
        daily_call_budget=args.daily_call_budget,
        daily_token_budget=args.daily_token_budget,
        hourly_token_budget=args.hourly_token_budget,
        tokens_per_call=args.tokens_per_call,
        event_driven=args.event_driven,
        low_burn=args.low_burn,
        leader_agent=args.leader_agent,
        leader_cli=args.leader_cli,
        wingman_agent=args.wingman_agent,
        wingman_cli=args.wingman_cli,
        claude_project_root=args.claude_project_root,
        gemini_project_root=args.gemini_project_root,
        codex_project_root=args.codex_project_root,
        wingman_project_root=args.wingman_project_root,
        gemini_model=args.gemini_model,
        gemini_fallback_model=args.gemini_fallback_model,
        gemini_capacity_retries=args.gemini_capacity_retries,
        gemini_capacity_backoff=args.gemini_capacity_backoff,
        claude_lanes=max(1, min(3, args.claude_lanes)),
        claude_team_id=args.claude_team_id,
        gemini_team_id=args.gemini_team_id,
        codex_team_id=args.codex_team_id,
        wingman_team_id=args.wingman_team_id,
        extra_workers=args.extra_worker,
        max_restarts=args.max_restarts,
        backoff_base=args.backoff_base,
        backoff_max=args.backoff_max,
    )
    # Patch monitor interval into cfg if we want to store it there,
    # but for now we'll just return it as a local var or use a custom action.
    # To keep it simple, I'll pass it to main.
    setattr(cfg, "monitor_interval", args.monitor_interval)
    return args.action, cfg


def _print_usage() -> None:
    prog = "scripts/autopilot/supervisor.sh"
    print(f"Usage: {prog} {{start|stop|status|restart|clean|monitor}} [options]")
    print()
    print("Commands:")
    print("  start    Start all autopilot processes")
    print("  stop     Stop all running processes")
    print("  status   Show process status")
    print("  restart  Stop then start all processes")
    print("  clean    Remove stale pid files and supervisor logs")
    print("  monitor  Watch for dead processes and restart them")
    print()
    print("Visibility:")
    print("  ./scripts/autopilot/headless_status.sh --once")
    print("  ./scripts/autopilot/headless_status.sh --watch --interval 10")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point — mirrors ``supervisor.sh`` behaviour."""
    action, cfg = build_config_from_args(argv)

    if action not in _VALID_ACTIONS:
        _print_usage()
        return 1

    # Initialize policy and orchestrator
    policy_path = Path(cfg.project_root) / "config" / "policy.balanced.json"
    if not policy_path.exists():
        _log("WARN", f"Policy file not found: {policy_path}. This may lead to unexpected behavior.")
        # Attempt to load a default policy without a file path if not found,
        # or handle this error more gracefully based on project conventions.
        # For now, we'll let Policy.load() fail if it strictly requires a file.
        # Alternatively, we could create a dummy Policy object here.
        # Given the orchestrator.policy.py, it expects a path.
        # Let's assume for now that if it doesn't exist, it's an error.
        raise FileNotFoundError(f"Policy file not found: {policy_path}")

    policy = Policy.load(path=policy_path)

    orchestrator = Orchestrator(root=Path(cfg.project_root), policy=policy)

    sup = Supervisor(cfg, orchestrator)
    dispatch = {
        "start": sup.start,
        "stop": sup.stop,
        "status": sup.status,
        "restart": sup.restart,
        "clean": sup.clean,
        "monitor": lambda: sup.monitor(interval=getattr(cfg, "monitor_interval", 30)),
    }
    dispatch[action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
