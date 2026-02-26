# Triple-CC Queue Triage Board Template

One-screen layout showing lane priorities, next tasks, and fallback
tasks during heavy backlog execution.

## Template

```markdown
## CC Queue Triage — [DATE] [TIME]

### Lane priorities
| Lane | Session | Primary task | Fallback task | Status |
|------|---------|-------------|---------------|--------|
| qa | CC1 | TASK-___ | TASK-___ | idle / working / blocked |
| default | CC2 | TASK-___ | TASK-___ | idle / working / blocked |
| devops | CC3 | TASK-___ | TASK-___ | idle / working / blocked |

### Queue depth
| Lane | Assigned | In progress | Blocked |
|------|----------|-------------|---------|
| qa | ___ | ___ | ___ |
| default | ___ | ___ | ___ |
| devops | ___ | ___ | ___ |
| frontend | ___ | ___ | ___ |
| backend | ___ | ___ | ___ |

### High-priority tasks (claim first)
1. TASK-___: [title] — lane: ___, reason: ___
2. TASK-___: [title] — lane: ___, reason: ___
3. TASK-___: [title] — lane: ___, reason: ___

### Blocked tasks needing attention
- TASK-___: [blocker description]

### Rotation needed?
- [ ] Any lane has 0 assigned tasks → rotate idle session
- [ ] Any lane has 10+ assigned tasks → add helper session
- [ ] Any session has 5+ consecutive tasks in same lane → rotate
```

## Filled example

```markdown
## CC Queue Triage — 2026-02-26 14:00

### Lane priorities
| Lane | Session | Primary task | Fallback task | Status |
|------|---------|-------------|---------------|--------|
| qa | CC1 | TASK-abc123 | TASK-def456 | working |
| default | CC2 | TASK-ghi789 | TASK-jkl012 | working |
| devops | CC3 | none | TASK-mno345 | idle |

### Queue depth
| Lane | Assigned | In progress | Blocked |
|------|----------|-------------|---------|
| qa | 8 | 1 | 2 |
| default | 12 | 1 | 1 |
| devops | 0 | 0 | 0 |
| frontend | 3 | 0 | 0 |
| backend | 2 | 0 | 0 |

### High-priority tasks (claim first)
1. TASK-pqr678: CORE-SUPPORT instance ID tests — lane: qa, reason: milestone blocker
2. TASK-stu901: Dispatch telemetry checker — lane: qa, reason: unblocked
3. TASK-vwx234: Evidence folder checker — lane: qa, reason: quick win

### Blocked tasks needing attention
- TASK-8014d190: incident-triage-order.md doesn't exist

### Rotation needed?
- [x] devops lane has 0 assigned tasks → CC3 rotates to help default
- [ ] default lane has 12 assigned tasks → CC3 joins as helper
- [ ] No session at 5+ consecutive yet
```

## How to populate

```
# Get queue depth per workstream
orchestrator_list_tasks(status="assigned")

# Get in-progress tasks
orchestrator_list_tasks(status="in_progress")

# Get blocked tasks
orchestrator_list_tasks(status="blocked")
```

## References

- [triple-cc-assignment-board.md](triple-cc-assignment-board.md) — Assignment tracking
- [triple-cc-rotation-policy.md](triple-cc-rotation-policy.md) — Rotation rules
- [triple-cc-lane-cheatsheet.md](triple-cc-lane-cheatsheet.md) — Lane assignment
