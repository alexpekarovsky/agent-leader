# CORE Acceptance Cheatsheet

> Quick-reference for CORE-02..06 acceptance terminology. One screen.

| Term | Definition | Pass Condition | Fail Condition |
|------|-----------|----------------|----------------|
| **Acceptance gate** | The review checkpoint a CORE item must clear before status moves to `done`. | All acceptance criteria met, evidence provided, reviewer signs off. | Any criterion unmet, missing evidence, or reviewer rejects. |
| **Evidence artifact** | A concrete output proving work was completed: test results, commit SHAs, task IDs, log snippets. | Artifact exists, is reproducible, and matches the claimed CORE scope. | Artifact missing, stale, or does not cover the claimed scope. |
| **Verification checklist** | Per-CORE list of items a reviewer checks before accepting. Defined in the acceptance template. | Every checklist item checked off with evidence linked. | One or more items unchecked or marked N/A without justification. |
| **Signoff** | Formal reviewer decision recorded against a CORE item: accept, defer, or reject. | Reviewer records `accept` with date and notes. | Reviewer records `defer` (needs rework) or `reject` (fundamental issue). |
| **Regression** | A previously passing test or behavior that now fails after new changes. | Zero regressions in the CORE scope and its upstream dependencies. | Any regression detected in CORE scope or upstream CORE items. |
| **Milestone %** | `(done CORE count) / 6 * 100`. Only moves in 17-point increments (1/6 steps). | Advances when a CORE item clears its acceptance gate. | Stays flat when no CORE item completes, regardless of task throughput. |
| **Delta** | The change in milestone % between two reporting periods. | Positive delta (e.g., 33% to 50%) means a CORE was accepted. | Zero delta means no CORE gate was cleared this period. |
| **Rollback criteria** | Conditions under which an accepted CORE is reverted to `in_progress`. | Not triggered: no regressions found post-acceptance. | Triggered: regression in accepted CORE, broken downstream dependency, or evidence invalidated. |
| **Blocker threshold** | The severity/count at which blockers halt progress on a CORE track. | Blockers below threshold (0 high-severity, <=2 medium open). | Any high-severity blocker open, or >2 medium blockers on one CORE. |

## Milestone % Quick Lookup

| Done | % | Delta from previous |
|------|---|--------------------|
| 0/6 | 0% | -- |
| 1/6 | 17% | +17 |
| 2/6 | 33% | +17 |
| 3/6 | 50% | +17 |
| 4/6 | 67% | +17 |
| 5/6 | 83% | +17 |
| 6/6 | 100% | +17 |

## Key Rules

- Milestone % only changes when a whole CORE clears its gate. Task-level progress does not move it.
- Evidence must be reproducible. A commit SHA alone is insufficient without linked test results.
- Rollback resets milestone % by 17 points and reopens the CORE for rework.
- Signoff requires a named reviewer -- automated validation alone is not sufficient.
