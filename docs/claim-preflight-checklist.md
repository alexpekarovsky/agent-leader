# Claim Preflight Checklist

Quick checks to run before calling `claim_next_task` when multiple sessions share the `claude_code` identity. Reduces duplicate claims and wasted work.

## Before Claiming

### 1. Check what's already in progress

```
orchestrator_list_tasks(status="in_progress")
```

- If another session is already working a task, don't claim yet — let it finish
- If you see a stuck task (>15 min with no progress), it may need reassignment

### 2. Check for pending overrides

```
orchestrator_status()
```

- Look at `claim_overrides` in the status output
- If an override is set for `claude_code`, the next claim will get that specific task
- Don't claim if the override was intended for a different session

### 3. Poll for recent events

```
orchestrator_poll_events(agent="claude_code")
```

- Check for correction events or plan changes from the manager
- If a task was just reassigned away from you, don't re-claim it

### 4. Verify your session label

Before claiming, decide your session label ([CC1], [CC2], [CC3]) so you can tag your report notes consistently.

## Claiming

```
orchestrator_claim_next_task(owner="claude_code")
```

After claiming, immediately note which task you got and confirm it's appropriate for your session's workstream.

## After Claiming

### If you got the wrong task

The engine's atomic claim prevents double-assignment, but you may get a task intended for a different workstream. Options:

1. **Work it anyway** — if it's within your capability
2. **Submit as blocked** — with a note explaining the mismatch:
   ```
   orchestrator_submit_report(
     task_id="TASK-xxx",
     agent="claude_code",
     commit_sha="<any sha>",
     status="blocked",
     notes="[CC2] Wrong stream. Reassign to CC1.",
     test_summary={"command": "n/a", "passed": 0, "failed": 0}
   )
   ```

### If no task was returned

- All tasks may be assigned or in progress — wait for the other session to finish
- Check `orchestrator_list_tasks(status="assigned")` — if tasks exist but aren't claimable, they may be assigned to a different agent (e.g., `codex`)

## Collision Recovery

If two sessions accidentally claim tasks in quick succession and one gets a task it shouldn't have:

1. The "wrong" session submits the task as `blocked` with a note
2. The manager re-assigns the task on the next validation cycle
3. The correct session can then claim it via override

Do **not** try to have one session work on another session's claimed task — the report will be accepted (same `claude_code` owner) but it creates audit confusion.

## References

- [multi-cc-conventions.md](multi-cc-conventions.md) — Session labels and etiquette
- [dual-cc-quick-ref.md](dual-cc-quick-ref.md) — Quick reference card
- [task-queue-hygiene.md](task-queue-hygiene.md) — Blocking and deduplication
