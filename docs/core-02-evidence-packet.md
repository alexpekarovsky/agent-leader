# CORE-02 Restart Acceptance Evidence Packet Checklist

Checklist for packaging CORE-02 restart acceptance evidence into a
consistent artifact bundle for review and signoff.

## Artifact bundle structure

```
evidence/core-02/
  README.md                    # This checklist (filled in)
  status-snapshot.json         # orchestrator_list_agents output
  status-snapshot-active.json  # orchestrator_list_agents(active_only=true)
  audit-log.json               # orchestrator_list_audit_logs output
  agent-list-two-workers.json  # Output showing two distinct workers
  stale-detection.json         # Output showing stale vs active
  test-results.txt             # test_status_agent_identities.py output
  operator-notes.md            # Free-form notes and observations
```

## Artifact collection checklist

### Step 1: Pre-restart baseline

- [ ] Capture `orchestrator_list_agents(active_only=false)` → `status-snapshot.json`
- [ ] Verify file contains agent entries with instance_id fields

### Step 2: Two-worker verification

- [ ] Start two Claude Code worker sessions
- [ ] Capture `orchestrator_list_agents(active_only=true)` → `agent-list-two-workers.json`
- [ ] Verify two distinct claude_code entries with unique instance_ids

### Step 3: Stale detection

- [ ] Stop one worker
- [ ] Wait for stale threshold (~60s)
- [ ] Capture `orchestrator_list_agents(active_only=false)` → `stale-detection.json`
- [ ] Verify stopped worker shows stale/disconnected

### Step 4: Audit trail

- [ ] Capture `orchestrator_list_audit_logs(limit=20)` → `audit-log.json`
- [ ] Verify agent registration and heartbeat events present

### Step 5: Test results

- [ ] Run `python3 -m unittest tests/test_status_agent_identities.py -v`
- [ ] Save output → `test-results.txt`
- [ ] Verify all tests pass

### Step 6: Operator notes

- [ ] Record any anomalies or deviations in `operator-notes.md`
- [ ] Note environment (OS, shell, MCP server version)
- [ ] Record timestamps for each step

## Verification mapping

| CORE-02 checklist step | Artifact file | Present? |
|------------------------|---------------|----------|
| Agent list with instance_id | status-snapshot.json | |
| Instance_id format | status-snapshot.json | |
| Two workers distinguishable | agent-list-two-workers.json | |
| Stale detection per-instance | stale-detection.json | |
| Backward compatibility | status-snapshot.json | |
| Unit tests pass | test-results.txt | |

## Bundle validation

Before signoff, verify:

- [ ] All artifact files exist and are non-empty
- [ ] JSON files parse without errors
- [ ] Test results show 0 failures
- [ ] Operator notes are filled in
- [ ] All checklist items are checked or explained

## Signoff

```
Packager: _______________
Reviewer: _______________
Date: _______________
Bundle status: COMPLETE / INCOMPLETE
Notes: _______________
```

## References

- [core-02-verification-checklist.md](core-02-verification-checklist.md) -- Verification steps
- [core-02-evidence-template.md](core-02-evidence-template.md) -- Evidence capture template
- [evidence-folder-layout.md](evidence-folder-layout.md) -- Folder structure
