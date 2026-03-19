"""Process supervisor for headless autopilot loops.

Manages background agent processes (manager, workers, watchdog) with PID-file
tracking, topology-aware enablement, and graceful shutdown.  Designed to be
called from the thin shell wrapper ``scripts/autopilot/supervisor.sh`` or
directly via ``python3 -m orchestrator.supervisor``.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

# Default process names in canonical order.
_BASE_PROCS = ("manager", "wingman", "claude", "gemini", "codex_worker", "watchdog")

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
    max_idle_cycles: int = 0
    daily_call_budget: int = 0
    event_driven: bool = False
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
    claude_team_id: str = ""
    gemini_team_id: str = ""
    codex_team_id: str = ""
    wingman_team_id: str = ""
    extra_workers: List[ExtraWorker] = field(default_factory=list)
    max_restarts: int = 5
    backoff_base: int = 10
    backoff_max: int = 120
    # Resolved at finalise time.
    repo_root: str = ""

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

def proc_enabled(name: str, leader_agent: str) -> bool:
    """Return whether *name* should run given *leader_agent*."""
    if name == "claude":
        return leader_agent != "claude_code"
    if name == "gemini":
        return leader_agent != "gemini"
    if name == "codex_worker":
        return leader_agent != "codex"
    return True


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

def proc_cmd(name: str, cfg: SupervisorConfig,
             extra_names: Sequence[str] = (),
             extra_cmds: Sequence[str] = ()) -> str:
    """Return the shell command string for *name*."""
    # Check extras first.
    for i, ename in enumerate(extra_names):
        if ename == name:
            return extra_cmds[i]

    root = cfg.repo_root
    scripts = f"{root}/scripts/autopilot"

    def _team_arg(tid: str) -> str:
        return f" --team-id {tid}" if tid else ""

    def _event_driven_arg() -> str:
        return " --event-driven" if cfg.event_driven else ""

    if name == "manager":
        return (
            f"{scripts}/manager_loop.sh"
            f" --cli {cfg.leader_cli}"
            f" --leader-agent {cfg.leader_agent}"
            f" --project-root {cfg.project_root}"
            f" --interval {cfg.manager_interval}"
            f" --cli-timeout {cfg.manager_cli_timeout}"
            f" --log-dir {cfg.log_dir}"
            f" --idle-backoff {cfg.idle_backoff}"
            f" --max-idle-cycles {cfg.max_idle_cycles}"
            f" --daily-call-budget {cfg.daily_call_budget}"
        )
    if name == "wingman":
        return (
            f"{scripts}/worker_loop.sh"
            f" --cli {cfg.wingman_cli}"
            f" --agent {cfg.wingman_agent}"
            f" --lane wingman{_team_arg(cfg.wingman_team_id)}"
            f" --project-root {cfg.wingman_project_root}"
            f" --interval {cfg.worker_interval}"
            f" --cli-timeout {cfg.worker_cli_timeout}"
            f" --log-dir {cfg.log_dir}"
            f" --idle-backoff {cfg.idle_backoff}"
            f" --max-idle-cycles {cfg.max_idle_cycles}"
            f" --daily-call-budget {cfg.daily_call_budget}"
            f"{_event_driven_arg()}"
        )
    if name == "claude":
        return (
            f"{scripts}/worker_loop.sh"
            f" --cli claude --agent claude_code{_team_arg(cfg.claude_team_id)}"
            f" --project-root {cfg.claude_project_root}"
            f" --interval {cfg.worker_interval}"
            f" --cli-timeout {cfg.worker_cli_timeout}"
            f" --log-dir {cfg.log_dir}"
            f" --idle-backoff {cfg.idle_backoff}"
            f" --max-idle-cycles {cfg.max_idle_cycles}"
            f" --daily-call-budget {cfg.daily_call_budget}"
            f"{_event_driven_arg()}"
        )
    if name == "gemini":
        model_env = f"ORCHESTRATOR_GEMINI_MODEL={cfg.gemini_model} " if cfg.gemini_model else ""
        return (
            f"{model_env}{scripts}/worker_loop.sh"
            f" --cli gemini --agent gemini{_team_arg(cfg.gemini_team_id)}"
            f" --project-root {cfg.gemini_project_root}"
            f" --interval {cfg.worker_interval}"
            f" --cli-timeout {cfg.worker_cli_timeout}"
            f" --log-dir {cfg.log_dir}"
            f" --idle-backoff {cfg.idle_backoff}"
            f" --max-idle-cycles {cfg.max_idle_cycles}"
            f" --daily-call-budget {cfg.daily_call_budget}"
            f"{_event_driven_arg()}"
        )
    if name == "codex_worker":
        return (
            f"{scripts}/worker_loop.sh"
            f" --cli codex --agent codex{_team_arg(cfg.codex_team_id)}"
            f" --project-root {cfg.codex_project_root}"
            f" --interval {cfg.worker_interval}"
            f" --cli-timeout {cfg.worker_cli_timeout}"
            f" --log-dir {cfg.log_dir}"
            f" --idle-backoff {cfg.idle_backoff}"
            f" --max-idle-cycles {cfg.max_idle_cycles}"
            f" --daily-call-budget {cfg.daily_call_budget}"
            f"{_event_driven_arg()}"
        )
    if name == "watchdog":
        return (
            f"{scripts}/watchdog_loop.sh"
            f" --project-root {cfg.project_root}"
            f" --interval 15"
            f" --log-dir {cfg.log_dir}"
        )
    raise ValueError(f"unknown process name: {name}")


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

@dataclass
class ProcessStatus:
    name: str
    state: str  # running | stopped | dead | disabled
    pid: Optional[int]
    restarts: int


class Supervisor:
    """Headless process supervisor — Python equivalent of supervisor.sh."""

    def __init__(self, cfg: SupervisorConfig) -> None:
        cfg.finalise()
        self.cfg = cfg
        # Register extra workers.
        self._extra_names: List[str] = []
        self._extra_cmds: List[str] = []
        self._procs: List[str] = list(_BASE_PROCS)
        self._register_extras()

    # -- extra worker registration ------------------------------------------

    def _register_extras(self) -> None:
        scripts = f"{self.cfg.repo_root}/scripts/autopilot"
        for ew in self.cfg.extra_workers:
            if ew.name in self._extra_names or ew.name in _BASE_PROCS:
                raise ValueError(f"duplicate process name: {ew.name}")
            if ew.lane not in ("default", "wingman"):
                raise ValueError(f"invalid lane '{ew.lane}' for extra worker '{ew.name}'")
            cmd = (
                f"{scripts}/worker_loop.sh"
                f" --cli {ew.cli} --agent {ew.agent}"
                f" --lane {ew.lane} --team-id {ew.team_id}"
                f" --project-root {ew.project_root}"
                f" --interval {self.cfg.worker_interval}"
                f" --cli-timeout {self.cfg.worker_cli_timeout}"
                f" --log-dir {self.cfg.log_dir}"
                f" --idle-backoff {self.cfg.idle_backoff}"
                f" --max-idle-cycles {self.cfg.max_idle_cycles}"
                f" --daily-call-budget {self.cfg.daily_call_budget}"
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
        if not proc_enabled(name, self.cfg.leader_agent):
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

        if not proc_enabled(name, self.cfg.leader_agent):
            return ProcessStatus(name, "disabled", None, restarts)

        pid = _read_pid(self.cfg.pid_dir, name)
        if pid is None:
            return ProcessStatus(name, "stopped", None, restarts)
        if _is_alive(pid):
            return ProcessStatus(name, "running", pid, restarts)
        return ProcessStatus(name, "dead", pid, restarts)

    def _get_agent_display_info(self, name: str) -> Dict[str, str]:
        info: Dict[str, str] = {"role": "N/A", "type": "N/A", "model": "N/A"}

        if name == "manager":
            info["role"] = "leader/manager"
            info["type"] = self.cfg.leader_agent
        elif name == "claude":
            info["role"] = "main Claude implementation worker"
            info["type"] = "claude_code"
            # Assuming a default model if not explicitly configured in the future
            info["model"] = "claude-v3" 
        elif name == "gemini":
            info["role"] = "Gemini worker"
            info["type"] = "gemini"
            info["model"] = self.cfg.gemini_model
        elif name == "wingman":
            info["role"] = "Claude-backed wingman/reviewer lane"
            info["type"] = self.cfg.wingman_agent
            info["model"] = "claude-v3" # Assuming a default model
        elif name == "codex_worker":
            info["role"] = "codex worker"
            info["type"] = "codex"
        else:
            # Check for extra workers
            for ew in self.cfg.extra_workers:
                if ew.name == name:
                    info["role"] = f"extra worker ({ew.lane} lane)"
                    info["type"] = ew.agent
                    # Model not typically specified for extra workers via current config
                    break
        return info

    # -- public actions -----------------------------------------------------

    def start(self) -> None:
        """Start all enabled processes, tearing down disabled ones."""
        os.makedirs(self.cfg.log_dir, exist_ok=True)
        os.makedirs(self.cfg.pid_dir, exist_ok=True)
        _log("INFO", f"starting all processes (project={self.cfg.project_root})")
        for name in self._procs:
            if proc_enabled(name, self.cfg.leader_agent):
                self._start_proc(name)
            else:
                self._stop_proc(name)
        print(f"Supervisor started. PID dir: {self.cfg.pid_dir}")
        print(f"Check status: supervisor.sh status")

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
        print(f"{'Process':<15} {'State':<10} {'PID':<8} {'Restarts':<10} {'Role':<30} {'Type':<15} {'Model':<20}")
        print("-" * 110) # Separator line
        results = []
        for name in self._procs:
            ps = self._status_proc(name)
            display_info = self._get_agent_display_info(name)
            results.append(ps)
            pid_str = str(ps.pid) if ps.pid is not None else "-"
            print(
                f"{ps.name:<15} {ps.state:<10} {pid_str:<8} {ps.restarts:<10} "
                f"{display_info['role']:<30} {display_info['type']:<15} {display_info['model']:<20}"
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
        """Continuously check for dead processes and restart them."""
        _log("INFO", f"Starting supervisor monitor loop (interval={interval}s)")
        try:
            while True:
                for name in self._procs:
                    if not proc_enabled(name, self.cfg.leader_agent):
                        continue
                    
                    ps = self._status_proc(name)
                    if ps.state == "dead":
                        _log("WARN", f"Detected dead process: {name} (pid={ps.pid})")
                        if ps.restarts < self.cfg.max_restarts:
                            # Calculate backoff: base * (2 ^ restarts)
                            delay = min(self.cfg.backoff_base * (2 ** ps.restarts), self.cfg.backoff_max)
                            _log("INFO", f"Restarting {name} in {delay}s (restart count={ps.restarts + 1}/{self.cfg.max_restarts})")
                            time.sleep(delay)
                            
                            self._start_proc(name)
                            # Increment restart count
                            new_count = ps.restarts + 1
                            _restart_count_file(self.cfg.pid_dir, name).write_text(str(new_count))
                        else:
                            _log(
                                "ERROR", 
                                f"Process {name} reached max restarts ({self.cfg.max_restarts}). Manual intervention required."
                            )
                
                time.sleep(interval)
        except KeyboardInterrupt:
            _log("INFO", "Monitor loop stopped by user.")

    # -- JSON-friendly status for MCP tools ---------------------------------

    def status_json(self) -> List[Dict]:
        """Return status as a list of dicts (no stdout side effects)."""
        results = []
        for name in self._procs:
            ps = self._status_proc(name)
            results.append({
                "name": ps.name,
                "state": ps.state,
                "pid": ps.pid,
                "restarts": ps.restarts,
            })
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
    parser.add_argument("--claude-team-id", default="")
    parser.add_argument("--gemini-team-id", default="")
    parser.add_argument("--codex-team-id", default="")
    parser.add_argument("--wingman-team-id", default="")
    parser.add_argument("--extra-worker", action="append", default=[], type=_parse_extra_worker)
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

    sup = Supervisor(cfg)
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
