#!/usr/bin/env python3
"""
agent-leader-orchestrator MCP Server
Expose configurable multi-agent orchestration tools via MCP JSON-RPC.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None

sys.stdout = os.fdopen(sys.stdout.fileno(), "w", 1)
sys.stderr = os.fdopen(sys.stderr.fileno(), "w", 1)

__version__ = "0.1.0"
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(os.getenv("ORCHESTRATOR_ROOT", str(SCRIPT_DIR))).resolve()
EXPECTED_ROOT_RAW = os.getenv("ORCHESTRATOR_EXPECTED_ROOT", "").strip()
POLICY_PATH = Path(
    os.getenv("ORCHESTRATOR_POLICY", str(ROOT_DIR / "config" / "policy.codex-manager.json"))
).resolve()
STATUS_VERBOSE_PATHS = os.getenv("ORCHESTRATOR_STATUS_VERBOSE_PATHS", "").strip().lower() in {"1", "true", "yes"}

if EXPECTED_ROOT_RAW:
    expected_root = Path(EXPECTED_ROOT_RAW).resolve()
    if ROOT_DIR != expected_root:
        raise RuntimeError(
            f"ORCHESTRATOR_ROOT mismatch: got '{ROOT_DIR}', expected '{expected_root}'"
        )

try:
    POLICY = Policy.load(POLICY_PATH)
    ORCH = Orchestrator(root=ROOT_DIR, policy=POLICY)
except Exception as exc:
    print(f"Failed to initialize orchestrator: {exc}", file=sys.stderr)
    raise

_AUTO_LOOP_STOP = threading.Event()
_AUTO_LOOP_THREAD: Optional[threading.Thread] = None
_DEBUG_WINDOW_LOCK = threading.Lock()
_DEBUG_WINDOW_UNTIL_EPOCH: float = 0.0
_DEBUG_WINDOW_SOURCE: str = ""
_DEBUG_WINDOW_MINUTES: int = 15


def send_response(response: Dict[str, Any]) -> None:
    print(json.dumps(response), flush=True)


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2)


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
            "name": "orchestrator_enable_debug_logging",
            "description": "Enable high-detail MCP tool debug tracing for a bounded window (default 15 minutes). During the window, each MCP tool call records duration, args, result/error, and request id into audit logs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "duration_minutes": {"type": "integer", "default": 15},
                    "source": {"type": "string", "default": "codex"},
                },
            },
        },
        {
            "name": "orchestrator_debug_logging_status",
            "description": "Return current debug-logging window status and remaining time.",
            "inputSchema": {"type": "object", "properties": {}},
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
                    "project_override": {
                        "type": "string",
                        "description": "Optional manager-only override for project_root (and cwd when missing) to recover from project metadata mismatch.",
                    },
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_set_agent_project_context",
            "description": "Leader-only project context correction for an agent. Updates project_root/cwd metadata used by same-project verification.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "project_root": {"type": "string"},
                    "cwd": {"type": "string", "description": "Optional; defaults to project_root when omitted."},
                    "source": {"type": "string", "description": "Leader/source agent id."},
                },
                "required": ["agent", "project_root", "source"],
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
            "description": "List tasks, optionally filtered by status or owner. Use for planning dashboards and polling.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Optional status filter (assigned|in_progress|reported|done|bug_open|blocked)."},
                    "owner": {"type": "string", "description": "Optional owner filter (codex|claude_code|gemini)."},
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
                },
                "required": ["agent"],
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


def _debug_window_state(now_epoch: Optional[float] = None) -> Dict[str, Any]:
    now = now_epoch if now_epoch is not None else time.time()
    with _DEBUG_WINDOW_LOCK:
        until = float(_DEBUG_WINDOW_UNTIL_EPOCH)
        source = str(_DEBUG_WINDOW_SOURCE)
        minutes = int(_DEBUG_WINDOW_MINUTES)
    enabled = until > now
    remaining = max(0, int(until - now))
    until_iso = datetime.fromtimestamp(until, tz=timezone.utc).isoformat() if enabled else None
    return {
        "enabled": enabled,
        "remaining_seconds": remaining,
        "until_utc": until_iso,
        "configured_minutes": minutes,
        "source": source,
    }


def _set_debug_window(duration_minutes: int, source: str) -> Dict[str, Any]:
    now = time.time()
    minutes = max(1, min(int(duration_minutes), 240))
    until = now + (minutes * 60)
    with _DEBUG_WINDOW_LOCK:
        global _DEBUG_WINDOW_UNTIL_EPOCH, _DEBUG_WINDOW_SOURCE, _DEBUG_WINDOW_MINUTES
        _DEBUG_WINDOW_UNTIL_EPOCH = until
        _DEBUG_WINDOW_SOURCE = source
        _DEBUG_WINDOW_MINUTES = minutes
    return _debug_window_state(now_epoch=now)


def _debug_trace_tool_call(
    tool_name: str,
    request_id: Any,
    args: Dict[str, Any],
    status: str,
    duration_ms: int,
    result: Optional[Any] = None,
    error: Optional[str] = None,
) -> None:
    debug_state = _debug_window_state()
    if not bool(debug_state.get("enabled")):
        return
    try:
        ORCH.bus.append_audit(
            {
                "category": "mcp_tool_debug_trace",
                "tool": tool_name,
                "request_id": str(request_id),
                "status": status,
                "duration_ms": int(duration_ms),
                "args": _sanitize_for_audit(args),
                "result": _sanitize_for_audit(result) if result is not None else None,
                "error": error,
                "debug_window": debug_state,
            }
        )
    except Exception:
        pass


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


def _ok_and_audit(
    request_id: Any,
    tool_name: str,
    args: Dict[str, Any],
    payload: Any,
    started_at: Optional[float] = None,
) -> Dict[str, Any]:
    _audit_tool_call(tool_name=tool_name, args=args, status="ok", result=payload)
    duration_ms = 0
    if started_at is not None:
        duration_ms = max(0, int((time.time() - float(started_at)) * 1000))
    _debug_trace_tool_call(
        tool_name=tool_name,
        request_id=request_id,
        args=args,
        status="ok",
        duration_ms=duration_ms,
        result=payload,
    )
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
        report_status = report.get("status", "blocked")
        passed = report_status == "done" and failed_tests == 0
        if strict:
            passed = passed and bool(report.get("commit_sha")) and has_command

        notes = (
            f"Auto manager cycle accepted report {report.get('commit_sha', 'unknown')}"
            if passed
            else f"Auto manager cycle rejected report status={report_status}, failed_tests={failed_tests}, has_command={has_command}"
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

    stale_reassignments = ORCH.reassign_stale_tasks_to_active_workers(
        source=ORCH.manager_agent(),
        stale_after_seconds=stale_after_seconds,
        include_blocked=True,
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

    return {
        "processed_reports": processed,
        "report_retry_queue": retry_queue,
        "auto_connect": auto_connect,
        "stale_reassignments": stale_reassignments,
        "stale_requeues": stale_requeues,
        "remaining_by_owner": by_owner,
        "pending_total": sum(bucket["pending"] for bucket in by_owner.values()),
        "open_blockers": open_blockers,
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


def _live_status_report(args: Dict[str, Any]) -> Dict[str, Any]:
    tasks = ORCH.list_tasks()
    blockers_open = ORCH.list_blockers(status="open")
    bugs_open = ORCH.list_bugs(status="open")
    roles = ORCH.get_roles()
    agents_all = ORCH.list_agents(active_only=False)
    by_agent = {item.get("agent"): item for item in agents_all}

    total_tasks = len(tasks)
    done_tasks = len([task for task in tasks if task.get("status") == "done"])
    reported_tasks = len([task for task in tasks if task.get("status") == "reported"])
    overall_auto = _percent(done_tasks, total_tasks)

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

    lines = [
        "Current live status:",
        "",
        f"- Overall project: {overall}%",
        f"- Phase 1 (Architecture + Vertical Slice): {phase_1}%",
        f"- Phase 2 (Content Pipeline): {phase_2}%",
        f"- Phase 3 (Full Production): {phase_3}%",
        f"- Backend vertical slice ({backend_task_id}): {backend_percent}%",
        f"- Frontend vertical slice ({frontend_task_id}): {frontend_percent}%",
        f"- QA/validation completion: {qa_percent}%",
        "",
        "Pipeline health:",
        "",
        f"- Reported tasks: {reported_tasks}",
        f"- Open blockers: {len(blockers_open)}",
        f"- Open bugs: {len(bugs_open)}",
    ]

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
        project_root = str(info.get("project_root") or "-")
        cwd = str(info.get("cwd") or "-")

        in_progress_ids = [t.get("id") for t in tasks if t.get("owner") == agent and t.get("status") == "in_progress"]
        reported_ids = [t.get("id") for t in tasks if t.get("owner") == agent and t.get("status") == "reported"]
        chunks: List[str] = []
        if in_progress_ids:
            chunks.append("in_progress on " + ", ".join(in_progress_ids))
        if reported_ids:
            chunks.append("reported: " + ", ".join(reported_ids))
        chunks.append(f"project_root={project_root}")
        chunks.append(f"cwd={cwd}")
        tail = "; " + "; ".join(chunks)
        lines.append(f"- {agent} ({role}): {status}{tail}")

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
                "reported_tasks": reported_tasks,
                "open_blockers": len(blockers_open),
                "open_bugs": len(bugs_open),
            },
        },
        "agent_connection_contexts": [
            {
                "agent": agent,
                "role": role_by_agent.get(agent, "team member"),
                "status": str((by_agent.get(agent) or {}).get("status", "unknown")),
                "project_root": str((by_agent.get(agent) or {}).get("project_root") or ""),
                "cwd": str((by_agent.get(agent) or {}).get("cwd") or ""),
            }
            for agent in all_agent_names
        ],
        "recommended_cadence_seconds": 600,
    }
    return payload


def handle_tool_call(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments", {})
    started_at = time.time()

    def _ok_call(payload: Any) -> Dict[str, Any]:
        return _ok_and_audit(request_id, str(name), args if isinstance(args, dict) else {"raw_arguments": args}, payload, started_at=started_at)

    try:
        if name == "orchestrator_guide":
            return _ok_call(_guide_payload())

        if name == "orchestrator_status":
            tasks = ORCH.list_tasks()
            bugs = ORCH.list_bugs()
            agents = ORCH.list_agents(active_only=True)
            roles = ORCH.get_roles()
            live_status = _live_status_report({})
            by_status: Dict[str, int] = {}
            for task in tasks:
                by_status[task["status"]] = by_status.get(task["status"], 0) + 1
            payload: Dict[str, Any] = {
                "server": "agent-leader-orchestrator",
                "version": __version__,
                "root_name": ROOT_DIR.name,
                "policy_name": POLICY.name,
                "manager": roles.get("leader"),
                "roles": roles,
                "task_count": len(tasks),
                "task_status_counts": by_status,
                "bug_count": len(bugs),
                "active_agents": [agent["agent"] for agent in agents],
                "active_agent_contexts": [
                    {
                        "agent": agent.get("agent"),
                        "status": agent.get("status"),
                        "project_root": agent.get("project_root"),
                        "cwd": agent.get("cwd"),
                    }
                    for agent in agents
                ],
                "live_status_text": live_status.get("report_text", ""),
                "live_status": live_status.get("report", {}),
                "agent_connection_contexts": live_status.get("agent_connection_contexts", []),
                "recommended_status_cadence_seconds": live_status.get("recommended_cadence_seconds", 600),
                "auto_manager_cycle": {
                    "running": bool(_AUTO_LOOP_THREAD and _AUTO_LOOP_THREAD.is_alive()),
                    "interval_seconds": max(5, min(int(os.getenv("ORCHESTRATOR_AUTO_MANAGER_CYCLE_SECONDS", "15")), 300)),
                },
            }
            if STATUS_VERBOSE_PATHS:
                payload["root"] = str(ROOT_DIR)
                payload["policy"] = str(POLICY_PATH)
            return _ok_call(payload)

        if name == "orchestrator_get_roles":
            return _ok_call(ORCH.get_roles())

        if name == "orchestrator_set_role":
            result = ORCH.set_role(
                agent=args["agent"],
                role=args["role"],
                source=args["source"],
            )
            return _ok_call(result)

        if name == "orchestrator_list_audit_logs":
            logs = list(
                ORCH.bus.read_audit(
                    limit=int(args.get("limit", 100)),
                    tool_name=args.get("tool"),
                    status=args.get("status"),
                )
            )
            return _ok_call(logs)

        if name == "orchestrator_enable_debug_logging":
            duration_minutes = int(args.get("duration_minutes", 15))
            source = str(args.get("source", "codex"))
            window = _set_debug_window(duration_minutes=duration_minutes, source=source)
            return _ok_call(
                {
                    "ok": True,
                    "message": "Debug logging enabled for MCP tool calls",
                    "debug_window": window,
                    "query_hint": {
                        "tool": "orchestrator_list_audit_logs",
                        "filters": {"tool": "", "status": ""},
                        "note": "Search category=mcp_tool_debug_trace in bus/audit.jsonl for full debug traces.",
                    },
                }
            )

        if name == "orchestrator_debug_logging_status":
            return _ok_call(_debug_window_state())

        if name == "orchestrator_live_status_report":
            return _ok_call(_live_status_report(args))

        if name == "orchestrator_register_agent":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            entry = ORCH.register_agent(agent=args["agent"], metadata=metadata)
            return _ok_call(entry)

        if name == "orchestrator_heartbeat":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            entry = ORCH.heartbeat(agent=args["agent"], metadata=metadata)
            return _ok_call(entry)

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
            return _ok_call(result)

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
                project_override=args.get("project_override"),
            )
            return _ok_call(result)

        if name == "orchestrator_set_agent_project_context":
            result = ORCH.set_agent_project_context(
                agent=args["agent"],
                project_root=args["project_root"],
                source=args["source"],
                cwd=args.get("cwd"),
            )
            return _ok_call(result)

        if name == "orchestrator_list_agents":
            agents = ORCH.list_agents(
                active_only=bool(args.get("active_only", False)),
                stale_after_seconds=int(args.get("stale_after_seconds", 600)),
            )
            return _ok_call(agents)

        if name == "orchestrator_discover_agents":
            discovered = ORCH.discover_agents(
                active_only=bool(args.get("active_only", False)),
                stale_after_seconds=int(args.get("stale_after_seconds", 600)),
            )
            return _ok_call(discovered)

        if name == "orchestrator_bootstrap":
            ORCH.bootstrap()
            return _ok_call({"ok": True, "policy": POLICY.name, "manager": ORCH.manager_agent()})

        if name == "orchestrator_create_task":
            acceptance = args.get("acceptance_criteria")
            if acceptance is None:
                acceptance = ["Tests pass", "Acceptance criteria satisfied"]
            if isinstance(acceptance, str):
                acceptance = [acceptance]
            task = ORCH.create_task(
                title=args.get("title", ""),
                workstream=args.get("workstream", "default"),
                description=args.get("description", ""),
                owner=args.get("owner"),
                acceptance_criteria=acceptance,
            )
            return _ok_call(task)

        if name == "orchestrator_dedupe_tasks":
            result = ORCH.dedupe_open_tasks(source=args.get("source", ORCH.manager_agent()))
            return _ok_call(result)

        if name == "orchestrator_list_tasks":
            status = args.get("status")
            owner = args.get("owner")
            tasks = ORCH.list_tasks()
            if status:
                tasks = [task for task in tasks if task.get("status") == status]
            if owner:
                tasks = [task for task in tasks if task.get("owner") == owner]
            return _ok_call(tasks)

        if name == "orchestrator_get_tasks_for_agent":
            tasks = ORCH.list_tasks_for_owner(owner=args["agent"], status=args.get("status"))
            return _ok_call(tasks)

        if name == "orchestrator_claim_next_task":
            task = ORCH.claim_next_task(owner=args["agent"])
            if task:
                return _ok_call(task)
            return _ok_call(
                {
                    "task": None,
                    "message": "No claimable task",
                    "retry_hint": {
                        "strategy": "event_poll_then_backoff",
                        "poll_timeout_ms": 120000,
                        "backoff_seconds": 15,
                    },
                }
            )

        if name == "orchestrator_set_claim_override":
            result = ORCH.set_claim_override(
                agent=args["agent"],
                task_id=args["task_id"],
                source=args["source"],
            )
            return _ok_call(result)

        if name == "orchestrator_update_task_status":
            task = ORCH.set_task_status(
                task_id=args["task_id"],
                status=args["status"],
                source=args["source"],
                note=args.get("note", ""),
            )
            return _ok_call(task)

        if name == "orchestrator_submit_report":
            test_summary = args.get("test_summary", {})
            if isinstance(test_summary, str):
                test_summary = _parse_json_argument(test_summary, "object")
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
                        "pending_total": cycle.get("pending_total", 0),
                    },
                }
                # Help workers continue without extra manual "claim next" reminders.
                result["auto_claim_next"] = ORCH.claim_next_task(owner=reporting_agent)
            return _ok_call(result)

        if name == "orchestrator_validate_task":
            result = ORCH.validate_task(
                task_id=args["task_id"],
                passed=bool(args["passed"]),
                notes=args["notes"],
                source=args["source"],
            )
            return _ok_call(result)

        if name == "orchestrator_list_bugs":
            bugs = ORCH.list_bugs(status=args.get("status"), owner=args.get("owner"))
            return _ok_call(bugs)

        if name == "orchestrator_raise_blocker":
            blocker = ORCH.raise_blocker(
                task_id=args["task_id"],
                agent=args["agent"],
                question=args["question"],
                options=args.get("options", []),
                severity=args.get("severity", "medium"),
            )
            return _ok_call(blocker)

        if name == "orchestrator_list_blockers":
            blockers = ORCH.list_blockers(status=args.get("status"), agent=args.get("agent"))
            return _ok_call(blockers)

        if name == "orchestrator_resolve_blocker":
            blocker = ORCH.resolve_blocker(
                blocker_id=args["blocker_id"],
                resolution=args["resolution"],
                source=args["source"],
            )
            return _ok_call(blocker)

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
            return _ok_call(event)

        if name == "orchestrator_poll_events":
            polled = ORCH.poll_events(
                agent=args["agent"],
                cursor=args.get("cursor"),
                limit=int(args.get("limit", 50)),
                timeout_ms=int(args.get("timeout_ms", 0)),
                auto_advance=bool(args.get("auto_advance", True)),
            )
            return _ok_call(polled)

        if name == "orchestrator_ack_event":
            ack = ORCH.ack_event(agent=args["agent"], event_id=args["event_id"])
            return _ok_call(ack)

        if name == "orchestrator_get_agent_cursor":
            cursor = ORCH.get_agent_cursor(agent=args["agent"])
            return _ok_call({"agent": args["agent"], "cursor": cursor})

        if name == "orchestrator_manager_cycle":
            strict = bool(args.get("strict", False))
            cycle = _manager_cycle(strict=strict)
            return _ok_call(cycle)

        if name == "orchestrator_reassign_stale_tasks":
            result = ORCH.reassign_stale_tasks_to_active_workers(
                source=args.get("source", ORCH.manager_agent()),
                stale_after_seconds=int(args.get("stale_after_seconds", 600)),
                include_blocked=bool(args.get("include_blocked", True)),
            )
            return _ok_call(result)

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
            return _ok_call({"decision_path": str(path)})

        raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:
        duration_ms = max(0, int((time.time() - started_at) * 1000))
        _debug_trace_tool_call(
            tool_name=str(name),
            request_id=request_id,
            args=args if isinstance(args, dict) else {"raw_arguments": args},
            status="error",
            duration_ms=duration_ms,
            error=str(exc),
        )
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
