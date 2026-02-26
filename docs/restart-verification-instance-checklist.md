# Restart Verification Checklist: Instance-Aware Status Visibility

> Post-restart checklist to verify agent_instances and active_agent_identities
> are visible and correct across Codex, Claude Code, and Gemini clients.

## Pre-Restart

- [ ] Note current agent states before restart
- [ ] Record expected instance_ids for each agent
- [ ] Ensure policy file is up-to-date: `config/policy.codex-manager.json`

## Post-Restart Steps

### 1. Verify Server Is Running

```bash
# Check MCP server process
ps aux | grep orchestrator_mcp_server
```

- [ ] Server process is running
- [ ] No startup errors in logs

### 2. Verify Per-Client

#### Codex (Leader)

```
Call: orchestrator_status
```

- [ ] Response contains `agent_instances` key
- [ ] Response contains `active_agent_identities` key
- [ ] `manager` field shows `codex`
- [ ] `roles.leader` shows `codex`

#### Claude Code (Team Member)

```
Call: orchestrator_connect_to_leader(agent="claude_code", ...)
```

- [ ] `connected: true`
- [ ] `verified: true`
- [ ] `identity.same_project: true`
- [ ] Instance appears in `orchestrator_status().agent_instances`

#### Gemini (Team Member)

```
Call: orchestrator_connect_to_leader(agent="gemini", ...)
```

- [ ] `connected: true`
- [ ] `verified: true`
- [ ] Instance appears in `orchestrator_status().agent_instances`

### 3. Verify Instance Fields

For each connected agent, check `orchestrator_list_agent_instances()`:

- [ ] `agent_name` is correct
- [ ] `instance_id` is non-empty (not `#default` for new clients)
- [ ] `role` is `leader` or `team_member`
- [ ] `status` is `active`
- [ ] `project_root` matches working directory
- [ ] `last_seen` is recent (within last minute)

### 4. Verify Multi-Instance (If Applicable)

If running multiple Claude Code instances:

- [ ] Each instance has distinct `instance_id`
- [ ] Both appear in `agent_instances`
- [ ] Sort order is deterministic (by agent_name, then instance_id)

### 5. Verify Stale/Offline Handling

- [ ] Disconnect one agent (close client)
- [ ] Wait for `heartbeat_timeout_minutes` (default: 10)
- [ ] Verify `status` changes to `stale` in instance list
- [ ] Verify `active_agent_identities` no longer includes stale agent

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `agent_instances` key missing | Server version | Reinstall MCP server |
| `instance_id` is `agent#default` | Client metadata | Update client to send `instance_id` |
| `verified: false` | Project root mismatch | Ensure same `project_root` in metadata |
| Agent shows `stale` immediately | Clock skew | Check system time |
| Empty `project_root` | Missing `cwd` in metadata | Update client connection metadata |

## Expected Fields Reference

```
agent_instances[]:
  agent_name, instance_id, role, status,
  project_root, current_task_id, last_seen

active_agent_identities[]:
  agent, instance_id, status, last_seen
```
