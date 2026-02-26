# CORE-05/06 Telemetry and No-Op Operator Verification Checklist

Validation checklist for dispatch telemetry scaffolding (CORE-05) and
no-op diagnostics on manager execute timeout (CORE-06).

## CORE-05: Dispatch telemetry visibility

### Command/ack flow

After manager dispatches a task to a worker:

```
orchestrator_poll_events(agent="codex", timeout_ms=5000)
```

- [ ] `dispatch.command` event visible with correlation ID
- [ ] Event includes `task_id` and `target_agent`
- [ ] `dispatch.ack` event follows from worker
- [ ] Ack includes matching correlation ID

### Result flow

After worker completes and reports:

- [ ] `worker.result` or `worker.error` event visible
- [ ] Event includes correlation ID from original dispatch
- [ ] Result links back to the dispatch command

### Telemetry in audit log

```
orchestrator_list_audit_logs(limit=10)
```

- [ ] Dispatch events appear in audit trail
- [ ] Correlation IDs are consistent across command→ack→result chain
- [ ] Timestamps show chronological ordering

### Event schema validation

Each dispatch event should contain:

| Field | Type | Present in |
|-------|------|-----------|
| `correlation_id` | string | command, ack, result, noop |
| `task_id` | string | command, ack, result |
| `source_agent` | string | all events |
| `target_agent` | string | command |
| `timestamp` | ISO 8601 | all events |
| `event_type` | string | all events |

- [ ] All required fields present in observed events
- [ ] No missing correlation IDs

## CORE-06: No-op diagnostic on timeout

### Triggering a no-op

When a manager dispatch receives no ack within the timeout window:

- [ ] `dispatch.noop` event emitted automatically
- [ ] Noop includes correlation ID of the timed-out command
- [ ] Noop includes `reason` field (e.g., "ack_timeout")

### Verifying no-op in logs

```
# Check watchdog or event log
orchestrator_poll_events(agent="codex", timeout_ms=5000)
```

- [ ] `dispatch.noop` event appears after timeout period
- [ ] Manager can distinguish noop from successful ack
- [ ] Noop event does not cause task state change (advisory only)

### Timeout behavior

| Scenario | Expected event | Task state |
|----------|---------------|------------|
| Worker acks in time | `dispatch.ack` | Unchanged (in_progress) |
| Worker does not ack | `dispatch.noop` after timeout | Unchanged (manager decides next) |
| Worker errors | `worker.error` | Manager reassigns or blocks |
| Worker completes | `worker.result` | Reported → validation |

### Manager reaction to noop

After observing a `dispatch.noop`:

- [ ] Manager can retry the dispatch
- [ ] Manager can reassign the task
- [ ] Manager can raise a blocker
- [ ] Noop count visible in diagnostics

## End-to-end verification

Run a complete dispatch cycle and verify the full chain:

1. Manager creates dispatch command → `dispatch.command` event
2. Worker receives and acks → `dispatch.ack` event
3. Worker completes → `worker.result` event
4. All three events share the same `correlation_id`

```
# Verify correlation chain
orchestrator_list_audit_logs(limit=20)
# Filter for a specific correlation_id
```

- [ ] Complete chain visible in audit log
- [ ] No orphaned commands without ack or noop
- [ ] Timestamps are monotonically increasing

## References

- [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) — Event schema definitions
- [roadmap.md](roadmap.md) — Phase D deterministic dispatch
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — Dispatch acknowledgment gap
