# Milestone Communication Template

Reusable template for reporting AUTO-M1 milestone progress to the operator. Copy and fill in the sections for each update.

## Template

```
## Milestone Progress Update — [DATE]

### Overall Progress
- **Milestone**: AUTO-M1 (Near-Automatic Restart)
- **Completion**: [DONE] / [TOTAL] tasks = [PERCENT]%
- **Delta since last update**: +[N] tasks completed

### Category Breakdown
| Category       | Done | In Progress | Assigned | Total |
|----------------|------|-------------|----------|-------|
| CORE           | [N]  | [N]         | [N]      | [N]   |
| CORE-SUPPORT   | [N]  | [N]         | [N]      | [N]   |
| OPS            | [N]  | [N]         | [N]      | [N]   |
| **Total**      | [N]  | [N]         | [N]      | [N]   |

### Tasks Completed This Cycle
- TASK-xxx: [title] (commit [sha])
- TASK-yyy: [title] (commit [sha])

### Currently In Progress
- TASK-zzz: [title] — [agent], started [time]

### Blockers
- [ ] [Description of blocker] — affects TASK-xxx
- (none)

### Next Actions
1. [Next task or priority]
2. [Follow-up item]

### Notes
[Any additional context, risks, or decisions needed]
```

## Example (Filled In)

```
## Milestone Progress Update — 2026-02-26

### Overall Progress
- **Milestone**: AUTO-M1 (Near-Automatic Restart)
- **Completion**: 12 / 41 tasks = 29%
- **Delta since last update**: +5 tasks completed

### Category Breakdown
| Category       | Done | In Progress | Assigned | Total |
|----------------|------|-------------|----------|-------|
| CORE           | 1    | 0           | 5        | 6     |
| CORE-SUPPORT   | 0    | 0           | 17       | 17    |
| OPS            | 11   | 1           | 6        | 18    |
| **Total**      | 12   | 1           | 28       | 41    |

### Tasks Completed This Cycle
- TASK-1ea47cf6: Restart milestone checklist (commit 43087eb)
- TASK-7804d491: Dual-CC quick reference card (commit 98ec31c)
- TASK-e3e2384f: Supervisor log naming doc (commit 945d464)
- TASK-9ca0ac62: Post-restart verification flowchart (commit d1f4061)
- TASK-02cfdca2: Milestone burnup tracker (commit 4c70d6e)

### Currently In Progress
- TASK-b23083b9: Supervisor startup profiles — claude_code

### Blockers
- (none)

### Next Actions
1. Complete remaining OPS docs and checkers
2. Begin CORE-SUPPORT test implementations

### Notes
All smoke tests passing (92/92). No state corruption detected.
```

## How to Generate the Numbers

### Quick % calculation

```bash
# From any connected CLI session:
orchestrator_list_tasks()
# Then count AUTO-M1 tasks by status
```

Or use the burnup tracker doc: [restart-milestone-burnup.md](restart-milestone-burnup.md)

### Formula

```
Milestone % = (done AUTO-M1 tasks / total AUTO-M1 tasks) x 100
```

### Counting tasks by category

- **CORE**: tasks with `AUTO-M1-CORE-0N` in the title (infrastructure changes)
- **CORE-SUPPORT**: tasks with `AUTO-M1-CORE-SUPPORT-NN` (tests for core changes)
- **OPS**: tasks with `AUTO-M1-OPS-NN` (docs and checkers)

## When to Send Updates

| Trigger | Frequency |
|---------|-----------|
| Batch of tasks completed | After every 3-5 completions |
| Blocker raised | Immediately |
| Milestone phase change (e.g., CORE done) | At the transition |
| Operator requests status | On demand |
| End of work session | Before disconnect |

## References

- [restart-milestone-burnup.md](restart-milestone-burnup.md) — Task list and progress tracking
- [restart-milestone-checklist.md](restart-milestone-checklist.md) — What the milestone delivers
