# Triple-CC Lane Assignment Cheat Sheet

Quick reference for assigning and rotating CC1/CC2/CC3 work lanes.

## Default lane assignment

| Session | Lane | Focus |
|---------|------|-------|
| CC1 | `qa` | Tests, checkers, validators |
| CC2 | `default` | Docs, guides, templates |
| CC3 | `devops` | Scripts, supervisor, infra |

## Assigning first tasks

```
# CC1: qa task
set_claim_override(agent="claude_code", task_id="TASK-qa1", source="codex")
# → CC1 claims → clear override
set_claim_override(agent="claude_code", task_id="", source="codex")

# CC2: docs task
set_claim_override(agent="claude_code", task_id="TASK-doc1", source="codex")
# → CC2 claims → clear override
set_claim_override(agent="claude_code", task_id="", source="codex")

# CC3: devops task
set_claim_override(agent="claude_code", task_id="TASK-dev1", source="codex")
# → CC3 claims → clear override
set_claim_override(agent="claude_code", task_id="", source="codex")
```

## When to rotate

| Trigger | Action |
|---------|--------|
| Lane empty (no tasks in primary) | Move to fallback lane |
| 5+ consecutive tasks in same lane | Check other lanes |
| Session idle for 2+ cycles | Pick up from any lane |
| Queue imbalance (10+ in one lane, 0 in another) | Rebalance |

## Rotation fallback order

| Session | 1st choice | 2nd choice | 3rd choice |
|---------|-----------|-----------|-----------|
| CC1 | `qa` | `default` | `devops` |
| CC2 | `default` | `qa` | `devops` |
| CC3 | `devops` | `default` | `qa` |

## Quick queue check

```
orchestrator_list_tasks(status="assigned")
# Count tasks per workstream to identify imbalances
```

## References

- [triple-cc-rotation-policy.md](triple-cc-rotation-policy.md) — Full rotation rules
- [multi-cc-partition-templates.md](multi-cc-partition-templates.md) — Partition strategy
- [triple-cc-daily-kickoff.md](triple-cc-daily-kickoff.md) — Kickoff checklist
