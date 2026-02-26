# CORE-03/04 Lease Evidence Cross-Source Reconciliation Template

Template for comparing lease-related evidence across status output,
audit logs, and watchdog JSONL during acceptance verification.

## Metadata

```
Operator: _______________
Date: _______________
Task under test: TASK-_______________
```

## Source collection

Gather evidence from all three sources for the same lease event:

### Source 1: Status output

```
orchestrator_list_tasks(status="in_progress")
```

```json
[paste task entry with lease fields]
```

### Source 2: Audit log

```
orchestrator_list_audit_logs(limit=10)
```

```json
[paste audit entries for task.claimed / task.lease_expired]
```

### Source 3: Watchdog JSONL

```bash
cat "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)"
```

```json
[paste watchdog entries for lease events]
```

## Cross-source comparison: Lease issuance

| Field | Status output | Audit log | Watchdog | Match? |
|-------|--------------|-----------|----------|--------|
| `task_id` | | | | |
| `lease_id` | | | n/a | |
| `owner` / `owner_instance_id` | | | | |
| `claimed_at` | | | | |
| `expires_at` | | | | |
| `attempt_index` | | | | |

### Mismatch notes

| Field | Discrepancy | Likely cause | Resolution |
|-------|------------|--------------|------------|
| | | | |

## Cross-source comparison: Lease renewal

| Field | Status (before) | Status (after) | Audit log | Match? |
|-------|----------------|----------------|-----------|--------|
| `renewed_at` | | | | |
| `expires_at` | | | | |
| `task status` | | | | |

### Mismatch notes

| Field | Discrepancy | Likely cause | Resolution |
|-------|------------|--------------|------------|
| | | | |

## Cross-source comparison: Lease expiry

| Field | Status output | Audit log | Watchdog | Match? |
|-------|--------------|-----------|----------|--------|
| `task_id` | | | | |
| `owner_instance_id` | | | | |
| `expiry timestamp` | | | | |
| `task status after` | | | | |
| `attempt_index after` | | | | |

### Mismatch notes

| Field | Discrepancy | Likely cause | Resolution |
|-------|------------|--------------|------------|
| | | | |

## Cross-source comparison: Recovery after report

| Field | Status output | Audit log | Watchdog | Match? |
|-------|--------------|-----------|----------|--------|
| `task_id` | | | | |
| `lease cleared` | | | n/a | |
| `task status` | | | | |
| `report timestamp` | | | | |

### Mismatch notes

| Field | Discrepancy | Likely cause | Resolution |
|-------|------------|--------------|------------|
| | | | |

## Common mismatch patterns

| Pattern | Sources affected | Typical cause | Fix |
|---------|-----------------|---------------|-----|
| Timestamp drift >2s | Status vs audit | Clock skew or async write | Verify both use same clock |
| Missing lease in watchdog | Status+audit vs watchdog | Watchdog ran before event | Re-run watchdog one-shot |
| attempt_index off by 1 | Status vs audit | Race between expiry and requeue | Check event ordering |
| owner_instance_id missing | Any source | Old engine without instance support | Upgrade or use fallback ID |

## Reconciliation verdict

| Comparison | Sources | Consistent? | Notes |
|------------|---------|-------------|-------|
| Issuance | status + audit | | |
| Issuance | status + watchdog | | |
| Renewal | status (before/after) + audit | | |
| Expiry | status + audit + watchdog | | |
| Recovery | status + audit | | |
| **Overall** | all | **YES / NO** | |

## Signoff

```
Operator: _______________
Date: _______________
Reconciliation: CONSISTENT / INCONSISTENT
Action items: _______________
```

## References

- [core-03-04-lease-verification.md](core-03-04-lease-verification.md) -- Checklist
- [core-03-04-evidence-template.md](core-03-04-evidence-template.md) -- Evidence capture
- [lease-schema-test-plan.md](lease-schema-test-plan.md) -- Test cases
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) -- Watchdog event schema
