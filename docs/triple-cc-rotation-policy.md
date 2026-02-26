# Triple-CC Workstream Rotation Policy

Rules for rotating CC1/CC2/CC3 sessions across workstreams to prevent
starvation when sharing a single `claude_code` identity.

## Problem

With three CC sessions and one identity, the `claim_next_task` API
returns tasks in queue order.  If one workstream has many more tasks,
sessions working on other workstreams may starve — their tasks pile
up while the busy workstream drains first.

## Rotation rules

### Rule 1: Fixed primary workstream

Each session has a primary workstream assignment:

| Session | Primary workstream | Fallback |
|---------|-------------------|----------|
| CC1 | `qa` | `default`, then `devops` |
| CC2 | `default` | `qa`, then `devops` |
| CC3 | `devops` | `default`, then `qa` |

### Rule 2: Claim from primary first

Each session should attempt to work on tasks from its primary
workstream.  Use `set_claim_override` to direct the next task:

```
# Manager routes a qa task to CC1
orchestrator_set_claim_override(
  agent="claude_code",
  task_id="TASK-qa-next",
  source="codex"
)
```

### Rule 3: Rotate on empty queue

When a session's primary workstream has no claimable tasks, it moves
to its fallback workstream.  The rotation order is:

```
primary → fallback_1 → fallback_2 → idle
```

### Rule 4: Maximum consecutive tasks per workstream

No session should work on more than **5 consecutive tasks** from the
same workstream without checking other workstreams for pending work.
This prevents tunnel vision on a deep queue.

### Rule 5: Idle session picks up overflow

If a session goes idle (no tasks in primary or fallback), it should
pick up tasks from any workstream with the longest queue.

## Rotation triggers

| Trigger | Action |
|---------|--------|
| Primary queue empty | Move to fallback workstream |
| 5 consecutive tasks in same workstream | Check other workstreams for pending tasks |
| Session idle for 2+ cycles | Pick up from any workstream |
| Manager publishes rebalance event | All sessions re-read their assignments |

## Rebalance event

The manager can trigger a rotation review:

```
orchestrator_publish_event(
  type="manager.execution_plan",
  source="codex",
  payload={
    "action": "rebalance",
    "partitions": [
      {"session": "CC1", "workstream": "qa", "tasks_remaining": 3},
      {"session": "CC2", "workstream": "default", "tasks_remaining": 12},
      {"session": "CC3", "workstream": "devops", "tasks_remaining": 0}
    ],
    "instruction": "CC3 has no devops tasks. Reassign CC3 to help CC2 with default workstream."
  }
)
```

## Starvation detection

The manager or operator should monitor for starvation:

```
# Check queue depth per workstream
orchestrator_list_tasks(status="assigned")
```

If any workstream has more than **10 assigned tasks** while another
has 0, rebalance by reassigning a session.

## Limitations

- The `claim_next_task` API does not filter by workstream — rotation
  depends on `set_claim_override` or session discipline
- No automatic enforcement — the manager must actively monitor and
  rebalance
- Rotation becomes unnecessary once instance-aware mode ships
  (each instance can have workstream affinity in its registration)

## References

- [multi-cc-partition-templates.md](multi-cc-partition-templates.md) — Workstream-based partitioning
- [triple-cc-assignment-board.md](triple-cc-assignment-board.md) — Assignment tracking
- [triple-cc-session-naming.md](triple-cc-session-naming.md) — Session label conventions
- [dual-cc-operation.md](dual-cc-operation.md) — Dual-session coordination
