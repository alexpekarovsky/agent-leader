# CORE-03/04 Lease Evidence Capture Template

Structured template for recording lease issuance (CORE-03) and expiry
recovery (CORE-04) observations from status, audit, and log outputs.

## Metadata

```
Operator: _______________
Date: _______________
CORE-03/04 checklist: docs/core-03-04-lease-verification.md
Restart test ID: _______________
```

## CORE-03: Lease issuance on claim

### 3.1 Claim response evidence

**Command:**

```
orchestrator_claim_next_task(agent="claude_code")
```

**Raw output:**

```json
[paste claim response here]
```

**Source provenance:** orchestrator claim_next_task response

### 3.2 Lease fields in task list

**Command:**

```
orchestrator_list_tasks(status="in_progress")
```

**Raw output (relevant task):**

```json
[paste task entry showing lease object]
```

**Source provenance:** orchestrator list_tasks

### 3.3 Lease field verification

| Field | Expected | Observed | Pass/Fail |
|-------|----------|----------|-----------|
| `lease.lease_id` | Non-empty string | | |
| `lease.expires_at` | Future timestamp | | |
| `lease.attempt_index` | 1 (first claim) | | |
| `lease.owner_instance_id` | Matches claimer | | |
| `lease.claimed_at` | Recent timestamp | | |

### 3.4 Audit trail evidence

**Command:**

```
orchestrator_list_audit_logs(limit=5)
```

**Raw output (relevant entries):**

```json
[paste audit entries showing task.claimed with lease]
```

**Source provenance:** orchestrator audit log

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| `task.claimed` event present | | |
| Lease metadata in audit payload | | |

## CORE-03: Lease renewal

### 3.5 Renewal evidence

**Action taken:** [heartbeat/renewal command]

**Before renewal:**

```json
[paste lease state before]
```

**After renewal:**

```json
[paste lease state after]
```

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| `renewed_at` updated | | |
| `expires_at` extended | | |
| Task remains `in_progress` | | |

## CORE-04: Lease expiry and recovery

### 4.1 Expiry detection evidence

**Setup:** [How expiry was triggered - e.g., stopped worker, waited for TTL]

**Watchdog output:**

```json
[paste watchdog-*.jsonl entries showing lease_expired]
```

**Source provenance:** watchdog JSONL

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| `task.lease_expired` event | | |
| Includes `task_id` | | |
| Includes `owner_instance_id` | | |
| Task transitions to `assigned` | | |

### 4.2 Auto-requeue evidence

**Command:**

```
orchestrator_list_tasks(status="assigned")
```

**Raw output (relevant task):**

```json
[paste showing expired task requeued]
```

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Expired task in assigned queue | | |
| `attempt_index` incremented | | |
| Task claimable by any agent | | |

### 4.3 Repeated expiry to blocker

**Setup:** [Number of expirations triggered]

**Commands:**

```
orchestrator_list_tasks(status="blocked")
orchestrator_list_blockers(status="open")
```

**Raw output:**

```json
[paste blocked task and blocker entries]
```

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Task `blocked` after max retries | | |
| Auto-blocker raised | | |
| Task no longer claimable | | |

### 4.4 Recovery after report

**Command:**

```
orchestrator_list_tasks(status="reported")
```

**Raw output:**

```json
[paste task showing cleared lease]
```

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Lease cleared after report | | |
| No expiry fires post-report | | |
| Normal validation proceeds | | |

## Configuration evidence

**Command:**

```
orchestrator_status()
```

| Config | Expected | Observed |
|--------|----------|----------|
| `lease_ttl_seconds` | 600 | |
| `max_retries` | 3 | |

## Overall result

| Section | Result |
|---------|--------|
| CORE-03 Issuance | PASS / FAIL |
| CORE-03 Renewal | PASS / FAIL |
| CORE-04 Expiry | PASS / FAIL |
| CORE-04 Requeue | PASS / FAIL |
| CORE-04 Blocker | PASS / FAIL |
| CORE-04 Recovery | PASS / FAIL |
| **Overall** | **PASS / FAIL** |

## Signoff

```
Operator: _______________
Date: _______________
Result: PASS / FAIL
Notes: _______________
```

## References

- [core-03-04-lease-verification.md](core-03-04-lease-verification.md) -- Checklist
- [lease-schema-test-plan.md](lease-schema-test-plan.md) -- Test cases T1-T8
- [lease-operator-expectations.md](lease-operator-expectations.md) -- Pre/post behavior
- [evidence-folder-layout.md](evidence-folder-layout.md) -- Evidence storage
