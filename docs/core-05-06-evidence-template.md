# CORE-05/06 Telemetry and No-Op Evidence Template

Captures dispatch command, ack, noop, audit chain, and timeout diagnostics.
## Metadata

```
Operator: _______________
Date:     _______________
Test ID:  _______________
```

## dispatch.command evidence

```json
PASTE_DISPATCH_COMMAND_EVENT
```

| Check                        | P/F |
|------------------------------|-----|
| `dispatch.command` visible   |     |
| `correlation_id` present     |     |
| `task_id` present            |     |
| `target_agent` present       |     |

## dispatch.ack evidence

```json
PASTE_DISPATCH_ACK_EVENT
```

| Check                              | P/F |
|------------------------------------|-----|
| `dispatch.ack` emitted             |     |
| `correlation_id` matches command   |     |
| `source` matches worker            |     |

## dispatch.noop evidence

```json
PASTE_DISPATCH_NOOP_EVENT
```

| Check                              | P/F |
|------------------------------------|-----|
| `dispatch.noop` emitted            |     |
| `correlation_id` matches command   |     |
| `reason` field present             |     |
| Reason value: `_______________`    |     |

## Audit log chain (command -> ack -> result)

```json
PASTE_AUDIT_LOG_ENTRIES
```

| Step       | Event              | Timestamp | Present? |
|------------|-------------------|-----------|----------|
| 1. Dispatch | `dispatch.command` |           |          |
| 2. Ack      | `dispatch.ack`    |           |          |
| 3. Result   | `worker.result`   |           |          |

| Check                           | P/F |
|---------------------------------|-----|
| Complete chain visible          |     |
| Correlation IDs consistent      |     |
| Timestamps chronological        |     |

## Timeout diagnostic

| Field             | Value |
|-------------------|-------|
| Noop reason       |       |
| `elapsed_seconds` |       |
| Target worker     |       |
| Correlation ID    |       |

## Summary

| Evidence point | Result | | Evidence point | Result |
|----------------|--------|-|----------------|--------|
| dispatch.command | PASS / FAIL | | Audit log chain | PASS / FAIL |
| dispatch.ack | PASS / FAIL | | Timeout diagnostic | PASS / FAIL |
| dispatch.noop | PASS / FAIL | | **Overall** | **PASS / FAIL** |

**Operator:** _______________ | **Date:** _______________ | **Result:** PASS / FAIL

## References

- [core-05-06-telemetry-verification-checklist.md](core-05-06-telemetry-verification-checklist.md)
- [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md)
