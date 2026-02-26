# Queue Hygiene Checker

Step-by-step procedure for neutralizing mistaken bulk-task creation
waves.  Covers status verification, event publication, and
post-cleanup validation.

## When to use

Run this procedure when:

- A manager cycle accidentally created a large batch of unwanted tasks
- Tasks were created with wrong workstream, owner, or acceptance criteria
- A duplicate task wave was generated despite deduplication

## Procedure

### Step 1: Identify affected tasks

List recently created tasks and identify the bad batch:

```
orchestrator_list_tasks(status="assigned")
```

Look for tasks with similar titles, timestamps, or workstream patterns
that indicate a bulk-creation mistake.

### Step 2: Block all affected tasks

For each task in the mistaken batch, set status to `blocked` with a
rollback note:

```
orchestrator_update_task_status(
  task_id="TASK-xxx",
  status="blocked",
  source="operator",
  note="Rollback: bulk-creation mistake. Do not implement."
)
```

Repeat for every affected task.  Tasks in `blocked` status are excluded
from the claimable queue immediately.

### Step 3: Check for in-progress claims

Verify no agent has already claimed a task from the bad batch:

```
orchestrator_list_tasks(status="in_progress")
```

If any in-progress tasks belong to the bad batch:

1. Wait for the agent to complete and submit a report, then block
   the task during validation
2. Or update the task to `blocked` directly — the agent's next
   `submit_report` will fail with a status mismatch

### Step 4: Clear claim overrides

If any `set_claim_override` entries target affected tasks:

```
orchestrator_set_claim_override(
  agent="claude_code",
  task_id="",
  source="operator"
)
orchestrator_set_claim_override(
  agent="gemini",
  task_id="",
  source="operator"
)
```

### Step 5: Publish correction event

Notify all agents about the rollback:

```
orchestrator_publish_event(
  type="manager.correction",
  source="operator",
  payload={
    "action": "bulk_task_rollback",
    "affected_tasks": ["TASK-aaa", "TASK-bbb", "TASK-ccc"],
    "reason": "Mistaken bulk creation — tasks do not match milestone scope",
    "instruction": "Ignore these tasks. Do not implement or reference them."
  }
)
```

### Step 6: Run deduplication

If duplicates exist alongside valid tasks:

```
orchestrator_dedupe_tasks(source="operator")
```

This closes newer duplicates and keeps the oldest canonical version.

### Step 7: Verify cleanup

```
# No affected tasks should be assignable
orchestrator_list_tasks(status="assigned")

# No affected tasks should be in progress
orchestrator_list_tasks(status="in_progress")

# Affected tasks should show blocked
orchestrator_list_tasks(status="blocked")
```

Confirm:

- [ ] All affected tasks show `status: "blocked"` with rollback note
- [ ] No assigned tasks remain from the bad batch
- [ ] No in-progress tasks remain from the bad batch
- [ ] Correction event published
- [ ] Claim overrides cleared for all agents
- [ ] Next manager cycle does not recreate the tasks

## Append-only constraint

The orchestrator event log is append-only.  The correction event does
not remove the original creation events — it adds a new event that
supersedes them.  Agents reading the event stream will see both the
original creation and the correction.  The `manager.correction` event
type signals that earlier events should be disregarded.

Similarly, `state/tasks.json` retains all tasks including blocked ones.
There is no `delete_task` API.  Blocked tasks remain in the file but
are excluded from active queues.

## Prevention

To reduce the risk of mistaken bulk creation:

- Use `--dry-run` or review task titles before calling `create_task`
  in a loop
- Set reasonable limits on tasks created per manager cycle
- Monitor task counts after each manager cycle
- Use `orchestrator_dedupe_tasks` proactively after large creation runs

## References

- [task-queue-hygiene.md](task-queue-hygiene.md) — Full queue hygiene guide
- [dual-cc-operation.md](dual-cc-operation.md) — Multi-session coordination
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Stale task recovery
