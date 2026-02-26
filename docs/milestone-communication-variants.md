# Milestone Communication Variants

Progress communication examples tailored for different audiences and channels.
Each variant includes both overall project % and AUTO-M1 milestone %.

---

## Variant 1: Technical (Engineering / Operator)

For operators and engineers who need field names, task IDs, test counts, and
commit references.

```
AUTO-M1 Milestone: 50% (3/6 core items)
Overall Project: 82% (268/327 tasks done)

Completed this cycle:
  CORE-05 Dispatch telemetry — TASK-f028e203 (commit 0bf6e06)
    Tests: 14 passed, 0 failed (pytest tests/test_dispatch_telemetry.py)
  CORE-03 Lease schema — TASK-ba1b2ee1 (commit 296d68a)
    Tests: 8 passed, 0 failed (pytest tests/test_lease_schema.py)

In progress:
  CORE-04 Lease recovery — TASK-3cb6bab0, owner: claude_code
    Lease: LEASE-e5f6a7b8, expires: 2026-02-26T16:20:00Z
  CORE-06 Noop diagnostics — TASK-e75fb59d, owner: claude_code

Agents:
  codex        active  last_seen=3s   task=TASK-82466844
  claude_code  active  last_seen=5s   task=TASK-3cb6bab0
  gemini       active  last_seen=12s  task=TASK-dc0af9ac

Queue: 24 assigned, 2 in_progress, 268 done
Blockers: 3 open (BLK-0cbfcffb high, BLK-44748b57 medium, BLK-1938f365 high)
Integrity: OK (no regressions, no state corruption)
```

### When to use

- Handoff between operator sessions
- Debugging task pipeline issues
- Audit trail for milestone acceptance

---

## Variant 2: Non-Technical (Stakeholder / Project Lead)

Plain language focused on capabilities delivered and projected timeline. No
task IDs or field names.

```
AUTO-M1 Restart Milestone: 50% complete
Overall Project: 82% complete

What shipped:
  - The system now records timing data for every task dispatch,
    making it possible to detect when commands are lost or delayed.
  - Task leases have time limits, so a crashed worker's tasks are
    automatically returned to the queue instead of getting stuck.

What is in progress:
  - Automatic recovery of expired leases during the manager cycle.
  - Diagnostic reporting for commands that produce no result.

Team health:
  All three agents are online and processing tasks. No capacity issues.

Blockers:
  Three items need operator decisions before work can continue.
  None are critical.

Projected timeline:
  At the current pace (2-3 core items per week), the remaining 3 items
  are expected to complete within 7-10 days.
```

### When to use

- Weekly status emails to project leads
- Milestone review meetings
- Executive summary requests

---

## Variant 3: Short (Slack / Chat)

Two to three lines maximum. Suitable for Slack channels or quick status pings.

```
AUTO-M1: 50% (3/6 core) | Overall: 82% | 3 agents online
Shipped: dispatch telemetry, lease schema. Next: lease recovery, noop diagnostics.
Blockers: 3 open (none critical)
```

### When to use

- Slack channel updates
- Quick replies to "how's it going?"
- Dashboard ticker line

---

## Additional Short Variants at Different Stages

### Early stage (17%)

```
AUTO-M1: 17% (1/6 core) | Overall: 76% | 2/3 agents online
Shipped: instance-aware status. In progress: lease schema, dispatch telemetry.
Blockers: 10 open -- operator review needed
```

### Mid stage (33%)

```
AUTO-M1: 33% (2/6 core) | Overall: 79% | 3/3 agents online
Shipped: status visibility, lease schema. Next up: lease recovery, dispatch telemetry.
Blockers: 6 open, trending down
```

### Late stage (83%)

```
AUTO-M1: 83% (5/6 core) | Overall: 88% | 3/3 agents online
One item remaining: noop diagnostics. Queue nearly drained (8 assigned).
Blockers: 1 open -- final stretch
```

### Complete (100%)

```
AUTO-M1: 100% (6/6 core) | Overall: 91%
All core items shipped and validated. Remaining work: support tasks and QA.
Blockers: 0 open
```

---

## Format Selection Guide

| Audience | Variant | Includes |
|----------|---------|----------|
| Operators / Engineers | Technical | Task IDs, commit SHAs, test counts, agent status, lease details |
| Project leads / Stakeholders | Non-technical | Capabilities delivered, plain language, timeline projections |
| Slack / Chat | Short | Percentages, one-line summary, blocker count |

## References

- [milestone-communication-template.md](milestone-communication-template.md) -- Full template
- [milestone-status-examples.md](milestone-status-examples.md) -- Percentage-based examples
- [status-percent-interpretation.md](status-percent-interpretation.md) -- Why percentages diverge
