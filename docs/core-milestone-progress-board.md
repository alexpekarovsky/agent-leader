# CORE Milestone Progress Board

Live progress board for CORE-02 through CORE-06. Copy the blank
template and fill in as milestones advance. The computed milestone
percentage reflects CORE-track progress only, not overall project
completion.

---

## Board Template (Blank)

| Core ID | Title | Status | Evidence | Blockers | Weight | Notes |
|---------|-------|--------|----------|----------|--------|-------|
| CORE-02 | Instance-Aware Status | `not_started` | | | ~17% | |
| CORE-03 | Lease Schema | `not_started` | | CORE-02 | ~17% | |
| CORE-04 | Lease Expiry Recovery | `not_started` | | CORE-03 | ~17% | |
| CORE-05 | Dispatch Telemetry | `not_started` | | CORE-02 | ~17% | |
| CORE-06 | Noop Diagnostics | `not_started` | | CORE-05 | ~17% | |

**Milestone %:** 0%

---

## Column Definitions

| Column | Description |
|--------|-------------|
| **Core ID** | Identifier: CORE-02 through CORE-06. |
| **Title** | Short name for the milestone. |
| **Status** | One of: `not_started`, `in_progress`, `done`. |
| **Evidence** | Task IDs (e.g., TASK-abc123), commit SHAs (e.g., a1b2c3d), test counts (e.g., 8p/0f). Comma-separated. |
| **Blockers** | Upstream CORE IDs that must be `done` before this row can move to `in_progress`. Clear the field once the blocker is resolved. |
| **Weight** | Percentage contribution to milestone total. Each CORE is ~17% (6 items, approximately equal). |
| **Notes** | Free-form: caveats, reviewer comments, partial-progress details. |

### Status Values

| Value | Meaning | Operator action |
|-------|---------|-----------------|
| `not_started` | Work has not begun. | Check if blockers are resolved before starting. |
| `in_progress` | Implementation or testing underway. | Monitor for blockers; check evidence is accumulating. |
| `done` | Accepted by reviewer with evidence. | Clear downstream blocker references. |

---

## Computed Milestone %

```
milestone_percent = (count of rows with status = "done") / 6 * 100
```

Round to the nearest whole number. Each `done` row adds approximately
17 percentage points.

| Done count | Milestone % |
|------------|-------------|
| 0 | 0% |
| 1 | 17% |
| 2 | 33% |
| 3 | 50% |
| 4 | 67% |
| 5 | 83% |
| 6 | 100% |

This percentage tracks CORE milestone completion only. It does not
include non-CORE workstreams (frontend, QA gates, supervisor, etc.).
For overall project %, see `orchestrator_live_status_report`.

---

## Example: 2/6 Done (33%)

Scenario: CORE-02 and CORE-05 are accepted. Lease track is in
progress. Noop diagnostics not yet started.

| Core ID | Title | Status | Evidence | Blockers | Weight | Notes |
|---------|-------|--------|----------|----------|--------|-------|
| CORE-02 | Instance-Aware Status | `done` | TASK-a1b2c3, TASK-d4e5f6; SHA a1b2c3d; 12p/0f | | ~17% | Accepted 2026-02-20 |
| CORE-03 | Lease Schema | `in_progress` | TASK-g7h8i9; SHA b2c3d4e; 5p/0f so far | | ~17% | Lease record created on claim; renewal pending test |
| CORE-04 | Lease Expiry Recovery | `not_started` | | CORE-03 | ~17% | Blocked on CORE-03 completion |
| CORE-05 | Dispatch Telemetry | `done` | TASK-j0k1l2, TASK-m3n4o5; SHA d4e5f6a; 10p/0f | | ~17% | Accepted 2026-02-22 |
| CORE-06 | Noop Diagnostics | `not_started` | | | ~17% | CORE-05 done; ready to start |

**Milestone %:** 33% (2/6 done)

**Board state notes:**
- Lease track partially complete: CORE-03 in progress, CORE-04 blocked.
- Dispatch track partially complete: CORE-05 done, CORE-06 ready.
- Two tracks can advance in parallel from this point.

---

## Example: 4/6 Done (67%)

Scenario: Both tracks nearly complete. Only CORE-04 and CORE-06
remain in progress.

| Core ID | Title | Status | Evidence | Blockers | Weight | Notes |
|---------|-------|--------|----------|----------|--------|-------|
| CORE-02 | Instance-Aware Status | `done` | TASK-a1b2c3, TASK-d4e5f6; SHA a1b2c3d; 12p/0f | | ~17% | Accepted 2026-02-20 |
| CORE-03 | Lease Schema | `done` | TASK-g7h8i9, TASK-p6q7r8; SHA b2c3d4e; 8p/0f | | ~17% | Accepted 2026-02-24 |
| CORE-04 | Lease Expiry Recovery | `in_progress` | TASK-s9t0u1; SHA c3d4e5f; 4p/1f | | ~17% | 1 failing test: concurrent requeue edge case |
| CORE-05 | Dispatch Telemetry | `done` | TASK-j0k1l2, TASK-m3n4o5; SHA d4e5f6a; 10p/0f | | ~17% | Accepted 2026-02-22 |
| CORE-06 | Noop Diagnostics | `in_progress` | TASK-v2w3x4; SHA e5f6a7b; 3p/0f | | ~17% | Noop emission works; consecutive-noop warning pending |

**Milestone %:** 67% (4/6 done)

**Board state notes:**
- CORE-04 has a failing test on the concurrent requeue edge case.
  Fix before acceptance.
- CORE-06 noop emission verified; consecutive-noop stale-agent
  warning not yet implemented.
- No blockers remain in the Blockers column -- all upstream
  dependencies resolved.

---

## Updating the Board

1. **Starting work:** Set status to `in_progress`. Verify all entries
   in the Blockers column for that row are `done`.
2. **Recording evidence:** Add task IDs, commit SHAs, and test counts
   to the Evidence column as work proceeds. Use format:
   `TASK-xxx; SHA yyy; Np/Mf` (passed/failed).
3. **Completing a milestone:** Set status to `done`. Ensure all
   acceptance criteria from the acceptance template are checked.
   Remove any CORE-XX references from downstream Blockers columns.
4. **Recalculating %:** Count `done` rows and divide by 6.

---

## Board vs. Acceptance Report

| Aspect | Progress Board | Acceptance Report |
|--------|---------------|-------------------|
| Purpose | At-a-glance status for standups and dashboards | Formal sign-off with detailed evidence |
| Granularity | One row per CORE milestone | Full section per CORE with checklists |
| Updated by | Any team member during work | Reviewer during acceptance cycle |
| Evidence depth | Summary (task IDs, SHAs, pass/fail counts) | Full detail (log snapshots, checklist items) |

Use the progress board for daily tracking. Use the acceptance report
template (`core-milestone-acceptance-template.md`) for formal reviews.
