# Operator FAQ: Instance-Aware Status Fields

> Quick-reference FAQ for operators working with the orchestrator's
> instance-aware status output (`agent_instances`, `active_agent_identities`).

---

### Q1: What is `agent_instances` and how is it different from `active_agents`?

`active_agents` is a simple list of agent names currently online (e.g.
`["codex", "claude_code", "gemini"]`). `agent_instances` is a detailed list
of per-instance records that tracks each distinct connection of an agent,
including its `instance_id`, `role`, `project_root`, `current_task_id`,
`status`, and `last_seen` timestamp. One agent can have multiple instance
records if it reconnects with a different session.

---

### Q2: What is `active_agent_identities`?

`active_agent_identities` is a summary of currently active agents with their
identity metadata — `agent` name, `instance_id`, `status`, `last_seen`, and
`verified` flag. It only includes agents whose last heartbeat is within the
staleness threshold (default: `heartbeat_timeout_minutes` from policy).

---

### Q3: How is `instance_id` determined?

The engine derives `instance_id` using this priority:

1. **Explicit `instance_id`** in metadata (highest priority)
2. **`session_id`** — used when no explicit instance_id is provided
3. **`connection_id`** — fallback when neither instance_id nor session_id exists
4. **`{agent}#default`** — final fallback when no ID metadata is available

Once set, the instance_id persists across heartbeats unless explicitly
overridden in the next registration or heartbeat call.

---

### Q4: Why do I see multiple instance records for the same agent?

Each time an agent registers with a different `session_id` or `instance_id`,
a new instance record is created in `agent_instances.json`. Previous records
are preserved. This happens when:

- The agent process restarts (new session)
- A different terminal/process connects as the same agent
- The agent is deployed on multiple machines

Only the most recent instance (by `last_seen`) is considered "active" for
task claiming and lease operations.

---

### Q5: What happens to old instance records after a restart?

Old instance records remain in `agent_instances.json` with their last
`last_seen` timestamp. They are marked as `offline` when their age exceeds
the `heartbeat_timeout_minutes` threshold. They are NOT automatically deleted.
This preserves audit history and allows operators to see connection patterns.

---

### Q6: Do I need to restart the orchestrator server after agent reconnection?

No. The MCP server handles agent re-registration dynamically. When an agent
calls `orchestrator_connect_to_leader` or `orchestrator_heartbeat` with new
metadata, the engine updates the agent entry and creates a new instance record
if the `instance_id` differs. No server restart is required.

However, the `orchestrator_bootstrap` call is idempotent — calling it again
after restart will NOT overwrite existing state (agents, tasks, instances).
It only creates missing files.

---

### Q7: How do I verify an agent's identity after reconnection?

Check the `verified` field in `active_agent_identities` or `list_agents`
output. An agent is verified when:

- `verification_source` is present in metadata
- `same_project` is `true` (agent's `project_root` matches the orchestrator's)
- The agent has sent a heartbeat within the staleness threshold

Use `orchestrator_list_agents(active_only=true)` to see only verified,
active agents.

---

### Q8: What fields are required in agent metadata for full verification?

The following fields are required for `verified=true` identity:

| Field | Purpose |
|-------|---------|
| `client` | CLI tool name (e.g. `claude-code`, `codex`) |
| `model` | Model identifier (e.g. `claude-opus-4-6`) |
| `cwd` | Current working directory |
| `project_root` | Project root path (must match orchestrator) |
| `permissions_mode` | Permission level (e.g. `default`) |
| `sandbox_mode` | Sandbox setting (e.g. `workspace-write`) |
| `session_id` | Unique session identifier |
| `connection_id` | Connection identifier |
| `server_version` | MCP server version |
| `verification_source` | Source of verification (e.g. `mcp`) |

---

### Q9: How do leases interact with instance_id?

When an agent claims a task, the lease records the `owner_instance_id` —
the `instance_id` of the claiming instance. Lease renewal requires the
renewing agent to have the same `instance_id` as the original claimant.
If the agent restarts with a new session (new `instance_id`), it cannot
renew the old lease. The expired lease will be recovered by the watchdog
and the task requeued for re-claiming.

---

### Q10: Why does `active_agent_identities` show fewer entries than `agent_instances`?

`active_agent_identities` only includes agents with recent heartbeats
(within `heartbeat_timeout_minutes`). `agent_instances` includes all
historical instance records regardless of staleness. An agent that
connected yesterday but hasn't sent a heartbeat today will appear in
`agent_instances` (as offline) but NOT in `active_agent_identities`.

---

### Q11: How do I troubleshoot a "stale" agent?

1. Check `orchestrator_list_agents(active_only=false)` — find the agent's
   `last_seen` timestamp and `age_seconds`
2. If `age_seconds` exceeds the timeout, the agent hasn't sent a heartbeat
3. Check the agent's process — is it running? Can it reach the MCP server?
4. Have the agent call `orchestrator_connect_to_leader` to re-establish
   the connection
5. After reconnection, verify with `orchestrator_list_agents(active_only=true)`

---

### Q12: What is the `current_task_id` field in instance records?

`current_task_id` shows the task currently assigned to that agent instance
(status `in_progress`). It is updated when the agent claims or completes
a task. A value of `null` means the instance has no active task. This field
is useful for seeing at a glance what each agent is working on.

---

### Q13: Can two instances of the same agent work on different tasks simultaneously?

Yes. Each instance has its own `instance_id` and can independently claim
and work on tasks. The orchestrator tracks leases per-instance, so
instance A's lease on task 1 is independent of instance B's lease on task 2.
Both share the same `owner` (agent name) but have different
`owner_instance_id` values.

---

### Q14: How do I see the full status payload with all instance-aware fields?

Call `orchestrator_status` — the response includes:

```
active_agents:             ["codex", "claude_code"]
active_agent_identities:   [{agent, instance_id, status, last_seen, verified}, ...]
agent_instances:           [{agent_name, instance_id, role, status, project_root,
                             current_task_id, last_seen}, ...]
```

For detailed per-agent info, use `orchestrator_list_agents(active_only=false)`.

---

### Q15: Are instance records preserved across `orchestrator_bootstrap`?

Yes. `bootstrap()` is idempotent — it only creates state files that don't
exist yet. Existing `agent_instances.json`, `agents.json`, and `tasks.json`
are preserved. This means agent registrations and instance history survive
server restarts.
