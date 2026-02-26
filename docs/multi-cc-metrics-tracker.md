# Multi-CC Metrics Tracker Template

Template to track throughput, collisions, and blockers across multi-CC
sessions. Fill at the end of each session; compare across sessions to
spot trends.

## Session metrics table

Copy this table for each session:

```
## Session: [DATE] [START_TIME]-[END_TIME]
## Sessions active: CC1, CC2 [, CC3]
## Partitioning: [free-claim | override-directed | workstream-split]

| Metric            | CC1 | CC2 | CC3 | Total |
|--------------------|-----|-----|-----|-------|
| tasks_completed    |     |     |     |       |
| tasks_blocked      |     |     |     |       |
| duplicate_claims   |     |     |     |       |
| collisions         |     |     |     |       |
| avg_cycle_time (s) |     |     |     |       |
| git_conflicts      |     |     |     |       |
| blockers_raised    |     |     |     |       |
| blockers_resolved  |     |     |     |       |
```

## Counting rules

### What counts as a collision

A collision is any event where two sessions interfered with each other:

- Duplicate claim (both sessions claimed the same task)
- Git merge conflict between session commits
- Claim override overwritten by another session
- Report rejected because other session already reported

### What counts as throughput

- A task counts as `completed` when it reaches `done` status after validation
- A task counts as `blocked` if a blocker was raised during work on it
- Only count tasks completed during this session, not carryovers

### What counts as a duplicate claim

- Both sessions received the same `task_id` from `claim_next_task`
- Or both sessions started working on the same task (even if only one formally claimed it)
- Check via: `orchestrator_list_audit_logs` filtering for `task.claimed` events

### Cycle time

- Measured from `claim_next_task` to `submit_report` for each task
- Use audit log timestamps for precise measurement
- Average across all tasks completed by each session

## Data collection commands

```bash
# Tasks completed by status
orchestrator_list_tasks(status="done")

# Open blockers
orchestrator_list_blockers(status="open")

# Recent audit entries (look for claim/report pairs)
orchestrator_list_audit_logs(limit=50)

# Count collisions in watchdog
grep -c "duplicate_claim\|stale_task" "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)"
```

## Cross-session comparison

| Date | Sessions | Tasks done | Collisions | Blockers | Avg cycle (s) | Notes |
|------|----------|-----------|------------|----------|---------------|-------|
|      |          |           |            |          |               |       |
|      |          |           |            |          |               |       |

## Usage notes

- Fill metrics at end of each session before shutting down workers
- If collision count rises across sessions, tighten partitioning strategy
- If avg_cycle_time rises, check for task complexity growth or worker issues
- Compare 2-CC vs 3-CC sessions to find the throughput sweet spot
- Zero collisions with low throughput may indicate over-partitioning

## References

- [dual-cc-conventions.md](dual-cc-conventions.md) -- Session labeling and claim etiquette
- [multi-cc-escalation-ladder.md](multi-cc-escalation-ladder.md) -- Escalation levels and scenarios
- [collision-postmortem-template.md](collision-postmortem-template.md) -- Postmortem format for incidents
