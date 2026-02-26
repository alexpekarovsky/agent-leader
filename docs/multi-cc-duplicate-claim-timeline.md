# Duplicate-Claim Timeline Capture Template

Quick timeline template for documenting duplicate-claim incidents in
multi-CC operation. Fill this in immediately when a collision is detected.

## Timeline template

Copy and fill in:

```
## Duplicate-Claim Incident — [DATE]

Task ID: TASK-________
Sessions involved: CC1, CC2

### Timeline

| Timestamp | Session | Action | Evidence source |
|-----------|---------|--------|-----------------|
| HH:MM:SS  | CC1     |        |                 |
| HH:MM:SS  | CC2     |        |                 |
| HH:MM:SS  | operator|        |                 |

### Resolution
- Which session kept the task:
- How the other session's work was handled:
- Time to resolution:
```

## Evidence sources

Gather evidence from these locations:

| Source | Command / location | What to look for |
|--------|-------------------|-----------------|
| Task list | `orchestrator_list_tasks(status="in_progress")` | Two sessions working same task ID |
| Audit log | `orchestrator_list_audit_logs(limit=20)` | `task.claimed` events with same `task_id` |
| Watchdog JSONL | `cat "$(ls -t .autopilot-logs/watchdog-*.jsonl \| head -1)"` | `stale_task` or `duplicate_claim` entries |
| Worker logs | `grep TASK-xxx .autopilot-logs/worker-claude_code-*.log` | Claim and report activity per session |
| Event bus | `orchestrator_poll_events(agent="codex")` | `manager.sync` or blocker events about the collision |

## Example filled-in timeline

```
## Duplicate-Claim Incident — 2026-02-26

Task ID: TASK-abc12345
Sessions involved: CC1, CC2

### Timeline

| Timestamp | Session  | Action                                    | Evidence source       |
|-----------|----------|-------------------------------------------|-----------------------|
| 14:02:10  | CC1      | Called claim_next_task, got TASK-abc12345  | Audit log entry #47   |
| 14:02:12  | CC2      | Called claim_next_task, got TASK-abc12345  | Audit log entry #48   |
| 14:02:15  | CC1      | Started working (git checkout, editing)    | Worker log tail        |
| 14:05:00  | CC2      | Started working (same files)              | Worker log tail        |
| 14:08:30  | operator | Noticed both sessions on same task         | orchestrator_list_tasks |
| 14:09:00  | operator | Raised blocker, reassigned CC2             | Blocker #3             |
| 14:09:30  | CC2      | Abandoned task, called claim_next_task     | Audit log entry #52   |

### Resolution
- CC1 kept the task and completed it.
- CC2's partial work was discarded (no commit pushed).
- Time to resolution: ~7 minutes.
```

## Post-incident questions

- [ ] Were claim overrides in use? If not, should they have been?
- [ ] Did both sessions call `claim_next_task` within the same cycle?
- [ ] Was the engine's atomic claim working? (If both got the same task, check engine version)
- [ ] How much work was wasted by the duplicate?
- [ ] Should task partitioning strategy change (workstream split, override-only)?
- [ ] Is this a repeat incident? Check previous timelines for the same pattern.

## References

- [dual-cc-operation.md](dual-cc-operation.md) -- Technical collision analysis
- [dual-cc-conventions.md](dual-cc-conventions.md) -- Session labeling and claim etiquette
- [multi-cc-escalation-ladder.md](multi-cc-escalation-ladder.md) -- When to raise blockers
- [collision-postmortem-template.md](collision-postmortem-template.md) -- Full postmortem format
