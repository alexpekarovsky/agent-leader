# CORE-05/06 Witness Log Template

Timestamped log for telemetry/noop acceptance observation.

## Metadata

```
Observer: _______________
Date:     _______________
Commit:   _______________
```

## Log format

```
[TIME] EVENT_TYPE | source=X | correlation_id=Y | details
```

## Witness log

Copy and fill rows as events occur:

```
[__:__:__.___] dispatch.command  | source=codex        | correlation_id=________ | task_id=________ target=claude_code
[__:__:__.___] dispatch.ack      | source=claude_code   | correlation_id=________ | status=accepted task_id=________
[__:__:__.___] worker.result     | source=claude_code   | correlation_id=________ | task_id=________ status=done
[__:__:__.___] dispatch.result   | source=codex        | correlation_id=________ | validated=true
[__:__:__.___] dispatch.command  | source=codex        | correlation_id=________ | task_id=________ target=claude_code
[__:__:__.___] dispatch.noop     | source=watchdog     | correlation_id=________ | reason=ack_timeout elapsed_ms=________
```

## Timing measurements

| From event          | To event            | elapsed_ms | Within budget? |
|---------------------|---------------------|------------|----------------|
| dispatch.command    | dispatch.ack        |            | YES / NO       |
| dispatch.ack        | worker.result       |            | YES / NO       |
| dispatch.command    | dispatch.noop       |            | YES / NO       |
| worker.result       | dispatch.result     |            | YES / NO       |

## Noop observation

| Field             | Value |
|-------------------|-------|
| Trigger scenario  |       |
| Noop reason       |       |
| Timeout configured|       |
| Actual elapsed_ms |       |
| Worker state      |       |

## Chain completeness

| Correlation ID | command | ack | result/noop | Complete? |
|----------------|---------|-----|-------------|-----------|
|                | Y/N     | Y/N | Y/N         | YES / NO  |
|                | Y/N     | Y/N | Y/N         | YES / NO  |

## Anomalies

| # | Time  | Description | Severity |
|---|-------|-------------|----------|
| 1 |       |             | low/med/high |

## Signoff

```
Observer: _______________
Date:     _______________
Verdict:  PASS / FAIL
```

## References

- [core-05-06-telemetry-verification-checklist.md](core-05-06-telemetry-verification-checklist.md)
- [core-05-06-evidence-template.md](core-05-06-evidence-template.md)
- [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md)
