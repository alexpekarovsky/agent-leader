# Status Percent Interpretation: Overall vs Milestone

> Explains why overall project % and restart milestone % can diverge, with
> examples for operator orientation.

## Two Different Metrics

| Metric | What It Measures | Source |
|---|---|---|
| **Overall project %** | `done / total_tasks × 100` across all tasks ever created | `orchestrator_status().live_status.overall_project_percent` |
| **Phase/milestone %** | Completion within a specific phase or milestone scope | `live_status.phase_1_percent`, `phase_2_percent`, etc. |

## Why They Diverge

### Scenario 1: Large Task Backlog

```
Total tasks: 300    Done: 213    Overall: 72%
Phase 1 tasks: 250  Done: 213    Phase 1: 85%
Phase 2 tasks: 50   Done: 0      Phase 2: 0%
```

Overall is 72% but Phase 1 is 85% because Phase 2 tasks (not yet started) drag
the overall number down.

### Scenario 2: Restart Milestone (AUTO-M1) vs Full Project

The AUTO-M1 restart milestone covers CORE-02 through CORE-06 (instance-aware
status, leases, recovery, dispatch telemetry, manager cycle). These are a subset
of the full project which also includes DOCS, EXEC, frontend, and QA tasks.

```
AUTO-M1 core tasks: 168   Done: 168   Milestone: 100%
All project tasks:  297   Done: 213   Overall:    72%
```

The milestone is complete but the overall project is not, because gemini's
frontend tasks and codex's QA tasks are still pending.

### Scenario 3: Blocked Tasks

Blocked tasks count toward total but cannot complete until unblocked:

```
Total: 100   Done: 70   Blocked: 10   Overall: 70%
Achievable:  90 (100 - blocked)        Max possible: 90%
```

The overall % cannot reach 100% until blockers are resolved.

## Backend Vertical Slice vs Frontend Vertical Slice

| Metric | Scope | Example |
|---|---|---|
| `backend_percent` | Tasks under `RETRO-BE-*` or backend workstream | 91% |
| `frontend_percent` | Tasks under `RETRO-FE-*` or frontend workstream | 0% |

These track independent workstreams. Backend can be nearly done while frontend
hasn't started (e.g., gemini is offline).

## QA/Validation Completion

`qa_validation_percent` reflects the ratio of validated (done) tasks to total
reported + done tasks. It measures how much of the completed work has been
reviewed, not how much work is left.

## Quick Reference for Operators

| You see | It means |
|---|---|
| Overall 72%, Phase 1 85% | Phase 2+ tasks exist but aren't started yet |
| Overall 72%, Backend 91% | Backend nearly done; frontend/QA lagging |
| Overall 72%, QA 72% | Validation is keeping pace with completion |
| Phase 1 100%, Overall 72% | Milestone done but project has more phases |
| Overall stuck at N% | Check for blocked tasks or offline agents |

## References

- AUTO-M1 core checklist: `docs/restart-milestone-checklist.md`
- Live status source: `orchestrator_status().live_status`
- Burnup chart data: `docs/restart-milestone-burnup.md`
