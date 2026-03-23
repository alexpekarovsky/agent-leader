"""Persistent worker sessions — eliminate CLI cold-start per task.

Instead of spawning a fresh CLI process per task cycle, the persistent worker:
1. Maintains a long-running Python process with hot orchestrator connection
2. Claims tasks directly via the orchestrator engine (no MCP round-trip)
3. Dispatches task execution to the CLI with a stripped-down prompt
4. Watches a signal file for new task notifications when idle
5. Chains consecutive tasks without inter-cycle sleep

Falls back to legacy spawn-per-cycle on repeated failures.
"""
from __future__ import annotations

import importlib
import json
import os
import signal as signal_mod
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# Store original time.strftime for use in mocks that need to call the original.
_original_time_strftime = time.strftime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PersistentWorkerConfig:
    """All tunables for the persistent worker."""

    cli: str = ""
    agent: str = ""
    lane: str = "default"
    team_id: str = ""
    instance_id: str = ""
    project_root: str = ""
    repo_root: str = ""
    log_dir: str = ""
    pid_dir: str = ""
    process_name: str = ""
    cli_timeout: int = 600
    max_consecutive_failures: int = 3
    signal_poll_interval: int = 2
    signal_max_wait: int = 300
    heartbeat_interval: int = 60
    idle_backoff: str = "30,60,120,300,900"
    max_idle_cycles: int = 200
    max_tasks_per_session: int = 0  # 0 = unlimited; restart after N tasks to bound memory.
    daily_call_budget: int = 100
    daily_token_budget: int = 0
    hourly_token_budget: int = 0
    tokens_per_call: int = 10000

    def finalise(self) -> None:
        """Fill in derived defaults."""
        if not self.repo_root:
            self.repo_root = str(Path(__file__).resolve().parents[1])
        if not self.project_root:
            self.project_root = self.repo_root
        if not self.log_dir:
            self.log_dir = os.path.join(self.project_root, ".autopilot-logs")
        if not self.pid_dir:
            self.pid_dir = os.path.join(self.project_root, ".autopilot-pids")
        if not self.process_name:
            self.process_name = self.agent
        if not self.instance_id:
            self.instance_id = f"{self.agent}#headless-{self.lane}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_AGENTS = {
    "codex": ["codex"],
    "claude": ["claude_code", "ccm"],
    "gemini": ["gemini"],
}


def _log(level: str, msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"[{ts}] [{level}] {msg}", file=sys.stderr, flush=True)


def _signal_file(project_root: str, agent: str) -> Path:
    return Path(project_root) / "state" / f".wakeup-{agent}"


def _build_cli_cmd(cli: str, project_root: str, env: dict) -> List[str]:
    """Build the CLI command list for a given tool."""
    if cli == "codex":
        return ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox",
                "-C", project_root, "-"]
    if cli == "claude":
        return ["claude", "--dangerously-skip-permissions", "-p", ""]
    if cli == "gemini":
        cmd = ["gemini", "--approval-mode", "yolo"]
        model = (env.get("ORCHESTRATOR_GEMINI_MODEL", "").strip()
                 or env.get("GEMINI_MODEL", "").strip())
        if model:
            cmd.extend(["-m", model])
        cmd.extend(["-p", ""])
        return cmd
    raise ValueError(f"unsupported CLI: {cli}")


def _get_token_exhaustion_marker_path(log_dir: str, agent: str) -> str:
    """Returns the path to the token budget exhaustion marker file.
    This is consistent with supervisor.py's _budget_exhaustion_file,
    which expects a generic token budget exhaustion marker.
    """
    return os.path.join(log_dir, f"{agent}.token_budget_exhausted")


def _get_budget_state(budget_file_path: str) -> Dict[str, Any]:
    """Reads the budget state from a JSON file."""
    try:
        with open(budget_file_path, 'r') as f:
            content = f.read().strip()
        return json.loads(content)
    except FileNotFoundError:
        # File doesn't exist, return default state
        pass
    except (json.JSONDecodeError, OSError) as e:
        _log("WARN", f"failed to read or parse budget file {budget_file_path}: {e}, resetting state")
    return {"call_count": 0, "token_count": 0, "last_reset_day": None, "last_reset_hour": None}


def _set_budget_state(budget_file_path: str, state: Dict[str, Any]) -> None:
    """Writes the budget state to a JSON file."""
    try:
        # Ensure the parent directory exists
        os.makedirs(os.path.dirname(budget_file_path), exist_ok=True)
        with open(budget_file_path, 'w') as f:
            json.dump(state, f)
            f.flush() # Explicitly flush to disk
    except OSError as e:
        _log("ERROR", f"failed to write budget file {budget_file_path}: {e}")


# ---------------------------------------------------------------------------
# Persistent Worker
# ---------------------------------------------------------------------------

class PersistentWorker:
    """Long-running worker with hot orchestrator context.

    Eliminates per-task cold-start by:
    - Keeping the orchestrator connection alive across tasks
    - Claiming tasks via direct Python calls (no MCP round-trip in CLI)
    - Building stripped-down prompts (no connect/poll/claim ceremony)
    - Chaining tasks immediately (no inter-cycle sleep)
    """

    def __init__(self, cfg: PersistentWorkerConfig) -> None:
        cfg.finalise()
        self.cfg = cfg
        self._consecutive_failures = 0
        self._cycle = 0
        self._idle_streak = 0
        self._shutdown = False
        self._orch: Any = None
        self._call_count = 0
        self._tasks_completed = 0
        self._session_start: float = time.time()

        # Ensure dirs exist.
        os.makedirs(cfg.log_dir, exist_ok=True)
        os.makedirs(cfg.pid_dir, exist_ok=True)
        Path(cfg.project_root, "state").mkdir(parents=True, exist_ok=True)

    # -- orchestrator access ------------------------------------------------

    def _get_orchestrator(self) -> Any:
        """Lazy-init orchestrator with hot connection."""
        if self._orch is None:
            if self.cfg.repo_root not in sys.path:
                sys.path.insert(0, self.cfg.repo_root)
            from orchestrator.engine import Orchestrator
            from orchestrator.policy import Policy

            policy_path = Path(self.cfg.repo_root) / "config" / "policy.codex-manager.json"
            policy = Policy.load(policy_path)
            self._orch = Orchestrator(root=Path(self.cfg.repo_root), policy=policy)
        return self._orch

    def _connect(self) -> Dict[str, Any]:
        """Register and connect to leader via hot orchestrator."""
        orch = self._get_orchestrator()
        result = orch.connect_to_leader(
            agent=self.cfg.agent,
            source=self.cfg.agent,
            metadata={
                "client": self.cfg.cli,
                "cwd": self.cfg.project_root,
                "project_root": self.cfg.project_root,
                "instance_id": self.cfg.instance_id,
                "lane": self.cfg.lane,
                "session_type": "persistent",
                "task_activity": "idle",
                "process_state": "running",
                "role": "team_member",
                "permissions_mode": "headless",
                "sandbox_mode": "danger-full-access",
            },
        )
        _log("INFO", f"connected to leader agent={self.cfg.agent} verified={result.get('verified')}")
        return result

    def _heartbeat(self, activity: str = "idle") -> None:
        """Emit heartbeat to orchestrator."""
        try:
            orch = self._get_orchestrator()
            orch.heartbeat(
                agent=self.cfg.agent,
                metadata={
                    "instance_id": self.cfg.instance_id,
                    "lane": self.cfg.lane,
                    "session_type": "persistent",
                    "task_activity": activity,
                    "process_state": "running",
                },
            )
        except Exception:
            pass  # Non-critical

    # -- task management ----------------------------------------------------

    def _has_claimable_work(self) -> bool:
        """Check tasks.json for claimable work without claiming."""
        tasks_path = Path(self.cfg.project_root) / "state" / "tasks.json"
        _log("DEBUG", f"_has_claimable_work: checking for claimable work in {tasks_path}")
        if not tasks_path.exists():
            _log("DEBUG", f"_has_claimable_work: {tasks_path} does not exist.")
            return False
        try:
            raw_tasks_content = tasks_path.read_text(encoding="utf-8")
            _log("DEBUG", f"_has_claimable_work: tasks.json content: {raw_tasks_content}")
            tasks = json.loads(raw_tasks_content)
        except Exception as e:
            _log("DEBUG", f"_has_claimable_work: failed to read or parse tasks.json: {e}")
            return False
        if not isinstance(tasks, list):
            _log("DEBUG", f"_has_claimable_work: tasks.json content is not a list.")
            return False

        for task in tasks:
            _log("DEBUG", f"_has_claimable_work: evaluating task {task.get('id')}")
            _log("DEBUG", f"  Task owner: {task.get('owner')}, self.cfg.agent: {self.cfg.agent}")
            if str(task.get("owner", "")).strip() != self.cfg.agent:
                _log("DEBUG", "  Owner mismatch. Skipping.")
                continue
            _log("DEBUG", f"  Task status: {task.get('status')}")
            if str(task.get("status", "")).strip().lower() not in {"assigned", "bug_open", "in_progress"}:
                _log("DEBUG", "  Status not assigned, bug_open, or in_progress. Skipping.")
                continue
            if self.cfg.team_id:
                tid = str(task.get("team_id", "")).strip().lower()
                _log("DEBUG", f"  Task team_id: {tid}, self.cfg.team_id: {self.cfg.team_id.lower()}")
                if tid and tid != self.cfg.team_id.lower():
                    _log("DEBUG", "  Team ID mismatch. Skipping.")
                    continue
            if self.cfg.lane == "wingman":
                ws = str(task.get("workstream", "")).strip().lower()
                _log("DEBUG", f"  Task workstream: {ws}, self.cfg.lane: {self.cfg.lane}")
                if ws != "qa":
                    title = str(task.get("title", "")).strip().lower()
                    desc = str(task.get("description", "")).strip().lower()
                    _log("DEBUG", f"  Task title: {title}, description: {desc}")
                    if not any(k in f"{title} {desc}" for k in ("qa", "regression", "test")):
                        _log("DEBUG", "  Not QA-scoped for wingman lane. Skipping.")
                        continue
            _log("DEBUG", f"_has_claimable_work: found claimable task {task.get('id')}. Returning True.")
            return True
        _log("DEBUG", "_has_claimable_work: no claimable tasks found. Returning False.")
        return False

    def _claim_next_task(self) -> Optional[Dict[str, Any]]:
        """Claim next available task directly via orchestrator engine."""
        _log("DEBUG", "attempting to claim next task...")
        try:
            orch = self._get_orchestrator()
            result = orch.claim_next_task(
                owner=self.cfg.agent,
                instance_id=self.cfg.instance_id,
                team_id=self.cfg.team_id or None,
            )
            if result and result.get("id"):
                _log("DEBUG", f"claimed task: {result.get('id')}, throttled: {result.get('throttled')}")
                if not result.get("throttled"):
                    return result
            elif result and result.get("throttled"):
                _log("DEBUG", f"claim throttled: {result.get('message')}")
        except Exception as e:
            _log("WARN", f"claim_next_task failed: {e}")
        _log("DEBUG", "no task claimed.")
        return None

    # -- prompt building ----------------------------------------------------

    def _build_task_prompt(self, task: Dict[str, Any]) -> str:
        """Build a minimal task prompt — no orchestrator ceremony."""
        task_id = task.get("id", "unknown")
        title = task.get("title", "")
        description = task.get("description", "")
        criteria = task.get("acceptance_criteria", [])
        criteria_text = "\n".join(f"  - {c}" for c in criteria) if criteria else "  (none specified)"
        task_team_id = str(task.get("team_id", "")).strip()

        lane_rules = ""
        if self.cfg.lane == "wingman":
            lane_rules = (
                '\n   - QA lane guard: if this task is not QA-scoped, do not execute it.\n'
                f'     * call orchestrator_update_task_status(task_id="{task_id}", status="assigned",'
                f' note="Wingman QA lane: task is not QA-scoped; returned to queue")\n'
                f'     * call orchestrator_publish_event(source="{self.cfg.agent}", type="manager.sync",'
                f' payload={{"task_id":"{task_id}","reason":"wingman_non_qa_task_requeued"}})\n'
                '     * print "rerouted_non_qa" and exit'
            )

        team_rules = ""
        if self.cfg.team_id:
            team_rules = (
                f'\n   - Team lane guard: if task.team_id exists and does not match "{self.cfg.team_id}", do not execute it.\n'
                '   - For non-matching team task:\n'
                f'     * call orchestrator_update_task_status(task_id="{task_id}", status="assigned",'
                f' note="Headless team lane: task team_id mismatch; returned to queue")\n'
                f'     * call orchestrator_publish_event(source="{self.cfg.agent}", type="manager.sync",'
                f' payload={{"task_id":"{task_id}","reason":"team_id_mismatch_requeued",'
                f'"expected_team_id":"{self.cfg.team_id}"}})\n'
                '     * print "rerouted_team_mismatch" and exit'
            )

        # Read spec file for implementation guidance if available.
        spec_section = ""
        try:
            orch = self._get_orchestrator()
            spec = orch.get_spec(task_id)
            if spec:
                constraints = spec.get("constraints", {})
                refs = spec.get("references", {})
                parts = ["\n  Spec (implementation guidance):"]
                if constraints:
                    parts.append(f"    Risk: {constraints.get('risk', 'medium')}")
                    parts.append(f"    Test plan: {constraints.get('test_plan', 'targeted')}")
                    parts.append(f"    Doc impact: {constraints.get('doc_impact', 'none')}")
                if refs.get("parent_task_id"):
                    parts.append(f"    Parent task: {refs['parent_task_id']}")
                if refs.get("tags"):
                    parts.append(f"    Tags: {', '.join(refs['tags'])}")
                spec_section = "\n".join(parts) + "\n"
        except Exception:
            pass  # Spec is optional — don't block task execution.

        project_name = Path(self.cfg.project_root).name
        return (
            f"Project: {project_name}\n"
            f"You are worker agent {self.cfg.agent} executing a pre-claimed task.\n"
            f"Lane: {self.cfg.lane}\n"
            f"Team: {self.cfg.team_id or 'none'}\n"
            f"\n"
            f"Task already claimed (skip connect/poll/claim steps):\n"
            f"  Task ID: {task_id}\n"
            f"  Title: {title}\n"
            f"  Description: {description}\n"
            f"  Acceptance criteria:\n{criteria_text}\n"
            f"{spec_section}"
            f"{lane_rules}{team_rules}\n"
            f"\n"
            f"Execute this task:\n"
            f"- Implement the required changes in this project\n"
            f"- Run relevant tests/build checks\n"
            f"- call orchestrator_submit_report with commit SHA and test results\n"
            f"- if blocked, call orchestrator_raise_blocker instead of stalling\n"
            f"- Exit after completing the task\n"
            f"\n"
            f"Rules:\n"
            f"- Work only inside {self.cfg.project_root}\n"
            f"- Use MCP tools for orchestration state\n"
            f"- Never silently stop; submit report or raise blocker\n"
        )

    # -- Gemini capacity detection -----------------------------------------

    # Markers that indicate a model capacity / rate-limit error.
    _CAPACITY_ERROR_MARKERS = (
        "MODEL_CAPACITY_EXHAUSTED",
        "No capacity available for model",
        "RESOURCE_EXHAUSTED",
        "rateLimitExceeded",
        "429",
        "Too Many Requests",
        "quota exceeded",
    )

    def _detect_capacity_error(self, output_file: str) -> bool:
        """Scan CLI output for capacity / rate-limit error markers.

        Equivalent of shell ``detect_gemini_capacity_error`` in common.sh.
        Returns True if a capacity error was detected.
        """
        try:
            with open(output_file, "r", errors="replace") as f:
                text = f.read()
        except (OSError, FileNotFoundError):
            return False
        lower = text.lower()
        for marker in self._CAPACITY_ERROR_MARKERS:
            if marker.lower() in lower:
                return True
        return False

    def _handle_capacity_error(self) -> None:
        """Record capacity error and apply capacity-specific backoff.

        Writes a capacity_errors counter file (like the shell version) and
        uses a longer backoff without incrementing ``_consecutive_failures``.
        """
        process_key = self.cfg.process_name
        pid_dir = self.cfg.pid_dir
        os.makedirs(pid_dir, exist_ok=True)
        capacity_file = os.path.join(pid_dir, f"{process_key}.capacity_errors")

        # Read and increment the streak counter.
        streak = 0
        try:
            with open(capacity_file, "r") as f:
                streak = int(f.read().strip())
        except (OSError, ValueError):
            pass
        streak += 1
        try:
            with open(capacity_file, "w") as f:
                f.write(str(streak))
        except OSError:
            pass

        # Use capacity-specific backoff: longer sleep, exponential from 30s base.
        backoff = min(30 * (2 ** (streak - 1)), 900)
        _log("WARN",
             f"capacity error detected (streak={streak}); "
             f"backoff {backoff}s (not incrementing consecutive_failures)")

        # Update heartbeat metadata so the engine knows we're capacity-degraded.
        try:
            orch = self._get_orchestrator()
            orch.heartbeat(
                agent=self.cfg.agent,
                metadata={
                    "instance_id": self.cfg.instance_id,
                    "lane": self.cfg.lane,
                    "session_type": "persistent",
                    "task_activity": "capacity_degraded",
                    "process_state": "running",
                    "capacity_errors": streak,
                    "status": "capacity_degraded",
                },
            )
        except Exception:
            pass

        time.sleep(backoff)

    def _clear_capacity_errors(self) -> None:
        """Clear the capacity error streak counter on success."""
        process_key = self.cfg.process_name
        capacity_file = os.path.join(self.cfg.pid_dir, f"{process_key}.capacity_errors")
        try:
            if os.path.exists(capacity_file):
                os.unlink(capacity_file)
        except OSError:
            pass

    # -- CLI execution ------------------------------------------------------

    def _run_cli(self, prompt: str) -> tuple:
        """Execute CLI with the given prompt. Returns (exit_code, output_file)."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_file = os.path.join(
            self.cfg.log_dir,
            f"worker-{self.cfg.agent}-{self.cfg.cli}-{ts}.log",
        )

        env = os.environ.copy()
        env["ORCHESTRATOR_AGENT"] = self.cfg.agent
        env["ORCHESTRATOR_ROLE"] = self.cfg.lane
        env["ORCHESTRATOR_INSTANCE_ID"] = self.cfg.instance_id

        # Identity safety check.
        if self.cfg.cli in _VALID_AGENTS:
            if self.cfg.agent not in _VALID_AGENTS[self.cfg.cli]:
                _log("ERROR", f"agent identity mismatch: CLI '{self.cfg.cli}' cannot act as '{self.cfg.agent}'")
                return 1, out_file

        cmd = _build_cli_cmd(self.cfg.cli, self.cfg.project_root, env)
        _log("INFO", f"running CLI {self.cfg.cli} → {out_file}")

        prompt_fd = None
        try:
            prompt_fd = tempfile.NamedTemporaryFile(
                mode="w", suffix=".prompt", delete=False,
            )
            prompt_fd.write(prompt)
            prompt_fd.close()

            with open(prompt_fd.name, "rb") as stdin_f, open(out_file, "wb") as out_f:
                try:
                    result = subprocess.run(
                        cmd,
                        cwd=self.cfg.project_root,
                        stdin=stdin_f,
                        stdout=out_f,
                        stderr=subprocess.STDOUT,
                        timeout=self.cfg.cli_timeout,
                        env=env,
                        check=False,
                    )
                    return result.returncode, out_file
                except subprocess.TimeoutExpired:
                    with open(out_file, "ab") as f:
                        f.write(
                            f"\n[AUTOPILOT] CLI timeout after {self.cfg.cli_timeout}s"
                            f" for {self.cfg.cli}\n".encode("utf-8")
                        )
                    _log("ERROR", f"CLI timeout after {self.cfg.cli_timeout}s")
                    return 124, out_file
        finally:
            if prompt_fd is not None:
                try:
                    os.unlink(prompt_fd.name)
                except OSError:
                    pass

    # -- signal-based idle wait ---------------------------------------------

    def _wait_for_signal(self) -> bool:
        """Watch signal file for new task notification.

        Uses fswatcher.py (kqueue/inotify) when available, otherwise polls.
        Returns True if signal received, False on timeout.
        """
        signal_path = _signal_file(self.cfg.project_root, self.cfg.agent)
        fswatcher = Path(self.cfg.repo_root) / "scripts" / "autopilot" / "fswatcher.py"

        # Record baseline mtime.
        baseline_mtime = 0
        if signal_path.exists():
            try:
                baseline_mtime = int(signal_path.stat().st_mtime * 1000)
            except OSError:
                pass

        waited = 0
        last_heartbeat = 0

        while waited < self.cfg.signal_max_wait:
            if self._shutdown:
                return False

            chunk = min(
                self.cfg.signal_max_wait - waited,
                self.cfg.heartbeat_interval if self.cfg.heartbeat_interval > 0 else self.cfg.signal_max_wait,
            )

            if fswatcher.exists():
                # Use OS-native watcher.
                try:
                    rc = subprocess.run(
                        ["python3", str(fswatcher), str(signal_path), str(chunk),
                         "--baseline-mtime", str(baseline_mtime)],
                        capture_output=True, timeout=chunk + 5,
                    ).returncode
                    if rc == 0:
                        return True
                except (subprocess.TimeoutExpired, OSError):
                    pass
            else:
                # Polling fallback.
                chunk_waited = 0
                while chunk_waited < chunk:
                    time.sleep(self.cfg.signal_poll_interval)
                    chunk_waited += self.cfg.signal_poll_interval
                    if signal_path.exists():
                        try:
                            cur = int(signal_path.stat().st_mtime * 1000)
                            if cur != baseline_mtime:
                                return True
                        except OSError:
                            pass

            waited += chunk
            if self.cfg.heartbeat_interval > 0 and waited - last_heartbeat >= self.cfg.heartbeat_interval:
                self._heartbeat("idle")
                last_heartbeat = waited

        return False

    # -- budget management --------------------------------------------------

    def _consume_budget(self, tokens_consumed: int) -> bool:
        """Check daily call and token budgets. Returns False if exhausted."""
        from orchestrator.budget import consume_call

        budget_root = Path(self.cfg.log_dir)
        key = f"worker-{self.cfg.cli}-{self.cfg.agent}"
        safe_key = key.replace("/", "_")

        now = time.time()
        day = time.strftime("%Y%m%d", time.localtime(now))
        hour = time.strftime("%Y%m%d%H", time.localtime(now))

        # --- Daily Call Budget (unified module with file locking) ---
        if self.cfg.daily_call_budget > 0:
            if not consume_call(key, self.cfg.daily_call_budget, str(budget_root)):
                _log("WARN", f"daily call budget exhausted ({self.cfg.daily_call_budget})")
                return False

        # --- Daily Token Budget ---
        daily_token_budget_file = str(budget_root / f".budget-{safe_key}-{day}.token_count.json")
        daily_token_state = _get_budget_state(daily_token_budget_file)

        if daily_token_state.get("last_reset_day") != day:
            daily_token_state = {"call_count": 0, "token_count": 0, "last_reset_day": day}

        if self.cfg.daily_token_budget > 0:
            if (daily_token_state["token_count"] + tokens_consumed) > self.cfg.daily_token_budget:
                self._mark_budget_exhausted("daily")
                _log("WARN",
                     f"daily token budget exhausted ({self.cfg.daily_token_budget}); "
                     f"current={daily_token_state['token_count']} consumed={tokens_consumed}")
                return False

        # --- Hourly Token Budget ---
        hourly_token_budget_file = str(budget_root / f".budget-{safe_key}-{hour}.hourly_token_count.json")
        hourly_token_state = _get_budget_state(hourly_token_budget_file)

        if hourly_token_state.get("last_reset_hour") != hour:
            hourly_token_state = {"call_count": 0, "token_count": 0, "last_reset_hour": hour}

        if self.cfg.hourly_token_budget > 0:
            if (hourly_token_state["token_count"] + tokens_consumed) > self.cfg.hourly_token_budget:
                self._mark_budget_exhausted("hourly")
                _log("WARN",
                     f"hourly token budget exhausted ({self.cfg.hourly_token_budget}); "
                     f"current={hourly_token_state['token_count']} consumed={tokens_consumed}")
                return False

        # If all budgets are fine, increment and save (token budgets only;
        # daily call budget was already incremented by consume_call above).
        daily_token_state["token_count"] += tokens_consumed
        _set_budget_state(daily_token_budget_file, daily_token_state)

        hourly_token_state["token_count"] += tokens_consumed
        _set_budget_state(hourly_token_budget_file, hourly_token_state)

        self._call_count += 1
        return True

    def _mark_budget_exhausted(self, budget_type: str) -> None:
        """Creates a marker file to indicate budget exhaustion.

        Writes to pid_dir (not log_dir) so the supervisor monitor can detect it
        via ``_is_budget_window_active``.  Uses the same JSON format as the shell
        ``write_budget_exhaustion_marker`` in common.sh.
        """
        from datetime import datetime as _dt, timedelta, timezone as _tz
        process_key = self.cfg.process_name
        pid_dir = self.cfg.pid_dir
        os.makedirs(pid_dir, exist_ok=True)
        marker_path = os.path.join(pid_dir, f"{process_key}.token_budget_exhausted")
        now_utc = _dt.now(_tz.utc)
        if budget_type == "hourly":
            next_window = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        else:
            next_window = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        marker_data = {
            "process_key": process_key,
            "window": budget_type,
            "exhausted_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "next_window_at": next_window.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            with open(marker_path, "w") as f:
                json.dump(marker_data, f)
            _log("INFO", f"created {budget_type} budget exhaustion marker: {marker_path}")
            # Emit an orchestrator event for budget exhaustion.
            orch = self._get_orchestrator()
            orch.publish_event(
                event_type="agent.budget_exhausted",
                source=self.cfg.agent,
                payload={
                    "agent": self.cfg.agent,
                    "budget_type": budget_type,
                    "reason": f"{budget_type} token budget exhausted",
                    "instance_id": self.cfg.instance_id,
                },
            )
        except OSError as e:
            _log("ERROR", f"failed to create {budget_type} budget exhaustion marker {marker_path}: {e}")

    # -- auto-resume from roadmap -------------------------------------------

    def _auto_resume_from_roadmap(self) -> int:
        """Check roadmap for backlog items and create tasks if available.

        Returns the number of tasks created (0 if none).
        """
        try:
            orch = self._get_orchestrator()
            result = orch.plan_from_roadmap(
                source=self.cfg.agent,
                team_id=self.cfg.team_id or None,
                limit=5,
            )
            created = len(result.get("created", []))
            if created > 0:
                # Touch the wakeup signal so other idle workers notice.
                sig = _signal_file(self.cfg.project_root, self.cfg.agent)
                sig.parent.mkdir(parents=True, exist_ok=True)
                sig.write_text(str(created), encoding="utf-8")
                # Publish event for observability.
                orch.publish_event(
                    event_type="worker.auto_resume",
                    source=self.cfg.agent,
                    payload={
                        "agent": self.cfg.agent,
                        "tasks_created": created,
                        "backlog_remaining": result.get("backlog_remaining", 0),
                        "instance_id": self.cfg.instance_id,
                    },
                )
            return created
        except Exception as e:
            _log("WARN", f"auto-resume from roadmap failed: {e}")
            return 0

    # -- task release on exit -----------------------------------------------

    def _release_tasks(self) -> int:
        """Reset owned in_progress tasks to 'assigned' with cleared lease.

        Called on worker exit so tasks don't stay stuck for 30 min until
        stale-requeue kicks in.  Returns number of tasks released.
        """
        released = 0
        try:
            tasks_path = Path(self.cfg.project_root) / "state" / "tasks.json"
            if not tasks_path.exists():
                return 0
            raw = tasks_path.read_text(encoding="utf-8")
            tasks = json.loads(raw)
            if not isinstance(tasks, list):
                return 0
            changed = False
            for task in tasks:
                if (str(task.get("owner", "")).strip() == self.cfg.agent
                        and str(task.get("status", "")).strip().lower() == "in_progress"):
                    task["status"] = "assigned"
                    task["lease"] = None
                    changed = True
                    released += 1
                    _log("INFO", f"released task {task.get('id')} back to assigned")
            if changed:
                tasks_path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
        except Exception as e:
            _log("WARN", f"_release_tasks failed: {e}")
        return released

    # -- session metrics ----------------------------------------------------

    def _emit_session_metrics(self, exit_reason: str) -> None:
        """Publish session summary event for observability."""
        self._release_tasks()
        uptime = time.time() - self._session_start
        _log("INFO",
             f"session metrics: tasks={self._tasks_completed} cycles={self._cycle}"
             f" uptime={uptime:.0f}s reason={exit_reason}")
        try:
            orch = self._get_orchestrator()
            orch.publish_event(
                event_type="worker.session_end",
                source=self.cfg.agent,
                payload={
                    "agent": self.cfg.agent,
                    "instance_id": self.cfg.instance_id,
                    "lane": self.cfg.lane,
                    "tasks_completed": self._tasks_completed,
                    "cycles": self._cycle,
                    "uptime_seconds": round(uptime),
                    "exit_reason": exit_reason,
                    "cli": self.cfg.cli,
                },
            )
        except Exception:
            pass  # Best-effort — don't block shutdown.

    # -- main loop ----------------------------------------------------------

    def run(self) -> int:
        """Main persistent worker loop. Returns exit code."""
        _log("INFO",
             f"persistent worker starting agent={self.cfg.agent} cli={self.cfg.cli}"
             f" lane={self.cfg.lane} team={self.cfg.team_id or 'none'}")

        # Graceful shutdown on SIGTERM/SIGINT — release tasks before exit.
        def _handle_signal(signum: int, frame: Any) -> None:
            _log("INFO", f"received signal {signum}, shutting down")
            self._shutdown = True
            self._release_tasks()

        signal_mod.signal(signal_mod.SIGTERM, _handle_signal)
        signal_mod.signal(signal_mod.SIGINT, _handle_signal)

        # Establish hot orchestrator connection.
        try:
            self._connect()
        except Exception as e:
            _log("ERROR", f"failed to connect: {e}")
            return 1

        while not self._shutdown:
            self._cycle += 1
            _log("INFO", f"persistent cycle={self._cycle} agent={self.cfg.agent}")

            # Budget check.
            if not self._consume_budget(self.cfg.tokens_per_call):
                _log("WARN", "budget exhausted; exiting persistent worker")
                self._emit_session_metrics("budget_exhausted")
                return 0

            # Check for claimable work.
            if not self._has_claimable_work():
                self._idle_streak += 1
                self._heartbeat("idle")
                _log("INFO", f"no claimable work (idle_streak={self._idle_streak})")

                if self._idle_streak >= self.cfg.max_idle_cycles > 0:
                    # Auto-resume: check roadmap for backlog before exiting.
                    created = self._auto_resume_from_roadmap()
                    if created > 0:
                        _log("INFO", f"auto-resume: created {created} tasks from roadmap; resetting idle streak")
                        self._idle_streak = 0
                        continue
                    _log("INFO", f"max idle cycles reached ({self.cfg.max_idle_cycles}); no backlog remaining; exiting")
                    self._emit_session_metrics("max_idle")
                    return 0

                # Wait for signal file.
                if self._wait_for_signal():
                    _log("INFO", "wakeup signal received")
                    continue
                continue

            self._idle_streak = 0

            # Claim task via hot orchestrator.
            task = self._claim_next_task()
            if not task:
                _log("INFO", "claim returned nothing; brief backoff")
                time.sleep(2)
                continue

            task_id = task.get("id", "unknown")
            _log("INFO", f"claimed task={task_id} title={task.get('title', '')!r}")
            self._heartbeat("working")

            # Build stripped-down prompt and execute.
            prompt = self._build_task_prompt(task)
            rc, out_file = self._run_cli(prompt)

            # Check for capacity/rate-limit errors before treating as generic failure.
            if rc != 0 and self._detect_capacity_error(out_file):
                _log("WARN", f"task={task_id} hit capacity error (rc={rc})")
                self._handle_capacity_error()
                # Don't increment consecutive_failures for capacity errors.
                continue

            if rc == 0:
                _log("INFO", f"task={task_id} completed rc=0")
                self._consecutive_failures = 0
                self._tasks_completed += 1
                self._clear_capacity_errors()
            else:
                _log("ERROR", f"task={task_id} failed rc={rc}")
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.cfg.max_consecutive_failures:
                    _log("ERROR",
                         f"consecutive failures ({self._consecutive_failures}) reached max"
                         f" ({self.cfg.max_consecutive_failures}); exiting for fallback")
                    self._emit_session_metrics("max_failures")
                    return 1

            # Session task limit: restart worker to bound memory growth.
            if self.cfg.max_tasks_per_session > 0 and self._tasks_completed >= self.cfg.max_tasks_per_session:
                _log("INFO",
                     f"session task limit reached ({self._tasks_completed}/{self.cfg.max_tasks_per_session}); "
                     f"exiting for fresh session")
                self._emit_session_metrics("session_limit")
                return 0

            # No inter-cycle sleep — immediately check for next task.

        self._emit_session_metrics("shutdown")
        _log("INFO", "persistent worker shutdown complete")
        return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_config_from_args(argv: Sequence[str] | None = None) -> PersistentWorkerConfig:
    """Parse CLI arguments into a config."""
    import argparse

    parser = argparse.ArgumentParser(description="Persistent worker session")
    parser.add_argument("--cli", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--lane", default="default")
    parser.add_argument("--team-id", default="")
    parser.add_argument("--instance-id", default="")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--log-dir", default="")
    parser.add_argument("--pid-dir", default="")
    parser.add_argument("--process-name", default="")
    parser.add_argument("--cli-timeout", type=int, default=600)
    parser.add_argument("--max-consecutive-failures", type=int, default=3)
    parser.add_argument("--signal-poll-interval", type=int, default=2)
    parser.add_argument("--signal-max-wait", type=int, default=300)
    parser.add_argument("--heartbeat-interval", type=int, default=60)
    parser.add_argument("--idle-backoff", default="30,60,120,300,900")
    parser.add_argument("--max-idle-cycles", type=int, default=30)
    parser.add_argument("--max-tasks-per-session", type=int, default=0)
    parser.add_argument("--daily-call-budget", type=int, default=100)
    parser.add_argument("--daily-token-budget", type=int, default=0)
    parser.add_argument("--hourly-token-budget", type=int, default=0)
    parser.add_argument("--tokens-per-call", type=int, default=10000)

    args = parser.parse_args(argv)
    return PersistentWorkerConfig(
        cli=args.cli,
        agent=args.agent,
        lane=args.lane,
        team_id=args.team_id,
        instance_id=args.instance_id,
        project_root=args.project_root,
        repo_root=args.repo_root,
        log_dir=args.log_dir,
        pid_dir=args.pid_dir,
        process_name=args.process_name,
        cli_timeout=args.cli_timeout,
        max_consecutive_failures=args.max_consecutive_failures,
        signal_poll_interval=args.signal_poll_interval,
        signal_max_wait=args.signal_max_wait,
        heartbeat_interval=args.heartbeat_interval,
        idle_backoff=args.idle_backoff,
        max_idle_cycles=args.max_idle_cycles,
        max_tasks_per_session=args.max_tasks_per_session,
        daily_call_budget=args.daily_call_budget,
        daily_token_budget=args.daily_token_budget,
        hourly_token_budget=args.hourly_token_budget,
        tokens_per_call=args.tokens_per_call,
    )


def main(argv: list[str] | None = None) -> int:
    cfg = build_config_from_args(argv)
    worker = PersistentWorker(cfg)
    return worker.run()


if __name__ == "__main__":
    sys.exit(main())
