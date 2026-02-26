# CORE Milestone Status Cards

> Reusable text cards for each CORE task and the aggregate milestone.
> Copy, fill in, paste into status updates or dashboards.

---

## Per-CORE Cards

```
CORE-02: Instance-Aware Status
Status: [not_started|in_progress|done]  Weight: 17%
Evidence: [task IDs, commit SHAs, test counts]
Blockers: [count]  Next Action: [description]
```

```
CORE-03: Lease Schema
Status: [not_started|in_progress|done]  Weight: 17%
Evidence: [task IDs, commit SHAs, test counts]
Blockers: [count]  Next Action: [description]
Depends on: CORE-02
```

```
CORE-04: Lease Expiry Recovery
Status: [not_started|in_progress|done]  Weight: 17%
Evidence: [task IDs, commit SHAs, test counts]
Blockers: [count]  Next Action: [description]
Depends on: CORE-03
```

```
CORE-05: Dispatch Telemetry
Status: [not_started|in_progress|done]  Weight: 17%
Evidence: [task IDs, commit SHAs, test counts]
Blockers: [count]  Next Action: [description]
Depends on: CORE-02
```

```
CORE-06: Noop Diagnostics
Status: [not_started|in_progress|done]  Weight: 17%
Evidence: [task IDs, commit SHAs, test counts]
Blockers: [count]  Next Action: [description]
Depends on: CORE-05
```

---

## Aggregate Card

```
AUTO-M1 CORE Milestone (Aggregate)
Done: [n]/6  Milestone %: [0|17|33|50|67|83|100]%
In Progress: [list CORE IDs]
Not Started: [list CORE IDs]
Open Blockers: [count] ([high-severity count] high)
Overall Project %: [n]%
Next Gate Target: CORE-[XX] ([title])
```

---

## Filled Examples

### Early Stage (1/6 done)

```
CORE-02: Instance-Aware Status
Status: done  Weight: 17%
Evidence: TASK-a1b2c3, TASK-d4e5f6; SHA a1b2c3d; 12p/0f
Blockers: 0  Next Action: --
```

```
CORE-03: Lease Schema
Status: in_progress  Weight: 17%
Evidence: TASK-g7h8i9; SHA b2c3d4e; 5p/0f (partial)
Blockers: 0  Next Action: Complete renewal test coverage
Depends on: CORE-02 (done)
```

```
CORE-04: Lease Expiry Recovery
Status: not_started  Weight: 17%
Evidence: --
Blockers: 1  Next Action: Wait for CORE-03 completion
Depends on: CORE-03 (in_progress)
```

```
CORE-05: Dispatch Telemetry
Status: in_progress  Weight: 17%
Evidence: TASK-j0k1l2; SHA c3d4e5f; 6p/1f
Blockers: 0  Next Action: Fix audience filtering edge case
Depends on: CORE-02 (done)
```

```
CORE-06: Noop Diagnostics
Status: not_started  Weight: 17%
Evidence: --
Blockers: 1  Next Action: Wait for CORE-05 completion
Depends on: CORE-05 (in_progress)
```

```
AUTO-M1 CORE Milestone (Aggregate)
Done: 1/6  Milestone %: 17%
In Progress: CORE-03, CORE-05
Not Started: CORE-04, CORE-06
Open Blockers: 2 (0 high)
Overall Project %: 45%
Next Gate Target: CORE-03 (Lease Schema)
```

### Late Stage (4/6 done)

```
CORE-02: Instance-Aware Status
Status: done  Weight: 17%
Evidence: TASK-a1b2c3, TASK-d4e5f6; SHA a1b2c3d; 12p/0f
Blockers: 0  Next Action: --
```

```
CORE-03: Lease Schema
Status: done  Weight: 17%
Evidence: TASK-g7h8i9, TASK-p6q7r8; SHA b2c3d4e; 8p/0f
Blockers: 0  Next Action: --
Depends on: CORE-02 (done)
```

```
CORE-04: Lease Expiry Recovery
Status: in_progress  Weight: 17%
Evidence: TASK-s9t0u1; SHA c3d4e5f; 4p/1f
Blockers: 0  Next Action: Fix concurrent requeue test
Depends on: CORE-03 (done)
```

```
CORE-05: Dispatch Telemetry
Status: done  Weight: 17%
Evidence: TASK-j0k1l2, TASK-m3n4o5; SHA d4e5f6a; 10p/0f
Blockers: 0  Next Action: --
Depends on: CORE-02 (done)
```

```
CORE-06: Noop Diagnostics
Status: done  Weight: 17%
Evidence: TASK-v2w3x4, TASK-y5z6a7; SHA e5f6a7b; 9p/0f
Blockers: 0  Next Action: --
Depends on: CORE-05 (done)
```

```
AUTO-M1 CORE Milestone (Aggregate)
Done: 4/6  Milestone %: 67%
In Progress: CORE-04
Not Started: --
Open Blockers: 0 (0 high)
Overall Project %: 76%
Next Gate Target: CORE-04 (Lease Expiry Recovery)
```

---

## Card Field Reference

| Field | Format | Example |
|-------|--------|---------|
| Status | `not_started`, `in_progress`, `done` | `done` |
| Weight | Always `17%` (each CORE is 1/6) | `17%` |
| Evidence | `TASK-xxx; SHA yyy; Np/Mf` | `TASK-a1b2c3; SHA a1b2c3d; 12p/0f` |
| Blockers | Integer count of open blockers | `0` |
| Next Action | Short verb phrase or `--` if done | `Fix renewal edge case` |
| Depends on | Upstream CORE ID + its status | `CORE-03 (done)` |
| Milestone % | `(done/6)*100`, whole numbers only | `67%` |
