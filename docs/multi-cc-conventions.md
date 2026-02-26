# Multi-CC Report Note Conventions and Queue Hygiene

Conventions for running 2-3 Claude Code sessions sharing the `claude_code` identity. Extends [dual-cc-conventions.md](dual-cc-conventions.md) with triple-CC labeling and queue hygiene for mistaken tasks.

> **Interim workaround** until `instance_id` ships in Phase B.

## Session Labels

| Sessions | Labels | Use case |
|----------|--------|----------|
| 2 | CC1, CC2 | Normal dual operation |
| 3 | CC1, CC2, CC3 | Sprint acceleration |

### Label assignment

Assign labels by role or workstream:

| Label | Suggested role |
|-------|---------------|
| CC1 | Primary worker (backend/features) |
| CC2 | Secondary worker (docs/tests) |
| CC3 | QA or overflow (smoke tests, validation) |

## Report Note Tags

Always tag report notes with the session label:

```
notes="[CC1] Implemented lease schema. 8/8 tests pass."
notes="[CC2] Created supervisor troubleshooting doc."
notes="[CC3] Ran full smoke test suite. 99/99 pass."
```

### Tag format

- Square brackets: `[CC1]`, `[CC2]`, `[CC3]`
- At the start of the notes string
- One tag per report (the session that did the work)

## Task Claiming Etiquette

### Don't race

With 3 sessions, race conditions on `claim_next_task` are more likely. Use overrides:

```
# Operator directs specific tasks to each session:
set_claim_override(agent="claude_code", task_id="TASK-aaa", source="codex")
# CC1 claims TASK-aaa

set_claim_override(agent="claude_code", task_id="TASK-bbb", source="codex")
# CC2 claims TASK-bbb

set_claim_override(agent="claude_code", task_id="TASK-ccc", source="codex")
# CC3 claims TASK-ccc
```

### Override is per-agent, not per-session

Setting a new override replaces the previous one. Coordinate sequentially:

1. Set override for CC1 → CC1 claims → clear
2. Set override for CC2 → CC2 claims → clear
3. Set override for CC3 → CC3 claims → clear

### Check before reassigning

With 3 sessions, more tasks are in_progress simultaneously. Before reassigning:

```
orchestrator_list_tasks(status="in_progress")
```

Verify the owning session is actually idle, not just slow.

## Duplicate Claim Avoidance

### Problem

If two sessions call `claim_next_task` at the same time:
- Both get different tasks (engine is atomic per task)
- But one session may get a task intended for the other

### Prevention

1. **Use overrides** for critical task routing
2. **Stagger claims**: let one session finish claiming before the next starts
3. **Check in_progress**: before claiming, see what's already being worked on

### If a wrong session claimed a task

The task is assigned to `claude_code` regardless of which session claimed it. Any session can work on it. If you need to redirect:

```
# Submit a report as blocked with a note:
orchestrator_submit_report(
  task_id="TASK-xxx",
  agent="claude_code",
  commit_sha="<any recent sha>",
  status="blocked",
  notes="[CC2] Wrong session claimed this. Reassign to CC1 stream.",
  test_summary={"command": "n/a", "passed": 0, "failed": 0}
)
```

## Mistaken Task Rollback

### Task created by mistake

Tasks cannot be deleted (by design — preserves audit trail). To neutralize a mistaken task:

1. Claim the task: `claim_next_task(owner="claude_code")` or use override
2. Submit a blocking report:
   ```
   orchestrator_submit_report(
     task_id="TASK-xxx",
     agent="claude_code",
     commit_sha="<any sha>",
     status="blocked",
     notes="[CC1] Created by mistake. Blocking to remove from active queue.",
     test_summary={"command": "n/a", "passed": 0, "failed": 0}
   )
   ```

### Duplicate task

If two identical tasks exist:

1. Use `orchestrator_dedupe_tasks()` if available
2. Or block one manually (as above) with note: "Duplicate of TASK-yyy"

### Task assigned to wrong agent

```
# Update task status back to assigned:
orchestrator_update_task_status(
  task_id="TASK-xxx",
  status="assigned",
  source="codex",
  note="Reassigning from claude_code to codex"
)
```

## Git Collision Prevention (3 Sessions)

With 3 sessions committing to the same branch:

1. **Pull before commit**: `git pull --rebase` in every session before committing
2. **Different files**: assign tasks that touch different directories
3. **Sequential pushes**: don't push from 3 sessions simultaneously
4. **Merge conflicts**: resolve immediately to avoid blocking other sessions

## References

- [dual-cc-conventions.md](dual-cc-conventions.md) — Original dual-CC conventions
- [dual-cc-operation.md](dual-cc-operation.md) — Collision analysis and workflows
- [dual-cc-quick-ref.md](dual-cc-quick-ref.md) — Quick reference card
- [task-queue-hygiene.md](task-queue-hygiene.md) — Task cancellation and deduplication
