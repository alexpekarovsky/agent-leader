# CORE-03/04 Lease Acceptance Signoff Workflow

Consolidated workflow for preparing, reviewing, and signing off the
CORE-03 (lease issuance) and CORE-04 (lease expiry/recovery) acceptance
evidence. Ties together witness observations, cross-source reconciliation,
the acceptance packet index, and the reviewer checklist into a single
step-by-step process.

## Workflow overview

```
Step 1: Collect evidence (witness log)
   |
Step 2: Reconcile across sources
   |
Step 3: Assemble packet (packet index)
   |
Step 4: Self-review and fill checklist
   |
Step 5: Submit for reviewer signoff
```

## Artifact map

| Artifact | Template doc | Purpose | CORE |
|----------|-------------|---------|------|
| Witness log | [lease-witness-log-template.md](lease-witness-log-template.md) | Record live observations of lease behavior | 03+04 |
| Reconciliation | [core-03-04-cross-source-reconciliation.md](core-03-04-cross-source-reconciliation.md) | Cross-check status, audit, and watchdog | 03+04 |
| Packet index | [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md) | Artifact inventory with collection status | 03+04 |
| Reviewer checklist | [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md) | Reviewer pass/fail criteria per section | 03+04 |
| Evidence template | [core-03-04-evidence-template.md](core-03-04-evidence-template.md) | Raw evidence capture format | 03+04 |
| Signoff summary | [core-02-04-signoff-summary.md](core-02-04-signoff-summary.md) | Combined CORE-02..04 signoff record | 02-04 |

## Step 1: Collect evidence (witness log)

Use [lease-witness-log-template.md](lease-witness-log-template.md) to
record observations during a live test session.

### CORE-03 observations (lease issuance)

| Obs | Scenario | What to capture | Source |
|-----|----------|----------------|--------|
| 1 | Lease created on claim | lease_id, task_id, owner_instance_id, claimed_at, expires_at, attempt_index | `claim_next_task()` response |
| 2 | Lease renewal extends expiry | renewed_at updated, expires_at extended | `renew_lease()` response |
| 3 | Lease released on report | Lease cleared, task status `reported` | `submit_report()` + task record |
| 6 | Instance_id fallback | `{agent}#default` when no explicit ID | `claim_next_task()` response |

### CORE-04 observations (expiry recovery)

| Obs | Scenario | What to capture | Source |
|-----|----------|----------------|--------|
| 4 | Expired lease triggers requeue | Task back to `assigned`, attempt_index incremented | Expiry cycle + event bus |
| 5 | Repeated expiry raises blocker | Task `blocked` after max retries, blocker reason | Expiry cycle + `list_blockers()` |

### Evidence collection commands

```bash
# Claim response with lease fields (C03-01)
orchestrator_claim_next_task agent=claude_code > evidence/core-03/claim-response.json

# Task list showing lease (C03-02)
orchestrator_list_tasks status=in_progress > evidence/core-03/task-lease.json

# Audit log entries (C03-03)
orchestrator_list_audit_logs limit=20 > evidence/core-03/audit-claim.json

# Watchdog expiry event (C04-01)
cat "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)" > evidence/core-04/watchdog-expiry.jsonl

# Blockers (C04-04)
orchestrator_list_blockers > evidence/core-04/auto-blocker.json

# Test results (C03-05)
python3 -m unittest tests/test_lease_schema_test_plan.py -v > evidence/core-03/test-results.txt 2>&1
```

## Step 2: Reconcile across sources

Use [core-03-04-cross-source-reconciliation.md](core-03-04-cross-source-reconciliation.md)
to compare evidence from status output, audit logs, and watchdog JSONL.

### Required comparisons

| Event | Sources to compare | Artifact ID |
|-------|-------------------|-------------|
| Lease issuance | status + audit + watchdog | C04-06 |
| Lease renewal | status (before/after) + audit | C04-06 |
| Lease expiry | status + audit + watchdog | C04-06 |
| Recovery after report | status + audit | C04-06 |

### Pass criteria

- All fields match across sources (within 2s timestamp tolerance)
- No unresolved contradictions
- `attempt_index` consistent across all sources
- `owner_instance_id` consistent across all sources

## Step 3: Assemble packet (packet index)

Use [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md)
and fill in the CORE-03 and CORE-04 sections.

### CORE-03 artifacts checklist

| Artifact ID | Description | File | Collected? |
|------------|-------------|------|-----------|
| C03-01 | Claim response with lease | evidence/core-03/claim-response.json | |
| C03-02 | Task list showing lease fields | evidence/core-03/task-lease.json | |
| C03-03 | Audit log with task.claimed | evidence/core-03/audit-claim.json | |
| C03-04 | Lease field verification table | evidence/core-03/field-check.md | |
| C03-05 | Test results | evidence/core-03/test-results.txt | |

### CORE-04 artifacts checklist

| Artifact ID | Description | File | Collected? |
|------------|-------------|------|-----------|
| C04-01 | Watchdog lease_expired event | evidence/core-04/watchdog-expiry.jsonl | |
| C04-02 | Requeued task in assigned list | evidence/core-04/requeue.json | |
| C04-03 | Blocked task after max retries | evidence/core-04/blocked-task.json | |
| C04-04 | Auto-blocker raised | evidence/core-04/auto-blocker.json | |
| C04-05 | Recovery after report | evidence/core-04/post-report.json | |
| C04-06 | Cross-source reconciliation | evidence/core-04/reconciliation.md | |

### Completeness gate

- [ ] All 5 CORE-03 artifacts present and non-empty
- [ ] All 6 CORE-04 artifacts present and non-empty
- [ ] All JSON files parse without errors
- [ ] No placeholder text remaining

## Step 4: Self-review

Before submitting for reviewer signoff, verify these criteria using
the CORE-03 and CORE-04 sections of [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md).

### CORE-03 self-check

- [ ] `lease_id` is non-empty and unique per claim
- [ ] `expires_at` equals `claimed_at + configured TTL`
- [ ] `owner_instance_id` matches the claiming agent's instance_id
- [ ] `attempt_index` starts at 1 for first claim
- [ ] Test results show 0 failures for T1, T2, T6, T7

### CORE-04 self-check

- [ ] `attempt_index` incremented on each re-lease
- [ ] Max retries threshold honored (task blocked at correct count)
- [ ] Blocker reason mentions "lease expired" or equivalent
- [ ] Report submission clears the lease (no lingering expiry)
- [ ] Cross-source reconciliation has no contradictions

## Step 5: Submit for reviewer signoff

### Handoff checklist

- [ ] Packet index filled in with all artifact locations
- [ ] Packet status set to READY
- [ ] Witness log signed by observer
- [ ] Reconciliation verdict recorded
- [ ] Self-review completed with no open issues

### Reviewer workflow

The reviewer uses [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md) to:

1. Verify artifact completeness (all 11 artifacts present)
2. Validate evidence quality (field consistency, correlation)
3. Check cross-source reconciliation for contradictions
4. Record per-section verdict (CORE-03 and CORE-04 separately)
5. Record combined verdict
6. Sign off or reject with documented reasons

### Rejection triggers

| # | Condition | Resolution |
|---|-----------|------------|
| 1 | Missing artifact without justification | Collect missing evidence |
| 2 | Test failures in lease tests | Fix code, re-run tests |
| 3 | Unresolved cross-source contradictions | Investigate root cause |
| 4 | Blocker did not auto-raise at max retries | Verify watchdog config |
| 5 | Witness log unsigned or undated | Have observer sign |

## Final signoff record

Record the signoff in [core-02-04-signoff-summary.md](core-02-04-signoff-summary.md).

```
Preparer: _______________
Reviewer: _______________
Date: _______________

CORE-03 verdict: PASS / FAIL
CORE-04 verdict: PASS / FAIL
Combined: APPROVED / REJECTED
Notes: _______________
```

## References

- [lease-witness-log-template.md](lease-witness-log-template.md) -- Live observation template
- [core-03-04-cross-source-reconciliation.md](core-03-04-cross-source-reconciliation.md) -- Cross-source comparison
- [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md) -- Artifact inventory
- [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md) -- Reviewer pass/fail criteria
- [core-03-04-evidence-template.md](core-03-04-evidence-template.md) -- Raw evidence capture
- [core-02-04-signoff-summary.md](core-02-04-signoff-summary.md) -- Combined signoff record
- [lease-schema-test-plan.md](lease-schema-test-plan.md) -- Test case definitions (T1-T8)
- [lease-operator-expectations.md](lease-operator-expectations.md) -- Before/after lease behavior
