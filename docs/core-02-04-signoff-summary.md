# CORE-02/03/04 Combined Signoff Evidence Summary

Combined evidence summary for the first half of the AUTO-M1 core
milestone (instance-aware status + lease system). Use this to
consolidate evidence from individual templates for final signoff.

## Metadata

```
Reviewer: _______________
Date: _______________
Milestone: AUTO-M1 (CORE-02..04 checkpoint)
```

## CORE-02: Instance-aware status

### Evidence sources

| Source | Location | Collected? |
|--------|----------|-----------|
| Evidence template | [core-02-evidence-template.md](core-02-evidence-template.md) | YES / NO |
| Verification checklist | [core-02-verification-checklist.md](core-02-verification-checklist.md) | YES / NO |
| Test results | `tests/test_status_agent_identities.py` | YES / NO |

### Summary

| Check | Result | Evidence link |
|-------|--------|--------------|
| All agents have instance_id | PASS / FAIL | evidence template Step 1 |
| Format {agent}#{suffix} | PASS / FAIL | evidence template Step 2 |
| Two workers distinguishable | PASS / FAIL | evidence template Step 3 |
| Stale detection per-instance | PASS / FAIL | evidence template Step 4 |
| Backward compatibility | PASS / FAIL | evidence template compat section |
| Unit tests pass | PASS / FAIL | test output |

**CORE-02 verdict:** PASS / FAIL

## CORE-03: Lease issuance

### Evidence sources

| Source | Location | Collected? |
|--------|----------|-----------|
| Evidence template | [core-03-04-evidence-template.md](core-03-04-evidence-template.md) | YES / NO |
| Cross-source reconciliation | [core-03-04-cross-source-reconciliation.md](core-03-04-cross-source-reconciliation.md) | YES / NO |
| Verification checklist | [core-03-04-lease-verification.md](core-03-04-lease-verification.md) | YES / NO |
| Test results | `tests/test_lease_schema_test_plan.py` | YES / NO |

### Summary

| Check | Result | Evidence link |
|-------|--------|--------------|
| Lease object in claim response | PASS / FAIL | evidence template 3.1 |
| All lease fields present | PASS / FAIL | evidence template 3.3 |
| Audit trail shows lease | PASS / FAIL | evidence template 3.4 |
| Renewal updates timestamps | PASS / FAIL | evidence template 3.5 |
| Cross-source consistent | PASS / FAIL | reconciliation template |
| Unit tests pass | PASS / FAIL | test output |

**CORE-03 verdict:** PASS / FAIL

## CORE-04: Lease expiry and recovery

### Evidence sources

| Source | Location | Collected? |
|--------|----------|-----------|
| Evidence template | [core-03-04-evidence-template.md](core-03-04-evidence-template.md) | YES / NO |
| Cross-source reconciliation | [core-03-04-cross-source-reconciliation.md](core-03-04-cross-source-reconciliation.md) | YES / NO |
| Verification checklist | [core-03-04-lease-verification.md](core-03-04-lease-verification.md) | YES / NO |

### Summary

| Check | Result | Evidence link |
|-------|--------|--------------|
| Expiry detection works | PASS / FAIL | evidence template 4.1 |
| Auto-requeue works | PASS / FAIL | evidence template 4.2 |
| Repeated expiry blocks task | PASS / FAIL | evidence template 4.3 |
| Recovery after report | PASS / FAIL | evidence template 4.4 |
| Cross-source consistent | PASS / FAIL | reconciliation template |
| Configuration visible | PASS / FAIL | evidence template config |

**CORE-04 verdict:** PASS / FAIL

## Combined checkpoint

| CORE task | Verdict | Blocker? |
|-----------|---------|----------|
| CORE-02 | PASS / FAIL | |
| CORE-03 | PASS / FAIL | |
| CORE-04 | PASS / FAIL | |
| **Checkpoint** | **PASS / FAIL** | |

## Milestone impact

```
CORE-02..04 weight: 50% of total CORE milestone
If all pass: milestone moves from 17% to ~67%
```

## Signoff

```
Reviewer: _______________
Date: _______________
Checkpoint: PASS / FAIL
Notes: _______________
```

## References

- [core-02-evidence-template.md](core-02-evidence-template.md)
- [core-03-04-evidence-template.md](core-03-04-evidence-template.md)
- [core-03-04-cross-source-reconciliation.md](core-03-04-cross-source-reconciliation.md)
- [restart-milestone-checklist.md](restart-milestone-checklist.md)
