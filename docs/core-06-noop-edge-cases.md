# CORE-06 No-Op Timeout Edge Cases

Addendum covering edge cases beyond the standard ack-timeout path.

## Edge case 1: No active worker

**Scenario:** Manager emits `dispatch.command` but no worker is connected.

**Expected:** `dispatch.noop` with `reason: "no_active_worker"` after timeout.

**Verification:**
```
# 1. Stop all workers
# 2. Trigger manager cycle
orchestrator_manager_cycle()
# 3. Poll for noop
orchestrator_poll_events(agent="codex", timeout_ms=5000)
```

**Evidence:**
```json
PASTE_NOOP_EVENT_HERE
```

| Check                              | P/F |
|------------------------------------|-----|
| `dispatch.command` emitted         |     |
| No `dispatch.ack` received         |     |
| `dispatch.noop` with `no_active_worker` |  |

## Edge case 2: Duplicate claim race

**Scenario:** Two workers both attempt to ack the same `dispatch.command`.

**Expected:** Only one `dispatch.ack` succeeds; other gets rejected or a different command.

**Verification:**
```
# 1. Start two workers
# 2. Dispatch single command
orchestrator_manager_cycle()
# 3. Check audit log for duplicate ack attempts
orchestrator_list_audit_logs(limit=10)
```

**Evidence:**
```json
PASTE_AUDIT_ENTRIES_HERE
```

| Check                              | P/F |
|------------------------------------|-----|
| Exactly one `dispatch.ack` for the correlation_id |  |
| Second worker got different command or rejection   |  |
| No task claimed by both workers    |     |

## Edge case 3: Worker crashes mid-task

**Scenario:** Worker sends `dispatch.ack` but crashes before producing a result.

**Expected:** `dispatch.noop` with `reason: "worker_timeout"` after result timeout.

**Verification:**
```
# 1. Worker acks command, then kill worker process
# 2. Wait for result timeout
# 3. Check event bus and watchdog
orchestrator_poll_events(agent="codex", timeout_ms=5000)
```

**Evidence:** `PASTE_NOOP_EVENT` | **Watchdog:** `PASTE_STALE_TASK_ENTRY`

| Check | P/F |
|-------|-----|
| `dispatch.ack` received initially, no `worker.result` within timeout | |
| `dispatch.noop` with `worker_timeout` | |
| Watchdog `stale_task` event emitted | |

## Summary

| Edge case | Result | | Edge case | Result |
|-----------|--------|-|-----------|--------|
| 1 No active worker | PASS / FAIL | | 3 Worker crash mid-task | PASS / FAIL |
| 2 Duplicate claim race | PASS / FAIL | | | |

## References

- [core-05-06-telemetry-verification-checklist.md](core-05-06-telemetry-verification-checklist.md)
- [supervisor-known-limitations.md](supervisor-known-limitations.md)
