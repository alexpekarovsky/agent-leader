# Triple-CC Daily Kickoff Checklist

Quick alignment checklist before starting CC1/CC2/CC3 work sessions.

## Before first claim

- [ ] All sessions target same project root and git branch
- [ ] Confirm session labels: CC1, CC2, CC3
- [ ] Clear any stale `set_claim_override` entries
- [ ] Check queue: `orchestrator_list_tasks(status="assigned")`
- [ ] Assign lanes (workstreams) per session

## Lane assignment

| Session | Primary lane | Fallback |
|---------|-------------|----------|
| CC1 | __________ | __________ |
| CC2 | __________ | __________ |
| CC3 | __________ | __________ |

## First task routing

```
# Route CC1's first task
set_claim_override(agent="claude_code", task_id="TASK-___", source="codex")
# CC1 claims, then clear override before setting CC2's
set_claim_override(agent="claude_code", task_id="", source="codex")
```

Repeat for CC2 and CC3. **Never set two overrides without clearing between them** — this prevents duplicate claims.

## Duplicate-claim prevention

- [ ] Only one override active at a time
- [ ] Each session confirms its claimed task ID before starting work
- [ ] Monitor: `orchestrator_list_tasks(status="in_progress")`

## Queue snapshot

| Metric | Count |
|--------|-------|
| Assigned | ___ |
| In progress | ___ |
| Blocked | ___ |
| Done | ___ |

## References

- [multi-cc-partition-templates.md](multi-cc-partition-templates.md)
- [duplicate-claim-playbook.md](duplicate-claim-playbook.md)
- [triple-cc-rotation-policy.md](triple-cc-rotation-policy.md)
