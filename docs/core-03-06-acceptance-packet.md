# CORE-03..06 Combined Acceptance Packet & Reviewer Checklist

Consolidated signoff artifact for AUTO-M1-CORE-03 (lease schema), CORE-04 (lease expiry recovery), CORE-05 (dispatch telemetry), and CORE-06 (no-op diagnostics).

## Evidence Index

| CORE task | Evidence source | Template |
|-----------|----------------|----------|
| CORE-03 | Lease issuance on claim | [core-03-04-evidence-template.md](core-03-04-evidence-template.md) §1-2 |
| CORE-04 | Lease expiry + requeue | [core-03-04-evidence-template.md](core-03-04-evidence-template.md) §3-6 |
| CORE-03/04 | Cross-source reconciliation | [core-03-04-reconciliation-template.md](core-03-04-reconciliation-template.md) |
| CORE-05 | dispatch.command + dispatch.ack | [core-05-06-evidence-template.md](core-05-06-evidence-template.md) §1-2 |
| CORE-06 | dispatch.noop + diagnostics | [core-05-06-evidence-template.md](core-05-06-evidence-template.md) §3-5 |
| CORE-06 | No-op edge cases | [core-06-noop-edge-cases.md](core-06-noop-edge-cases.md) |
| CORE-05/06 | Witness log | [core-05-06-witness-log-template.md](core-05-06-witness-log-template.md) |

## Part 1: CORE-03/04 Lease Reviewer Checklist

### Functional checks

| # | Check | Evidence ref | Pass? |
|---|-------|-------------|-------|
| L1 | `claim_next_task` returns lease object with `lease_id`, `expires_at`, `attempt_index` | Evidence §1 | [ ] |
| L2 | `lease.owner_instance_id` matches claiming agent's instance | Evidence §1 | [ ] |
| L3 | `renew_lease` extends `expires_at` and updates `renewed_at` | Evidence §2 | [ ] |
| L4 | Expired lease transitions task from `in_progress` to `assigned` | Evidence §3 | [ ] |
| L5 | `attempt_index` increments on re-lease after expiry | Evidence §3 | [ ] |
| L6 | Repeated expiry (>= `max_retries`) raises auto-blocker | Evidence §5 | [ ] |
| L7 | `submit_report` clears/releases the lease | Evidence §6 | [ ] |
| L8 | Watchdog emits `stale_task` for expired leases | Evidence §4 | [ ] |
| L9 | Cross-source reconciliation shows no mismatches | Reconciliation template | [ ] |

### Code quality

| # | Check | Pass? |
|---|-------|-------|
| L10 | Test cases T1-T8 from [lease-schema-test-plan.md](lease-schema-test-plan.md) pass | [ ] |
| L11 | Existing test suite unaffected | [ ] |
| L12 | Configuration parameters (`lease_ttl_seconds`, `max_retries`) documented | [ ] |

## Part 2: CORE-05/06 Telemetry Reviewer Checklist

### Functional checks

| # | Check | Evidence ref | Pass? |
|---|-------|-------------|-------|
| T1 | Manager cycle emits `dispatch.command` events | Evidence §1 | [ ] |
| T2 | Worker ack produces `dispatch.ack` event | Evidence §2 | [ ] |
| T3 | Timeout produces `dispatch.noop` with diagnostic reason | Evidence §3 | [ ] |
| T4 | Audit log shows command→ack→result chain | Evidence §4 | [ ] |
| T5 | No-active-worker edge case produces correct noop reason | Edge cases §1 | [ ] |
| T6 | Duplicate-claim race handled (one ack wins) | Edge cases §2 | [ ] |
| T7 | Worker crash mid-task produces timeout noop | Edge cases §3 | [ ] |
| T8 | Witness log timings are reasonable (no unexplained gaps) | Witness log | [ ] |

### Code quality

| # | Check | Pass? |
|---|-------|-------|
| T9 | Telemetry events match schema in [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) | [ ] |
| T10 | Existing test suite unaffected | [ ] |
| T11 | Noop reason codes documented | [ ] |

## Dependency Verification

| Dependency | Required for | Verified? |
|------------|-------------|-----------|
| CORE-01 (instance_id) | CORE-03 lease `owner_instance_id` | [ ] |
| CORE-02 (instance-aware status) | CORE-04 per-instance expiry detection | [ ] |
| CORE-03 (lease schema) | CORE-04 expiry recovery | [ ] |
| CORE-01 (instance_id) | CORE-05 dispatch targeting | [ ] |
| CORE-05 (dispatch telemetry) | CORE-06 noop diagnostics | [ ] |

## Signoff

| Role | Name | Date | CORE-03/04 | CORE-05/06 |
|------|------|------|-----------|-----------|
| Implementer | | | | |
| Reviewer | | | | |
| Operator | | | | |

**Verdict options:** Accepted / Accepted with notes / Rejected (specify reason)

**Notes:**
```
<any reviewer notes>
```

## References

- [core-03-04-lease-verification-checklist.md](core-03-04-lease-verification-checklist.md)
- [core-05-06-telemetry-verification-checklist.md](core-05-06-telemetry-verification-checklist.md)
- [lease-schema-test-plan.md](lease-schema-test-plan.md)
- [core-blocker-triage-template.md](core-blocker-triage-template.md)
- [restart-milestone-burnup.md](restart-milestone-burnup.md)
