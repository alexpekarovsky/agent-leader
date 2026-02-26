# Dual Claude Code Operation in MVP

How to run two Claude Code sessions against the same project today, despite single-agent identity limitations.

## The Core Limitation

The orchestrator identifies agents by name (`claude_code`), not by instance. Both sessions register as `claude_code`, share one heartbeat slot, and compete for the same task claims. There is no `instance_id` until Phase B (see [docs/swarm-mode.md](swarm-mode.md)).

### What breaks with naive dual operation

| Problem | Cause |
|---------|-------|
| Heartbeat overwrite | Second session's `connect_to_leader` overwrites the first session's metadata (session_id, connection_id) |
| Double claim | Both sessions call `claim_next_task(agent="claude_code")` — only one wins, but the loser may retry and claim a different task before the first session finishes |
| Report collision | Both sessions can call `submit_report` for tasks owned by `claude_code` — the engine accepts whichever arrives first |
| Status confusion | `orchestrator_status` shows one `claude_code` entry regardless of how many sessions are running |

### What still works

- Task creation with `owner` override routes tasks correctly
- `set_claim_override` can direct a specific task to `claude_code`
- Events and correction broadcasts are visible to all connected sessions
- Git commits from different sessions are distinguishable by commit SHA and message

## Recommended Dual-CC Workflow

### Option A: Manual task partitioning (simplest)

Assign tasks directly to each session using claim overrides. Avoids race conditions entirely.

```
# Session 1 operator: force claim a specific task
orchestrator_set_claim_override(agent="claude_code", task_id="TASK-aaa", source="codex")
# Then in Session 1: claim_next_task picks up TASK-aaa

# Session 2 operator: force a different task
orchestrator_set_claim_override(agent="claude_code", task_id="TASK-bbb", source="codex")
# Then in Session 2: claim_next_task picks up TASK-bbb
```

**Downside**: Requires operator to manually assign each task. Only practical for a small number of tasks.

### Option B: Workstream separation

Create tasks in different workstreams and have each session only work on its assigned workstream. This requires manual discipline since the engine doesn't enforce per-session workstream filters.

```
# Session 1: only work on backend tasks
# Session 2: only work on devops tasks
```

**Downside**: Relies on session-level prompts to enforce scope. The claim API doesn't filter by workstream.

### Option C: Sequential claiming with coordination (current practice)

Both sessions use the normal `claim_next_task` flow. The engine's atomic claim prevents double-assignment of the same task. However, sessions may interleave and race.

Coordination conventions:
1. Each session calls `connect_to_leader` at startup — the later connection wins the metadata slot
2. Both sessions claim tasks normally — the engine ensures each task is claimed by exactly one caller
3. If a session finds no claimable tasks, it waits (the other session may be working through the queue)
4. Submitted reports reference the commit SHA, so the manager can validate regardless of which session submitted

**Downside**: Status metadata shows whichever session connected most recently. Heartbeat age may look stale for the other session.

## Collision Avoidance Checklist

Before starting dual-CC operation:

- [ ] Verify both sessions target the same project root (same `state/` directory)
- [ ] Ensure no `set_claim_override` is active from a previous session
- [ ] Agree on workstream or task partitioning strategy
- [ ] Keep both sessions on the same git branch to avoid merge conflicts
- [ ] Monitor `orchestrator_list_tasks(status="in_progress")` to confirm no duplicate claims

During operation:

- [ ] If a task appears stuck, check which session is actually working on it before reassigning
- [ ] Don't run `reassign_stale_tasks` with low thresholds — it may reassign a task the other session is actively implementing
- [ ] Watch for git conflicts when both sessions commit to the same files

## Known Edge Cases

### Heartbeat staleness false positive

With two sessions, the heartbeat slot is shared. Session B's `connect_to_leader` overwrites Session A's `last_seen`. If Session B disconnects, Session A's heartbeat may appear stale even though it's actively working. The manager or watchdog may flag `claude_code` as degraded.

**Workaround**: Have both sessions call `orchestrator_heartbeat` periodically (the worker loop does this automatically).

### Report for wrong session's task

Both sessions submit reports as `claude_code`. If Session A completes TASK-aaa and Session B completes TASK-bbb, both reports are accepted normally since the engine validates by task owner (`claude_code`) and commit SHA, not by session identity.

If both sessions accidentally work on the same task (shouldn't happen with atomic claims, but possible with overrides), the first report wins and the second gets a validation error.

### Claim override race

If you set a `claim_override` for `claude_code`, both sessions compete to claim it. The first `claim_next_task` call wins. Clear the override after the intended session claims, or the other session may pick it up on retry.

## When to Use Dual-CC vs. Wait for Swarm Mode

| Scenario | Recommendation |
|----------|----------------|
| Small batch of independent tasks | Dual-CC with manual partitioning works fine |
| Large task queue with dependencies | Wait for instance-aware presence (Phase B) |
| Continuous autopilot operation | Use single CC + gemini (designed configuration) |
| One-off acceleration of a backlog | Dual-CC with sequential claiming is acceptable |

## Future: Instance-Aware Resolution

Phase B of the roadmap ([docs/roadmap.md](roadmap.md)) adds `instance_id` to the agent registration:

```
claude_code#worker-01
claude_code#worker-02
```

Each instance gets its own heartbeat slot, claim scope, and status entry. This eliminates all collision problems described above. The supervisor will support `--worker-count N` for launching multiple instances of the same CLI type.

## References

- [docs/swarm-mode.md](swarm-mode.md) — Full swarm mode prerequisites
- [docs/roadmap.md](roadmap.md) — Phase B instance-aware presence details
- [docs/headless-mvp-architecture.md](headless-mvp-architecture.md) — MVP limitations table
- docs/task-queue-hygiene.md — Claim override and task cancellation procedures
