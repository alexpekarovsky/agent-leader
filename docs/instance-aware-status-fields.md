# Instance-Aware Status Fields (Operator Reference)

Field definitions for the planned instance-aware status view.  These
fields will appear in `orchestrator_list_agents` and status dashboards
once AUTO-M1-CORE-01/02 ship.

## Status fields

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `agent_name` | string | `claude_code` | Base agent identity (unchanged from MVP) |
| `instance_id` | string | `claude_code#worker-01` | Unique instance identifier combining agent name and instance suffix |
| `role` | string | `team_member` | Agent role: `leader` or `team_member` |
| `status` | string | `active` | Registration status: `active`, `idle`, `stale`, `disconnected` |
| `project_root` | string | `/Users/alex/project` | Absolute path to the project this instance is working on |
| `current_task_id` | string \| null | `TASK-abcdef12` | Task currently claimed by this instance, or null if idle |
| `last_seen` | string | `2026-02-26T00:10:00Z` | ISO 8601 timestamp of last heartbeat |
| `lease_expiry` | string \| null | `2026-02-26T00:20:00Z` | When the current task lease expires (future, with CORE-03/04) |

## Status values

| Value | Meaning | Operator action |
|-------|---------|-----------------|
| `active` | Instance connected and heartbeating normally | None |
| `idle` | Instance connected but has no claimed task | Check if tasks are available |
| `stale` | Heartbeat age exceeds threshold | Verify instance is still running |
| `disconnected` | Instance has not heartbeated for an extended period | Restart the instance or reassign its tasks |

## Instance ID format

```
{agent_name}#{instance_suffix}
```

Examples:
- `claude_code#worker-01` — first Claude Code worker
- `claude_code#worker-02` — second Claude Code worker
- `gemini#worker-01` — Gemini worker
- `codex#leader` — manager/leader instance

The instance suffix is assigned at registration time.  The supervisor
will support `--worker-count N` to launch multiple instances with
sequential suffixes.

## Current MVP vs instance-aware

| Aspect | MVP (now) | Instance-aware (planned) |
|--------|-----------|-------------------------|
| Identity | `claude_code` (shared) | `claude_code#worker-01` (unique) |
| Heartbeat | One slot per agent name | One slot per instance |
| Status | Shows one entry regardless of session count | Shows each instance separately |
| Task ownership | By agent name | By instance ID |
| Stale detection | Per agent name | Per instance |

## Example status output (planned)

```
Agent status:
  codex#leader         active   task=none           last_seen=2s ago
  claude_code#worker-01  active   task=TASK-abc123  last_seen=5s ago
  claude_code#worker-02  active   task=TASK-def456  last_seen=3s ago
  gemini#worker-01     idle     task=none           last_seen=8s ago
```

## References

- [roadmap.md](roadmap.md) — Phase B instance-aware presence
- [dual-cc-operation.md](dual-cc-operation.md) — Current multi-session workaround
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — Instance limitation
- [swarm-mode.md](swarm-mode.md) — Full swarm mode prerequisites
