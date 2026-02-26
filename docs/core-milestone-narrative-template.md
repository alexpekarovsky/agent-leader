# CORE Milestone Progress Narrative Templates

> Two narrative variants for CORE-02..06 progress reporting.
> Engineering variant for technical audiences; Operator variant for stakeholders.

---

## Engineering Variant

```
CORE Milestone Progress — Engineering Report
Date: ___________  Reporter: ___________

AUTO-M1 Core %: ___% (_/6 done)

── Completed COREs ──────────────────────────────
[For each completed CORE, copy this block:]

CORE-__: ___________
  Accepted: __________ (date)
  Task IDs: __________
  Commit SHAs: __________
  Tests: __ passed / __ failed / __ skipped
  Code coverage delta: __% -> __%
  Reviewer: __________

── In-Progress COREs ────────────────────────────
[For each in-progress CORE, copy this block:]

CORE-__: ___________
  Task IDs (active): __________
  Branch/commits: __________
  Tests written: __ passed / __ failed
  Code coverage: __%
  Remaining work: __________
  Estimated completion: __________

── Not Started COREs ────────────────────────────
[For each not-started CORE:]

CORE-__: ___________
  Blocked by: __________
  Prerequisites remaining: __________

── Test Summary ─────────────────────────────────
Total CORE-scope tests: __ passed / __ failed / __ skipped
Regressions detected: __ (list if any: __________)
Integration tests: __ passed / __ failed

── Notes ────────────────────────────────────────
__________
```

### Engineering Fill-In Guide

| Field | Source | Example |
|-------|--------|---------|
| AUTO-M1 Core % | `(done_count / 6) * 100` | 50% (3/6 done) |
| Task IDs | `orchestrator_list_tasks(status="done")` | TASK-a1b2c3, TASK-d4e5f6 |
| Commit SHAs | `git log --oneline` for CORE scope | a1b2c3d, b2c3d4e |
| Tests passed/failed | Test runner output for CORE tests | 24 passed / 0 failed |
| Code coverage delta | Coverage tool diff pre/post CORE | 78% -> 83% |

---

## Operator Variant

```
CORE Milestone Progress — Operator Summary
Date: ___________  Prepared by: ___________

AUTO-M1 Core %: ___% (_/6 done)

── Capabilities Delivered ───────────────────────
[For each completed CORE:]

CORE-__: ___________
  What it enables: __________
  Accepted on: __________
  Confidence: high / medium / low

── Capabilities In Progress ─────────────────────
[For each in-progress CORE:]

CORE-__: ___________
  Current state: __________
  Expected delivery: __________
  Risk level: low / medium / high
  Risk detail: __________

── Capabilities Not Started ─────────────────────
[For each not-started CORE:]

CORE-__: ___________
  Waiting on: __________
  Impact if delayed: __________

── Team Health ──────────────────────────────────
Active agents: __________
Offline agents: __________
Throughput trend: improving / steady / declining
Morale/blockers note: __________

── Blockers Resolved This Period ────────────────
Total resolved: __
Notable: __________

── Blockers Open ────────────────────────────────
Total open: __ (__ high severity)
Top blocker: __________
Escalation needed: yes / no

── Overall Context ──────────────────────────────
AUTO-M1 Core %: ___%  (milestone track)
Overall project %: ___%  (all workstreams)
Next CORE target: CORE-__ (__________)

── Notes ────────────────────────────────────────
__________
```

### Operator Fill-In Guide

| Field | Source | Example |
|-------|--------|---------|
| AUTO-M1 Core % | `(done_count / 6) * 100` | 33% (2/6 done) |
| What it enables | CORE description from glossary | Agents now have unique identities |
| Confidence | Reviewer assessment post-acceptance | high |
| Throughput trend | Compare tasks/hour across last 3 periods | steady |
| Blockers open | `orchestrator_list_blockers(status="open")` | 3 open (1 high) |

---

## CORE Capability Quick Reference

Use these descriptions in the Operator variant:

| CORE | Title | Capability Delivered |
|------|-------|---------------------|
| CORE-02 | Instance-Aware Status | Each agent has a unique verified identity; manager sees who is active, stale, or offline. |
| CORE-03 | Lease Schema | Tasks have time-bounded ownership; no two agents work the same task simultaneously. |
| CORE-04 | Lease Expiry Recovery | Expired leases are automatically detected and tasks requeued for pickup by healthy agents. |
| CORE-05 | Dispatch Telemetry | Manager dispatches are traceable end-to-end with correlation IDs and ack/timeout tracking. |
| CORE-06 | Noop Diagnostics | Unresponsive dispatches generate diagnostic events for root-cause analysis. |
