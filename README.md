# agent-leader

Multi-agent orchestrator MCP server for coordinating AI coding teams (Codex CLI + Claude Code + Gemini CLI).

## What It Does

Provides a shared task bus and coordination layer so multiple AI agents can build a project in parallel — one acting as manager, others as builders. All communication happens via MCP tools with file-backed state, so any agent can connect, claim tasks, and report completions autonomously.

## Architecture

```
Manager (Codex CLI)
  ├── orchestrator_create_task      → assigns work by workstream
  ├── orchestrator_validate_task    → reviews and approves completions
  └── orchestrator_manager_cycle    → runs the coordination loop

Builder A (Claude Code)             Builder B (Gemini CLI)
  ├── orchestrator_claim_next_task    ├── orchestrator_claim_next_task
  ├── orchestrator_update_task_status ├── orchestrator_update_task_status
  └── orchestrator_submit_report      └── orchestrator_submit_report
```

State is persisted to a `bus/` directory in the project root — tasks, agents, events, reports, and bugs all live there.

## Policy System

Behavior is controlled by a policy JSON file. The default (`policy.codex-manager.json`) sets Codex as manager and routes workstreams:

```json
{
  "roles": { "manager": "codex" },
  "routing": {
    "backend": "claude_code",
    "frontend": "gemini",
    "qa": "codex"
  },
  "triggers": {
    "heartbeat_timeout_minutes": 10,
    "auto_open_bug_on_validation_failure": true,
    "auto_requeue_on_offline": true
  }
}
```

## MCP Tools (34 total)

**Bootstrap & Registration**
- `orchestrator_bootstrap` — init runtime state for a new project
- `orchestrator_register_agent` / `orchestrator_heartbeat` — agent presence
- `orchestrator_connect_team_members` / `orchestrator_connect_to_leader` — handshake

**Task Lifecycle**
- `orchestrator_create_task` — manager creates + assigns work
- `orchestrator_claim_next_task` — builder claims next assigned task
- `orchestrator_update_task_status` — mark in_progress / blocked
- `orchestrator_submit_report` — builder delivers with commit + test evidence
- `orchestrator_validate_task` — manager approves or opens bug loop
- `orchestrator_set_claim_override` — manager directs priority claims

**Coordination**
- `orchestrator_publish_event` / `orchestrator_poll_events` — async event bus
- `orchestrator_raise_blocker` / `orchestrator_resolve_blocker` — blockers
- `orchestrator_list_tasks` / `orchestrator_list_bugs` / `orchestrator_list_agents`
- `orchestrator_manager_cycle` — one-shot: validate reported tasks + reconnect stale agents
- `orchestrator_reassign_stale_tasks` — redistribute work from offline agents

**Observability**
- `orchestrator_list_audit_logs` — full MCP call audit trail
- `orchestrator_live_status_report` — % complete per workstream
- `orchestrator_enable_debug_logging` / `orchestrator_debug_logging_status`

## Setup

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "agent-leader-orchestrator": {
      "type": "stdio",
      "command": "env",
      "args": [
        "ORCHESTRATOR_ROOT=/path/to/your/project",
        "ORCHESTRATOR_POLICY=/path/to/agent-leader/current/config/policy.codex-manager.json",
        "python3",
        "/path/to/agent-leader/current/orchestrator_mcp_server.py"
      ]
    }
  }
}
```

Each agent (Codex, Claude Code, Gemini) connects to the same MCP server via their own Claude/Codex/Gemini config pointing at the same project root.

## Proven Results

- Built a full-stack React + FastAPI detective game in a **6-hour autonomous session** (Feb 15, 2026)
- Backend (Claude Code) and frontend (Gemini) developed in parallel with zero human intervention
- Manager (Codex) handled task assignment, bug tracking, and validation throughout

## Agent Role Guide

| Project Type | Manager | Primary Builder | Secondary |
|---|---|---|---|
| Full-stack product | Codex CLI | Claude Code | Gemini CLI |
| Frontend-heavy | Codex CLI | Gemini CLI | Claude Code |
| Backend/API | Codex CLI | Claude Code | Gemini CLI |
| Research/prototyping | Gemini CLI | Gemini CLI | Codex CLI |
| Security hardening | Codex CLI | Claude Code | Gemini CLI |

## Known Limitations

See `orchestrator/engine.py` for documented edge cases:
- Workers doing long tasks should call `orchestrator_heartbeat` periodically to stay visible
- Reconnect handshake has a configurable timeout (`manager_cycle_auto_connect_timeout_seconds`) — increase if agents have slow startup
- Claim overrides require the task's current owner to match the target agent
