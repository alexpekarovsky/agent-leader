# CORE-03/04 Lease Observability Evidence Template

Captures lease issuance, renewal, expiry recovery, watchdog, blocker, and release evidence.

## Metadata

```
Operator: _______________
Date:     _______________
Test ID:  _______________
```

## Lease issuance

Command: `orchestrator_claim_next_task(agent="claude_code")`

```json
PASTE_CLAIM_RESPONSE_HERE
```

| Field | Expected | P/F |
|-------|----------|-----|
| `lease.lease_id` | Non-empty string | |
| `lease.expires_at` | Future timestamp | |
| `lease.attempt_index` | 1 (first claim) | |
| `lease.owner_instance_id` | Matches claimer | |

## Lease renewal

Before: `PASTE_BEFORE` | After: `PASTE_AFTER`

Checks: `renewed_at` updated (P/F ___), `expires_at` extended (P/F ___), task `in_progress` (P/F ___)

## Expiry recovery

```json
PASTE_REQUEUED_TASK_HERE
```

Checks: task `assigned` (P/F ___), `attempt_index` incremented (P/F ___), claimable (P/F ___)

## Watchdog evidence

```json
PASTE_WATCHDOG_JSONL_ENTRY
```

Checks: `stale_task` present (P/F ___), correct `task_id` (P/F ___), `owner_instance_id` (P/F ___)

## Blocker evidence

```json
PASTE_BLOCKER_ENTRY_HERE
```

Checks: task `blocked` (P/F ___), auto-blocker raised (P/F ___), not claimable (P/F ___)

## Report release

```json
PASTE_POST_REPORT_TASK_HERE
```

Checks: lease cleared (P/F ___), no post-report expiry (P/F ___), status `reported` (P/F ___)

## Summary

| Evidence point | Result | | Evidence point | Result |
|----------------|--------|-|----------------|--------|
| Lease issuance | PASS / FAIL | | Watchdog event | PASS / FAIL |
| Lease renewal | PASS / FAIL | | Blocker on retries | PASS / FAIL |
| Expiry recovery | PASS / FAIL | | Report release | PASS / FAIL |

**Overall:** PASS / FAIL | Operator: _______________ | Date: _______________

## References

- [core-03-04-lease-verification-checklist.md](core-03-04-lease-verification-checklist.md)
- [lease-schema-test-plan.md](lease-schema-test-plan.md)
