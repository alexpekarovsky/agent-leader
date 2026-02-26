# CORE-02 Operator Verification Checklist

Verification for AUTO-M1-CORE-02 (instance-aware status section for
multi-session visibility).

## Pre-check: confirm CORE-01

Before verifying CORE-02, confirm that CORE-01 instance_id support is working:

```
orchestrator_status()
```

- [ ] Status output includes `instance_id` in agent metadata
- [ ] No errors related to missing instance fields

## Step 1: Call orchestrator_list_agents

```
orchestrator_list_agents(active_only=false)
```

- [ ] Response returns a list of agent entries
- [ ] Each entry has an `instance_id` field (non-null, non-empty)
- [ ] Each entry includes all expected fields (see table below)

### Expected fields per entry

| Field | Type | Example | Check |
|-------|------|---------|-------|
| `agent_name` | string | `claude_code` | Present, matches known agent |
| `instance_id` | string | `claude_code#worker-01` | Non-empty |
| `role` | string | `team_member` | One of: `leader`, `team_member` |
| `status` | string | `active` | One of: `active`, `idle`, `stale`, `disconnected` |
| `last_seen` | ISO 8601 | `2026-02-26T00:10:00Z` | Recent timestamp |

## Step 2: Verify instance_id format

- [ ] Each `instance_id` follows the format `{agent_name}#{suffix}`
- [ ] The `{agent_name}` prefix matches the `agent_name` field
- [ ] The `#{suffix}` portion is non-empty (e.g., `worker-01`, `leader`, `default`)
- [ ] No duplicate `instance_id` values across all entries

Examples of valid formats:
- `claude_code#worker-01`
- `claude_code#worker-02`
- `gemini#worker-01`
- `codex#leader`

## Step 3: Start two workers, verify separate entries

Start two Claude Code worker sessions and verify both appear:

```
# After both workers connect:
orchestrator_list_agents(active_only=true)
```

- [ ] Two separate entries for `claude_code` appear
- [ ] Each has a distinct `instance_id` (e.g., `#worker-01` and `#worker-02`)
- [ ] Each has its own `last_seen` timestamp
- [ ] Each shows its own `current_task_id` (or null if idle)
- [ ] No duplicate entries

## Step 4: Stop one worker, verify stale/disconnected

Stop one of the two workers and wait for the stale threshold:

```
# After stopping one worker, wait ~60s, then:
orchestrator_list_agents(active_only=false)
```

- [ ] Stopped worker shows `stale` or `disconnected` status
- [ ] Running worker remains `active`
- [ ] Stopped worker's `last_seen` is old (no longer updating)
- [ ] Running worker's `last_seen` is recent
- [ ] No cross-contamination (stopping one does not affect the other)

## Pass/fail criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| All agents have `instance_id` | Field present and non-empty | Field missing or empty |
| Format is `{agent}#{suffix}` | Matches pattern | Wrong format or missing separator |
| Two workers distinguishable | Separate entries with unique IDs | Single entry or duplicate IDs |
| Stale detection per-instance | Only stopped worker shows stale | Both show stale, or neither does |
| Backward compatibility | Agents without explicit ID get `{agent}#default` | Error or missing entry |

## References

- [instance-aware-status-fields.md](instance-aware-status-fields.md) -- Field definitions and status values
- [restart-milestone-checklist.md](restart-milestone-checklist.md) -- Post-restart validation context
- [roadmap.md](roadmap.md) -- Phase B instance-aware presence
