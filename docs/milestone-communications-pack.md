# AUTO-M1 Milestone Communications Pack

Full communications package for the AUTO-M1 (Near-Automatic Restart) milestone
rollout. Contains templates for kickoff, weekly updates, and completion
announcements in short, medium, and detailed variants.

---

## 1. Kickoff Announcement

### 1a. Short (Slack / Chat)

```
AUTO-M1 kickoff: building near-automatic restart capability.
6 core items across instance tracking, leases, telemetry, and recovery.
Target: 2-3 weeks. Team: codex (lead), claude_code, gemini.
```

### 1b. Medium (Email / Meeting Notes)

```
Subject: AUTO-M1 Milestone Kickoff -- Near-Automatic Restart

We are starting work on the AUTO-M1 milestone, which will enable
near-automatic restart of agent loops with minimal operator intervention.

Scope: 6 core infrastructure items
  - CORE-01: Instance ID support
  - CORE-02: Instance-aware status visibility
  - CORE-03: Lease schema and TTL
  - CORE-04: Lease recovery in manager cycle
  - CORE-05: Dispatch telemetry
  - CORE-06: Noop diagnostics

Team:
  codex (manager/lead), claude_code (implementation), gemini (frontend)

Timeline: 2-3 weeks estimated
Blockers: None at kickoff
Next actions: Begin CORE-02 and CORE-03 in parallel
```

### 1c. Detailed (Project Document)

```
Subject: AUTO-M1 Milestone Kickoff -- Near-Automatic Restart

## Summary

The AUTO-M1 milestone delivers the infrastructure required for
near-automatic restart of the multi-agent orchestration system.
After completion, restarting agent loops requires minimal manual
intervention -- the system can detect stale instances, recover
expired leases, and provide diagnostic data for operator review.

## Milestone Scope

6 core items plus supporting tests and documentation:

| Item    | Title                           | Dependencies |
|---------|---------------------------------|--------------|
| CORE-01 | Instance ID support             | None         |
| CORE-02 | Instance-aware status visibility| CORE-01      |
| CORE-03 | Lease schema and TTL            | None         |
| CORE-04 | Lease recovery in manager cycle | CORE-03      |
| CORE-05 | Dispatch telemetry              | None         |
| CORE-06 | Noop diagnostics                | CORE-05      |

Supporting work: ~35 tasks across CORE-SUPPORT (tests) and OPS (docs).

## Progress Baseline

AUTO-M1 Milestone: 0% (0/6 core items)
Overall Project: 72% (213/297 tasks done)

## Team Health

| Agent       | Status  | Role           |
|-------------|---------|----------------|
| codex       | active  | Manager / lead |
| claude_code | active  | Implementation |
| gemini      | active  | Frontend       |

Queue: 84 assigned, 0 in_progress, 213 done
Blockers: 0 open

## Risks

- Gemini offline periods may delay frontend-dependent items.
- Lease recovery (CORE-04) depends on CORE-03 completing first.
- Noop diagnostics (CORE-06) depends on CORE-05.

## Next Actions

1. Begin CORE-02 (instance-aware status) and CORE-03 (lease schema)
   in parallel -- no dependencies between them.
2. Assign CORE-05 (dispatch telemetry) to second CC session if
   available.
3. Schedule first weekly update for end of week 1.
```

---

## 2. Weekly Update

### 2a. Short (Slack / Chat)

```
AUTO-M1 weekly: 33% (2/6 core) | Overall: 79%
Shipped: status visibility, lease schema. Next: lease recovery.
Team: 3/3 online. Blockers: 6 open (none critical).
```

### 2b. Medium (Email / Meeting Notes)

```
Subject: AUTO-M1 Weekly Update -- Week 1

## Progress
AUTO-M1 Milestone: 33% (2/6 core items complete)
Overall Project: 79% (254/322 tasks done)
Delta: +2 core items, +41 tasks since kickoff

## Completed This Week
- CORE-02: Instance-aware status visibility (validated)
- CORE-03: Lease schema and TTL (validated)

## In Progress
- CORE-04: Lease recovery -- claude_code, ~60% done
- CORE-05: Dispatch telemetry -- claude_code, started

## Team Health
codex (active), claude_code (active), gemini (active)
Queue: 38 assigned, 2 in_progress, 254 done

## Blockers
6 open blockers, none critical. 4 are medium-severity doc
prerequisites. 2 are high-severity stale task issues under review.

## Next Actions
1. Complete CORE-04 (lease recovery) -- expected mid-week
2. Continue CORE-05 (dispatch telemetry)
3. Begin CORE-06 (noop diagnostics) once CORE-05 ships
4. Resolve 2 high-severity blockers
```

### 2c. Detailed (Project Document)

```
Subject: AUTO-M1 Weekly Update -- Week 1

## Summary

Good progress in week 1. Two of six core items shipped and validated.
Lease recovery work is well underway and unblocked by the completed
lease schema. All agents online with no capacity issues.

## Progress

AUTO-M1 Milestone: 33% (2/6 core items complete)
Overall Project: 79% (254/322 tasks done)
Delta since kickoff: +2 core items, +41 tasks completed

## Completed Tasks (Core)

| Item    | Title                     | Task ID        | Commit  | Tests       |
|---------|---------------------------|----------------|---------|-------------|
| CORE-02 | Instance-aware status     | TASK-13a1fc1d  | a82ebde | 6 pass/0 fail |
| CORE-03 | Lease schema and TTL      | TASK-ba1b2ee1  | 296d68a | 8 pass/0 fail |

## In Progress

| Item    | Title                     | Owner       | Est. Completion |
|---------|---------------------------|-------------|-----------------|
| CORE-04 | Lease recovery            | claude_code | Mid-week 2      |
| CORE-05 | Dispatch telemetry        | claude_code | End of week 2   |

## Not Started

| Item    | Title                     | Blocked By |
|---------|---------------------------|------------|
| CORE-01 | Instance ID support       | None       |
| CORE-06 | Noop diagnostics          | CORE-05    |

## Team Health

| Agent       | Status | Tasks Done | Current Task   |
|-------------|--------|------------|----------------|
| codex       | active | 18         | TASK-82466844  |
| claude_code | active | 23         | TASK-3cb6bab0  |
| gemini      | active | 0          | TASK-dc0af9ac  |

Queue: 38 assigned, 2 in_progress, 254 done
Integrity: OK (no regressions, no state corruption)

## Blockers (6 open)

| ID             | Severity | Task           | Summary                        |
|----------------|----------|----------------|--------------------------------|
| BLK-0cbfcffb   | high     | TASK-ba1b2ee1  | Stale task -- reassign?        |
| BLK-1938f365   | high     | TASK-e75fb59d  | Stale task -- resume or defer? |
| BLK-44748b57   | medium   | TASK-3cb6bab0  | Missing prerequisite doc       |
| BLK-a2c91b03   | medium   | TASK-53733337  | Test fixture dependency        |
| BLK-d7e44f19   | medium   | TASK-82466844  | Schema clarification needed    |
| BLK-f1b08e22   | medium   | TASK-dc0af9ac  | Frontend spec incomplete       |

## Risks

- Two high-severity blockers need operator decisions this week.
- CORE-06 cannot start until CORE-05 ships (sequential dependency).
- Gemini has no completed tasks yet -- monitor for connectivity issues.

## Next Actions

1. Complete CORE-04 lease recovery (priority)
2. Continue CORE-05 dispatch telemetry
3. Resolve BLK-0cbfcffb and BLK-1938f365 (high severity)
4. Review gemini task progress
5. Plan CORE-06 start once CORE-05 is validated
```

---

## 3. Milestone Completion Announcement

### 3a. Short (Slack / Chat)

```
AUTO-M1 complete: 100% (6/6 core) | Overall: 91%
All core restart infrastructure shipped and validated.
Remaining: support tasks and QA. 0 open blockers.
```

### 3b. Medium (Email / Meeting Notes)

```
Subject: AUTO-M1 Milestone Complete -- Near-Automatic Restart

## Summary
The AUTO-M1 milestone is complete. All 6 core infrastructure items
have been implemented, tested, and validated.

## Final Status
AUTO-M1 Milestone: 100% (6/6 core items)
Overall Project: 91% (285/313 tasks done)

## What Shipped
- Instance-aware status: each worker has a unique identity
- Lease management: tasks auto-recover when workers crash
- Dispatch telemetry: every command is tracked end-to-end
- Noop diagnostics: silent failures are now visible

## Team Health
All agents active. 0 open blockers. Queue nearly drained.

## Next Actions
1. Complete remaining CORE-SUPPORT test tasks
2. Finalize OPS documentation
3. Run full regression before declaring phase complete
4. Begin planning Phase B (swarm mode prerequisites)
```

### 3c. Detailed (Project Document)

```
Subject: AUTO-M1 Milestone Complete -- Near-Automatic Restart

## Summary

The AUTO-M1 (Near-Automatic Restart) milestone is complete. All 6
core infrastructure items have been implemented, tested, validated,
and merged. The system now supports near-automatic restart of agent
loops with minimal operator intervention.

## Final Status

AUTO-M1 Milestone: 100% (6/6 core items complete)
Overall Project: 91% (285/313 tasks done)
Duration: 18 days (kickoff to completion)

## Deliverables

| Item    | Title                      | Task ID        | Commit  | Tests         | Validated |
|---------|----------------------------|----------------|---------|---------------|-----------|
| CORE-01 | Instance ID support        | TASK-13a1fc1d  | 573b6dd | 4 pass/0 fail | Yes       |
| CORE-02 | Instance-aware status      | TASK-439df85f  | a82ebde | 6 pass/0 fail | Yes       |
| CORE-03 | Lease schema and TTL       | TASK-ba1b2ee1  | 296d68a | 8 pass/0 fail | Yes       |
| CORE-04 | Lease recovery             | TASK-3cb6bab0  | 092e110 | 12 pass/0 fail| Yes       |
| CORE-05 | Dispatch telemetry         | TASK-f028e203  | 0bf6e06 | 14 pass/0 fail| Yes       |
| CORE-06 | Noop diagnostics           | TASK-e75fb59d  | 573b6dd | 9 pass/0 fail | Yes       |

Total tests: 53 passed, 0 failed

## Capabilities Delivered

1. **Instance-aware status**: `orchestrator_status()` distinguishes
   individual workers by instance ID. Operators can see exactly which
   sessions are active, idle, or stale.

2. **Lease-based task ownership**: Every in_progress task has a
   time-limited lease. If the owner crashes, the lease expires and
   the task returns to the assigned queue automatically.

3. **Automatic lease recovery**: The manager cycle detects expired
   leases and requeues affected tasks without operator intervention.

4. **Dispatch telemetry**: Every command dispatch is tracked with
   correlation IDs, timing data, and acknowledgment status.

5. **Noop diagnostics**: When a dispatch produces no result (lost
   command, unresponsive agent), the system generates a diagnostic
   event with the reason and suggested action.

## Team Health

| Agent       | Status | Tasks Completed | Blockers Resolved |
|-------------|--------|-----------------|-------------------|
| codex       | active | 42              | 8                 |
| claude_code | active | 51              | 12                |
| gemini      | active | 6               | 0                 |

Queue: 2 assigned, 0 in_progress, 285 done
Blockers: 0 open (22 resolved during milestone)
Bugs: 0 open (3 found and fixed during milestone)
Integrity: OK across all status checks

## Blockers Resolved During Milestone

22 blockers raised and resolved. Breakdown:
- 6 high severity (stale tasks, crash recovery)
- 12 medium severity (doc prerequisites, schema questions)
- 4 low severity (naming conventions, formatting)

Average resolution time: 4.2 hours

## Risks Retired

- Lease expiry race conditions -- mitigated by atomic state updates
- Dispatch message loss -- mitigated by correlation tracking
- Multi-session identity confusion -- mitigated by instance IDs

## Remaining Work

| Category     | Assigned | In Progress | Done | Total |
|--------------|----------|-------------|------|-------|
| CORE         | 0        | 0           | 6    | 6     |
| CORE-SUPPORT | 2        | 0           | 15   | 17    |
| OPS          | 0        | 0           | 18   | 18    |

28 tasks remain (CORE-SUPPORT tests and final QA).

## Next Actions

1. Complete 2 remaining CORE-SUPPORT test tasks
2. Run full regression suite across all modules
3. Update operator runbook with new lease and telemetry procedures
4. Archive milestone evidence in evidence/ folder
5. Begin planning Phase B (swarm mode prerequisites)
6. Schedule post-milestone retrospective
```

---

## Template Usage Notes

- Replace placeholder values (task IDs, commits, counts) with live data
  from `orchestrator_status()` and `orchestrator_list_tasks()`.
- Choose the variant that matches your audience and channel.
- Always include both AUTO-M1 % and overall project % for context.
- Update blocker counts from `orchestrator_list_blockers(status=open)`.

## References

- [milestone-communication-template.md](milestone-communication-template.md) -- Base template
- [milestone-status-examples.md](milestone-status-examples.md) -- Percentage examples
- [milestone-communication-variants.md](milestone-communication-variants.md) -- Audience variants
- [restart-milestone-checklist.md](restart-milestone-checklist.md) -- Acceptance gates
