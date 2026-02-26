# CORE Milestone % Progress Board Template

> Compact operator template for tracking AUTO-M1 core milestone rows (CORE-02
> through CORE-06) with evidence links, blocker tracking, and computed milestone
> percentage. Designed for copy-paste into status reports.

---

## Compact Board (Copy-Paste Ready)

```
AUTO-M1 CORE Milestone: {milestone}% ({done_count}/6 done)
Overall Project:        {overall}%  ({done_tasks}/{total_tasks} tasks)

ID      Title                   Status       Evidence              Blockers
──────  ──────────────────────  ───────────  ────────────────────  ────────
CORE-02 Instance-Aware Status   {status_02}  {evidence_02}         —
CORE-03 Lease Schema            {status_03}  {evidence_03}         {blk_03}
CORE-04 Lease Expiry Recovery   {status_04}  {evidence_04}         {blk_04}
CORE-05 Dispatch Telemetry      {status_05}  {evidence_05}         {blk_05}
CORE-06 Noop Diagnostics        {status_06}  {evidence_06}         {blk_06}

Tracks: Lease (02→03→04)  Dispatch (02→05→06)
```

---

## Status Values

| Status | Indicator | Meaning |
|---|---|---|
| `DONE` | Accepted with evidence | All acceptance criteria met, reviewer signed off |
| `IN_PROG` | Work underway | Evidence accumulating; check for stale progress |
| `BLOCKED` | Upstream dependency unmet | Cannot start until listed blocker is DONE |
| `NOT_STD` | Not yet started | No work begun; may be waiting on blocker |

---

## Evidence Format

Each evidence cell uses a compact format linking to verifiable artifacts:

```
{task_count}T {commit_count}C {passed}p/{failed}f
```

| Token | Meaning | Example |
|---|---|---|
| `NT` | N tasks completed for this milestone | `4T` = 4 tasks done |
| `NC` | N commits | `3C` = 3 commits |
| `Np/Mf` | N tests passed, M failed | `23p/0f` = all green |

**Full evidence (for drill-down):**
```
CORE-03: 4T 3C 23p/0f
  Tasks: TASK-abc123, TASK-def456, TASK-ghi789, TASK-jkl012
  SHAs:  16d34b0, c005ce3, f6125ea
  Tests: test_lease_issuance_schema_fixture (23p/0f)
```

---

## Blocker Tracking

### Dependency Map

```
CORE-02 ─── (foundation, no blockers)
  ├── CORE-03 ← blocked by CORE-02
  │     └── CORE-04 ← blocked by CORE-03
  └── CORE-05 ← blocked by CORE-02
        └── CORE-06 ← blocked by CORE-05
```

### Blocker Column Rules

| Blocker Value | Meaning | Action |
|---|---|---|
| `—` | No blockers | Row can proceed |
| `CORE-02` | Blocked on CORE-02 | Wait for CORE-02 DONE, then clear |
| `CORE-03` | Blocked on CORE-03 | Wait for CORE-03 DONE, then clear |
| `BLK-xxx` | External blocker | See `list_blockers()` for details |

When a blocking row reaches DONE, clear its ID from all downstream blocker cells.

---

## Computed Milestone %

```
milestone_percent = (rows with status DONE) / 6 × 100
```

| Done | % | Board State |
|---|---|---|
| 0/6 | 0% | All not started |
| 1/6 | 17% | Foundation only (CORE-02) |
| 2/6 | 33% | Foundation + one track started |
| 3/6 | 50% | Halfway — both tracks advancing |
| 4/6 | 67% | Both tracks nearly complete |
| 5/6 | 83% | One row remaining |
| 6/6 | 100% | AUTO-M1 core milestone complete |

### Milestone % vs Overall Project %

| Metric | Scope | Source |
|---|---|---|
| **Milestone %** | CORE-02..06 only (6 items) | Board count above |
| **Phase 1 %** | All Phase 1 tasks (CORE + support + docs) | `live_status.phase_1_percent` |
| **Overall %** | All tasks across all phases | `live_status.overall_project_percent` |

Milestone % can be 100% while overall % is lower — this is expected when
frontend, QA, or later phases have remaining work.

---

## Filled Example: 5/6 Done (83%)

```
AUTO-M1 CORE Milestone: 83% (5/6 done)
Overall Project:        76%  (239/313 tasks)

ID      Title                   Status       Evidence              Blockers
──────  ──────────────────────  ───────────  ────────────────────  ────────
CORE-02 Instance-Aware Status   DONE         6T 4C 21p/0f         —
CORE-03 Lease Schema            DONE         5T 3C 39p/0f         —
CORE-04 Lease Expiry Recovery   DONE         4T 3C 30p/0f         —
CORE-05 Dispatch Telemetry      DONE         5T 3C 57p/0f         —
CORE-06 Noop Diagnostics        IN_PROG      2T 1C 25p/0f         —

Tracks: Lease (02→03→04) ✓✓✓  Dispatch (02→05→06) ✓✓◻
```

**Board notes:**
- Lease track complete (CORE-02 → 03 → 04 all DONE)
- Dispatch track: CORE-06 in progress, noop emission verified, consecutive-noop
  warning pending test
- All upstream blockers resolved — no entries in Blockers column

### Evidence Drill-Down (for the filled example)

```
CORE-02: 6T 4C 21p/0f
  Tasks: TASK-034874fd, TASK-8f31f055, (+4)
  SHAs:  9856c34, 9110aec, (+2)
  Tests: test_agent_instances_field_snapshots (21p/0f)

CORE-03: 5T 3C 39p/0f
  Tasks: TASK-3decb920, TASK-be0833cd, (+3)
  SHAs:  c005ce3, 16d34b0, (+1)
  Tests: test_lease_renewal_identity_binding (16p/0f)
         test_lease_issuance_schema_fixture (23p/0f)

CORE-04: 4T 3C 30p/0f
  Tasks: TASK-09fafecf, TASK-83ec323d, (+2)
  SHAs:  1f71e0c, f6125ea, (+1)
  Tests: test_lease_recovery_event_audit_correlation (18p/0f)
         test_lease_recovery_scenarios_matrix (12p/0f)

CORE-05: 5T 3C 57p/0f
  Tasks: TASK-402be034, TASK-5e8abf05, (+3)
  SHAs:  1008b3c, cd5761b, (+1)
  Tests: test_telemetry_fixture_pack (35p/0f)
         test_dispatch_command_payload_fixtures (22p/0f)

CORE-06: 2T 1C 25p/0f (in progress)
  Tasks: TASK-f857dac9, (+1)
  SHAs:  f8db7c9
  Tests: test_dispatch_noop_schema (25p/0f)
```

---

## Updating the Board

1. **Start work:** Change status to `IN_PROG`. Verify all blocker IDs are `DONE`.
2. **Add evidence:** Update evidence cell as tasks complete: `{N}T {N}C {N}p/{N}f`.
3. **Complete milestone:** Change status to `DONE`. Remove this CORE-XX from all
   downstream blocker cells. Recalculate milestone %.
4. **Report:** Include milestone % alongside overall % in every status update
   (see `docs/percent-reporting-template.md`).

---

## Related Docs

- **Progress board (full):** `docs/core-milestone-progress-board.md` — detailed board with column definitions
- **Percent reporting:** `docs/percent-reporting-template.md` — status update templates
- **Acceptance template:** `docs/core-milestone-acceptance-template.md` — formal sign-off
- **Dependency map:** `docs/core-milestone-dependency-map.md` — critical path analysis
- **Burnup tracker:** `docs/restart-milestone-burnup.md` — task-level tracking
