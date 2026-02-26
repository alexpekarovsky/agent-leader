# CORE-03 Lease Issuance — Reviewer Bundle

Single-document bundle for CORE-03 (lease issuance on claim) acceptance review. Consolidates the artifact inventory, evidence collection, witness observations, cross-source reconciliation, and reviewer checklist into one signoff-ready package.

## How to Use This Bundle

**Preparer (operator/implementer):**
1. Copy this file to `evidence/core-03/core-03-bundle-YYYY-MM-DD.md`
2. Fill in Bundle Metadata (use session labels like CC1/CC2 — see Appendix B)
3. Collect evidence for each artifact in Section 2 (paste raw JSON output)
4. Record witness observations in Section 3 (fill all Match? columns)
5. Complete the reconciliation table in Section 4
6. Set status to **READY** and notify the reviewer

**Reviewer:**
1. Confirm status is READY and preparer is identified
2. Walk through Section 5 checklist — reject if any mandatory check fails
3. Spot-check at least 2 evidence entries against the lease field table
4. Verify cross-source reconciliation has no contradictions
5. Record verdict in Section 6 and sign off
6. See Appendix A for example filled entries to compare against

## Bundle Metadata

| Field | Value |
|-------|-------|
| **Bundle ID** | AUTO-M1-CORE-03-BUNDLE-[DATE] |
| **Project** | claude-multi-ai |
| **Preparer** | [name / session label, e.g. CC1 or CC-backend] |
| **Reviewer** | [name / session label] |
| **Date** | [YYYY-MM-DD] |
| **Commit under test** | [git SHA] |
| **Session** | [CC1 / CC2 / CC-backend — see Appendix B] |
| **Status** | DRAFT / READY / SIGNED OFF |

---

## Section 1: Artifact Inventory

Evidence artifacts required for CORE-03 acceptance. Each artifact must be collected and stored at the indicated location before review.

| Artifact ID | Description | File/Location | Provenance | Collected? |
|-------------|-------------|---------------|------------|------------|
| C03-01 | Claim response with lease | evidence/core-03/claim-response.json | `orchestrator_claim_next_task()` | |
| C03-02 | Task list showing lease fields | evidence/core-03/task-lease.json | `orchestrator_list_tasks()` | |
| C03-03 | Audit log with `task.claimed` | evidence/core-03/audit-claim.json | `orchestrator_list_audit_logs()` | |
| C03-04 | Lease field verification table | evidence/core-03/field-check.md | Manual verification | |
| C03-05 | Test results | evidence/core-03/test-results.txt | `test_lease_schema_test_plan.py` | |

### Required Lease Fields (C03-04 reference)

All 7 fields must be present in the claim response:

| Field | Type | Set by | Verification |
|-------|------|--------|--------------|
| `lease_id` | string | Engine on claim | Non-empty, unique per claim |
| `task_id` | string | Engine on claim | Matches claimed task |
| `owner_instance_id` | string | Engine from claim context | Matches claiming agent's instance |
| `claimed_at` | ISO 8601 | Engine on claim | Valid timestamp |
| `expires_at` | ISO 8601 | Engine on claim | `claimed_at + TTL` |
| `renewed_at` | ISO 8601 | Engine on renew | Initially null or matches claimed_at |
| `attempt_index` | integer | Engine, incremented on re-lease | Starts at 1 |

---

## Section 2: Evidence Collection

Paste raw evidence for each artifact below. These slots map directly to the artifact inventory above.

### C03-01: Claim Response

Command: `orchestrator_claim_next_task(agent="claude_code")`

```json
PASTE_CLAIM_RESPONSE_HERE
```

### C03-02: Task List with Lease

Command: `orchestrator_list_tasks(status="in_progress")`

```json
PASTE_TASK_WITH_LEASE_HERE
```

### C03-03: Audit Log Entry

Command: `orchestrator_list_audit_logs(tool="orchestrator_claim_next_task", limit=5)`

```json
PASTE_AUDIT_ENTRY_HERE
```

### C03-04: Lease Field Verification

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `lease_id` | Non-empty string | | |
| `task_id` | Matches claimed task | | |
| `owner_instance_id` | Matches claimer's instance_id | | |
| `claimed_at` | Valid ISO 8601 | | |
| `expires_at` | `claimed_at + configured TTL` | | |
| `renewed_at` | null or matches claimed_at | | |
| `attempt_index` | 1 (first claim) | | |

### C03-05: Test Results

Tests from [lease-schema-test-plan.md](lease-schema-test-plan.md) covering CORE-03: T1, T2, T6, T7.

```
PASTE_TEST_OUTPUT_HERE
```

| Test | Description | Pass/Fail |
|------|-------------|-----------|
| T1 | Lease issuance on claim | |
| T2 | Lease renewal extends expiry | |
| T6 | Claim without instance_id uses fallback | |
| T7 | Concurrent claim creates only one lease | |

---

## Section 3: Witness Observations

Direct observations of lease behavior during testing. Each observation records expected vs. actual behavior with source provenance.

### Observation 1: Lease Created on Claim

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `lease.lease_id` | Non-empty string | | |
| `lease.task_id` | Matches claimed task | | |
| `lease.owner_instance_id` | Matches claimer's instance_id | | |
| `lease.claimed_at` | Valid ISO 8601 timestamp | | |
| `lease.expires_at` | `claimed_at + TTL` | | |
| `lease.attempt_index` | 1 (first claim) | | |
| Task status | `in_progress` | | |

**Source**: `orchestrator_claim_next_task()` response
**Timestamp**: ____
**Audit log entry ID**: ____

### Observation 2: Lease Renewal Extends Expiry

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `renewed_at` | Updated to current time | | |
| `expires_at` | Extended beyond previous value | | |
| `attempt_index` | Unchanged from claim | | |
| Task status | Still `in_progress` | | |

**Source**: `renew_lease()` response
**Timestamp**: ____
**Audit log entry ID**: ____

### Observation 3: Lease Released on Report

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| Active lease | Cleared/absent | | |
| Task status | `reported` | | |
| Expiry check | Does not fire post-report | | |

**Source**: `orchestrator_submit_report()` response + task record
**Timestamp**: ____
**Audit log entry ID**: ____

### Observation 4: Instance_id Fallback in Lease

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `owner_instance_id` | `{agent}#default` when no explicit ID | | |
| Lease otherwise | Normal issuance | | |

**Source**: `orchestrator_claim_next_task()` response (no instance_id provided)
**Timestamp**: ____

---

## Section 4: Cross-Source Reconciliation

Compares lease issuance evidence across Status API, audit log, and event bus to verify consistency.

| Evidence Point | Status API | Audit Log | Event Bus | Match? | Notes |
|----------------|------------|-----------|-----------|--------|-------|
| Lease issued | | | | | |
| Lease renewed | | | | | |
| Lease released | | | | | |

### How to Fill Each Column

- **Status API**: `orchestrator_list_tasks(status="in_progress")` output showing lease fields
- **Audit log**: `orchestrator_list_audit_logs(limit=20)` — look for `task.claimed` entries
- **Event bus**: `orchestrator_poll_events()` — look for `task.status_changed` events

### Mismatch Resolution

When sources disagree, use this priority:

| Priority | Source | Rationale |
|----------|--------|-----------|
| 1 | Audit log | Append-only, records all state changes |
| 2 | Status API | Reflects current in-memory state |
| 3 | Event bus | May have unacked events |

### Per-Row Evidence (fill for any mismatched rows)

**Status API:**
```json
PASTE_HERE
```

**Audit log:**
```json
PASTE_HERE
```

**Event bus:**
```json
PASTE_HERE
```

**Reconciliation verdict**: PASS / FAIL
**Mismatched rows**: ____

---

## Section 5: Reviewer Checklist

### Pre-Review

- [ ] All 5 artifact slots filled in Section 2
- [ ] Bundle status is READY (not DRAFT)
- [ ] Preparer identified and available for questions

### Artifact Completeness

| Artifact | Present? | Valid? | Notes |
|----------|----------|--------|-------|
| C03-01: Claim response with lease | | | Must contain lease object with all 7 fields |
| C03-02: Task list showing lease fields | | | At least 1 task with active lease |
| C03-03: Audit log with `task.claimed` | | | Timestamp matches claim response |
| C03-04: Lease field verification table | | | All 7 fields checked |
| C03-05: Test results | | | All CORE-03 tests pass (T1, T2, T6, T7) |

### Evidence Quality

- [ ] `lease_id` format is consistent (non-empty string, unique per claim)
- [ ] `expires_at` is exactly `claimed_at + configured TTL`
- [ ] `owner_instance_id` matches the claiming agent's actual instance_id
- [ ] `attempt_index` starts at 1 for first claim
- [ ] Concurrent claim test (T7) evidence shows atomic behavior
- [ ] Witness observations (Section 3) have all Match? columns filled
- [ ] Cross-source reconciliation (Section 4) shows no contradictions

### Rejection Criteria

The bundle should be rejected if any of the following are true:

| # | Condition |
|---|-----------|
| 1 | Any artifact is missing without documented justification |
| 2 | Test results show failures in T1, T2, T6, or T7 |
| 3 | Cross-source reconciliation has unresolved contradictions |
| 4 | Lease field verification table has any unmatched fields |
| 5 | Witness observations are unsigned or undated |

---

## Section 6: Verdict and Signoff

### Reviewer Verdict

| Criterion | Pass/Fail |
|-----------|-----------|
| All 5 artifacts present and valid | |
| Lease field values internally consistent | |
| Test results show 0 failures for T1, T2, T6, T7 | |
| Witness observations complete (4/4) | |
| Cross-source reconciliation clean | |
| **CORE-03 overall** | **PASS / FAIL** |

### Signoff

| Role | Name / Session | Date | Approved |
|------|---------------|------|----------|
| Preparer | [name / CC1 / CC2] | | |
| Observer | [name / CC1 / CC2] | | YES / NO |
| Reviewer | [name / CC1 / CC2] | | YES / NO |

### Anomalies

_Record any unexpected behavior, edge cases, or warnings observed during the review._

| # | Description | Source | Severity |
|---|-------------|--------|----------|
| 1 | | | low / medium / high |

---

## Appendix A: Example Acceptance Packet Layout

Example of a completed CORE-03 acceptance packet directory structure using `[claude-multi-ai][AUTO-M1-CORE]` conventions:

```
evidence/
  core-03/
    claim-response.json          # C03-01: Raw claim_next_task response
    task-lease.json              # C03-02: list_tasks showing lease fields
    audit-claim.json             # C03-03: Audit log task.claimed entry
    field-check.md               # C03-04: Filled lease field verification
    test-results.txt             # C03-05: pytest output for T1,T2,T6,T7
```

### Example C03-01: Claim Response (filled)

```json
{
  "id": "TASK-abc12345",
  "title": "[claude-multi-ai][AUTO-M1-CORE] Implement lease schema",
  "status": "in_progress",
  "owner": "claude_code",
  "lease": {
    "lease_id": "lease-7f3a9e2b",
    "task_id": "TASK-abc12345",
    "owner_instance_id": "claude_code#worker-01",
    "claimed_at": "2026-02-26T08:00:00+00:00",
    "expires_at": "2026-02-26T08:10:00+00:00",
    "renewed_at": null,
    "attempt_index": 1
  }
}
```

### Example C03-04: Lease Field Verification (filled)

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `lease_id` | Non-empty string | `lease-7f3a9e2b` | YES |
| `task_id` | Matches claimed task | `TASK-abc12345` | YES |
| `owner_instance_id` | Matches claimer | `claude_code#worker-01` | YES |
| `claimed_at` | Valid ISO 8601 | `2026-02-26T08:00:00+00:00` | YES |
| `expires_at` | `claimed_at + 600s` | `2026-02-26T08:10:00+00:00` | YES |
| `renewed_at` | null (first claim) | `null` | YES |
| `attempt_index` | 1 | `1` | YES |

### Example Reviewer Verdict (filled)

| Criterion | Pass/Fail |
|-----------|-----------|
| All 5 artifacts present and valid | PASS |
| Lease field values internally consistent | PASS |
| Test results show 0 failures for T1, T2, T6, T7 | PASS |
| Witness observations complete (4/4) | PASS |
| Cross-source reconciliation clean | PASS |
| **CORE-03 overall** | **PASS** |

---

## Appendix B: Tagging Conventions

All CORE-03 artifacts follow `[claude-multi-ai][AUTO-M1-CORE]` conventions.
For session labeling, see [dual-cc-conventions.md](dual-cc-conventions.md).

| Convention | Format | Example |
|------------|--------|---------|
| Task title prefix | `[claude-multi-ai][AUTO-M1-CORE-03]` | `[claude-multi-ai][AUTO-M1-CORE-03] Implement lease schema` |
| Bundle ID | `AUTO-M1-CORE-03-BUNDLE-YYYYMMDD` | `AUTO-M1-CORE-03-BUNDLE-20260226` |
| Evidence directory | `evidence/core-03/` | `evidence/core-03/claim-response.json` |
| Commit message tag | `[AUTO-M1-CORE-03]` | `feat: [AUTO-M1-CORE-03] add lease schema to claim` |
| Audit log filter | `tool=orchestrator_claim_next_task` | Filters claim-related audit entries |
| Session label | CC1 / CC2 / CC-backend | Used in Preparer, Reviewer, and Signoff fields |
| Report note prefix | `[CC1]` or `[CC-backend]` | `[CC1] Lease issuance verified, all 7 fields present` |

---

## References

- [lease-schema-test-plan.md](lease-schema-test-plan.md) — Test case definitions (T1-T8)
- [lease-operator-expectations.md](lease-operator-expectations.md) — Before/after lease behavior
- [core-03-04-lease-verification-checklist.md](core-03-04-lease-verification-checklist.md) — Operator verification steps
- [core-03-04-evidence-template.md](core-03-04-evidence-template.md) — Raw evidence slots
- [core-03-04-reconciliation-template.md](core-03-04-reconciliation-template.md) — Full reconciliation template
- [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md) — Combined packet index
- [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md) — Combined reviewer checklist
- [dual-cc-conventions.md](dual-cc-conventions.md) — Session labeling conventions (CC1/CC2)
