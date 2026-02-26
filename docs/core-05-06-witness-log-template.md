# CORE-05/06 Telemetry/No-Op Acceptance Witness Log

Witness log for recording telemetry and no-op acceptance observations
in real time during verification runs.

## Session info

```
Witness: _______________
Date: _______________
Test environment: [local | staging]
```

## Event log

Record each observed event as it happens:

| # | Time (HH:MM:SS) | Event type | Correlation ID | Source agent | Task ID | Notes |
|---|-----------------|------------|----------------|-------------|---------|-------|
| 1 | | `dispatch.command` | | | | |
| 2 | | `dispatch.ack` | | | | |
| 3 | | `worker.result` | | | | |
| 4 | | `dispatch.noop` | | | | |
| 5 | | | | | | |

## Command path witness

### Dispatch command observed

```json
[paste raw event]
```

- Correlation ID: `_______________`
- Task ID: `_______________`
- Target agent: `_______________`
- Timestamp: `_______________`

### Ack observed

```json
[paste raw event]
```

- Correlation ID matches command: YES / NO
- Latency (command to ack): _____ ms

### Result observed

```json
[paste raw event]
```

- Correlation ID matches command: YES / NO
- Latency (ack to result): _____ s

## No-op/timeout path witness

### Timeout trigger setup

```
Method: [stopped worker | no worker connected | artificial delay]
Expected timeout window: _____ ms
```

### No-op observed

```json
[paste raw dispatch.noop event]
```

- Correlation ID: `_______________`
- Reason field value: `_______________`
- Actual wait before noop: _____ ms
- Task state after noop: `_______________` (should be unchanged)

### Timeout escalation

| Escalation step | Observed? | Details |
|-----------------|-----------|---------|
| Manager retry | | |
| Manager reassign | | |
| Blocker raised | | |
| Noop count incremented | | |

## Correlation chain summary

| Chain # | Correlation ID | command? | ack? | result/noop? | Complete? |
|---------|---------------|----------|------|--------------|-----------|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

## Timing summary

| Metric | Value |
|--------|-------|
| Avg command-to-ack latency | |
| Avg ack-to-result latency | |
| Timeout-to-noop latency | |
| Total chains observed | |
| Complete chains | |
| Orphaned commands | |

## CORE-05/06 signoff

| Check | Pass/Fail |
|-------|-----------|
| dispatch.command events visible | |
| dispatch.ack events with matching correlation | |
| worker.result events with matching correlation | |
| dispatch.noop events on timeout | |
| Noop includes reason field | |
| No task state change on noop | |
| Audit log has all events | |
| Timestamps monotonically increasing | |

```
Witness: _______________
Verdict: PASS / FAIL
Date: _______________
```

## References

- [core-05-06-telemetry-verification.md](core-05-06-telemetry-verification.md) -- Verification checklist
- [core-05-06-evidence-template.md](core-05-06-evidence-template.md) -- Evidence capture template
- [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) -- Event schema
