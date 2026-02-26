# CORE-06 No-Op Diagnostic Correlation-First Evidence Capture

Addendum to CORE-05/06 witness templates with a correlation-first
capture approach for no-op timeout diagnostics and retries.

## Correlation-first capture

Instead of recording events chronologically, organize evidence by
correlation ID to quickly verify complete noop chains.

### Correlation chain record

Copy one block per dispatch correlation chain:

```
## Chain: [correlation_id]

Command:
  timestamp: _______________
  task_id: _______________
  target_agent: _______________
  source: event bus / audit log

Ack:
  timestamp: _______________  (or MISSING)
  latency from command: _____ ms

Noop (if timeout):
  timestamp: _______________
  reason: _______________
  latency from command: _____ ms

Retry (if any):
  new correlation_id: _______________
  retry count: ___
  outcome: ack / noop / error
```

### Batch capture table

| Correlation ID | Command time | Ack time | Noop time | Reason | Retry? | Final outcome |
|---------------|-------------|----------|-----------|--------|--------|---------------|
| | | | | | | |
| | | | | | | |
| | | | | | | |

## Retry and escalation tracking

### Retry chain

When a noop triggers a retry, link the chains:

| Original correlation | Retry 1 correlation | Retry 2 correlation | Final outcome |
|---------------------|--------------------|--------------------|---------------|
| | | | ack / noop / blocker |

### Escalation outcomes

| Correlation ID | Noop count | Manager action | Result |
|---------------|------------|----------------|--------|
| | 1 | retry | |
| | 2 | retry | |
| | 3+ | raise blocker | |

## Quick verification checklist

For each noop correlation chain:

- [ ] `dispatch.command` has correlation ID
- [ ] `dispatch.noop` has same correlation ID
- [ ] `reason` field is present and meaningful
- [ ] No phantom `dispatch.ack` arrived after noop
- [ ] Task state unchanged after noop (advisory only)
- [ ] Manager retry (if any) uses new correlation ID
- [ ] Escalation occurred at expected retry threshold

## References

- [core-05-06-witness-log-template.md](core-05-06-witness-log-template.md) -- Witness log
- [core-06-noop-edge-cases.md](core-06-noop-edge-cases.md) -- Edge cases
- [core-05-06-telemetry-verification.md](core-05-06-telemetry-verification.md) -- Checklist
