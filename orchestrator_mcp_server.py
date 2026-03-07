#!/usr/bin/env python3
"""
agent-leader-orchestrator MCP Server
Expose configurable multi-agent orchestration tools via MCP JSON-RPC.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.doctor import build_doctor_payload
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy
from orchestrator.supervisor import ExtraWorker, Supervisor, SupervisorConfig

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None

# Force line-buffered stdout/stderr for MCP JSON-RPC transport.
# Skip when running under a test harness (pytest captures stdout via wrapper
# objects whose fileno() may be invalid or shared).
if not hasattr(sys, "_called_from_test") and os.environ.get("PYTEST_CURRENT_TEST") is None:
    try:
        sys.stdout = os.fdopen(sys.stdout.fileno(), "w", 1)
        sys.stderr = os.fdopen(sys.stderr.fileno(), "w", 1)
    except (OSError, AttributeError):
        pass

__version__ = "0.1.0"
SCRIPT_DIR = Path(__file__).resolve().parent
STARTUP_CWD = Path.cwd().resolve()
ORCHESTRATOR_ROOT_RAW = os.getenv("ORCHESTRATOR_ROOT", "").strip()
# Prefer explicit ORCHESTRATOR_ROOT. When absent, fall back to startup cwd
# so project-local launches from a shared install can still bind correctly.
ROOT_DIR = Path(ORCHESTRATOR_ROOT_RAW or str(STARTUP_CWD)).resolve()
EXPECTED_ROOT_RAW = os.getenv("ORCHESTRATOR_EXPECTED_ROOT", "").strip()
ENFORCE_SHARED_BINDING = os.getenv("ORCHESTRATOR_ENFORCE_SHARED_BINDING", "1").strip().lower() not in {"0", "false", "no"}
POLICY_PATH = Path(
    os.getenv("ORCHESTRATOR_POLICY", str(ROOT_DIR / "config" / "policy.codex-manager.json"))
).resolve()
STATUS_VERBOSE_PATHS = os.getenv("ORCHESTRATOR_STATUS_VERBOSE_PATHS", "").strip().lower() in {"1", "true", "yes"}
RUN_ID = os.getenv("ORCHESTRATOR_RUN_ID", "").strip()
PROMPT_PROFILE_VERSION = os.getenv("ORCHESTRATOR_PROMPT_PROFILE_VERSION", "").strip()
ALLOW_SHARED_MCP_JSON_PATH = os.getenv("ORCHESTRATOR_ALLOW_SHARED_MCP_JSON_PATH", "").strip().lower() in {"1", "true", "yes"}


def _is_shared_agent_leader_install(path: Path) -> bool:
    p = str(path)
    return "/.local/share/agent-leader/current" in p


def _project_mcp_server_uses_shared_path(root_dir: Path) -> bool:
    mcp_path = root_dir / ".mcp.json"
    if not mcp_path.exists():
        return False
    try:
        payload = json.loads(mcp_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        return False
    server = servers.get("agent-leader-orchestrator")
    if not isinstance(server, dict):
        return False
    command = str(server.get("command", "") or "")
    args = server.get("args", [])
    if not isinstance(args, list):
        args = []
    cmdline = " ".join([command] + [str(item) for item in args])
    return "/.local/share/agent-leader/current/" in cmdline


# ── Binding validation (deferred errors instead of hard crash) ──────
_BINDING_ERROR: Optional[str] = None

if EXPECTED_ROOT_RAW:
    expected_root = Path(EXPECTED_ROOT_RAW).resolve()
    if ROOT_DIR != expected_root:
        _BINDING_ERROR = (
            f"ORCHESTRATOR_ROOT mismatch: got '{ROOT_DIR}', expected '{expected_root}'"
        )

if not _BINDING_ERROR and ENFORCE_SHARED_BINDING and _is_shared_agent_leader_install(SCRIPT_DIR):
    if not ORCHESTRATOR_ROOT_RAW:
        if ROOT_DIR == SCRIPT_DIR:
            _BINDING_ERROR = (
                "Shared agent-leader install requires explicit ORCHESTRATOR_ROOT "
                "to prevent cross-project binding leaks. "
                "Set ORCHESTRATOR_ROOT in your MCP server config env."
            )
    elif not EXPECTED_ROOT_RAW:
        _BINDING_ERROR = (
            "Shared agent-leader install requires ORCHESTRATOR_EXPECTED_ROOT "
            "(must match ORCHESTRATOR_ROOT). "
            "Set ORCHESTRATOR_EXPECTED_ROOT in your MCP server config env."
        )

if (
    not _BINDING_ERROR
    and not ALLOW_SHARED_MCP_JSON_PATH
    and ROOT_DIR == SCRIPT_DIR
    and _project_mcp_server_uses_shared_path(ROOT_DIR)
):
    _BINDING_ERROR = (
        "Project .mcp.json points agent-leader-orchestrator to shared install path "
        "'/.local/share/agent-leader/current'. In project-local mode, update .mcp.json "
        "to launch this repo's orchestrator_mcp_server.py and policy."
    )

if _BINDING_ERROR:
    # Log to stderr but do NOT crash — run in degraded mode so the client
    # gets a proper JSON-RPC error instead of "Transport closed".
    print(f"agent-leader-orchestrator: BINDING ERROR (degraded mode): {_BINDING_ERROR}", file=sys.stderr)

try:
    if _BINDING_ERROR:
        POLICY = None  # type: ignore[assignment]
        ORCH = None  # type: ignore[assignment]
    else:
        POLICY = Policy.load(POLICY_PATH)
        ORCH = Orchestrator(root=ROOT_DIR, policy=POLICY)
except Exception as exc:
    print(f"Failed to initialize orchestrator: {exc}", file=sys.stderr)
    _BINDING_ERROR = f"Orchestrator init failed: {exc}"
    POLICY = None  # type: ignore[assignment]
    ORCH = None  # type: ignore[assignment]

_AUTO_LOOP_STOP = threading.Event()
_AUTO_LOOP_THREAD: Optional[threading.Thread] = None
STATUS_SNAPSHOTS_PATH = ROOT_DIR / "state" / "status_snapshots.jsonl"
STATUS_SNAPSHOTS_LOCK = ROOT_DIR / "state" / ".status_snapshots.lock"

# ── Runtime / source consistency ────────────────────────────────────
_SOURCE_FILES = [
    SCRIPT_DIR / "orchestrator_mcp_server.py",
    SCRIPT_DIR / "orchestrator" / "engine.py",
    SCRIPT_DIR / "orchestrator" / "policy.py",
    SCRIPT_DIR / "orchestrator" / "bus.py",
]


def _compute_source_hash(paths: List[Path]) -> str:
    """SHA-256 over the concatenated contents of *paths* that exist."""
    h = hashlib.sha256()
    for p in sorted(paths):
        try:
            h.update(p.read_bytes())
        except Exception:
            pass
    return h.hexdigest()


def _git_head_short(repo: Path) -> Optional[str]:
    """Return the short git HEAD commit hash, or None."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


_STARTUP_SOURCE_HASH: str = _compute_source_hash(_SOURCE_FILES)
_STARTUP_GIT_COMMIT: Optional[str] = _git_head_short(SCRIPT_DIR)
_SERVER_BINDING = {
    "pid": os.getpid(),
    "startup_cwd": str(STARTUP_CWD),
    "root_dir": str(ROOT_DIR),
    "script_dir": str(SCRIPT_DIR),
    "shared_install": _is_shared_agent_leader_install(SCRIPT_DIR),
    "orchestrator_root_env_set": bool(ORCHESTRATOR_ROOT_RAW),
    "expected_root_env_set": bool(EXPECTED_ROOT_RAW),
    "strict_shared_binding": bool(ENFORCE_SHARED_BINDING),
}


def _runtime_source_consistency() -> Dict[str, Any]:
    """Compare startup source identity with current on-disk state."""
    current_hash = _compute_source_hash(_SOURCE_FILES)
    current_commit = _git_head_short(SCRIPT_DIR)
    source_changed = current_hash != _STARTUP_SOURCE_HASH
    commit_changed = (
        _STARTUP_GIT_COMMIT is not None
        and current_commit is not None
        and current_commit != _STARTUP_GIT_COMMIT
    )
    mismatch = source_changed or commit_changed
    warnings: List[str] = []
    if source_changed:
        warnings.append("source_hash_mismatch: runtime server may be stale")
    if commit_changed:
        warnings.append(
            f"git_commit_mismatch: startup={_STARTUP_GIT_COMMIT} current={current_commit}"
        )
    return {
        "ok": not mismatch,
        "mismatch_detected": mismatch,
        "startup_source_hash": _STARTUP_SOURCE_HASH,
        "current_source_hash": current_hash,
        "startup_git_commit": _STARTUP_GIT_COMMIT,
        "current_git_commit": current_commit,
        "source_files_checked": [p.name for p in sorted(_SOURCE_FILES)],
        "warnings": warnings,
    }


def _server_binding_health() -> Dict[str, Any]:
    warnings: List[str] = []
    startup_cwd_matches_root = STARTUP_CWD == ROOT_DIR
    if not startup_cwd_matches_root:
        warnings.append(
            f"startup_cwd_root_mismatch: cwd={STARTUP_CWD} root={ROOT_DIR}"
        )
    if _SERVER_BINDING["shared_install"] and not _SERVER_BINDING["orchestrator_root_env_set"]:
        warnings.append("shared_install_without_orchestrator_root_env")
    if _SERVER_BINDING["shared_install"] and not _SERVER_BINDING["expected_root_env_set"]:
        warnings.append("shared_install_without_expected_root_env")
    return {
        **_SERVER_BINDING,
        "startup_cwd_matches_root": startup_cwd_matches_root,
        "ok": len(warnings) == 0,
        "warnings": warnings,
    }


def send_response(response: Dict[str, Any]) -> None:
    print(json.dumps(response), flush=True)


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2)


def _append_jsonl(path: Path, lock_path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return
    with lock_path.open("a+", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _tail_jsonl(path: Path, limit: int = 200) -> List[Dict[str, Any]]:
    if not path.exists() or limit <= 0:
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return rows[-limit:]


def _status_integrity_and_provenance(current_task_count: int, current_done_count: int) -> Dict[str, Any]:
    max_seen_task_count = current_task_count
    max_seen_done_count = current_done_count
    last_good_source = "current_status"
    warnings: List[str] = []

    for row in ORCH.bus.read_audit(limit=400, tool_name="orchestrator_status", status="ok"):
        result = row.get("result", {})
        if not isinstance(result, dict):
            continue
        try:
            task_count = int(result.get("task_count", 0))
        except Exception:
            continue
        try:
            done_count = int((result.get("task_status_counts") or {}).get("done", 0))
        except Exception:
            done_count = 0
        if task_count > max_seen_task_count:
            max_seen_task_count = task_count
            max_seen_done_count = max(max_seen_done_count, done_count)
            last_good_source = "audit.orchestrator_status"

    for snap in _tail_jsonl(STATUS_SNAPSHOTS_PATH, limit=400):
        try:
            task_count = int(snap.get("task_count", 0))
            done_count = int((snap.get("task_status_counts") or {}).get("done", 0))
        except Exception:
            continue
        if task_count > max_seen_task_count:
            max_seen_task_count = task_count
            max_seen_done_count = max(max_seen_done_count, done_count)
            last_good_source = "state.status_snapshots"

    task_count_regression = current_task_count < max_seen_task_count
    if task_count_regression:
        warnings.append(
            f"task_count_regression_detected: current={current_task_count} < historical_max={max_seen_task_count}"
        )

    corrected_percent: Optional[float] = None
    if max_seen_task_count > 0:
        # If current state regressed, prefer historical max counts as safer estimate.
        numerator = max_seen_done_count if task_count_regression else current_done_count
        denominator = max_seen_task_count if task_count_regression else current_task_count
        corrected_percent = round((numerator / denominator) * 100.0, 2)

    return {
        "ok": not task_count_regression,
        "warnings": warnings,
        "task_count_regression_detected": task_count_regression,
        "current_task_count": current_task_count,
        "historical_max_task_count": max_seen_task_count,
        "current_done_count": current_done_count,
        "historical_max_done_count": max_seen_done_count,
        "provenance": {
            "task_counts": "estimated_live_state" if not task_count_regression else "estimated_live_state_degraded",
            "corrected_percent": "historical_max_from_audit_and_snapshots" if task_count_regression else "live_state",
            "last_good_source": last_good_source,
        },
        "corrected_overall_percent": corrected_percent,
    }


def _parse_json_argument(raw: Any, expected: str) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if expected == "object" and not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        if expected == "array" and not isinstance(parsed, list):
            raise ValueError("Expected JSON array")
        return parsed
    return {} if expected == "object" else []


def _supervisor_from_tool_args(args: Dict[str, Any]) -> Supervisor:
    project_root = str(args.get("project_root") or str(ROOT_DIR))
    extra_workers: List[ExtraWorker] = []
    raw_extra = args.get("extra_workers", [])
    if isinstance(raw_extra, list):
        for item in raw_extra:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            cli = str(item.get("cli", "")).strip()
            agent = str(item.get("agent", "")).strip()
            team_id = str(item.get("team_id", "")).strip()
            project = str(item.get("project_root", "")).strip()
            lane = str(item.get("lane", "default")).strip() or "default"
            if name and cli and agent and team_id and project:
                extra_workers.append(
                    ExtraWorker(
                        name=name,
                        cli=cli,
                        agent=agent,
                        team_id=team_id,
                        project_root=project,
                        lane=lane,
                    )
                )
    cfg = SupervisorConfig(
        project_root=project_root,
        leader_agent=str(args.get("leader_agent", "codex")),
        manager_interval=int(args.get("manager_interval", 20)),
        worker_interval=int(args.get("worker_interval", 25)),
        manager_cli_timeout=int(args.get("manager_cli_timeout", 300)),
        worker_cli_timeout=int(args.get("worker_cli_timeout", 600)),
        claude_project_root=str(args.get("claude_project_root", "")),
        gemini_project_root=str(args.get("gemini_project_root", "")),
        codex_project_root=str(args.get("codex_project_root", "")),
        wingman_project_root=str(args.get("wingman_project_root", "")),
        claude_team_id=str(args.get("claude_team_id", "")),
        gemini_team_id=str(args.get("gemini_team_id", "")),
        codex_team_id=str(args.get("codex_team_id", "")),
        wingman_team_id=str(args.get("wingman_team_id", "")),
        extra_workers=extra_workers,
    )
    return Supervisor(cfg)


def _run_supervisor_action(supervisor: Supervisor, action: str) -> Dict[str, Any]:
    # Supervisor methods print operator output. Suppress stdout to avoid
    # contaminating MCP JSON-RPC transport.
    with redirect_stdout(io.StringIO()):
        if action == "start":
            supervisor.start()
        elif action == "stop":
            supervisor.stop()
        elif action == "restart":
            supervisor.restart()
        elif action == "clean":
            supervisor.clean()
        else:
            raise ValueError(f"Unsupported supervisor action: {action}")
    return {
        "ok": True,
        "action": action,
        "project_root": supervisor.cfg.project_root,
        "leader_agent": supervisor.cfg.leader_agent,
        "processes": supervisor.status_json(),
    }


def handle_initialize(request_id: Any) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "agent-leader-orchestrator",
                "version": __version__,
            },
        },
    }


def handle_tools_list(request_id: Any) -> Dict[str, Any]:
    tools = [
        {
            "name": "orchestrator_guide",
            "description": "Return the orchestration playbook and exact MCP-only workflow for manager and team members.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "orchestrator_status",
            "description": "Show redacted status plus ready-to-paste live status report. When user asks for status updates, return live_status_text verbatim. Set ORCHESTRATOR_STATUS_VERBOSE_PATHS=1 for full paths.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "orchestrator_headless_start",
            "description": "Start headless supervisor lanes (manager/workers/watchdog) for this project without shell wrappers.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "leader_agent": {"type": "string", "description": "codex|claude_code|gemini"},
                    "manager_interval": {"type": "integer"},
                    "worker_interval": {"type": "integer"},
                    "manager_cli_timeout": {"type": "integer"},
                    "worker_cli_timeout": {"type": "integer"},
                    "claude_project_root": {"type": "string"},
                    "gemini_project_root": {"type": "string"},
                    "codex_project_root": {"type": "string"},
                    "wingman_project_root": {"type": "string"},
                    "claude_team_id": {"type": "string"},
                    "gemini_team_id": {"type": "string"},
                    "codex_team_id": {"type": "string"},
                    "wingman_team_id": {"type": "string"},
                    "extra_workers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "cli": {"type": "string"},
                                "agent": {"type": "string"},
                                "team_id": {"type": "string"},
                                "project_root": {"type": "string"},
                                "lane": {"type": "string"},
                            },
                            "required": ["name", "cli", "agent", "team_id", "project_root"],
                        },
                    },
                },
            },
        },
        {
            "name": "orchestrator_headless_stop",
            "description": "Stop headless supervisor lanes for this project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "leader_agent": {"type": "string", "description": "codex|claude_code|gemini"},
                    "claude_project_root": {"type": "string"},
                    "gemini_project_root": {"type": "string"},
                    "codex_project_root": {"type": "string"},
                    "wingman_project_root": {"type": "string"},
                    "claude_team_id": {"type": "string"},
                    "gemini_team_id": {"type": "string"},
                    "codex_team_id": {"type": "string"},
                    "wingman_team_id": {"type": "string"},
                    "extra_workers": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        {
            "name": "orchestrator_headless_status",
            "description": "Return machine-readable headless supervisor process status for this project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "leader_agent": {"type": "string", "description": "codex|claude_code|gemini"},
                    "claude_project_root": {"type": "string"},
                    "gemini_project_root": {"type": "string"},
                    "codex_project_root": {"type": "string"},
                    "wingman_project_root": {"type": "string"},
                    "claude_team_id": {"type": "string"},
                    "gemini_team_id": {"type": "string"},
                    "codex_team_id": {"type": "string"},
                    "wingman_team_id": {"type": "string"},
                    "extra_workers": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        {
            "name": "orchestrator_headless_restart",
            "description": "Restart headless supervisor lanes for this project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "leader_agent": {"type": "string", "description": "codex|claude_code|gemini"},
                    "claude_project_root": {"type": "string"},
                    "gemini_project_root": {"type": "string"},
                    "codex_project_root": {"type": "string"},
                    "wingman_project_root": {"type": "string"},
                    "claude_team_id": {"type": "string"},
                    "gemini_team_id": {"type": "string"},
                    "codex_team_id": {"type": "string"},
                    "wingman_team_id": {"type": "string"},
                    "extra_workers": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        {
            "name": "orchestrator_headless_clean",
            "description": "Clean stale pid/log artifacts for headless supervisor lanes in this project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "leader_agent": {"type": "string", "description": "codex|claude_code|gemini"},
                    "claude_project_root": {"type": "string"},
                    "gemini_project_root": {"type": "string"},
                    "codex_project_root": {"type": "string"},
                    "wingman_project_root": {"type": "string"},
                    "claude_team_id": {"type": "string"},
                    "gemini_team_id": {"type": "string"},
                    "codex_team_id": {"type": "string"},
                    "wingman_team_id": {"type": "string"},
                    "extra_workers": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        {
            "name": "orchestrator_doctor",
            "description": "Run actionable diagnostics for root/policy/auth/connectivity checks, including binding and identity verification hints.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "stale_after_seconds": {"type": "integer", "default": 600},
                },
            },
        },
        {
            "name": "orchestrator_parity_smoke",
            "description": "Run an operational parity smoke test checking lifecycle, status, and task flow, returning a diagnostic report.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "orchestrator_get_roles",
            "description": "Get current orchestrator role assignments (leader, team_members). Default leader is codex via policy unless changed.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "orchestrator_set_role",
            "description": "Set runtime role for an agent. role=leader or role=team_member. This allows non-codex leaders when desired.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "role": {"type": "string", "description": "leader|team_member"},
                    "source": {"type": "string"},
                    "instance_id": {"type": "string", "description": "Optional instance_id to bind when assigning leader role."},
                    "source_instance_id": {"type": "string", "description": "Optional source instance_id for leader-instance auth checks."},
                },
                "required": ["agent", "role", "source"],
            },
        },
        {
            "name": "orchestrator_list_audit_logs",
            "description": "List append-only MCP audit records (tool calls, status, args, results/errors).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 100},
                    "tool": {"type": "string"},
                    "status": {"type": "string", "description": "ok|error"},
                },
            },
        },
        {
            "name": "orchestrator_live_status_report",
            "description": "Generate the manager's live status update in the standard percentage + pipeline format. Call every 10 minutes (600s).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "overall_percent": {"type": "integer"},
                    "phase_1_percent": {"type": "integer"},
                    "phase_2_percent": {"type": "integer"},
                    "phase_3_percent": {"type": "integer"},
                    "backend_task_id": {"type": "string"},
                    "backend_percent": {"type": "integer"},
                    "frontend_task_id": {"type": "string"},
                    "frontend_percent": {"type": "integer"},
                    "qa_percent": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "orchestrator_register_agent",
            "description": "Register agent/tenant in the collaboration pool.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "default": {},
                        "description": "Recommended keys: client, model, version, cwd, session_id, host, platform.",
                    },
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_heartbeat",
            "description": "Update last-seen heartbeat for agent/tenant.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "default": {},
                        "description": "Optional runtime updates (e.g., current_task, model alias, cwd).",
                    },
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_connect_team_members",
            "description": "Manager one-shot team member activation handshake. Returns connected only for verified, same-project team members.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Manager/source agent id (usually codex)."},
                    "team_members": {"type": "array", "items": {"type": "string"}, "description": "Target team member agent IDs."},
                    "timeout_seconds": {"type": "integer", "default": 60},
                    "poll_interval_seconds": {"type": "integer", "default": 2},
                    "stale_after_seconds": {"type": "integer", "default": 600},
                },
                "required": ["source", "team_members"],
            },
        },
        {
            "name": "orchestrator_connect_to_leader",
            "description": "Team member one-shot attach flow with identity verification. Connection is considered valid only when identity is verified for this project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Team member agent id (e.g., claude_code, gemini)."},
                    "metadata": {
                        "type": "object",
                        "default": {},
                        "description": "Identity payload. Required for verified=true: client, model, cwd, permissions_mode, sandbox_mode, session_id, connection_id, server_version, verification_source.",
                    },
                    "status": {"type": "string", "default": "idle"},
                    "announce": {"type": "boolean", "default": True},
                    "source": {"type": "string", "description": "Caller/source agent id. Must match agent for verified connection."},
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_list_agents",
            "description": "List discovered tenants in pool with active/offline status plus identity and verification details.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "default": False},
                    "stale_after_seconds": {"type": "integer", "default": 600},
                },
            },
        },
        {
            "name": "orchestrator_discover_agents",
            "description": "Deep discovery view: registered agents plus inferred tenants, including identity and verification details.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "default": False},
                    "stale_after_seconds": {"type": "integer", "default": 600},
                },
            },
        },
        {
            "name": "orchestrator_bootstrap",
            "description": "Initialize orchestrator runtime state for a new project session. Call once before creating tasks.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "orchestrator_create_task",
            "description": "Create a task and assign owner via policy routing unless owner override is provided. Use for every delegated unit of work.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Concise task title."},
                    "workstream": {
                        "type": "string",
                        "description": "One of: backend|frontend|qa|devops|default. Controls policy-based assignment.",
                    },
                    "description": {
                        "type": "string",
                        "default": "",
                        "description": "Detailed implementation brief, constraints, and dependencies.",
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "description": "Definition of done checklist used by manager validation.",
                        "items": {"type": "string"},
                    },
                    "owner": {"type": "string", "description": "Optional explicit owner override"},
                    "risk": {"type": "string", "description": "Lean mode risk bucket: low|medium|high"},
                    "test_plan": {"type": "string", "description": "Lean mode test plan: smoke|targeted|full"},
                    "doc_impact": {"type": "string", "description": "Lean mode doc impact: none|readme|runbook|roadmap"},
                    "project_root": {"type": "string", "description": "Optional project root override for multi-project manager mode."},
                    "project_name": {"type": "string", "description": "Optional project name tag override."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional content tags. project:* and workstream:* are auto-added."},
                    "team_id": {"type": "string", "description": "Optional team id tag for multi-team routing."},
                },
                "required": ["title", "workstream"],
            },
        },
        {
            "name": "orchestrator_dedupe_tasks",
            "description": "Close duplicate open tasks (same normalized title/workstream/owner), keeping oldest canonical task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Actor applying dedupe (usually manager).", "default": "codex"},
                },
            },
        },
        {
            "name": "orchestrator_list_tasks",
            "description": "List tasks, optionally filtered by status, owner, or lane. Use for planning dashboards and polling.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Optional status filter (assigned|in_progress|reported|done|bug_open|blocked)."},
                    "owner": {"type": "string", "description": "Optional owner filter (codex|claude_code|gemini)."},
                    "project_name": {"type": "string", "description": "Optional project_name filter."},
                    "project_root": {"type": "string", "description": "Optional project_root filter."},
                    "team_id": {"type": "string", "description": "Optional team_id filter."},
                    "lane": {"type": "string", "description": "Optional lane filter (e.g., 'wingman' for tasks awaiting review)."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags filter (all tags must match)."},
                },
            },
        },
        {
            "name": "orchestrator_get_tasks_for_agent",
            "description": "Get tasks for a specific agent. Team members should use this when they need full queue visibility.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "codex|claude_code|gemini"},
                    "status": {"type": "string", "description": "Optional status filter"},
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_claim_next_task",
            "description": "Claim next task for an agent and move it to in_progress. Team members should call this before coding.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "codex|claude_code|gemini"},
                    "instance_id": {"type": "string", "description": "Optional explicit worker instance id for same-agent multi-session claims."},
                    "team_id": {"type": "string", "description": "Optional team_id scope for multi-team routing."},
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_renew_task_lease",
            "description": "Renew an active task lease for the task owner and current worker instance.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent": {"type": "string"},
                    "lease_id": {"type": "string"},
                    "instance_id": {"type": "string", "description": "Optional explicit worker instance id for same-agent multi-session lease renewal."},
                },
                "required": ["task_id", "agent", "lease_id"],
            },
        },
        {
            "name": "orchestrator_set_claim_override",
            "description": "Manager-enforced claim target: force next claim by agent to pick specific task_id first.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "task_id": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["agent", "task_id", "source"],
            },
        },
        {
            "name": "orchestrator_update_task_status",
            "description": "Update task lifecycle status (in_progress, blocked, etc.) with note metadata. Do not use for completion: use orchestrator_submit_report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string"},
                    "source": {"type": "string", "description": "Agent or manager writing the state change"},
                    "note": {"type": "string", "default": ""},
                },
                "required": ["task_id", "status", "source"],
            },
        },
        {
            "name": "orchestrator_submit_report",
            "description": "Submit team_member delivery report. Mandatory before claiming task completion. Rejects wrong owner/task mismatches.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID being reported."},
                    "agent": {"type": "string", "description": "Reporter agent id (must match task owner)."},
                    "commit_sha": {"type": "string", "description": "Commit containing implementation."},
                    "status": {"type": "string", "description": "done|blocked|needs_review"},
                    "test_summary": {
                        "type": "object",
                        "description": "Required executed test summary.",
                        "properties": {
                            "command": {"type": "string", "description": "Exact test command run."},
                            "passed": {"type": "integer", "description": "Count of passing tests."},
                            "failed": {"type": "integer", "description": "Count of failing tests."},
                        },
                        "required": ["command", "passed", "failed"],
                    },
                    "artifacts": {"type": "array", "items": {"type": "string"}, "description": "Optional changed files / evidence."},
                    "review_gate": {
                        "type": "object",
                        "description": "Optional wingman review decision metadata (required/status/reviewer_* fields).",
                    },
                    "notes": {"type": "string", "default": "", "description": "Implementation summary and residual risks."},
                },
                "required": ["task_id", "agent", "commit_sha", "status", "test_summary"],
            },
        },
        {
            "name": "orchestrator_validate_task",
            "description": "Manager validation step. passed=true closes task (and closes related bugs); passed=false opens/keeps bug loop.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "notes": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["task_id", "passed", "notes", "source"],
            },
        },
        {
            "name": "orchestrator_list_bugs",
            "description": "List validation-generated bugs, optionally filtered by status/owner.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "owner": {"type": "string"},
                },
            },
        },
        {
            "name": "orchestrator_raise_blocker",
            "description": "Team member raises structured blocker requiring manager/user input. Marks task as blocked.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent": {"type": "string", "description": "Task owner agent id."},
                    "question": {"type": "string", "description": "Exact question for manager/user."},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit choices."},
                    "severity": {"type": "string", "description": "low|medium|high", "default": "medium"},
                },
                "required": ["task_id", "agent", "question"],
            },
        },
        {
            "name": "orchestrator_list_blockers",
            "description": "List blockers raised by team members. Manager polls this to ask user for missing input.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "open|resolved"},
                    "agent": {"type": "string", "description": "Optional blocker agent filter."},
                },
            },
        },
        {
            "name": "orchestrator_resolve_blocker",
            "description": "Resolve blocker with manager/user decision and resume blocked task to in_progress.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "blocker_id": {"type": "string"},
                    "resolution": {"type": "string", "description": "Answer/decision from manager/user."},
                    "source": {"type": "string", "description": "Resolver id (usually codex)."},
                },
                "required": ["blocker_id", "resolution", "source"],
            },
        },
        {
            "name": "orchestrator_publish_event",
            "description": "Publish an event to the collaboration bus. Use for async notifications and coordination messages.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Event type, e.g., task.note, manager.announcement, team_member.ready."},
                    "source": {"type": "string", "description": "Agent/source publishing the event."},
                    "payload": {"type": "object", "description": "Arbitrary event payload body.", "default": {}},
                    "audience": {"type": "array", "items": {"type": "string"}, "description": "Optional target agents. Omit for broadcast."},
                },
                "required": ["type", "source"],
            },
        },
        {
            "name": "orchestrator_poll_events",
            "description": "Poll collaboration events for an agent with cursor-based replay. Supports optional long-poll timeout.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Polling agent id (codex|claude_code|gemini)."},
                    "cursor": {"type": "integer", "description": "Optional start offset. Defaults to stored agent cursor."},
                    "limit": {"type": "integer", "default": 50},
                    "timeout_ms": {"type": "integer", "default": 0, "description": "Wait time before returning when no new events."},
                    "auto_advance": {"type": "boolean", "default": True, "description": "Advance stored cursor automatically."},
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_ack_event",
            "description": "Acknowledge a specific event id for an agent.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "event_id": {"type": "string"},
                },
                "required": ["agent", "event_id"],
            },
        },
        {
            "name": "orchestrator_get_agent_cursor",
            "description": "Get current event cursor offset for an agent.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_manager_cycle",
            "description": "Run one manager cycle automatically: validate reported tasks first, auto-connect stale team members with active tasks, then summarize remaining work by owner.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "strict": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, fail validation when status != done OR failed tests > 0. If false, same default behavior.",
                    }
                },
            },
        },
        {
            "name": "orchestrator_reassign_stale_tasks",
            "description": "Re-advertise and reassign stale-owner tasks to other active team members so execution continues when one team member is degraded.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "default": "codex"},
                    "stale_after_seconds": {"type": "integer", "default": 600},
                    "include_blocked": {"type": "boolean", "default": True},
                },
            },
        },
        {
            "name": "orchestrator_decide_architecture",
            "description": "Record equal-rights architecture decision and create ADR artifact under decisions/.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "votes": {"type": "object", "description": "{agent: option}"},
                    "rationale": {"type": "object", "description": "{agent: rationale}"},
                },
                "required": ["topic", "options", "votes"],
            },
        },
    ]

    return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}


def _ok(request_id: Any, payload: Any) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": _json_text(payload),
                }
            ]
        },
    }


_AUDIT_REDACT_KEYS = {"token", "secret", "password", "api_key", "authorization", "auth"}


def _sanitize_for_audit(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if any(part in key_l for part in _AUDIT_REDACT_KEYS):
                cleaned[key] = "***redacted***"
            else:
                cleaned[key] = _sanitize_for_audit(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_for_audit(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _audit_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    status: str,
    result: Optional[Any] = None,
    error: Optional[str] = None,
) -> None:
    try:
        ORCH.bus.append_audit(
            {
                "category": "mcp_tool_call",
                "tool": tool_name,
                "status": status,
                "args": _sanitize_for_audit(args),
                "result": _sanitize_for_audit(result) if result is not None else None,
                "error": error,
            }
        )
    except Exception:
        pass


def _ok_and_audit(request_id: Any, tool_name: str, args: Dict[str, Any], payload: Any) -> Dict[str, Any]:
    _audit_tool_call(tool_name=tool_name, args=args, status="ok", result=payload)
    return _ok(request_id, payload)


def _guide_payload() -> Dict[str, Any]:
    roles = ORCH.get_roles()
    return {
        "purpose": "MCP-first multi-agent orchestration for manager/team member loops.",
        "roles": {
            "manager": roles.get("leader"),
            "team_member_agents": ["claude_code", "gemini", "codex"],
            "configured_roles": roles,
        },
        "required_sequences": {
            "manager": [
                "orchestrator_bootstrap",
                "orchestrator_create_task (repeat per work unit)",
                "orchestrator_list_blockers (ask user for required inputs)",
                "orchestrator_resolve_blocker (write user decision back)",
                "orchestrator_manager_cycle (poll until no pending tasks)",
                "orchestrator_decide_architecture (when a decision is required)",
            ],
            "team_member": [
                "orchestrator_claim_next_task",
                "orchestrator_poll_events (wait for manager instructions/updates)",
                "implement + test + commit",
                "orchestrator_submit_report",
                "orchestrator_raise_blocker (when blocked by missing input/access/decision)",
                "ask manager to validate",
            ],
        },
        "report_contract": {
            "required_fields": [
                "task_id",
                "agent",
                "commit_sha",
                "status",
                "test_summary.command",
                "test_summary.passed",
                "test_summary.failed",
            ]
        },
        "notes": [
            "Never claim done without orchestrator_submit_report.",
            "Manager should validate every reported task.",
            "Validation failure opens bug loop; pass closes task and related bugs.",
            "Use orchestrator_raise_blocker for any user-dependent decision or access issue.",
        ],
    }


def _manager_cycle(strict: bool) -> Dict[str, Any]:
    stale_after_seconds = ORCH._heartbeat_timeout_seconds()
    tasks = ORCH.list_tasks()
    processed: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    retry_base_seconds = int(ORCH.policy.triggers.get("report_retry_base_seconds", 15))
    retry_base_seconds = max(3, min(retry_base_seconds, 300))
    retry_max_seconds = int(ORCH.policy.triggers.get("report_retry_max_backoff_seconds", 300))
    retry_max_seconds = max(retry_base_seconds, min(retry_max_seconds, 3600))
    retry_max_attempts = int(ORCH.policy.triggers.get("report_retry_max_attempts", 20))
    retry_max_attempts = max(1, min(retry_max_attempts, 100))

    retry_queue = ORCH.process_report_retry_queue(
        max_attempts=retry_max_attempts,
        base_backoff_seconds=retry_base_seconds,
        max_backoff_seconds=retry_max_seconds,
        limit=20,
    )

    for task in tasks:
        if task.get("status") != "reported":
            continue

        report_path = ORCH.bus.reports_dir / f"{task['id']}.json"
        if not report_path.exists():
            result = ORCH.validate_task(
                task_id=task["id"],
                passed=False,
                notes="Missing report file",
                source=ORCH.manager_agent(),
            )
            processed.append({"task_id": task["id"], "passed": False, "result": result})
            continue

        report = json.loads(report_path.read_text(encoding="utf-8"))
        summary = report.get("test_summary", {}) or {}
        failed_tests = int(summary.get("failed", 1))
        has_command = bool(str(summary.get("command", "")).strip())
        report_status = str(report.get("status", "blocked")).strip().lower()
        has_commit = bool(str(report.get("commit_sha", "")).strip())
        strict_requirements_met = bool(has_commit and has_command) if strict else True
        review_gate = task.get("review_gate") if isinstance(task.get("review_gate"), dict) else {}
        review_status = str(review_gate.get("status", "")).strip().lower()
        review_approved = review_status in {"approved", "waived"}
        review_rejected = review_status == "rejected"

        passed = failed_tests == 0 and strict_requirements_met and (
            report_status == "done" or (report_status == "needs_review" and review_approved)
        )
        defer_for_manual_review = (
            report_status == "needs_review"
            and not review_approved
            and not review_rejected
            and failed_tests == 0
            and strict_requirements_met
        )
        if defer_for_manual_review:
            deferred.append(
                {
                    "task_id": task["id"],
                    "status": report_status,
                    "review_status": review_status or "unknown",
                    "reason": "awaiting_manual_review_decision",
                }
            )
            continue

        notes = (
            f"Auto manager cycle accepted report {report.get('commit_sha', 'unknown')}"
            if passed
            else (
                "Auto manager cycle rejected report "
                f"status={report_status}, failed_tests={failed_tests}, has_command={has_command}, "
                f"has_commit={has_commit}, review_status={review_status or 'none'}"
            )
        )
        result = ORCH.validate_task(
            task_id=task["id"],
            passed=passed,
            notes=notes,
            source=ORCH.manager_agent(),
        )
        processed.append({"task_id": task["id"], "passed": passed, "result": result})

    reconnect_statuses = {"in_progress", "blocked"}
    reconnect_candidates: List[str] = []
    seen_candidates = set()
    team_members = set(ORCH.get_roles().get("team_members", []) or [])
    for task in ORCH.list_tasks():
        if task.get("status") not in reconnect_statuses:
            continue
        owner = str(task.get("owner", "")).strip()
        if not owner or owner == ORCH.manager_agent():
            continue
        if team_members and owner not in team_members:
            continue
        if owner in seen_candidates:
            continue
        diag = ORCH._team_member_connect_diagnostic(team_member=owner, stale_after_seconds=stale_after_seconds)
        if not bool(diag.get("active")):
            reconnect_candidates.append(owner)
            seen_candidates.add(owner)

    auto_connect: Dict[str, Any] = {
        "attempted": False,
        "requested": reconnect_candidates,
        "status": "skipped",
        "reason": "no_stale_team_members_with_active_tasks",
    }
    if reconnect_candidates:
        reconnect_timeout = int(ORCH.policy.triggers.get("manager_cycle_auto_connect_timeout_seconds", 15))
        reconnect_timeout = max(5, min(reconnect_timeout, 60))
        reconnect_poll = int(ORCH.policy.triggers.get("manager_cycle_auto_connect_poll_seconds", 2))
        reconnect_poll = max(1, min(reconnect_poll, 10))
        connect_result = ORCH.connect_team_members(
            source=ORCH.manager_agent(),
            team_members=reconnect_candidates,
            timeout_seconds=reconnect_timeout,
            poll_interval_seconds=reconnect_poll,
            stale_after_seconds=stale_after_seconds,
        )
        auto_connect = {
            "attempted": True,
            "requested": reconnect_candidates,
            "status": connect_result.get("status", "timeout"),
            "connected": connect_result.get("connected", []),
            "missing": connect_result.get("missing", []),
            "elapsed_seconds": connect_result.get("elapsed_seconds", 0),
            "timeout_seconds": reconnect_timeout,
        }

    blocker_stale_seconds = int(ORCH.policy.triggers.get("blocker_auto_resolve_stale_seconds", 3600))
    auto_resolved_blockers = ORCH.auto_resolve_stale_blockers(
        source=ORCH.manager_agent(),
        stale_after_seconds=blocker_stale_seconds,
    )

    stale_reassignments = ORCH.reassign_stale_tasks_to_active_workers(
        source=ORCH.manager_agent(),
        stale_after_seconds=stale_after_seconds,
        include_blocked=True,
    )
    claim_override_noops = ORCH.emit_stale_claim_override_noops(
        source=ORCH.manager_agent(),
        timeout_seconds=int(ORCH.policy.triggers.get("manager_execute_noop_timeout_seconds", 60)),
    )
    lease_recoveries = ORCH.recover_expired_task_leases(
        source=ORCH.manager_agent(),
        stale_after_seconds=stale_after_seconds,
    )
    stale_requeues = ORCH.requeue_stale_in_progress_tasks(stale_after_seconds=stale_after_seconds)

    latest_tasks = ORCH.list_tasks()
    open_blockers = ORCH.list_blockers(status="open")
    by_owner: Dict[str, Dict[str, int]] = {}
    pending_statuses = {"assigned", "in_progress", "reported", "bug_open", "blocked"}
    for task in latest_tasks:
        owner = task.get("owner", "unknown")
        owner_bucket = by_owner.setdefault(owner, {"pending": 0, "done": 0})
        if task.get("status") in pending_statuses:
            owner_bucket["pending"] += 1
        if task.get("status") == "done":
            owner_bucket["done"] += 1

    # Republish compact task contract digest each manager cycle to reduce context drift.
    contracts = [
        {
            "task_id": task.get("id"),
            "owner": task.get("owner"),
            "title": task.get("title"),
            "status": task.get("status"),
            "acceptance_criteria": task.get("acceptance_criteria", []),
        }
        for task in latest_tasks
        if task.get("status") in pending_statuses
    ]
    ORCH.publish_event(
        event_type="manager.task_contracts",
        source=ORCH.manager_agent(),
        payload={"contracts": contracts},
    )

    # Evaluate unsupervised stop/escalation policy.
    stop_policy = ORCH.evaluate_stop_policy()
    # Inject deploy-mismatch trigger from MCP-layer runtime checks.
    if stop_policy.get("policy_enabled") and ORCH.policy.triggers.get("stop_on_deploy_mismatch", False):
        rsc = _runtime_source_consistency()
        if not rsc["ok"]:
            deploy_trigger = {
                "code": "deploy_mismatch",
                "severity": "critical",
                "detail": "; ".join(rsc.get("warnings", ["runtime source mismatch"])),
            }
            stop_policy["triggers"].append(deploy_trigger)
            stop_policy["reason_codes"].append("deploy_mismatch")
            stop_policy["stop_required"] = True

    return {
        "processed_reports": processed,
        "deferred_reports": deferred,
        "report_retry_queue": retry_queue,
        "auto_connect": auto_connect,
        "auto_resolved_blockers": auto_resolved_blockers,
        "stale_reassignments": stale_reassignments,
        "claim_override_noops": claim_override_noops,
        "lease_recoveries": lease_recoveries,
        "stale_requeues": stale_requeues,
        "remaining_by_owner": by_owner,
        "pending_total": sum(bucket["pending"] for bucket in by_owner.values()),
        "open_blockers": open_blockers,
        "stop_policy": stop_policy,
    }


def _auto_manager_loop() -> None:
    interval_seconds = int(os.getenv("ORCHESTRATOR_AUTO_MANAGER_CYCLE_SECONDS", "15"))
    interval_seconds = max(5, min(interval_seconds, 300))
    lock_path = ORCH.state_dir / ".manager_auto_cycle.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = lock_path.open("a+", encoding="utf-8")
    has_lock = False

    while not _AUTO_LOOP_STOP.is_set():
        if not has_lock:
            if fcntl is None:
                has_lock = True
            else:
                try:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    has_lock = True
                except BlockingIOError:
                    has_lock = False
        if has_lock:
            try:
                _manager_cycle(strict=True)
            except Exception as exc:  # pragma: no cover - defensive loop safety
                print(f"auto-manager-cycle error: {exc}", file=sys.stderr, flush=True)
        _AUTO_LOOP_STOP.wait(interval_seconds)

    if has_lock and fcntl is not None:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
    lock_fh.close()


def _start_auto_manager_loop() -> None:
    global _AUTO_LOOP_THREAD
    if _AUTO_LOOP_THREAD is not None and _AUTO_LOOP_THREAD.is_alive():
        return
    _AUTO_LOOP_THREAD = threading.Thread(
        target=_auto_manager_loop,
        name="orchestrator-auto-manager-cycle",
        daemon=True,
    )
    _AUTO_LOOP_THREAD.start()


def _percent(done: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round((done / total) * 100))


def _parse_iso(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _seconds_between(start: Any, end: Any) -> Optional[int]:
    s = _parse_iso(start)
    e = _parse_iso(end)
    if s is None or e is None:
        return None
    try:
        return max(0, int((e - s).total_seconds()))
    except Exception:
        return None


def _avg_int(values: List[int]) -> Optional[int]:
    if not values:
        return None
    return int(round(sum(values) / len(values)))


def _collect_commit_metrics(commit_sha: str) -> Dict[str, Any]:
    sha = str(commit_sha).strip()
    if not sha:
        return {"collected": False, "error": "empty_commit_sha", "provenance": "git"}
    try:
        proc = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--numstat", "-r", sha],
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {"collected": False, "error": str(exc), "provenance": "git"}
    if proc.returncode != 0:
        return {
            "collected": False,
            "error": (proc.stderr or proc.stdout or f"git rc={proc.returncode}").strip(),
            "provenance": "git",
        }
    files_changed = 0
    lines_added = 0
    lines_deleted = 0
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_s, del_s, _path = parts[0], parts[1], parts[2]
        files_changed += 1
        if add_s.isdigit():
            lines_added += int(add_s)
        if del_s.isdigit():
            lines_deleted += int(del_s)
    return {
        "collected": True,
        "commit_sha": sha,
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "net_lines": lines_added - lines_deleted,
        "provenance": "git",
    }


def _report_metrics_snapshot() -> Dict[str, Any]:
    reports_dir = ORCH.bus.reports_dir
    totals = {
        "reports_total": 0,
        "reports_with_commit_metrics": 0,
        "unique_commits": 0,
        "files_changed_total": 0,
        "lines_added_total": 0,
        "lines_deleted_total": 0,
        "net_lines_total": 0,
    }
    by_agent: Dict[str, Dict[str, int]] = {}
    seen_commits = set()
    try:
        report_files = sorted(reports_dir.glob("*.json"))
    except Exception:
        report_files = []
    for path in report_files:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        totals["reports_total"] += 1
        agent = str(item.get("agent", "unknown"))
        bucket = by_agent.setdefault(
            agent,
            {
                "reports": 0,
                "commits": 0,
                "files_changed": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "net_lines": 0,
            },
        )
        bucket["reports"] += 1
        commit_sha = str(item.get("commit_sha", "")).strip()
        if commit_sha:
            seen_commits.add(commit_sha)
        cm = item.get("commit_metrics")
        if not isinstance(cm, dict) or not cm.get("collected"):
            continue
        totals["reports_with_commit_metrics"] += 1
        bucket["commits"] += 1
        for src, dst in [
            ("files_changed", "files_changed"),
            ("lines_added", "lines_added"),
            ("lines_deleted", "lines_deleted"),
            ("net_lines", "net_lines"),
        ]:
            value = cm.get(src)
            if isinstance(value, int):
                totals[f"{dst}_total"] += value
                bucket[dst] += value
    totals["unique_commits"] = len(seen_commits)
    return {"totals": totals, "by_agent": by_agent, "provenance": "report_commit_metrics"}


def _aggregate_team_lanes(tasks: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Aggregate task counts by team_id and status for per-team lane visibility."""
    team_lanes: Dict[str, Dict[str, int]] = {}
    for task in tasks:
        team_id = task.get("team_id")
        if not team_id:
            continue
        if team_id not in team_lanes:
            team_lanes[team_id] = {"total": 0}
        team_lanes[team_id]["total"] += 1
        status = task.get("status", "unknown")
        team_lanes[team_id][status] = team_lanes[team_id].get(status, 0) + 1
    return team_lanes


def _status_metrics(tasks: List[Dict[str, Any]], bugs_open: List[Dict[str, Any]], blockers_open: List[Dict[str, Any]]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    done_tasks = [t for t in tasks if t.get("status") == "done"]
    reported_tasks = [t for t in tasks if t.get("status") == "reported"]
    in_progress_tasks = [t for t in tasks if t.get("status") == "in_progress"]
    blocked_tasks = [t for t in tasks if t.get("status") == "blocked"]
    superseded_tasks = [t for t in tasks if t.get("status") == "superseded"]
    archived_tasks = [t for t in tasks if t.get("status") == "archived"]

    time_to_claim = [v for v in (_seconds_between(t.get("assigned_at") or t.get("created_at"), t.get("claimed_at")) for t in tasks) if v is not None]
    time_to_report = [v for v in (_seconds_between(t.get("claimed_at"), t.get("reported_at")) for t in tasks) if v is not None]
    time_to_validate = [v for v in (_seconds_between(t.get("reported_at"), t.get("validated_at")) for t in tasks) if v is not None]

    stale_in_progress = 0
    stale_reported = 0
    for task in in_progress_tasks:
        ts = _parse_iso(task.get("claimed_at") or task.get("updated_at"))
        if ts and (now - ts).total_seconds() > 1800:
            stale_in_progress += 1
    for task in reported_tasks:
        ts = _parse_iso(task.get("reported_at") or task.get("updated_at"))
        if ts and (now - ts).total_seconds() > 600:
            stale_reported += 1

    report_metrics = _report_metrics_snapshot()
    return {
        "throughput": {
            "tasks_total": len(tasks),
            "tasks_done": len(done_tasks),
            "tasks_reported": len(reported_tasks),
            "tasks_in_progress": len(in_progress_tasks),
            "tasks_blocked": len(blocked_tasks),
            "tasks_superseded": len(superseded_tasks),
            "tasks_archived": len(archived_tasks),
            "completion_rate_percent": _percent(len(done_tasks), len(tasks)),
        },
        "timings_seconds": {
            "avg_time_to_claim": _avg_int(time_to_claim),
            "avg_time_to_report": _avg_int(time_to_report),
            "avg_time_to_validate": _avg_int(time_to_validate),
        },
        "reliability": {
            "open_bugs": len(bugs_open),
            "open_blockers": len(blockers_open),
            "stale_in_progress_over_30m": stale_in_progress,
            "stale_reported_over_10m": stale_reported,
        },
        "code_output": {
            **report_metrics.get("totals", {}),
            "by_agent": report_metrics.get("by_agent", {}),
            "provenance": report_metrics.get("provenance"),
        },
        "efficiency": {
            "energy_mode": "not_yet_instrumented",
            "metrics_provenance": "task_state + report_commit_metrics",
        },
    }


def _suggest_recovery_actions(
    tasks: List[Dict[str, Any]], 
    blockers: List[Dict[str, Any]], 
    bugs: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """Analyze state to suggest recovery actions for the operator."""
    actions = []
    now = datetime.now(timezone.utc)
    
    # 1. Stale in_progress tasks
    for task in tasks:
        if task.get("status") == "in_progress":
            claimed_at = _parse_iso(task.get("claimed_at"))
            if claimed_at:
                age = (now - claimed_at).total_seconds()
                if age > 1800: # 30 minutes
                    actions.append({
                        "type": "stale_task",
                        "task_id": task["id"],
                        "message": f"Task {task['id']} has been in_progress for {int(age//60)}m. If the agent is dead, reassign it.",
                        "action": f"orchestrator_reassign_stale_tasks(stale_after_seconds=600)"
                    })

    # 2. Open blockers
    for blk in blockers:
        if blk.get("status") == "open":
            actions.append({
                "type": "open_blocker",
                "blocker_id": blk["id"],
                "message": f"Blocker {blk['id']} is stopping Task {blk.get('task_id')}. Resolve it to resume work.",
                "action": f"orchestrator_resolve_blocker(blocker_id='{blk['id']}', resolution='...', source='operator')"
            })

    # 3. Open bugs
    for bug in bugs:
        if bug.get("status") == "open":
            actions.append({
                "type": "open_bug",
                "bug_id": bug["id"],
                "message": f"Bug {bug['id']} was found in Task {bug.get('source_task')}. Ensure an agent is assigned to fix it.",
                "action": f"orchestrator_list_tasks(owner='{bug.get('owner')}')"
            })

    # 4. No active leader
    # (Note: this check is handled by higher-level status but good to have here too)

    return actions


def _live_status_report(args: Dict[str, Any]) -> Dict[str, Any]:
    tasks = ORCH.list_tasks()
    blockers_open = ORCH.list_blockers(status="open")
    bugs_open = ORCH.list_bugs(status="open")
    roles = ORCH.get_roles()
    agents_all = ORCH.list_agents(active_only=False)
    by_agent = {item.get("agent"): item for item in agents_all}

    total_tasks = len(tasks)
    done_tasks = len([task for task in tasks if task.get("status") == "done"])
    reported_tasks = [task for task in tasks if task.get("status") == "reported"]
    reported_count = len(reported_tasks)
    overall_auto = _percent(done_tasks, total_tasks)

    # Wingman Lane Visibility: tasks with review_gate status 'pending' or 'rejected'
    wingman_pending = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "pending"]
    wingman_rejected = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "rejected"]
    wingman_count = len(wingman_pending) + len(wingman_rejected)

    recovery_actions = _suggest_recovery_actions(tasks, blockers_open, bugs_open)

    backend_tasks = [task for task in tasks if task.get("workstream") == "backend"]
    frontend_tasks = [task for task in tasks if task.get("workstream") == "frontend"]
    backend_done = len([task for task in backend_tasks if task.get("status") == "done"])
    frontend_done = len([task for task in frontend_tasks if task.get("status") == "done"])
    backend_auto = _percent(backend_done, len(backend_tasks))
    frontend_auto = _percent(frontend_done, len(frontend_tasks))

    backend_focus = next((task for task in backend_tasks if task.get("status") != "done"), None)
    if backend_focus is None and backend_tasks:
        backend_focus = backend_tasks[-1]

    frontend_focus = next((task for task in frontend_tasks if task.get("status") != "done"), None)
    if frontend_focus is None and frontend_tasks:
        frontend_focus = frontend_tasks[-1]

    overall = int(args.get("overall_percent", overall_auto))
    phase_1 = int(args.get("phase_1_percent", overall))
    phase_2 = int(args.get("phase_2_percent", 0))
    phase_3 = int(args.get("phase_3_percent", 0))

    backend_percent = int(args.get("backend_percent", backend_auto))
    frontend_percent = int(args.get("frontend_percent", frontend_auto))
    qa_percent = int(args.get("qa_percent", overall_auto))

    backend_task_id = args.get("backend_task_id")
    if not backend_task_id and backend_focus:
        backend_task_id = backend_focus.get("id")
    if not backend_task_id:
        backend_task_id = "n/a"

    frontend_task_id = args.get("frontend_task_id")
    if not frontend_task_id and frontend_focus:
        frontend_task_id = frontend_focus.get("id")
    if not frontend_task_id:
        frontend_task_id = "n/a"

    # Unified Header for both Interactive and Headless
    leader = str(roles.get("leader", "codex"))
    team = ", ".join(sorted(roles.get("team_members", []) or []))
    status_state = "Active" if any(a.get("status") == "active" for a in agents_all) else "Idle"
    in_progress_count = len([t for t in tasks if t.get("status") == "in_progress"])
    assigned_count = len([t for t in tasks if t.get("status") == "assigned"])

    lines = [
        f"ORCHESTRATOR STATUS: {status_state}",
        f"PROJECT: {ROOT_DIR}",
        f"LEADER: {leader} | TEAM: {team or 'none'}",
        f"PIPELINE: {total_tasks} Tasks | {assigned_count} Assigned | {in_progress_count} IP | {reported_count} Review | {done_tasks} Done",
        f"BLOCKERS: {len(blockers_open)} Open | BUGS: {len(bugs_open)} Open",
    ]
    if wingman_count > 0 or "ccm" in by_agent or "wingman" in team.lower():
        wingman_agent = "ccm" if "ccm" in by_agent else "none"
        wingman_status = by_agent.get(wingman_agent, {}).get("status", "offline") if wingman_agent != "none" else "n/a"
        lines.append(f"WINGMAN LANE: {wingman_agent} [{wingman_status}] | {wingman_count} Tasks Awaiting Review")
    
    lines.extend([
        "",
        "Progress details:",
        f"- Overall project: {overall}%",
        f"- Phase 1 (Architecture + Vertical Slice): {phase_1}%",
        f"- Phase 2 (Content Pipeline): {phase_2}%",
        f"- Phase 3 (Full Production): {phase_3}%",
        f"- Backend vertical slice ({backend_task_id}): {backend_percent}%",
        f"- Frontend vertical slice ({frontend_task_id}): {frontend_percent}%",
        f"- QA/validation completion: {qa_percent}%",
        "",
        "Pipeline health:",
        f"- Reported tasks: {reported_count}",
        f"- Open blockers: {len(blockers_open)}",
        f"- Open bugs: {len(bugs_open)}",
    ])

    # Team member operational summary for manager-friendly status checks.
    lines.extend(["", "Team members:"])
    role_by_agent: Dict[str, str] = {}
    leader = str(roles.get("leader", ""))
    if leader:
        role_by_agent[leader] = "manager"
    for member in roles.get("team_members", []) or []:
        if isinstance(member, str) and member and member not in role_by_agent:
            role_by_agent[member] = "team member"

    # Include discovered agents even if roles file doesn't list them yet.
    all_agent_names = sorted({*(role_by_agent.keys()), *(a for a in by_agent.keys() if isinstance(a, str))})
    for agent in all_agent_names:
        info = by_agent.get(agent, {})
        status = str(info.get("status", "unknown"))
        role = role_by_agent.get(agent, "team member")

        in_progress_ids = [t.get("id") for t in tasks if t.get("owner") == agent and t.get("status") == "in_progress"]
        reported_ids = [t.get("id") for t in tasks if t.get("owner") == agent and t.get("status") == "reported"]
        chunks: List[str] = []
        if in_progress_ids:
            chunks.append("in_progress on " + ", ".join(in_progress_ids))
        if reported_ids:
            chunks.append("reported: " + ", ".join(reported_ids))
        tail = "; " + "; ".join(chunks) if chunks else ""
        lines.append(f"- {agent} ({role}): {status}{tail}")

    # Per-team lane snapshot
    team_lanes = _aggregate_team_lanes(tasks)
    if team_lanes:
        lines.extend(["", "Team lanes:"])
        for tid in sorted(team_lanes):
            lc = team_lanes[tid]
            parts = []
            for key in ("in_progress", "reported", "blocked"):
                count = lc.get(key, 0)
                if count:
                    parts.append(f"{key}={count}")
            total = lc.get("total", 0)
            done = lc.get("done", 0)
            summary = f"{done}/{total} done"
            if parts:
                summary += ", " + ", ".join(parts)
            lines.append(f"- {tid}: {summary}")

    if recovery_actions:
        lines.extend(["", "Suggested recovery actions:"])
        for action in recovery_actions[:5]:
            lines.append(f"- [{action['type']}] {action['message']}")
            lines.append(f"  Suggested: {action['action']}")

    payload = {
        "report_text": "\n".join(lines),
        "report": {
            "overall_project_percent": overall,
            "phase_1_percent": phase_1,
            "phase_2_percent": phase_2,
            "phase_3_percent": phase_3,
            "backend_task_id": backend_task_id,
            "backend_percent": backend_percent,
            "frontend_task_id": frontend_task_id,
            "frontend_percent": frontend_percent,
            "qa_validation_percent": qa_percent,
            "pipeline_health": {
                "reported_tasks": reported_count,
                "open_blockers": len(blockers_open),
                "open_bugs": len(bugs_open),
            },
            "team_lane_counters": team_lanes,
            "suggested_recovery_actions": recovery_actions,
        },
        "recommended_cadence_seconds": 600,
    }
    return payload


def handle_tool_call(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments", {})

    try:
        if name == "orchestrator_guide":
            return _ok_and_audit(request_id, name, args, _guide_payload())

        if name == "orchestrator_doctor":
            stale_after = int(args.get("stale_after_seconds", 600))
            roles: Dict[str, Any] = {"leader": None, "team_members": []}
            manager: Optional[str] = None
            agents: List[Dict[str, Any]] = []
            discovered: Dict[str, Any] = {"registered_count": 0, "inferred_only_count": 0, "agents": []}
            if ORCH is not None:
                roles = ORCH.get_roles()
                manager = roles.get("leader")
                agents = ORCH.list_agents(active_only=False, stale_after_seconds=stale_after)
                discovered = ORCH.discover_agents(active_only=False, stale_after_seconds=stale_after)
            payload = build_doctor_payload(
                root_dir=ROOT_DIR,
                policy_path=POLICY_PATH,
                policy_name=POLICY.name if POLICY is not None else POLICY_PATH.name,
                policy_loaded=POLICY is not None,
                binding_error=_BINDING_ERROR,
                server_binding=_server_binding_health(),
                runtime_source_consistency=_runtime_source_consistency(),
                manager=manager,
                roles=roles,
                agents=agents,
                discovered=discovered,
                orch_available=ORCH is not None,
            )
            return _ok_and_audit(request_id, name, args, payload)

        if name == "orchestrator_headless_start":
            supervisor = _supervisor_from_tool_args(args if isinstance(args, dict) else {})
            payload = _run_supervisor_action(supervisor, "start")
            return _ok_and_audit(request_id, name, args, payload)

        if name == "orchestrator_headless_stop":
            supervisor = _supervisor_from_tool_args(args if isinstance(args, dict) else {})
            payload = _run_supervisor_action(supervisor, "stop")
            return _ok_and_audit(request_id, name, args, payload)

        if name == "orchestrator_headless_status":
            supervisor = _supervisor_from_tool_args(args if isinstance(args, dict) else {})
            payload = {
                "ok": True,
                "project_root": supervisor.cfg.project_root,
                "leader_agent": supervisor.cfg.leader_agent,
                "processes": supervisor.status_json(),
            }
            return _ok_and_audit(request_id, name, args, payload)

        if name == "orchestrator_headless_restart":
            supervisor = _supervisor_from_tool_args(args if isinstance(args, dict) else {})
            payload = _run_supervisor_action(supervisor, "restart")
            return _ok_and_audit(request_id, name, args, payload)

        if name == "orchestrator_headless_clean":
            supervisor = _supervisor_from_tool_args(args if isinstance(args, dict) else {})
            payload = _run_supervisor_action(supervisor, "clean")
            return _ok_and_audit(request_id, name, args, payload)

        # ── Degraded-mode guard: reject tool calls when binding failed ──
        if _BINDING_ERROR and ORCH is None:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "error": "orchestrator_binding_error",
                                "message": _BINDING_ERROR,
                                "hint": (
                                    "The MCP server started in degraded mode because of a "
                                    "configuration issue. Ensure ORCHESTRATOR_ROOT, "
                                    "ORCHESTRATOR_EXPECTED_ROOT, and ORCHESTRATOR_POLICY "
                                    "are set correctly in your MCP server config. "
                                    "See scripts/install_agent_leader_mcp.sh --help."
                                ),
                            }),
                        }
                    ],
                    "isError": True,
                },
            }

        if name == "orchestrator_status":
            tasks = ORCH.list_tasks()
            bugs = ORCH.list_bugs()
            agents = ORCH.list_agents(active_only=True)
            agent_instances = ORCH.list_agent_instances(active_only=False)
            roles = ORCH.get_roles()
            live_status = _live_status_report({})
            by_status: Dict[str, int] = {}
            for task in tasks:
                by_status[task["status"]] = by_status.get(task["status"], 0) + 1
            integrity = _status_integrity_and_provenance(
                current_task_count=len(tasks),
                current_done_count=int(by_status.get("done", 0)),
            )
            rsc = _runtime_source_consistency()
            binding = _server_binding_health()
            if not rsc["ok"]:
                integrity["warnings"] = integrity.get("warnings", []) + rsc["warnings"]
                integrity["ok"] = False
            if not binding["ok"]:
                integrity["warnings"] = integrity.get("warnings", []) + binding["warnings"]
                integrity["ok"] = False
            payload: Dict[str, Any] = {
                "server": "agent-leader-orchestrator",
                "version": __version__,
                "root_name": ROOT_DIR.name,
                "policy_name": POLICY.name,
                "manager": roles.get("leader"),
                "roles": roles,
                "task_count": len(tasks),
                "task_status_counts": by_status,
                "team_lane_counters": _aggregate_team_lanes(tasks),
                "bug_count": len(bugs),
                "recovery_actions": live_status.get("report", {}).get("suggested_recovery_actions", []),
                "active_agents": [agent["agent"] for agent in agents],
                "active_agent_identities": [
                    {
                        "agent": agent.get("agent"),
                        "instance_id": agent.get("instance_id"),
                        "status": agent.get("status"),
                        "last_seen": agent.get("last_seen"),
                    }
                    for agent in agents
                ],
                "agent_instances": [
                    {
                        "agent_name": item.get("agent_name"),
                        "instance_id": item.get("instance_id"),
                        "role": item.get("role"),
                        "status": item.get("status"),
                        "project_root": item.get("project_root"),
                        "current_task_id": item.get("current_task_id"),
                        "last_seen": item.get("last_seen"),
                    }
                    for item in agent_instances
                ],
                "live_status_text": live_status.get("report_text", ""),
                "live_status": live_status.get("report", {}),
                "integrity": integrity,
                "runtime_source_consistency": rsc,
                "server_binding": binding,
                "stats_provenance": {
                    "dashboard_percent": "live_status_report_estimate",
                    "task_summary": integrity.get("provenance", {}).get("task_counts"),
                    "integrity_state": "ok" if (integrity.get("ok") and rsc["ok"]) else "degraded",
                },
                "recommended_status_cadence_seconds": live_status.get("recommended_cadence_seconds", 600),
                "run_context": {
                    "run_id": RUN_ID or None,
                    "orchestrator_version": __version__,
                    "policy_name": POLICY.name,
                    "prompt_profile_version": PROMPT_PROFILE_VERSION or None,
                    "root_name": ROOT_DIR.name,
                },
                "metrics": _status_metrics(tasks=tasks, bugs_open=ORCH.list_bugs(status="open"), blockers_open=ORCH.list_blockers(status="open")),
                "auto_manager_cycle": {
                    "running": bool(_AUTO_LOOP_THREAD and _AUTO_LOOP_THREAD.is_alive()),
                    "interval_seconds": max(5, min(int(os.getenv("ORCHESTRATOR_AUTO_MANAGER_CYCLE_SECONDS", "15")), 300)),
                },
                "stop_policy": ORCH.evaluate_stop_policy(),
            }
            if STATUS_VERBOSE_PATHS:
                payload["root"] = str(ROOT_DIR)
                payload["policy"] = str(POLICY_PATH)
            try:
                _append_jsonl(
                    STATUS_SNAPSHOTS_PATH,
                    STATUS_SNAPSHOTS_LOCK,
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "run_id": RUN_ID or None,
                        "root_name": ROOT_DIR.name,
                        "task_count": len(tasks),
                        "task_status_counts": by_status,
                        "live_status": live_status.get("report", {}),
                        "integrity_ok": bool(integrity.get("ok")),
                        "integrity_warnings": integrity.get("warnings", []),
                        "provenance": payload.get("stats_provenance", {}),
                    },
                )
            except Exception:
                # Status should still succeed even if snapshot logging fails.
                pass
            return _ok_and_audit(
                request_id,
                name,
                args,
                payload,
            )

        if name == "orchestrator_get_roles":
            return _ok_and_audit(request_id, name, args, ORCH.get_roles())

        if name == "orchestrator_set_role":
            result = ORCH.set_role(
                agent=args["agent"],
                role=args["role"],
                source=args["source"],
                instance_id=args.get("instance_id"),
                source_instance_id=args.get("source_instance_id"),
            )
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_list_audit_logs":
            logs = list(
                ORCH.bus.read_audit(
                    limit=int(args.get("limit", 100)),
                    tool_name=args.get("tool"),
                    status=args.get("status"),
                )
            )
            return _ok_and_audit(request_id, name, args, logs)

        if name == "orchestrator_live_status_report":
            return _ok_and_audit(request_id, name, args, _live_status_report(args))

        if name == "orchestrator_register_agent":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            entry = ORCH.register_agent(agent=args["agent"], metadata=metadata)
            return _ok_and_audit(request_id, name, args, entry)

        if name == "orchestrator_heartbeat":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            entry = ORCH.heartbeat(agent=args["agent"], metadata=metadata)
            return _ok_and_audit(request_id, name, args, entry)

        if name in {"orchestrator_connect_team_members", "orchestrator_connect_workers"}:
            team_members = args.get("team_members", [])
            if not team_members:
                team_members = args.get("workers", [])
            if isinstance(team_members, str):
                team_members = _parse_json_argument(team_members, "array")
            result = ORCH.connect_team_members(
                source=args["source"],
                team_members=team_members,
                timeout_seconds=int(args.get("timeout_seconds", 60)),
                poll_interval_seconds=int(args.get("poll_interval_seconds", 2)),
                stale_after_seconds=int(args.get("stale_after_seconds", 600)),
            )
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_connect_to_leader":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            result = ORCH.connect_to_leader(
                agent=args["agent"],
                metadata=metadata,
                status=args.get("status", "idle"),
                announce=bool(args.get("announce", True)),
                source=args.get("source"),
            )
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_list_agents":
            agents = ORCH.list_agents(
                active_only=bool(args.get("active_only", False)),
                stale_after_seconds=int(args.get("stale_after_seconds", 600)),
            )
            return _ok_and_audit(request_id, name, args, agents)

        if name == "orchestrator_discover_agents":
            discovered = ORCH.discover_agents(
                active_only=bool(args.get("active_only", False)),
                stale_after_seconds=int(args.get("stale_after_seconds", 600)),
            )
            return _ok_and_audit(request_id, name, args, discovered)

        if name == "orchestrator_bootstrap":
            ORCH.bootstrap()
            return _ok_and_audit(request_id, name, args, {"ok": True, "policy": POLICY.name, "manager": ORCH.manager_agent()})

        if name == "orchestrator_create_task":
            acceptance = args.get("acceptance_criteria")
            if acceptance is None:
                acceptance = ["Tests pass", "Acceptance criteria satisfied"]
            if isinstance(acceptance, str):
                acceptance = [acceptance]
            tags = args.get("tags")
            if isinstance(tags, str):
                tags = _parse_json_argument(tags, "array")
            task = ORCH.create_task(
                title=args.get("title", ""),
                workstream=args.get("workstream", "default"),
                description=args.get("description", ""),
                owner=args.get("owner"),
                acceptance_criteria=acceptance,
                risk=args.get("risk"),
                test_plan=args.get("test_plan"),
                doc_impact=args.get("doc_impact"),
                project_root=args.get("project_root"),
                project_name=args.get("project_name"),
                tags=tags,
                team_id=args.get("team_id"),
            )
            return _ok_and_audit(request_id, name, args, task)

        if name == "orchestrator_dedupe_tasks":
            result = ORCH.dedupe_open_tasks(source=args.get("source", ORCH.manager_agent()))
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_list_tasks":
            tags = args.get("tags")
            if isinstance(tags, str):
                tags = _parse_json_argument(tags, "array")
            tasks = ORCH.list_tasks(
                status=args.get("status"),
                owner=args.get("owner"),
                project_name=args.get("project_name"),
                project_root=args.get("project_root"),
                team_id=args.get("team_id"),
                tags=tags,
                lane=args.get("lane"),
            )
            return _ok_and_audit(request_id, name, args, tasks)

        if name == "orchestrator_get_tasks_for_agent":
            tasks = ORCH.list_tasks_for_owner(owner=args["agent"], status=args.get("status"))
            return _ok_and_audit(request_id, name, args, tasks)

        if name == "orchestrator_claim_next_task":
            result = ORCH.claim_next_task(
                owner=args["agent"],
                instance_id=args.get("instance_id"),
                team_id=args.get("team_id"),
            )
            if result and isinstance(result, dict) and result.get("throttled"):
                # Anti-spam cooldown: rapid empty claims are suppressed.
                backoff = result.get("backoff_seconds", 5)
                return _ok(
                    request_id,
                    {
                        "task": None,
                        "throttled": True,
                        "message": result.get("message", "claim_cooldown"),
                        "retry_hint": {
                            "strategy": "backoff",
                            "backoff_seconds": backoff,
                            "cooldown_seconds": result.get("cooldown_seconds", 5),
                        },
                    },
                )
            if result:
                return _ok_and_audit(request_id, name, args, result)
            return _ok(
                request_id,
                {
                    "task": None,
                    "message": "No claimable task",
                    "retry_hint": {
                        "strategy": "event_poll_then_backoff",
                        "poll_timeout_ms": 120000,
                        "backoff_seconds": 15,
                    },
                },
            )

        if name == "orchestrator_renew_task_lease":
            result = ORCH.renew_task_lease(
                task_id=args["task_id"],
                agent=args["agent"],
                lease_id=args["lease_id"],
                instance_id=args.get("instance_id"),
            )
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_set_claim_override":
            result = ORCH.set_claim_override(
                agent=args["agent"],
                task_id=args["task_id"],
                source=args["source"],
            )
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_update_task_status":
            task = ORCH.set_task_status(
                task_id=args["task_id"],
                status=args["status"],
                source=args["source"],
                note=args.get("note", ""),
            )
            return _ok_and_audit(request_id, name, args, task)

        if name == "orchestrator_submit_report":
            test_summary = args.get("test_summary", {})
            if isinstance(test_summary, str):
                test_summary = _parse_json_argument(test_summary, "object")
            review_gate = args.get("review_gate")
            if isinstance(review_gate, str):
                review_gate = _parse_json_argument(review_gate, "object")
            reporting_agent = args["agent"]
            report = {
                "task_id": args["task_id"],
                "agent": reporting_agent,
                "commit_sha": args["commit_sha"],
                "status": args["status"],
                "test_summary": test_summary,
                "artifacts": args.get("artifacts", []),
                "notes": args.get("notes", ""),
            }
            if isinstance(review_gate, dict):
                report["review_gate"] = review_gate
            report["run_context"] = {
                "run_id": RUN_ID or None,
                "orchestrator_version": __version__,
                "policy_name": POLICY.name,
                "prompt_profile_version": PROMPT_PROFILE_VERSION or None,
                "root_name": ROOT_DIR.name,
            }
            report["commit_metrics"] = _collect_commit_metrics(report["commit_sha"])
            try:
                result = ORCH.ingest_report(report)
            except Exception as exc:
                queue_entry = ORCH.enqueue_report_retry(report=report, error=str(exc))
                result = {
                    "queued_for_retry": True,
                    "queue_entry": queue_entry,
                    "submit_error": str(exc),
                }
            auto_validate = bool(ORCH.policy.triggers.get("auto_validate_reports_on_submit", True))
            if auto_validate:
                cycle = _manager_cycle(strict=True)
                result = {
                    "report": result,
                    "auto_manager_cycle": {
                        "enabled": True,
                        "processed_reports": cycle.get("processed_reports", []),
                        "deferred_reports": cycle.get("deferred_reports", []),
                        "pending_total": cycle.get("pending_total", 0),
                    },
                }
                # Help workers continue without extra manual "claim next" reminders.
                result["auto_claim_next"] = ORCH.claim_next_task(owner=reporting_agent)
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_validate_task":
            result = ORCH.validate_task(
                task_id=args["task_id"],
                passed=bool(args["passed"]),
                notes=args["notes"],
                source=args["source"],
            )
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_list_bugs":
            bugs = ORCH.list_bugs(status=args.get("status"), owner=args.get("owner"))
            return _ok_and_audit(request_id, name, args, bugs)

        if name == "orchestrator_raise_blocker":
            blocker = ORCH.raise_blocker(
                task_id=args["task_id"],
                agent=args["agent"],
                question=args["question"],
                options=args.get("options", []),
                severity=args.get("severity", "medium"),
            )
            return _ok_and_audit(request_id, name, args, blocker)

        if name == "orchestrator_list_blockers":
            blockers = ORCH.list_blockers(status=args.get("status"), agent=args.get("agent"))
            return _ok_and_audit(request_id, name, args, blockers)

        if name == "orchestrator_resolve_blocker":
            blocker = ORCH.resolve_blocker(
                blocker_id=args["blocker_id"],
                resolution=args["resolution"],
                source=args["source"],
            )
            return _ok_and_audit(request_id, name, args, blocker)

        if name == "orchestrator_publish_event":
            payload = args.get("payload", {})
            if isinstance(payload, str):
                payload = _parse_json_argument(payload, "object")
            audience = args.get("audience", [])
            if isinstance(audience, str):
                audience = _parse_json_argument(audience, "array")
            event = ORCH.publish_event(
                event_type=args["type"],
                source=args["source"],
                payload=payload,
                audience=audience,
            )
            return _ok_and_audit(request_id, name, args, event)

        if name == "orchestrator_poll_events":
            polled = ORCH.poll_events(
                agent=args["agent"],
                cursor=args.get("cursor"),
                limit=int(args.get("limit", 50)),
                timeout_ms=int(args.get("timeout_ms", 0)),
                auto_advance=bool(args.get("auto_advance", True)),
            )
            return _ok_and_audit(request_id, name, args, polled)

        if name == "orchestrator_ack_event":
            ack = ORCH.ack_event(agent=args["agent"], event_id=args["event_id"])
            return _ok_and_audit(request_id, name, args, ack)

        if name == "orchestrator_get_agent_cursor":
            cursor = ORCH.get_agent_cursor(agent=args["agent"])
            return _ok_and_audit(request_id, name, args, {"agent": args["agent"], "cursor": cursor})

        if name == "orchestrator_manager_cycle":
            strict = bool(args.get("strict", False))
            cycle = _manager_cycle(strict=strict)
            return _ok_and_audit(request_id, name, args, cycle)

        if name == "orchestrator_reassign_stale_tasks":
            result = ORCH.reassign_stale_tasks_to_active_workers(
                source=args.get("source", ORCH.manager_agent()),
                stale_after_seconds=int(args.get("stale_after_seconds", 600)),
                include_blocked=bool(args.get("include_blocked", True)),
            )
            return _ok_and_audit(request_id, name, args, result)

        if name == "orchestrator_decide_architecture":
            votes = args.get("votes", {})
            rationale = args.get("rationale", {})
            if isinstance(votes, str):
                votes = _parse_json_argument(votes, "object")
            if isinstance(rationale, str):
                rationale = _parse_json_argument(rationale, "object")
            options = args.get("options", [])
            if isinstance(options, str):
                options = _parse_json_argument(options, "array")

            path = ORCH.record_architecture_decision(
                topic=args["topic"],
                options=options,
                votes=votes,
                rationale=rationale,
            )
            return _ok_and_audit(request_id, name, args, {"decision_path": str(path)})

        raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:
        _audit_tool_call(
            tool_name=str(name),
            args=args if isinstance(args, dict) else {"raw_arguments": args},
            status="error",
            error=str(exc),
        )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": str(exc),
            },
        }


def main() -> None:
    if ORCH is not None:
        _start_auto_manager_loop()
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            request = json.loads(line.strip())
            method = request.get("method")
            request_id = request.get("id")
            params = request.get("params", {})

            # JSON-RPC notifications do not include an id and must not receive responses.
            is_notification = "id" not in request
            if is_notification:
                if method == "notifications/initialized":
                    continue
                # Ignore unknown notifications silently for compatibility with strict clients.
                continue

            if method == "initialize":
                response = handle_initialize(request_id)
            elif method == "tools/list":
                response = handle_tools_list(request_id)
            elif method == "tools/call":
                response = handle_tool_call(request_id, params)
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

            send_response(response)
        except json.JSONDecodeError:
            continue
        except EOFError:
            break
        except Exception as exc:
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {exc}",
                    },
                }
            )


if __name__ == "__main__":
    main()
