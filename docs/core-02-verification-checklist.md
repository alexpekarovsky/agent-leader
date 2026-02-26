# CORE-02 Operator Verification Checklist

Post-restart verification for AUTO-M1-CORE-02 (instance-aware status
section for multi-session visibility).

## What CORE-02 delivers

Each running agent instance gets a unique entry in `orchestrator_list_agents`
with its own `instance_id`, heartbeat timestamp, and current task.

## Verification steps

### Step 1: Check agent list includes instance IDs

```
orchestrator_list_agents(active_only=false)
```

**Expected fields per entry:**

| Field | Example | Check |
|-------|---------|-------|
| `agent_name` | `claude_code` | Present |
| `instance_id` | `claude_code#worker-01` | Non-empty, matches format `{agent}#{suffix}` |
| `status` | `active` | One of: `active`, `idle`, `stale`, `disconnected` |
| `last_seen` | `2026-02-26T00:10:00Z` | Recent (within 60s) |

- [ ] All running agents appear in the list
- [ ] Each agent has a unique `instance_id`
- [ ] No duplicate `instance_id` values

### Step 2: Verify multiple instances distinguishable

If running multiple Claude Code sessions:

```
orchestrator_list_agents(active_only=true)
```

- [ ] Two separate entries for `claude_code` (e.g., `#worker-01` and `#worker-02`)
- [ ] Each has its own `last_seen` timestamp
- [ ] Each shows its own `current_task_id` (or null)

### Step 3: Verify stale detection is per-instance

Kill one instance and wait for stale threshold:

- [ ] Killed instance shows `stale` or `disconnected`
- [ ] Other instances of same agent remain `active`
- [ ] Stale instance does not affect other instances' status

### Step 4: Check instance records

```
orchestrator_list_agent_instances(active_only=false)
```

- [ ] Returns structured records with `agent_name`, `instance_id`, `metadata`
- [ ] Multiple instances of same agent appear as separate records
- [ ] `last_seen` timestamps are per-instance

## Backward compatibility check

- [ ] Agents without explicit `instance_id` get fallback format (`{agent}#default`)
- [ ] Existing single-session workflows still work (no regression)
- [ ] `connect_to_leader` without `instance_id` succeeds

## References

- [instance-aware-status-fields.md](instance-aware-status-fields.md) — Field definitions
- [roadmap.md](roadmap.md) — Phase B instance-aware presence
- [restart-milestone-checklist.md](restart-milestone-checklist.md) — Post-restart validation
