# Operator Quick-Reference: Restart Milestone Visibility Fields

> New status fields added for instance-aware agent tracking. These become
> visible after restarting the MCP server with the updated orchestrator.

## New Fields

### `agent_instances` (in `orchestrator_status`)

Array of per-instance rows for every registered agent, including offline ones.

| Field | Type | Description |
|---|---|---|
| `agent_name` | string | Agent identifier (claude_code, gemini, codex) |
| `instance_id` | string | Unique instance (e.g., `claude_code#worker-01`) |
| `role` | string | `leader` or `team_member` |
| `status` | string | `active`, `idle`, `stale`, `disconnected` |
| `project_root` | string | Working directory for this instance |
| `current_task_id` | string\|null | Task currently claimed by this instance |
| `last_seen` | ISO 8601 | Last heartbeat timestamp |

### `active_agent_identities` (in `orchestrator_status`)

Filtered list of active agents with identity details.

| Field | Type | Description |
|---|---|---|
| `agent` | string | Agent name |
| `instance_id` | string | Instance identifier |
| `status` | string | Always `active` (filtered) |
| `last_seen` | ISO 8601 | Last heartbeat |

## Examples

### Active Instance
```json
{
  "agent_name": "claude_code",
  "instance_id": "claude_code#worker-01",
  "role": "team_member",
  "status": "active",
  "project_root": "/Users/alex/claude-multi-ai",
  "current_task_id": "TASK-8f2649d2",
  "last_seen": "2026-02-26T15:32:46+00:00"
}
```

### Offline Instance
```json
{
  "agent_name": "gemini",
  "instance_id": "gemini#w1",
  "role": "team_member",
  "status": "stale",
  "project_root": "/Users/alex/claude-multi-ai",
  "current_task_id": null,
  "last_seen": "2026-02-21T22:20:20+00:00"
}
```

## Restart Requirement

To load updated server with these fields:
1. Stop running MCP server processes
2. Reinstall: `python orchestrator/install.py --target claude --mode project`
3. Restart Claude Code / Codex CLI session
4. Verify: call `orchestrator_status` and check for `agent_instances` key
