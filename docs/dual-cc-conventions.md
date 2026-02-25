# Dual Claude Code Session Conventions

Practical conventions for running two Claude Code sessions sharing the `claude_code` agent identity. These workarounds maintain operational clarity until `instance_id` support lands in Phase B (see [docs/swarm-mode.md](swarm-mode.md)).

## Session Labels

Since both sessions register as `claude_code`, use consistent labels in logs and communication to distinguish them.

### Convention: CC1 / CC2

| Label | Meaning | Example use |
|-------|---------|-------------|
| **CC1** | First Claude Code session (primary) | "CC1 working on backend tasks" |
| **CC2** | Second Claude Code session (secondary) | "CC2 handling doc tasks" |

Use these labels in:
- Operator notes when setting claim overrides
- Commit messages when attribution matters
- Report notes to identify which session completed the work

### Alternative: Workstream-based labels

If sessions are partitioned by workstream, name them accordingly:

| Label | Meaning |
|-------|---------|
| **CC-backend** | Session working backend tasks |
| **CC-docs** | Session working documentation tasks |
| **CC-qa** | Session working QA/test tasks |

## Report Note Prefixes

When submitting reports, prefix the `notes` field with the session label so the manager (and operators reviewing reports) can trace which session did the work.

```
# Session CC1 submitting a report:
orchestrator_submit_report(
  task_id="TASK-xxx",
  agent="claude_code",
  commit_sha="abc123",
  status="done",
  notes="[CC1] Implemented feature X. Tests pass.",
  ...
)

# Session CC2 submitting a report:
orchestrator_submit_report(
  task_id="TASK-yyy",
  agent="claude_code",
  commit_sha="def456",
  status="done",
  notes="[CC2] Added smoke test for feature Y.",
  ...
)
```

The engine doesn't parse these prefixes — they're for human readability in report review and audit logs.

## Claim Etiquette

### Rule 1: Don't race on claims

If both sessions call `claim_next_task` simultaneously, the engine's atomic claim prevents double-assignment. But the losing session will immediately claim the *next* available task, which may not be what you intended.

**Preferred**: Use `set_claim_override` to direct specific tasks to each session before claiming.

### Rule 2: One override at a time

The claim override is per-agent, not per-session. Setting an override in CC2 clears any override set by CC1:

```
# CC1 sets override for TASK-aaa
orchestrator_set_claim_override(agent="claude_code", task_id="TASK-aaa", source="codex")

# CC2 sets override for TASK-bbb — this replaces TASK-aaa override!
orchestrator_set_claim_override(agent="claude_code", task_id="TASK-bbb", source="codex")

# CC1 now claims TASK-bbb (not TASK-aaa)
```

**Fix**: Coordinate overrides sequentially. Set override, have the target session claim, then set the next override.

### Rule 3: Check before reassigning

Before calling `reassign_stale_tasks`, verify the other session isn't actively working:

```
# Check what's in progress
orchestrator_list_tasks(status="in_progress")
```

If a task has been `in_progress` for a reasonable time, the other session is probably working on it. Only reassign if you're sure the other session is idle or disconnected.

## Collision Avoidance Patterns

### Git branch strategy

Both sessions commit to the same branch. Avoid conflicts:

- **Different files**: Assign tasks that touch different parts of the codebase
- **Sequential commits**: If both sessions modify the same area, have one finish and push before the other starts
- **Pull before commit**: Run `git pull --rebase` before committing to catch the other session's changes

### Heartbeat coordination

Both sessions share one heartbeat slot. The most recent `connect_to_leader` or `orchestrator_heartbeat` call wins the metadata slot. This means:

- Status may show stale metadata for whichever session connected less recently
- The watchdog may flag `claude_code` as degraded if one session disconnects
- Both sessions should call heartbeat periodically (the worker loop does this automatically)

This is cosmetic — it doesn't affect task claims or report submission.

### Event visibility

Events published by one session are visible to both (they share the `claude_code` event cursor). If CC1 publishes a correction event, CC2 will see it on the next `poll_events` call. This is desirable — both sessions should be aware of corrections and plan changes.

## Operator Checklist

Before starting dual-CC:

- [ ] Decide on session labels (CC1/CC2 or workstream-based)
- [ ] Agree on task partitioning strategy (overrides, workstreams, or free-claim)
- [ ] Ensure both sessions are on the same git branch
- [ ] Clear any stale claim overrides from previous sessions

During operation:

- [ ] Use report note prefixes consistently
- [ ] Coordinate claim overrides sequentially, not in parallel
- [ ] Monitor `in_progress` tasks before reassigning
- [ ] Watch for git conflicts in shared files

After completion:

- [ ] Verify all submitted reports are accepted
- [ ] Check for any orphaned `in_progress` tasks
- [ ] Clear claim overrides

## References

- [docs/dual-cc-operation.md](dual-cc-operation.md) — Technical collision analysis and workflow options
- [docs/swarm-mode.md](swarm-mode.md) — Phase B instance-aware identity resolution
- [docs/task-queue-hygiene.md](task-queue-hygiene.md) — Claim override and task cancellation procedures
