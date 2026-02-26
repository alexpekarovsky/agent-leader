# CORE-02 Acceptance Packet Review Checklist (Reviewer Side)

Checklist for reviewers validating a submitted CORE-02 acceptance
evidence packet before granting signoff.

## Pre-review

- [ ] Packet folder exists at expected location (e.g., `evidence/core-02/`)
- [ ] README or index file present
- [ ] All expected artifact files listed (see packet checklist)

## Artifact completeness

| Artifact | Expected file | Present? | Non-empty? |
|----------|--------------|----------|-----------|
| Status snapshot | `status-snapshot.json` | | |
| Active-only snapshot | `status-snapshot-active.json` | | |
| Audit log | `audit-log.json` | | |
| Two-worker evidence | `agent-list-two-workers.json` | | |
| Stale detection | `stale-detection.json` | | |
| Test results | `test-results.txt` | | |
| Operator notes | `operator-notes.md` | | |

- [ ] All 7 artifacts present
- [ ] All JSON files parse without errors
- [ ] No placeholder text remaining (e.g., `[paste output here]`)

## Content validation

### Step 1: Agent list with instance IDs

Review `status-snapshot.json`:

- [ ] Contains agent entries (not empty array)
- [ ] Each entry has `instance_id` field
- [ ] Each `instance_id` is non-empty string
- [ ] `agent_name`, `status`, `last_seen` fields present

### Step 2: Instance ID format

- [ ] All instance IDs follow `{agent}#{suffix}` format
- [ ] Agent prefix matches the `agent_name` field
- [ ] No duplicate instance IDs

### Step 3: Two workers distinguishable

Review `agent-list-two-workers.json`:

- [ ] Two separate entries for `claude_code` (or target agent)
- [ ] Each has distinct `instance_id`
- [ ] Each has own `last_seen` timestamp
- [ ] Timestamps are plausible (within test window)

### Step 4: Stale detection per-instance

Review `stale-detection.json`:

- [ ] Stopped worker shows `stale` or `disconnected`
- [ ] Running worker shows `active`
- [ ] Stopped worker `last_seen` is older than running worker
- [ ] No cross-contamination between instances

### Step 5: Test results

Review `test-results.txt`:

- [ ] Test command is `python3 -m unittest tests/test_status_agent_identities.py -v`
- [ ] All tests show `ok` status
- [ ] 0 failures, 0 errors
- [ ] Test count matches expected (currently 10)

### Step 6: Backward compatibility

- [ ] Evidence shows agents without explicit ID get `{agent}#default`
- [ ] No errors from old-style connections in logs

## Operator notes review

- [ ] Environment recorded (OS, shell, MCP version)
- [ ] Timestamps recorded for each step
- [ ] Any anomalies documented with explanation
- [ ] No unresolved issues noted

## Reviewer verdict

| Criterion | Pass | Fail | N/A |
|-----------|------|------|-----|
| All artifacts present | | | |
| JSON files valid | | | |
| Instance IDs correct format | | | |
| Two workers distinguishable | | | |
| Stale detection works | | | |
| Tests pass | | | |
| Backward compatible | | | |
| Operator notes complete | | | |

### Decision

- [ ] **APPROVE** — All criteria pass, packet is complete
- [ ] **REQUEST CHANGES** — Issues found (list below)
- [ ] **REJECT** — Fundamental failures (list below)

### Issues found (if any)

| # | Issue | Severity | Resolution needed |
|---|-------|----------|-------------------|
| 1 | | | |
| 2 | | | |

## Signoff

```
Reviewer: _______________
Date: _______________
Decision: APPROVE / REQUEST CHANGES / REJECT
Notes: _______________
```

## References

- [core-02-evidence-packet.md](core-02-evidence-packet.md) -- Packet creation checklist
- [core-02-evidence-template.md](core-02-evidence-template.md) -- Evidence capture template
- [core-02-verification-checklist.md](core-02-verification-checklist.md) -- Verification steps
