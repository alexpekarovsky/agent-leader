# CORE-03/04 Cross-Source Reconciliation Template

Compares lease evidence across Status API, audit log, and watchdog JSONL.

## Metadata

```
Operator: _______________
Date:     _______________
Test ID:  _______________
```

## Reconciliation table

| Evidence point   | Status API | Audit log | Watchdog JSONL | Match? | Notes |
|------------------|-----------|-----------|----------------|--------|-------|
| Lease issued     |           |           | n/a            |        |       |
| Lease renewed    |           |           | n/a            |        |       |
| Lease expired    |           |           |                |        |       |
| Task requeued    |           |           |                |        |       |
| Blocker raised   |           |           | n/a            |        |       |
| Lease released   |           |           | n/a            |        |       |

### How to fill each column

- **Status API:** `orchestrator_list_tasks(status="...")` output
- **Audit log:** `orchestrator_list_audit_logs(limit=20)` entries
- **Watchdog JSONL:** `cat .autopilot-logs/watchdog-*.jsonl` entries

## Mismatch resolution

When sources disagree, use this priority order:

| Priority | Source     | Rationale                              |
|----------|-----------|----------------------------------------|
| 1        | Audit log | Append-only, records all state changes |
| 2        | Status API| Reflects current in-memory state       |
| 3        | Watchdog  | Periodic scan, may lag behind          |

### Common mismatch causes

| Mismatch                           | Likely cause                      | Fix                         |
|------------------------------------|-----------------------------------|-----------------------------|
| Status shows `in_progress`, audit shows `expired` | Expiry not yet applied | Wait for next watchdog scan |
| Watchdog missing expiry entry      | Scan interval too wide            | Check `--scan-interval` config |
| Audit has `claimed`, status has no lease | Lease cleared by report   | Verify report timestamp     |
| Status shows `assigned`, audit shows `blocked` | Blocker raised mid-scan | Re-query status API         |

## Per-row evidence slots

Paste raw output for any mismatched rows:

**Status API:**
```json
PASTE_HERE
```

**Audit log:**
```json
PASTE_HERE
```

**Watchdog JSONL:**
```json
PASTE_HERE
```

## Verdict

| All rows match? | Result      |
|-----------------|-------------|
| YES             | PASS        |
| NO              | FAIL -- list mismatched rows below |

Mismatched rows: _______________

```
Operator: _______________
Date:     _______________
Result:   PASS / FAIL
```

## References

- [core-03-04-lease-verification-checklist.md](core-03-04-lease-verification-checklist.md)
- [core-03-04-evidence-template.md](core-03-04-evidence-template.md)
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md)
