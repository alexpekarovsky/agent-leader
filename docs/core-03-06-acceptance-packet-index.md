# CORE-03..06 Combined Acceptance Packet Index

Index template for the CORE-03..06 acceptance evidence packet
covering lease system (CORE-03/04) and dispatch telemetry (CORE-05/06).

## Packet metadata

```
Packet ID: AUTO-M1-CORE-03-06-[DATE]
Preparer: _______________
Date: _______________
Status: DRAFT / READY / SIGNED OFF
```

## Artifact inventory

### CORE-03: Lease issuance

| Artifact ID | Description | File/location | Provenance | Collected? |
|------------|-------------|---------------|------------|-----------|
| C03-01 | Claim response with lease | evidence/core-03/claim-response.json | orchestrator claim_next_task | |
| C03-02 | Task list showing lease fields | evidence/core-03/task-lease.json | orchestrator list_tasks | |
| C03-03 | Audit log with task.claimed | evidence/core-03/audit-claim.json | orchestrator list_audit_logs | |
| C03-04 | Lease field verification table | evidence/core-03/field-check.md | manual verification | |
| C03-05 | Test results | evidence/core-03/test-results.txt | test_lease_schema_test_plan.py | |

### CORE-04: Lease expiry and recovery

| Artifact ID | Description | File/location | Provenance | Collected? |
|------------|-------------|---------------|------------|-----------|
| C04-01 | Watchdog lease_expired event | evidence/core-04/watchdog-expiry.jsonl | watchdog JSONL | |
| C04-02 | Requeued task in assigned list | evidence/core-04/requeue.json | orchestrator list_tasks | |
| C04-03 | Blocked task after max retries | evidence/core-04/blocked-task.json | orchestrator list_tasks | |
| C04-04 | Auto-blocker raised | evidence/core-04/auto-blocker.json | orchestrator list_blockers | |
| C04-05 | Recovery after report | evidence/core-04/post-report.json | orchestrator list_tasks | |
| C04-06 | Cross-source reconciliation | evidence/core-04/reconciliation.md | filled template | |

### CORE-05: Dispatch telemetry

| Artifact ID | Description | File/location | Provenance | Collected? |
|------------|-------------|---------------|------------|-----------|
| C05-01 | dispatch.command event | evidence/core-05/dispatch-command.json | orchestrator poll_events | |
| C05-02 | dispatch.ack event | evidence/core-05/dispatch-ack.json | orchestrator poll_events | |
| C05-03 | worker.result event | evidence/core-05/worker-result.json | orchestrator poll_events | |
| C05-04 | Audit log with dispatch events | evidence/core-05/audit-dispatch.json | orchestrator list_audit_logs | |
| C05-05 | Schema validation table | evidence/core-05/schema-check.md | manual verification | |

### CORE-06: No-op diagnostic

| Artifact ID | Description | File/location | Provenance | Collected? |
|------------|-------------|---------------|------------|-----------|
| C06-01 | dispatch.noop event | evidence/core-06/dispatch-noop.json | orchestrator poll_events | |
| C06-02 | Noop correlation chain | evidence/core-06/noop-chain.md | filled template | |
| C06-03 | Timeout behavior matrix | evidence/core-06/timeout-matrix.md | manual observation | |
| C06-04 | Edge case results | evidence/core-06/edge-cases.md | filled template | |
| C06-05 | Witness log | evidence/core-06/witness-log.md | filled template | |

## Completeness check

| Section | Total artifacts | Collected | Missing | Complete? |
|---------|----------------|-----------|---------|-----------|
| CORE-03 | 5 | | | |
| CORE-04 | 6 | | | |
| CORE-05 | 5 | | | |
| CORE-06 | 5 | | | |
| **Total** | **21** | | | |

## Cross-reference to signoff summaries

| Summary doc | Status |
|-------------|--------|
| [core-02-04-signoff-summary.md](core-02-04-signoff-summary.md) | DRAFT / COMPLETE |
| [core-05-06-signoff-summary.md](core-05-06-signoff-summary.md) | DRAFT / COMPLETE |

## Packet signoff

```
Preparer: _______________
Reviewer: _______________
Date: _______________
Packet status: COMPLETE / INCOMPLETE
Missing items: _______________
```

## References

- [core-03-04-evidence-template.md](core-03-04-evidence-template.md)
- [core-05-06-evidence-template.md](core-05-06-evidence-template.md)
- [core-03-04-cross-source-reconciliation.md](core-03-04-cross-source-reconciliation.md)
- [core-06-noop-correlation-capture.md](core-06-noop-correlation-capture.md)
- [evidence-folder-layout.md](evidence-folder-layout.md)
