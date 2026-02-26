# CORE-06 No-Op Timeout Edge Cases Addendum

Additional edge-case coverage for CORE-05/06 operator verification
focusing on no-op diagnostics under unusual conditions.

## Edge case 1: No active worker connected

### Setup

No worker is connected when manager dispatches a task.

### Expected behavior

| Step | Expected | Verification |
|------|----------|--------------|
| Manager dispatches | `dispatch.command` event emitted | Check event bus |
| Timeout window expires | `dispatch.noop` with `reason: "ack_timeout"` | Check event bus |
| Task state | Unchanged (still `assigned` or `in_progress`) | `list_tasks` |
| Manager reaction | May retry or raise blocker | Check audit log |

### Witness checklist

- [ ] `dispatch.noop` emitted (not stuck waiting forever)
- [ ] Correlation ID present in noop
- [ ] Reason is `ack_timeout` (not `worker_error` or other)
- [ ] No phantom ack appears later
- [ ] Manager does not crash or hang

## Edge case 2: Duplicate-claim risk during noop window

### Setup

Two workers connected. Manager dispatches to worker A, but worker A
is slow to ack. Worker B may attempt to claim the same task.

### Expected behavior

| Step | Expected | Verification |
|------|----------|--------------|
| Dispatch to worker A | `dispatch.command` event | Event bus |
| Worker A slow/no ack | `dispatch.noop` after timeout | Event bus |
| Worker B claims same task | Should succeed only if task reassigned | Audit log |
| Duplicate claim guard | At most one active lease | `list_tasks` |

### Witness checklist

- [ ] Only one worker holds the task at any time
- [ ] Noop does not automatically reassign (advisory only)
- [ ] Manager explicitly reassigns before worker B can claim
- [ ] No duplicate `in_progress` entries for same task

## Edge case 3: Worker acks after noop already emitted

### Setup

Manager emits noop, then worker belatedly sends ack.

### Expected behavior

| Step | Expected | Verification |
|------|----------|--------------|
| Noop emitted | `dispatch.noop` in event log | Event bus |
| Late ack arrives | `dispatch.ack` also in event log | Event bus |
| Manager sees both | Should prefer ack and cancel noop reaction | Audit log |
| Task state | Proceeds normally if ack is valid | `list_tasks` |

### Witness checklist

- [ ] Both noop and late ack visible in event log
- [ ] Manager handles late ack gracefully (no error)
- [ ] Task is not double-processed
- [ ] Correlation IDs match across all three events

## Edge case 4: Rapid successive dispatches with mixed ack/noop

### Setup

Manager dispatches 3 tasks rapidly. Task A gets ack, task B times out
(noop), task C gets ack.

### Expected behavior

| Task | Expected events | Correlation ID unique? |
|------|----------------|----------------------|
| A | command + ack + result | Yes |
| B | command + noop | Yes |
| C | command + ack + result | Yes |

### Witness checklist

- [ ] Each task has its own correlation ID
- [ ] Noop for task B does not interfere with A or C
- [ ] All correlation chains are complete (no orphans)
- [ ] Event ordering is correct per correlation chain

## Edge case 5: Manager restart during noop window

### Setup

Manager crashes and restarts while waiting for ack.

### Expected behavior

- [ ] Restarted manager does not re-emit the same dispatch.command
- [ ] Previous noop timer is effectively cancelled (or fires harmlessly)
- [ ] Task state is consistent after restart
- [ ] No duplicate correlation IDs from pre/post restart

## Telemetry/noop witness log mapping

| Edge case | Witness log field | What to record |
|-----------|-------------------|----------------|
| No worker | Noop observed section | Noop event + reason |
| Duplicate risk | Correlation chain summary | Both workers' events |
| Late ack | Event log table | Noop + late ack timestamps |
| Rapid dispatch | Correlation chain summary | All 3 chains |
| Manager restart | Timing summary | Pre/post restart events |

## References

- [core-05-06-telemetry-verification.md](core-05-06-telemetry-verification.md) -- Base checklist
- [core-05-06-witness-log-template.md](core-05-06-witness-log-template.md) -- Witness log
- [supervisor-known-limitations.md](supervisor-known-limitations.md) -- Dispatch ack gap
- [duplicate-claim-playbook.md](duplicate-claim-playbook.md) -- Collision response
