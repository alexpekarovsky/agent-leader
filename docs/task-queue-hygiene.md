# Task Queue Hygiene and Mistaken-Task Rollback

The orchestrator uses an append-only task model. There is no `delete_task` API. This document covers how to handle accidental task creation, clean up unwanted tasks, and prevent auto-reassignment races.

## The No-Delete Constraint

Tasks cannot be removed from `state/tasks.json` via MCP tools. This is intentional — it preserves audit trail integrity. Instead, unwanted tasks are moved to terminal states that exclude them from active queues.

## Cancelling a Mistaken Task

### Step 1: Block the task with a cancellation note

```
orchestrator_update_task_status(
  task_id="TASK-xxx",
  status="blocked",
  source="operator",
  note="Cancelled: created in error. Do not implement."
)
```

This removes the task from the claimable queue immediately.

### Step 2: Clear any claim override targeting this task

If a `set_claim_override` was issued for this task:

```
orchestrator_set_claim_override(
  agent="claude_code",
  task_id="",
  source="operator"
)
```

Setting an empty `task_id` clears the override. Repeat for each agent that may have an override.

### Step 3: Publish a correction event

Notify the team so agents don't reference the cancelled task:

```
orchestrator_publish_event(
  type="manager.correction",
  source="operator",
  payload={
    "action": "task_cancelled",
    "task_id": "TASK-xxx",
    "reason": "Created in error"
  }
)
```

### Step 4: Verify the active queue

```
orchestrator_list_tasks(status="assigned")
orchestrator_list_tasks(status="in_progress")
```

Confirm the cancelled task does not appear in either list.

## Bulk Cleanup: Cancelling Multiple Tasks

If a manager cycle created many unwanted tasks, block them in a batch:

```
# In a connected CLI session, for each unwanted task:
orchestrator_update_task_status(task_id="TASK-aaa", status="blocked", source="operator", note="Cancelled: batch cleanup")
orchestrator_update_task_status(task_id="TASK-bbb", status="blocked", source="operator", note="Cancelled: batch cleanup")
orchestrator_update_task_status(task_id="TASK-ccc", status="blocked", source="operator", note="Cancelled: batch cleanup")
```

Then publish a single correction event listing all affected IDs.

## Auto-Reassignment Race Conditions

The manager cycle and `orchestrator_reassign_stale_tasks` can reassign tasks automatically when an agent is stale. This can cause races if you're simultaneously trying to cancel tasks.

### Preventing races

1. **Block the task first** — blocked tasks are not reassigned by `reassign_stale_tasks`
2. **Then** clear overrides and publish events
3. **Verify** the task stayed blocked after the next manager cycle

If a manager cycle reassigns a blocked task back to `assigned` (this shouldn't happen, but if it does), block it again and check that no override is forcing it back.

### Checking for stale reassignment

Look for `reassigned_from` and `degraded_comm` fields on a task:

```
orchestrator_list_tasks(status="assigned")
```

Tasks with `degraded_comm: true` were auto-reassigned from a stale owner. This is normal behavior, not an error.

## Deduplication

The orchestrator has built-in deduplication. When `orchestrator_create_task` receives a title matching an existing open task, it returns the existing task with `deduplicated: true` instead of creating a duplicate.

To manually deduplicate after the fact:

```
orchestrator_dedupe_tasks(source="operator")
```

This closes newer duplicates and keeps the oldest canonical task.

## Direct State File Editing (Last Resort)

If MCP tools are insufficient (e.g., the server is down), you can edit `state/tasks.json` directly:

1. Stop all autopilot loops first (`supervisor.sh stop` or `tmux kill-session`)
2. Edit `state/tasks.json` — remove or modify task entries
3. Restart loops

**Caution**: Direct edits bypass audit logging. The orchestrator will not record what changed or why. Use MCP tools whenever possible.

## Verification Checklist

After any cleanup operation:

- [ ] Cancelled tasks show `status: "blocked"` with cancellation note
- [ ] No claim overrides point to cancelled tasks
- [ ] `orchestrator_list_tasks(status="assigned")` shows only intended tasks
- [ ] `orchestrator_list_tasks(status="in_progress")` has no orphaned tasks
- [ ] Correction event published if agents need to be notified
- [ ] Next manager cycle does not resurrect cancelled tasks
