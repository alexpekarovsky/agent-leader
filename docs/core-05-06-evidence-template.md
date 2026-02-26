# CORE-05/06 Telemetry and No-Op Evidence Capture Template

Structured template for recording dispatch command/ack/noop diagnostics
and timeout escalation observations during verification.

## Metadata

```
Operator: _______________
Date: _______________
CORE-05/06 checklist: docs/core-05-06-telemetry-verification.md
Restart test ID: _______________
```

## CORE-05: Dispatch telemetry visibility

### 5.1 Command/ack flow evidence

**Command:**

```
orchestrator_poll_events(agent="codex", timeout_ms=5000)
```

**Raw output (dispatch.command event):**

```json
[paste dispatch.command event here]
```

**Raw output (dispatch.ack event):**

```json
[paste dispatch.ack event here]
```

**Source provenance:** orchestrator event bus

**Correlation ID captured:** `_______________`

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| `dispatch.command` visible | | |
| Includes `correlation_id` | | |
| Includes `task_id` | | |
| Includes `target_agent` | | |
| `dispatch.ack` follows | | |
| Ack has matching `correlation_id` | | |

### 5.2 Result flow evidence

**Raw output (worker.result event):**

```json
[paste worker.result event here]
```

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| `worker.result` or `worker.error` visible | | |
| Includes `correlation_id` from dispatch | | |
| Links back to command | | |

### 5.3 Audit log evidence

**Command:**

```
orchestrator_list_audit_logs(limit=10)
```

**Raw output (dispatch-related entries):**

```json
[paste audit entries here]
```

**Source provenance:** orchestrator audit log

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Dispatch events in audit trail | | |
| Correlation IDs consistent | | |
| Timestamps chronological | | |

### 5.4 Event schema validation

For each observed dispatch event, verify required fields:

| Event | `correlation_id` | `task_id` | `source_agent` | `target_agent` | `timestamp` | `event_type` |
|-------|-------------------|-----------|-----------------|----------------|-------------|--------------|
| command | | | | | | |
| ack | | | | n/a | | |
| result | | | | n/a | | |

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| All required fields present | | |
| No missing correlation IDs | | |

## CORE-06: No-op diagnostic on timeout

### 6.1 No-op trigger evidence

**Setup:** [How timeout was triggered - e.g., no worker connected, worker paused]

**Command:**

```
orchestrator_poll_events(agent="codex", timeout_ms=5000)
```

**Raw output (dispatch.noop event):**

```json
[paste dispatch.noop event here]
```

**Correlation ID:** `_______________`

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| `dispatch.noop` emitted | | |
| Includes timed-out command's `correlation_id` | | |
| Includes `reason` field | | |
| `reason` value (e.g., `ack_timeout`) | | |

### 6.2 No-op in logs evidence

**Raw output (noop in event log):**

```json
[paste event log showing noop]
```

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Noop appears after timeout period | | |
| Distinguishable from successful ack | | |
| No task state change (advisory only) | | |

### 6.3 Timeout behavior matrix

Record observed behavior for each scenario:

| Scenario | Expected event | Observed event | Task state before | Task state after | Pass/Fail |
|----------|---------------|----------------|-------------------|------------------|-----------|
| Worker acks in time | `dispatch.ack` | | | | |
| Worker does not ack | `dispatch.noop` | | | | |
| Worker errors | `worker.error` | | | | |
| Worker completes | `worker.result` | | | | |

### 6.4 Manager reaction evidence

After observing a `dispatch.noop`:

| Action | Attempted | Result | Notes |
|--------|-----------|--------|-------|
| Retry dispatch | | | |
| Reassign task | | | |
| Raise blocker | | | |
| Noop count in diagnostics | | | |

## End-to-end correlation chain

### Full dispatch cycle evidence

**Correlation ID for chain:** `_______________`

| Step | Event type | Timestamp | Present? |
|------|-----------|-----------|----------|
| 1. Dispatch | `dispatch.command` | | |
| 2. Ack | `dispatch.ack` | | |
| 3. Result | `worker.result` | | |

**Audit log verification:**

```
orchestrator_list_audit_logs(limit=20)
# Filter for correlation_id: _______________
```

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Complete chain visible | | |
| No orphaned commands | | |
| Timestamps monotonically increasing | | |

## Overall result

| Section | Result |
|---------|--------|
| CORE-05 Command/ack | PASS / FAIL |
| CORE-05 Result flow | PASS / FAIL |
| CORE-05 Audit | PASS / FAIL |
| CORE-05 Schema | PASS / FAIL |
| CORE-06 Noop trigger | PASS / FAIL |
| CORE-06 Log visibility | PASS / FAIL |
| CORE-06 Timeout matrix | PASS / FAIL |
| E2E chain | PASS / FAIL |
| **Overall** | **PASS / FAIL** |

## Signoff

```
Operator: _______________
Date: _______________
Result: PASS / FAIL
Notes: _______________
```

## References

- [core-05-06-telemetry-verification.md](core-05-06-telemetry-verification.md) -- Checklist
- [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) -- Event schema
- [supervisor-known-limitations.md](supervisor-known-limitations.md) -- Dispatch ack gap
- [evidence-folder-layout.md](evidence-folder-layout.md) -- Evidence storage
