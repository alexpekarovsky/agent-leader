# CORE-02 Acceptance Packet & Reviewer Checklist

Combined artifact for validating and signing off AUTO-M1-CORE-02 (instance-aware status section for multi-session visibility).

## Part 1: Evidence Packet

Collect this evidence after running the [CORE-02 verification checklist](core-02-verification-checklist.md).

### 1.1 Pre-check: CORE-01 instance_id

```
orchestrator_register_agent(agent="claude_code", metadata={...})
```

**Evidence** (paste register response showing instance_id):
```
<paste here>
```

- [ ] `instance_id` field present in response
- [ ] Format matches `{agent}#{suffix}`

### 1.2 List agents shows instance-aware entries

```
orchestrator_list_agents()
```

**Evidence** (paste output):
```
<paste here>
```

- [ ] Each agent entry contains `instance_id`
- [ ] Each entry contains `agent_name`, `role`, `status`, `last_seen`

### 1.3 Two workers distinguishable

Start two workers, then list agents.

**Evidence** (paste output showing two separate entries):
```
<paste here>
```

- [ ] Two distinct `instance_id` values for same agent name
- [ ] Both show `status: active`
- [ ] Both have recent `last_seen` timestamps

### 1.4 Disconnected worker detection

Stop one worker, wait, then list agents.

**Evidence** (paste output):
```
<paste here>
```

- [ ] Stopped worker shows `stale` or `disconnected`
- [ ] Running worker still shows `active`

### 1.5 Backward compatibility

Connect a client without explicit `instance_id`.

**Evidence** (paste output):
```
<paste here>
```

- [ ] Fallback `instance_id` auto-generated (e.g., `{agent}#default` or `{agent}#{session_id}`)
- [ ] No errors for old-style clients

## Part 2: Reviewer Checklist

The reviewer validates the evidence packet before signing off.

### Functional checks

| # | Check | Pass? |
|---|-------|-------|
| R1 | Evidence 1.1 shows `instance_id` in registration response | [ ] |
| R2 | Evidence 1.2 shows all expected fields per [instance-aware-status-fields.md](instance-aware-status-fields.md) | [ ] |
| R3 | Evidence 1.3 shows two distinct `instance_id` values | [ ] |
| R4 | Evidence 1.4 shows correct status transition for stopped worker | [ ] |
| R5 | Evidence 1.5 shows backward-compatible fallback | [ ] |

### Code quality checks

| # | Check | Pass? |
|---|-------|-------|
| R6 | Implementation committed with tests | [ ] |
| R7 | Existing test suite passes (`python3 -m unittest discover tests -v`) | [ ] |
| R8 | No regressions in `orchestrator_status`, `list_agents`, `connect_to_leader` | [ ] |
| R9 | State file format documented or self-evident | [ ] |

### Documentation checks

| # | Check | Pass? |
|---|-------|-------|
| R10 | [instance-aware-status-fields.md](instance-aware-status-fields.md) matches implementation | [ ] |
| R11 | [core-02-verification-checklist.md](core-02-verification-checklist.md) steps are accurate | [ ] |
| R12 | [restart-milestone-burnup.md](restart-milestone-burnup.md) updated to reflect CORE-02 done | [ ] |

## Signoff

| Role | Name | Date | Verdict |
|------|------|------|---------|
| Implementer | | | |
| Reviewer | | | |
| Operator | | | |

**Verdict options:** Accepted / Accepted with notes / Rejected (specify reason)

**Notes:**
```
<any reviewer notes>
```

## References

- [core-02-verification-checklist.md](core-02-verification-checklist.md) — Verification steps
- [core-02-evidence-template.md](core-02-evidence-template.md) — Detailed evidence capture
- [instance-aware-status-fields.md](instance-aware-status-fields.md) — Field definitions
- [restart-milestone-burnup.md](restart-milestone-burnup.md) — Milestone progress
