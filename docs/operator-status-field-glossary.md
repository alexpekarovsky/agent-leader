# Operator Status Field Glossary

> Definitions for status fields related to agent instances, identities,
> and visibility in the orchestrator restart milestone.

## Agent Status Values

| Status | Meaning | Heuristic |
|---|---|---|
| **active** | Agent sent a heartbeat within the timeout window | `last_seen` < `heartbeat_timeout_minutes` ago |
| **idle** | Agent is connected but not working on a task | Metadata status field = "idle" |
| **stale** | Agent hasn't heartbeated within timeout | `last_seen` > `heartbeat_timeout_minutes` ago |
| **disconnected** | Agent never connected or explicitly disconnected | No entry in agents.json or manually removed |

## Instance Fields

| Field | Definition | Example |
|---|---|---|
| **agent_name** | Logical agent identifier shared across instances | `claude_code` |
| **instance_id** | Unique identifier for a specific running instance | `claude_code#worker-01` |
| **role** | Orchestrator role: `leader` (manages tasks) or `team_member` (executes tasks) | `team_member` |
| **project_root** | Filesystem path this instance is working in | `/Users/alex/claude-multi-ai` |
| **current_task_id** | Task ID this instance has claimed (null if idle) | `TASK-8f2649d2` |
| **last_seen** | ISO 8601 timestamp of last heartbeat | `2026-02-26T15:32:46+00:00` |
| **verified** | Whether identity was cryptographically verified on connect | `true` |

## Identity Derivation

`instance_id` is derived using this precedence chain:
1. Explicit `instance_id` in metadata (highest priority)
2. `session_id` from client metadata
3. `connection_id` from client metadata
4. `{agent_name}#default` (lowest priority fallback)

## Ambiguous Scenarios

| You see | What it means |
|---|---|
| `status: active`, `current_task_id: null` | Agent is connected but between tasks |
| `status: stale`, `current_task_id: TASK-xyz` | Agent went offline while working — task may need reassignment |
| Two instances with same `agent_name` | Multi-instance mode (e.g., two Claude Code workers) |
| `instance_id` ends with `#default` | Legacy client without explicit instance identity |
| `project_root` is empty | Agent connected without `cwd` or `project_root` metadata |

## Related Tools

| Tool | What it shows |
|---|---|
| `orchestrator_status` | Summary with `agent_instances` and `active_agent_identities` |
| `orchestrator_list_agents` | Full agent list with metadata and `verified` flag |
| `orchestrator_list_agent_instances` | Detailed instance rows with filtering |
