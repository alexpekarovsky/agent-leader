# CORE-05/06 Telemetry & No-op Verification Checklist

Verification for dispatch telemetry (CORE-05) and no-op diagnostics
(CORE-06). Confirms the command/ack/noop event flow works end-to-end.

## Step 1: Start manager cycle, verify dispatch.command events

Trigger a manager cycle that dispatches work to a worker:

```
orchestrator_manager_cycle()
```

Check the event bus for dispatch commands:

```
orchestrator_poll_events(agent="claude_code")
```

- [ ] A `dispatch.command` event was emitted
- [ ] Event includes `correlation_id` (non-empty, unique)
- [ ] Event includes `target` matching the worker agent
- [ ] Event includes `action` (e.g., `claim_next`, `work_task`)
- [ ] Event includes `timeout_seconds` (positive integer)
- [ ] Event includes ISO 8601 `timestamp`

## Step 2: Worker responds, verify dispatch.ack event

After the worker processes the command:

```
orchestrator_poll_events(agent="codex")
```

- [ ] A `dispatch.ack` event was emitted by the worker
- [ ] `correlation_id` matches the `dispatch.command` from Step 1
- [ ] `source` matches the worker agent (e.g., `claude_code`)
- [ ] `status` is one of: `accepted`, `rejected`, `busy`
- [ ] If `accepted`, `task_id` is present and matches the claimed task

## Step 3: Worker times out, verify dispatch.noop

To test the timeout path, dispatch a command to an agent that is not
running or is unresponsive. Wait for the command's `timeout_seconds` to
elapse.

```
orchestrator_poll_events(agent="codex")
```

- [ ] A `dispatch.noop` event was emitted
- [ ] `correlation_id` matches the original `dispatch.command`
- [ ] `source` identifies the timeout detector (watchdog or manager)
- [ ] `target` matches the unresponsive worker
- [ ] `reason` is one of: `ack_timeout`, `result_timeout`, `agent_disconnected`
- [ ] `elapsed_seconds` is present and >= the command's `timeout_seconds`

### Noop reason codes

| Reason | Meaning | Diagnostic value |
|--------|---------|-----------------|
| `ack_timeout` | No ack received within timeout | Worker may be dead or disconnected |
| `result_timeout` | Ack received but no result | Worker started but hung or crashed |
| `agent_disconnected` | Worker heartbeat went stale | Worker process is down |

## Step 4: Check audit log for command-ack-result chain

```
orchestrator_list_audit_logs(limit=20)
```

- [ ] Audit log contains the `dispatch.command` entry
- [ ] Audit log contains the matching `dispatch.ack` (or `dispatch.noop`)
- [ ] Entries share the same `correlation_id`
- [ ] Entries appear in chronological order: command -> ack/noop -> result
- [ ] Each entry includes the calling agent and timestamp

## Step 5: Verify timeout noop contains useful diagnostic info

Review the `dispatch.noop` event from Step 3:

- [ ] `reason` field clearly indicates why no response was received
- [ ] `elapsed_seconds` helps operators assess how long the system waited
- [ ] `target` identifies which worker failed to respond
- [ ] `correlation_id` allows tracing back to the originating command
- [ ] The noop event is visible in the manager log output

## Observable outputs summary

| Output | Where to check | What to look for |
|--------|---------------|-----------------|
| Event bus | `orchestrator_poll_events(agent=...)` | `dispatch.command`, `dispatch.ack`, `dispatch.noop` events |
| Audit log | `orchestrator_list_audit_logs(limit=20)` | Correlated chain of command/ack/result entries |
| Manager log | `.autopilot-logs/manager-codex-*.log` | Dispatch commands emitted and noop timeouts logged |

## Pass/fail criteria

| Criterion | Pass | Fail |
|-----------|------|------|
| Command emitted | `dispatch.command` in event bus | No command event |
| Ack received | `dispatch.ack` with matching correlation_id | Missing ack for live worker |
| Noop on timeout | `dispatch.noop` after timeout expires | No noop for dead worker |
| Audit trail | All events in audit log with correlation | Missing audit entries |
| Diagnostic info | Noop includes reason + elapsed_seconds | Empty or missing fields |

## References

- [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) -- Event payload schemas
- [roadmap.md](roadmap.md) -- Phase D deterministic dispatch
- [supervisor-known-limitations.md](supervisor-known-limitations.md) -- Current prototype gaps
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) -- Watchdog event format
