# Lease Acceptance Witness Log

Template for recording lease behavior observations during CORE-03/04 acceptance testing. Captures evidence from orchestrator status, audit logs, and watchdog outputs across issuance, renewal, and expiry recovery scenarios.

## Run Metadata

| Field | Value |
|-------|-------|
| **Date** | YYYY-MM-DD HH:MM UTC |
| **Observer** | [name or session label] |
| **Commit under test** | [git SHA] |
| **Lease TTL configured** | [seconds, e.g. 600] |
| **Max retries configured** | [integer, e.g. 3] |

## Observation Sources

| Source | Location | What to capture |
|--------|----------|-----------------|
| Status output | `orchestrator_status()` | `active_agents`, task counts, lease fields in task records |
| Audit log | `.autopilot-state/audit_log.jsonl` | `task.claimed`, `task.lease_renewed`, `task.lease_expired`, `task.requeued` entries |
| Watchdog output | `.autopilot-logs/supervisor-watchdog.log` | Stale task events, lease expiry notices |
| Event bus | `orchestrator_poll_events()` | `task.lease_expired`, `task.status_changed` events |

## Lease Issuance (CORE-03)

### Observation 1: Lease created on claim

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `lease.lease_id` | Non-empty string | | |
| `lease.task_id` | Matches claimed task | | |
| `lease.owner_instance_id` | Matches claimer's instance_id | | |
| `lease.claimed_at` | Valid ISO 8601 timestamp | | |
| `lease.expires_at` | `claimed_at + TTL` | | |
| `lease.attempt_index` | 1 (first claim) | | |
| Task status | `in_progress` | | |

**Source provenance**: `orchestrator_claim_next_task()` response
**Timestamp**: ____
**Audit log entry ID**: ____

### Observation 2: Lease renewal extends expiry

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `renewed_at` | Updated to current time | | |
| `expires_at` | Extended beyond previous value | | |
| `attempt_index` | Unchanged from claim | | |
| Task status | Still `in_progress` | | |

**Source provenance**: `renew_lease()` response
**Timestamp**: ____
**Audit log entry ID**: ____

### Observation 3: Lease released on report

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| Active lease | Cleared/absent | | |
| Task status | `reported` | | |
| Expiry check | Does not fire post-report | | |

**Source provenance**: `orchestrator_submit_report()` response + task record
**Timestamp**: ____
**Audit log entry ID**: ____

## Expiry Recovery (CORE-04)

### Observation 4: Expired lease triggers requeue

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| Task status | `assigned` (requeued) | | |
| `attempt_index` | Incremented (e.g. 1 -> 2) | | |
| `task.lease_expired` event | Emitted with task_id and owner | | |
| Task claimable | Yes, by any agent | | |

**Source provenance**: Expiry check cycle + event bus
**Timestamp**: ____
**Watchdog log line**: ____
**Audit log entry ID**: ____

### Observation 5: Repeated expiry raises blocker

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| Task status | `blocked` after max retries | | |
| Blocker reason | References repeated lease expiry | | |
| Task claimable | No | | |

**Source provenance**: Expiry check cycle + `orchestrator_list_blockers()`
**Timestamp**: ____
**Audit log entry ID**: ____

### Observation 6: Instance_id fallback in lease

| Field | Expected | Observed | Match? |
|-------|----------|----------|--------|
| `owner_instance_id` | `{agent}#default` when no explicit ID | | |
| Lease otherwise | Normal issuance | | |

**Source provenance**: `orchestrator_claim_next_task()` response (no instance_id provided)
**Timestamp**: ____

## Rollup

| Observation | Scenario | Pass/Fail |
|-------------|----------|-----------|
| 1 | Lease issuance on claim | |
| 2 | Lease renewal | |
| 3 | Lease release on report | |
| 4 | Expiry requeue | |
| 5 | Repeated expiry blocker | |
| 6 | Instance_id fallback | |
| **Total** | | _/6 |

## Overall Verdict

| Criterion | Result |
|-----------|--------|
| CORE-03 signoff (Obs 1-3, 6) | PASS / FAIL |
| CORE-04 signoff (Obs 4-5) | PASS / FAIL |
| Combined | PASS / FAIL |

## Anomalies

_Record any unexpected behavior, edge cases, or warnings observed during the run._

| # | Description | Source | Severity |
|---|-------------|--------|----------|
| 1 | | | low / medium / high |

## Signoff

| Role | Name | Date | Approved |
|------|------|------|----------|
| Observer | | | YES / NO |
| Reviewer | | | YES / NO |

## References

- [lease-schema-test-plan.md](lease-schema-test-plan.md) — Test case definitions (T1-T8)
- [lease-operator-expectations.md](lease-operator-expectations.md) — Before/after lease behavior
- [post-restart-verification.md](post-restart-verification.md) — Restart verification steps
- [restart-verification-run-log.md](restart-verification-run-log.md) — Restart run log template
