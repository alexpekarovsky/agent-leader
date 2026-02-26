# CORE Checkpoint Status Templates

> Ready-to-fill templates for status messages at each milestone threshold.
> Use when AUTO-M1 crosses 2/6, 3/6, 4/6, or 5/6 completed COREs.

---

## Checkpoint: 2/6 (33%)

```
AUTO-M1 Checkpoint — 33% (2/6 COREs done)
Date: __________

Milestone %: 33%
Completed: CORE-__, CORE-__
In Progress: CORE-__, CORE-__
Not Started: CORE-__
Next Target: CORE-__ (__________)

Team Summary:
  Active agents: __  Offline: __
  Tasks done this period: __  Blockers resolved: __

Overall Project Context:
  Overall project %: ___%
  AUTO-M1 is __ percentage points ahead of / behind / aligned with overall.

Notes: __________
```

### 2/6 Guidance

At 33%, two independent CORE items are accepted. Typical patterns:
- CORE-02 + CORE-05 (both base-level, no cross-dependency)
- CORE-02 + CORE-03 (lease track progressing sequentially)

Key question: Are both dependency tracks (lease and dispatch) unblocked?

---

## Checkpoint: 3/6 (50%)

```
AUTO-M1 Checkpoint — 50% (3/6 COREs done)
Date: __________

Milestone %: 50%
Completed: CORE-__, CORE-__, CORE-__
In Progress: CORE-__, CORE-__
Not Started: CORE-__
Next Target: CORE-__ (__________)

Team Summary:
  Active agents: __  Offline: __
  Tasks done this period: __  Blockers resolved: __
  Throughput trend: improving / steady / declining

Overall Project Context:
  Overall project %: ___%
  AUTO-M1 is at the halfway mark. Remaining COREs: __, __, __.
  Estimated time to 100%: __________

Notes: __________
```

### 3/6 Guidance

Halfway point. At least one dependency chain should be fully complete:
- Lease track: CORE-02 + CORE-03 + CORE-04 (all done)
- Dispatch track: CORE-02 + CORE-05 + CORE-06 (all done)

If neither chain is complete, both are partially done. Check for blockers on the longer chain.

---

## Checkpoint: 4/6 (67%)

```
AUTO-M1 Checkpoint — 67% (4/6 COREs done)
Date: __________

Milestone %: 67%
Completed: CORE-__, CORE-__, CORE-__, CORE-__
In Progress: CORE-__, CORE-__
Not Started: --
Next Target: CORE-__ (__________)

Team Summary:
  Active agents: __  Offline: __
  Tasks done this period: __  Blockers resolved: __
  Throughput trend: improving / steady / declining

Overall Project Context:
  Overall project %: ___%
  Two COREs remain. Both should be in_progress at this stage.
  Critical path: CORE-__ (estimated __________)

Regression Check:
  Any regressions in accepted COREs? yes / no
  If yes: __________

Notes: __________
```

### 4/6 Guidance

Two-thirds complete. Both remaining COREs should be actively in progress. If either is `not_started`, escalate -- a dependency may be stuck.

At this stage, run cross-CORE regression checks. Earlier accepted COREs should still pass all tests after later CORE changes.

---

## Checkpoint: 5/6 (83%)

```
AUTO-M1 Checkpoint — 83% (5/6 COREs done)
Date: __________

Milestone %: 83%
Completed: CORE-__, CORE-__, CORE-__, CORE-__, CORE-__
In Progress: CORE-__
Not Started: --
Next Target: CORE-__ (__________ — final CORE)

Team Summary:
  Active agents: __  Offline: __
  Tasks done this period: __  Blockers resolved: __
  All-CORE test suite: __ passed / __ failed

Overall Project Context:
  Overall project %: ___%
  One CORE remains for 100% milestone completion.
  Blocking issues on final CORE: __________

Final CORE Status:
  CORE-__: __________
  Evidence so far: __________
  Open items: __________
  Estimated acceptance: __________

Integration Readiness:
  Cross-CORE integration tests: __ passed / __ failed
  Full regression suite: __ passed / __ failed

Notes: __________
```

### 5/6 Guidance

One CORE away from completion. Focus entirely on the remaining item. Run the full integration test suite to ensure all 5 accepted COREs still work together.

If the final CORE is blocked, this is a high-severity escalation -- the entire milestone is gated on one item.

---

## Threshold Quick Reference

| Threshold | Milestone % | Typical Pattern | Key Action |
|-----------|-------------|-----------------|------------|
| 2/6 | 33% | Two base COREs done | Verify both tracks unblocked |
| 3/6 | 50% | One full chain done | Estimate time to 100% |
| 4/6 | 67% | Both chains nearly done | Run cross-CORE regression checks |
| 5/6 | 83% | One CORE remaining | Focus and escalate if blocked |
| 6/6 | 100% | All done | Full integration sign-off |
