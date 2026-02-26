# Triple-CC End-of-Shift Handoff Template

Template for summarizing completed work, in-progress tasks, blockers,
and suggested next claims when handing off between shifts or sessions.

## Template

```markdown
## CC Shift Handoff — [DATE] [TIME]

### Session summary
| Session | Tasks completed | Current task | Status |
|---------|----------------|--------------|--------|
| CC1 | TASK-___, TASK-___ | TASK-___ | done / in_progress / idle |
| CC2 | TASK-___, TASK-___ | TASK-___ | done / in_progress / idle |
| CC3 | TASK-___, TASK-___ | TASK-___ | done / in_progress / idle |

### Completed this shift
- [CC1] TASK-___: [title] @ [commit_sha]
- [CC2] TASK-___: [title] @ [commit_sha]
- [CC3] TASK-___: [title] @ [commit_sha]

### In progress (needs continuation)
- [CC_] TASK-___: [title] — [what's done, what remains]

### Blockers
- TASK-___: [blocker description] — [action needed]
- (none)

### Suggested next claims
1. TASK-___: [title] — [why prioritize]
2. TASK-___: [title] — [why prioritize]

### Queue state at handoff
| Metric | Count |
|--------|-------|
| Assigned | ___ |
| In progress | ___ |
| Reported | ___ |
| Blocked | ___ |
| Done | ___ |

### Notes
[Any context for the next operator/shift]
```

## Example

```markdown
## CC Shift Handoff — 2026-02-26 18:00

### Session summary
| Session | Tasks completed | Current task | Status |
|---------|----------------|--------------|--------|
| CC1 | TASK-abc, TASK-def | none | idle |
| CC2 | TASK-ghi | TASK-jkl | in_progress |
| CC3 | TASK-mno, TASK-pqr, TASK-stu | none | idle |

### Completed this shift
- [CC1] TASK-abc: Supervisor lifecycle tests @ d7ab431
- [CC1] TASK-def: Backoff tuning checker @ 6326797
- [CC2] TASK-ghi: Lease schema test plan checker @ 6326797
- [CC3] TASK-mno: Evidence folder layout @ d7ab431
- [CC3] TASK-pqr: Known limitations doc @ a56a95a
- [CC3] TASK-stu: PID collision checklist @ 708efc9

### In progress (needs continuation)
- [CC2] TASK-jkl: Multi-CC blocker wording library — 5 of 8 blockers written

### Blockers
- TASK-8014d190: incident-triage-order.md doesn't exist — needs creation first

### Suggested next claims
1. TASK-xxx: CORE-SUPPORT instance ID tests — high priority for milestone
2. TASK-yyy: Dispatch telemetry checker — unblocked, ready to implement

### Queue state at handoff
| Metric | Count |
|--------|-------|
| Assigned | 45 |
| In progress | 1 |
| Reported | 0 |
| Blocked | 3 |
| Done | 28 |

### Notes
All tests passing (92/92). No state corruption. CC2's in-progress task
is straightforward — just needs 3 more blocker message templates.
```

## References

- [triple-cc-assignment-board.md](triple-cc-assignment-board.md) — Live assignment board
- [triple-cc-daily-kickoff.md](triple-cc-daily-kickoff.md) — Start-of-shift checklist
- [milestone-communication-template.md](milestone-communication-template.md) — Milestone progress format
