# CORE Percent Delta Explainer

> Templates for explaining why AUTO-M1 milestone % changed or stayed flat.

---

## How Milestone % Works

AUTO-M1 milestone % is computed as:

```
milestone_percent = (COREs with status "done") / 6 * 100
```

It moves in discrete 17-point steps. The percentage only advances when a complete CORE item passes its acceptance gate. Individual task completions, commits, and test additions do not move it.

| COREs done | Milestone % |
|------------|-------------|
| 0 | 0% |
| 1 | 17% |
| 2 | 33% |
| 3 | 50% |
| 4 | 67% |
| 5 | 83% |
| 6 | 100% |

---

## Changed Templates (Positive Delta)

Use when milestone % increased between reporting periods.

### Template: Single CORE Accepted

```
AUTO-M1 advanced from __% to __% (_/6 -> _/6).
CORE-__ (___________) was validated with __ passing tests.
Evidence: [task IDs], [commit SHAs]. Reviewer: __________.
```

**Example:**
```
AUTO-M1 advanced from 33% to 50% (2/6 -> 3/6).
CORE-04 (lease expiry recovery) was validated with 7 passing tests.
Evidence: TASK-s9t0u1, TASK-w8x9y0; SHA c3d4e5f. Reviewer: codex.
```

### Template: Multiple COREs Accepted

```
AUTO-M1 advanced from __% to __% (_/6 -> _/6).
Two COREs accepted this period:
  - CORE-__ (___________): __ passing tests, SHA __________
  - CORE-__ (___________): __ passing tests, SHA __________
Total delta: +__ percentage points.
```

**Example:**
```
AUTO-M1 advanced from 17% to 50% (1/6 -> 3/6).
Two COREs accepted this period:
  - CORE-03 (lease schema): 8 passing tests, SHA b2c3d4e
  - CORE-05 (dispatch telemetry): 10 passing tests, SHA d4e5f6a
Total delta: +33 percentage points.
```

### Template: Final CORE (100%)

```
AUTO-M1 reached 100% (6/6 COREs done).
Final CORE accepted: CORE-__ (___________).
Full integration suite: __ passed / __ failed.
Milestone complete. All acceptance gates cleared.
```

---

## Unchanged Templates (Zero Delta)

Use when milestone % stayed flat between reporting periods.

### Template: Work in Progress, No Gate Cleared

```
AUTO-M1 remains at __% (_/6). __ tasks completed this cycle
but none advanced a CORE gate. Current work targets CORE-__
prerequisites.
```

**Example:**
```
AUTO-M1 remains at 17% (1/6). 45 tasks completed this cycle
but none advanced a CORE gate. Current work targets CORE-03
prerequisites.
```

### Template: Blocked

```
AUTO-M1 remains at __% (_/6). CORE-__ is blocked by
__________ (__ open blockers, __ high severity).
No CORE gate can advance until the blocker is resolved.
```

**Example:**
```
AUTO-M1 remains at 33% (2/6). CORE-04 is blocked by
a failing concurrent requeue test (1 open blocker, 1 high severity).
No CORE gate can advance until the blocker is resolved.
```

### Template: Acceptance Pending Review

```
AUTO-M1 remains at __% (_/6). CORE-__ has all tests passing
(__ passed / 0 failed) and is awaiting reviewer sign-off.
Expected to advance to __% once accepted.
```

**Example:**
```
AUTO-M1 remains at 50% (3/6). CORE-06 has all tests passing
(9 passed / 0 failed) and is awaiting reviewer sign-off.
Expected to advance to 67% once accepted.
```

### Template: Agent Offline

```
AUTO-M1 remains at __% (_/6). __________ is offline
(last seen __ minutes ago). __ tasks assigned to this agent
are stalled. Milestone cannot advance until agent recovers
or tasks are reassigned.
```

---

## Changed Templates (Negative Delta / Rollback)

Use when a previously accepted CORE is rolled back.

### Template: Regression Rollback

```
AUTO-M1 decreased from __% to __% (_/6 -> _/6).
CORE-__ (___________) was rolled back due to regression:
__________. The CORE reverts to in_progress status.
__ tests now failing that previously passed.
```

---

## Why % Stays Flat Despite Task Progress

Operators may see many tasks completing without milestone % moving. This is expected. Here is why:

1. **CORE gates are coarse.** Each gate represents a significant capability (identity, leases, recovery, telemetry, diagnostics). Many tasks contribute to a single gate.

2. **Tasks are prerequisites, not milestones.** Completing 50 tasks toward CORE-03 does not move milestone % until CORE-03 itself passes acceptance.

3. **Acceptance requires review.** Even when all tests pass, a CORE is not `done` until a reviewer signs off. Review latency creates flat periods.

4. **Blockers freeze gates.** A single high-severity blocker can prevent a CORE from completing even when all other work is done.

To show progress during flat periods, report task-level metrics alongside milestone %:

```
AUTO-M1 remains at 33% (2/6). However, 28 tasks completed toward
CORE-04 this cycle (4 remaining). CORE-04 acceptance expected
next period.
```
