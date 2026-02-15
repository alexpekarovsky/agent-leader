#!/usr/bin/env python3
"""
agent-leader-orchestrator MCP Server
Expose configurable multi-agent orchestration tools via MCP JSON-RPC.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy

sys.stdout = os.fdopen(sys.stdout.fileno(), "w", 1)
sys.stderr = os.fdopen(sys.stderr.fileno(), "w", 1)

__version__ = "0.1.0"
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(os.getenv("ORCHESTRATOR_ROOT", str(SCRIPT_DIR))).resolve()
EXPECTED_ROOT_RAW = os.getenv("ORCHESTRATOR_EXPECTED_ROOT", "").strip()
POLICY_PATH = Path(
    os.getenv("ORCHESTRATOR_POLICY", str(ROOT_DIR / "config" / "policy.codex-manager.json"))
).resolve()

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
            "description": "Return the orchestration playbook and exact MCP-only workflow for manager and workers.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "orchestrator_status",
            "description": "Show server root, active policy, manager role, task counts by status, and bug counts. Use this first in every session.",
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
            "name": "orchestrator_connect_workers",
            "description": "Manager one-shot worker activation handshake: ping workers, wait for register+heartbeat, return connected/missing.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Manager/source agent id (usually codex)."},
                    "workers": {"type": "array", "items": {"type": "string"}, "description": "Target worker agent IDs."},
                    "timeout_seconds": {"type": "integer", "default": 60},
                    "poll_interval_seconds": {"type": "integer", "default": 2},
                    "stale_after_seconds": {"type": "integer", "default": 300},
                },
                "required": ["source", "workers"],
            },
        },
        {
            "name": "orchestrator_connect_to_leader",
            "description": "Worker one-shot attach flow: register agent, heartbeat, and announce readiness to manager.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Worker agent id (e.g., claude_code, gemini)."},
                    "metadata": {"type": "object", "default": {}, "description": "Optional worker metadata (client/model/cwd)."},
                    "status": {"type": "string", "default": "idle"},
                    "announce": {"type": "boolean", "default": True},
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_list_agents",
            "description": "List discovered tenants in pool with active/offline status.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "default": False},
                    "stale_after_seconds": {"type": "integer", "default": 300},
                },
            },
        },
        {
            "name": "orchestrator_discover_agents",
            "description": "Deep discovery view: registered agents plus inferred tenants from events/tasks, with metadata and task-load details.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "default": False},
                    "stale_after_seconds": {"type": "integer", "default": 300},
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
            "description": "Get tasks for a specific agent. Workers should use this when they need full queue visibility.",
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
            "description": "Claim next task for an agent and move it to in_progress. Workers should call this before coding.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "codex|claude_code|gemini"},
                },
                "required": ["agent"],
            },
        },
        {
            "name": "orchestrator_update_task_status",
            "description": "Update task lifecycle status (in_progress, blocked, etc.) with note metadata.",
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
            "description": "Submit worker delivery report. Mandatory before claiming task completion. Rejects wrong owner/task mismatches.",
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
                },
                "required": ["task_id", "passed", "notes"],
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
            "description": "Worker raises structured blocker requiring manager/user input. Marks task as blocked.",
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
            "description": "List blockers raised by workers. Manager polls this to ask user for missing input.",
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
                    "type": {"type": "string", "description": "Event type, e.g., task.note, manager.announcement, worker.ready."},
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
            "description": "Run one manager cycle automatically: validate all reported tasks and summarize remaining work by owner.",
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


def _guide_payload() -> Dict[str, Any]:
    return {
        "purpose": "MCP-first multi-agent orchestration for manager/worker loops.",
        "roles": {
            "manager": POLICY.manager(),
            "worker_agents": ["claude_code", "gemini", "codex"],
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
            "worker": [
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
    stale_requeues = ORCH.requeue_stale_in_progress_tasks(stale_after_seconds=1800)
    tasks = ORCH.list_tasks()
    processed: List[Dict[str, Any]] = []

    for task in tasks:
        if task.get("status") != "reported":
            continue

        report_path = ORCH.bus.reports_dir / f"{task['id']}.json"
        if not report_path.exists():
            result = ORCH.validate_task(task_id=task["id"], passed=False, notes="Missing report file")
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
        result = ORCH.validate_task(task_id=task["id"], passed=passed, notes=notes)
        processed.append({"task_id": task["id"], "passed": passed, "result": result})

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
        source=POLICY.manager(),
        payload={"contracts": contracts},
    )

    return {
        "processed_reports": processed,
        "stale_requeues": stale_requeues,
        "remaining_by_owner": by_owner,
        "pending_total": sum(bucket["pending"] for bucket in by_owner.values()),
        "open_blockers": open_blockers,
    }


def _percent(done: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round((done / total) * 100))


def _live_status_report(args: Dict[str, Any]) -> Dict[str, Any]:
    tasks = ORCH.list_tasks()
    blockers_open = ORCH.list_blockers(status="open")
    bugs_open = ORCH.list_bugs(status="open")

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
        "recommended_cadence_seconds": 600,
    }
    return payload


def handle_tool_call(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments", {})

    try:
        if name == "orchestrator_guide":
            return _ok(request_id, _guide_payload())

        if name == "orchestrator_status":
            tasks = ORCH.list_tasks()
            bugs = ORCH.list_bugs()
            agents = ORCH.list_agents(active_only=True)
            by_status: Dict[str, int] = {}
            for task in tasks:
                by_status[task["status"]] = by_status.get(task["status"], 0) + 1
            return _ok(
                request_id,
                {
                    "server": "agent-leader-orchestrator",
                    "version": __version__,
                    "root": str(ROOT_DIR),
                    "policy": str(POLICY_PATH),
                    "policy_name": POLICY.name,
                    "manager": POLICY.manager(),
                    "task_count": len(tasks),
                    "task_status_counts": by_status,
                    "bug_count": len(bugs),
                    "active_agents": [agent["agent"] for agent in agents],
                },
            )

        if name == "orchestrator_live_status_report":
            return _ok(request_id, _live_status_report(args))

        if name == "orchestrator_register_agent":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            entry = ORCH.register_agent(agent=args["agent"], metadata=metadata)
            return _ok(request_id, entry)

        if name == "orchestrator_heartbeat":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            entry = ORCH.heartbeat(agent=args["agent"], metadata=metadata)
            return _ok(request_id, entry)

        if name == "orchestrator_connect_workers":
            workers = args.get("workers", [])
            if isinstance(workers, str):
                workers = _parse_json_argument(workers, "array")
            result = ORCH.connect_workers(
                source=args["source"],
                workers=workers,
                timeout_seconds=int(args.get("timeout_seconds", 60)),
                poll_interval_seconds=int(args.get("poll_interval_seconds", 2)),
                stale_after_seconds=int(args.get("stale_after_seconds", 300)),
            )
            return _ok(request_id, result)

        if name == "orchestrator_connect_to_leader":
            metadata = args.get("metadata", {})
            if isinstance(metadata, str):
                metadata = _parse_json_argument(metadata, "object")
            result = ORCH.connect_to_leader(
                agent=args["agent"],
                metadata=metadata,
                status=args.get("status", "idle"),
                announce=bool(args.get("announce", True)),
            )
            return _ok(request_id, result)

        if name == "orchestrator_list_agents":
            agents = ORCH.list_agents(
                active_only=bool(args.get("active_only", False)),
                stale_after_seconds=int(args.get("stale_after_seconds", 300)),
            )
            return _ok(request_id, agents)

        if name == "orchestrator_discover_agents":
            discovered = ORCH.discover_agents(
                active_only=bool(args.get("active_only", False)),
                stale_after_seconds=int(args.get("stale_after_seconds", 300)),
            )
            return _ok(request_id, discovered)

        if name == "orchestrator_bootstrap":
            ORCH.bootstrap()
            return _ok(request_id, {"ok": True, "policy": POLICY.name, "manager": POLICY.manager()})

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
            return _ok(request_id, task)

        if name == "orchestrator_list_tasks":
            status = args.get("status")
            owner = args.get("owner")
            tasks = ORCH.list_tasks()
            if status:
                tasks = [task for task in tasks if task.get("status") == status]
            if owner:
                tasks = [task for task in tasks if task.get("owner") == owner]
            return _ok(request_id, tasks)

        if name == "orchestrator_get_tasks_for_agent":
            tasks = ORCH.list_tasks_for_owner(owner=args["agent"], status=args.get("status"))
            return _ok(request_id, tasks)

        if name == "orchestrator_claim_next_task":
            task = ORCH.claim_next_task(owner=args["agent"])
            if task:
                return _ok(request_id, task)
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

        if name == "orchestrator_update_task_status":
            task = ORCH.set_task_status(
                task_id=args["task_id"],
                status=args["status"],
                source=args["source"],
                note=args.get("note", ""),
            )
            return _ok(request_id, task)

        if name == "orchestrator_submit_report":
            test_summary = args.get("test_summary", {})
            if isinstance(test_summary, str):
                test_summary = _parse_json_argument(test_summary, "object")
            report = {
                "task_id": args["task_id"],
                "agent": args["agent"],
                "commit_sha": args["commit_sha"],
                "status": args["status"],
                "test_summary": test_summary,
                "artifacts": args.get("artifacts", []),
                "notes": args.get("notes", ""),
            }
            result = ORCH.ingest_report(report)
            return _ok(request_id, result)

        if name == "orchestrator_validate_task":
            result = ORCH.validate_task(
                task_id=args["task_id"],
                passed=bool(args["passed"]),
                notes=args["notes"],
            )
            return _ok(request_id, result)

        if name == "orchestrator_list_bugs":
            bugs = ORCH.list_bugs(status=args.get("status"), owner=args.get("owner"))
            return _ok(request_id, bugs)

        if name == "orchestrator_raise_blocker":
            blocker = ORCH.raise_blocker(
                task_id=args["task_id"],
                agent=args["agent"],
                question=args["question"],
                options=args.get("options", []),
                severity=args.get("severity", "medium"),
            )
            return _ok(request_id, blocker)

        if name == "orchestrator_list_blockers":
            blockers = ORCH.list_blockers(status=args.get("status"), agent=args.get("agent"))
            return _ok(request_id, blockers)

        if name == "orchestrator_resolve_blocker":
            blocker = ORCH.resolve_blocker(
                blocker_id=args["blocker_id"],
                resolution=args["resolution"],
                source=args["source"],
            )
            return _ok(request_id, blocker)

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
            return _ok(request_id, event)

        if name == "orchestrator_poll_events":
            polled = ORCH.poll_events(
                agent=args["agent"],
                cursor=args.get("cursor"),
                limit=int(args.get("limit", 50)),
                timeout_ms=int(args.get("timeout_ms", 0)),
                auto_advance=bool(args.get("auto_advance", True)),
            )
            return _ok(request_id, polled)

        if name == "orchestrator_ack_event":
            ack = ORCH.ack_event(agent=args["agent"], event_id=args["event_id"])
            return _ok(request_id, ack)

        if name == "orchestrator_get_agent_cursor":
            cursor = ORCH.get_agent_cursor(agent=args["agent"])
            return _ok(request_id, {"agent": args["agent"], "cursor": cursor})

        if name == "orchestrator_manager_cycle":
            strict = bool(args.get("strict", False))
            cycle = _manager_cycle(strict=strict)
            return _ok(request_id, cycle)

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
            return _ok(request_id, {"decision_path": str(path)})

        raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": str(exc),
            },
        }


def main() -> None:
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
