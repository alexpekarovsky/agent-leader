# Session Rebalancing Playbook

How to redistribute work when one of CC1/CC2/CC3 sessions goes offline during active queue execution.

## Temporary Outage (< 15 minutes)

The disconnected session will likely reconnect soon. Don't reassign its tasks.

### Steps

1. **Identify the offline session**
   ```
   orchestrator_list_tasks(status="in_progress")
   ```
   Look for tasks owned by `claude_code` that haven't progressed.

2. **Wait before reassigning**
   - The task has a watchdog stale threshold (default 900s)
   - If the session reconnects within 15 min, it will resume automatically
   - Other sessions continue working their own tasks

3. **Monitor**
   ```
   orchestrator_status()
   ```
   Check if `claude_code` heartbeat resumes. With shared identity, any active session's heartbeat counts.

### Don't do

- Don't call `reassign_stale_tasks` with low thresholds
- Don't block the offline session's tasks
- Don't change claim overrides

## Prolonged Outage (> 15 minutes)

The session is not coming back soon. Redistribute its work.

### Steps

1. **Check what the offline session was working on**
   ```
   orchestrator_list_tasks(status="in_progress")
   ```
   Note the task ID and how far along it was (check recent worker logs).

2. **Decide: resume or reassign**

   | Situation | Action |
   |-----------|--------|
   | Task barely started | Block it, let remaining sessions claim fresh |
   | Task partially done with uncommitted work | Wait longer or accept the loss |
   | Task partially done with committed work | Remaining session picks up from commit |
   | Task nearly complete | Let remaining session finish via override |

3. **Reassign the stuck task**
   ```
   # Option A: Let engine handle it
   reassign_stale_tasks(source="codex", stale_after_seconds=900)

   # Option B: Manual reassignment
   orchestrator_update_task_status(
     task_id="TASK-xxx",
     status="assigned",
     source="codex",
     note="CC2 went offline. Reassigning."
   )
   ```

4. **Rebalance lanes**

   If CC2 went down and CC1 + CC3 remain:

   | Before | After |
   |--------|-------|
   | CC1: backend | CC1: backend + overflow |
   | CC2: docs (offline) | — |
   | CC3: QA/smoke | CC3: QA + docs |

5. **Update execution plan** (template for manager event)
   ```
   orchestrator_publish_event(
     event_type="plan.update",
     source="codex",
     payload={
       "reason": "CC2 offline — rebalancing lanes",
       "active_sessions": ["CC1", "CC3"],
       "cc1_scope": "backend + overflow from CC2",
       "cc3_scope": "QA + docs",
       "reassigned_tasks": ["TASK-xxx"]
     }
   )
   ```

## Two Sessions Go Offline

If both CC2 and CC3 are down, CC1 operates alone:

1. Reassign any stuck in_progress tasks
2. CC1 claims tasks sequentially (no override coordination needed)
3. Reduce scope to highest-priority items only
4. Consider pausing lower-priority workstreams

## Session Comes Back Online

When a previously offline session reconnects:

1. **Reconnect to leader**
   ```
   orchestrator_connect_to_leader(agent="claude_code", ...)
   ```

2. **Check for available work**
   ```
   orchestrator_list_tasks(status="assigned")
   ```

3. **Coordinate with active sessions**
   - Check if claim overrides are set
   - Announce session label in first report note: `[CC2] Back online.`
   - Resume normal lane assignment

## Session Label Consistency

When rebalancing, keep labels consistent:

- **Don't rename**: CC1 stays CC1, even if CC2 and CC3 are offline
- **Don't reuse**: If CC2 goes offline, don't make CC3 the "new CC2"
- **Document**: Note the rebalancing in report notes

## References

- [multi-cc-conventions.md](multi-cc-conventions.md) — Session labels
- [session-handoff-template.md](session-handoff-template.md) — Context transfer
- [claim-preflight-checklist.md](claim-preflight-checklist.md) — Pre-claim checks
