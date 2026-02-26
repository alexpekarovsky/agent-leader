# CORE-03..06 Acceptance Packet Reviewer Checklist

Reviewer-side checklist for validating CORE-03..06 combined acceptance packet contents and evidence quality. Use this alongside the [acceptance packet index](core-03-06-acceptance-packet-index.md).

## Pre-review

- [ ] Packet index received with all artifact locations filled in
- [ ] Packet status is READY (not DRAFT)
- [ ] Preparer identified and available for questions

## CORE-03: Lease Issuance

### Artifact Completeness

| Artifact | Present? | Valid? | Notes |
|----------|----------|--------|-------|
| C03-01: Claim response with lease | | | Must contain lease object with all 7 fields |
| C03-02: Task list showing lease fields | | | At least 1 task with active lease |
| C03-03: Audit log with task.claimed | | | Timestamp matches claim response |
| C03-04: Lease field verification table | | | All fields checked: lease_id, task_id, owner_instance_id, claimed_at, expires_at, renewed_at, attempt_index |
| C03-05: Test results | | | All lease issuance tests pass (T1, T2, T6, T7) |

### Evidence Quality

- [ ] `lease_id` format is consistent (non-empty string, unique per claim)
- [ ] `expires_at` is exactly `claimed_at + configured TTL`
- [ ] `owner_instance_id` matches the claiming agent's actual instance_id
- [ ] `attempt_index` starts at 1 for first claim
- [ ] Concurrent claim test (T7) evidence shows atomic behavior

### Reviewer Verdict: CORE-03

| Criterion | Pass/Fail |
|-----------|-----------|
| All 5 artifacts present | |
| Field values internally consistent | |
| Test results show 0 failures | |
| **CORE-03 overall** | PASS / FAIL |

---

## CORE-04: Lease Expiry and Recovery

### Artifact Completeness

| Artifact | Present? | Valid? | Notes |
|----------|----------|--------|-------|
| C04-01: Watchdog lease_expired event | | | JSONL with task_id and owner |
| C04-02: Requeued task in assigned list | | | Status changed from in_progress to assigned |
| C04-03: Blocked task after max retries | | | Status is blocked after N expiries |
| C04-04: Auto-blocker raised | | | Blocker references lease expiry |
| C04-05: Recovery after report | | | Lease cleared, no false expiry |
| C04-06: Cross-source reconciliation | | | Status, audit, watchdog agree |

### Evidence Quality

- [ ] `attempt_index` incremented on each re-lease (1 -> 2 -> ...)
- [ ] Max retries threshold honored (task blocked at correct count)
- [ ] Blocker reason mentions "lease expired" or equivalent
- [ ] Report submission clears the lease (no lingering expiry)
- [ ] Cross-source reconciliation shows no contradictions between status, audit log, and watchdog

### Reviewer Verdict: CORE-04

| Criterion | Pass/Fail |
|-----------|-----------|
| All 6 artifacts present | |
| Expiry/requeue chain verified | |
| Blocker auto-raised correctly | |
| Cross-source reconciliation clean | |
| **CORE-04 overall** | PASS / FAIL |

---

## CORE-05: Dispatch Telemetry

### Artifact Completeness

| Artifact | Present? | Valid? | Notes |
|----------|----------|--------|-------|
| C05-01: dispatch.command event | | | Contains task_id and correlation_id |
| C05-02: dispatch.ack event | | | Matches command's correlation_id |
| C05-03: worker.result event | | | Contains outcome and timing |
| C05-04: Audit log with dispatch events | | | Chronological dispatch flow |
| C05-05: Schema validation table | | | All required fields checked |

### Evidence Quality

- [ ] `correlation_id` chains correctly: command -> ack -> result
- [ ] Event timestamps are chronologically ordered
- [ ] Payload schema matches documented schema (all required keys present)
- [ ] Source fields identify the correct agents
- [ ] Audit log entries match event bus entries

### Reviewer Verdict: CORE-05

| Criterion | Pass/Fail |
|-----------|-----------|
| All 5 artifacts present | |
| Correlation chain unbroken | |
| Schema validation complete | |
| **CORE-05 overall** | PASS / FAIL |

---

## CORE-06: No-op Diagnostic

### Artifact Completeness

| Artifact | Present? | Valid? | Notes |
|----------|----------|--------|-------|
| C06-01: dispatch.noop event | | | Event with noop reason |
| C06-02: Noop correlation chain | | | Links to triggering conditions |
| C06-03: Timeout behavior matrix | | | Covers all timeout scenarios |
| C06-04: Edge case results | | | At least 3 edge cases documented |
| C06-05: Witness log | | | Observer-signed log |

### Evidence Quality

- [ ] Noop event includes clear reason for no-action
- [ ] Correlation chain links noop to the correct idle/timeout condition
- [ ] Timeout matrix covers: normal, extended, zero, negative values
- [ ] Edge cases include at least: empty queue, all agents offline, rapid successive noops
- [ ] Witness log signed by observer with timestamp

### Reviewer Verdict: CORE-06

| Criterion | Pass/Fail |
|-----------|-----------|
| All 5 artifacts present | |
| Noop reasons are clear and correct | |
| Edge cases adequately covered | |
| **CORE-06 overall** | PASS / FAIL |

---

## Combined Verdict

| Section | Artifacts | Quality | Verdict |
|---------|-----------|---------|---------|
| CORE-03 | _/5 | | PASS / FAIL |
| CORE-04 | _/6 | | PASS / FAIL |
| CORE-05 | _/5 | | PASS / FAIL |
| CORE-06 | _/5 | | PASS / FAIL |
| **Total** | _/21 | | **PASS / FAIL** |

## Rejection Criteria

The packet should be rejected if any of the following are true:

| # | Rejection condition |
|---|-------------------|
| 1 | Any artifact is missing without documented justification |
| 2 | Test results show failures in lease or telemetry tests |
| 3 | Cross-source reconciliation has unresolved contradictions |
| 4 | Correlation chain is broken (missing ack or result) |
| 5 | Witness log is unsigned or undated |
| 6 | Blocker auto-raise did not trigger at configured max retries |

## Reviewer Signoff

| Field | Value |
|-------|-------|
| **Reviewer** | |
| **Date** | |
| **Verdict** | APPROVED / REJECTED |
| **Rejection reason** | (if applicable) |
| **Follow-up needed** | (if applicable) |

## References

- [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md) — Packet artifact inventory
- [lease-witness-log-template.md](lease-witness-log-template.md) — Lease observation template
- [lease-schema-test-plan.md](lease-schema-test-plan.md) — Test case definitions (T1-T8)
- [lease-operator-expectations.md](lease-operator-expectations.md) — Before/after lease behavior
