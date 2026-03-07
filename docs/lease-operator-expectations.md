# Lease Operator Expectations

This guide translates roadmap lease behavior into operator expectations and recovery actions.

Roadmap alignment: Phase C in [roadmap.md](roadmap.md).

## Scope

- Tracks readiness for `AUTO-M1-CORE-03`.
- Tracks readiness for `AUTO-M1-CORE-04`.
- Applies to manager, worker, and wingman operators.

## Before/After

| Mode | Behavior |
|---|---|
| Before leases | `in_progress` tasks could remain stuck until manual intervention. |
| After leases | lease expiry drives automatic requeue/retry, reducing hidden stalls. |

## Core Terms

- lease: bounded ownership window for a claimed task.
- expiry: timeout point where a stale claim is invalidated.
- requeue: returning task to runnable state after expiry.
- claim: assignment transition from queue to active owner.
- heartbeat: periodic signal proving agent liveness and intent.

## Operator Recovery Commands

- `reassign_stale_tasks`
- `orchestrator_list_tasks`
- `orchestrator_update_task_status`

## Execution Timeline

| Step | Actor | Expected State |
|---|---|---|
| 1 | Manager | Task is created and `assigned`. |
| 2 | Worker | Task is claimed with lease metadata. |
| 3 | Worker | Heartbeat/renew path maintains lease freshness. |
| 4 | Watchdog | Detects missed renewals and pending expiry. |
| 5 | Manager | Expired lease triggers requeue or retry policy. |
| 6 | Worker | Next eligible worker claims and continues safely. |

| Phase | Focus | Operator Impact |
|---|---|---|
| Phase B | `instance_id` reliability | cleaner attribution for claim ownership |
| Phase C | lease + expiry + requeue | fewer stuck tasks and manual restarts |
| Phase D | dispatch/no-op contract | deterministic handoff visibility |
