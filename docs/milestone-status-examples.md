# Milestone Status Reporting Examples

Status reporting examples at different AUTO-M1 milestone percentages. Use these
as reference when generating or reviewing milestone updates.

## Template

```
AUTO-M1 Milestone: {pct}% ({done}/{total} core items complete)
Overall Project: {overall_pct}%

Completed: {list of completed CORE-NN items}
In Progress: {list of in-progress CORE-NN items}
Not Started: {list of not-started CORE-NN items}

Team: {agent} ({status}), ...
Queue: {assigned} assigned, {in_progress} in_progress, {done} done
Blockers: {open_count} open
```

## Core Items Reference

| Item | Title |
|------|-------|
| CORE-01 | Instance ID support |
| CORE-02 | Instance-aware status visibility |
| CORE-03 | Lease schema and TTL |
| CORE-04 | Lease recovery in manager cycle |
| CORE-05 | Dispatch telemetry |
| CORE-06 | Noop diagnostics |

---

## Example at 17% (1/6 core items)

```
AUTO-M1 Milestone: 17% (1/6 core items complete)
Overall Project: 76%

Completed: CORE-02 (Instance-aware status visibility)
In Progress: CORE-03 (Lease schema), CORE-05 (Dispatch telemetry)
Not Started: CORE-01, CORE-04, CORE-06

Team: codex (active), claude_code (active), gemini (offline)
Queue: 52 assigned, 0 in_progress, 239 done
Blockers: 10 open
```

Interpretation: One core deliverable shipped. Two items actively worked on.
Gemini is offline so frontend tasks are stalled. Blocker count is elevated --
operator should review `orchestrator_list_blockers(status=open)`.

---

## Example at 33% (2/6 core items)

```
AUTO-M1 Milestone: 33% (2/6 core items complete)
Overall Project: 79%

Completed: CORE-02 (Instance-aware status visibility),
           CORE-03 (Lease schema)
In Progress: CORE-04 (Lease recovery), CORE-05 (Dispatch telemetry)
Not Started: CORE-01, CORE-06

Team: codex (active), claude_code (active), gemini (active)
Queue: 38 assigned, 2 in_progress, 254 done
Blockers: 6 open
```

Interpretation: Two core items landed. Lease recovery depends on the lease
schema that just completed -- CORE-04 is now unblocked. All three agents
online. Blocker count trending down.

---

## Example at 50% (3/6 core items)

```
AUTO-M1 Milestone: 50% (3/6 core items complete)
Overall Project: 82%

Completed: CORE-02 (Instance-aware status visibility),
           CORE-03 (Lease schema),
           CORE-05 (Dispatch telemetry)
In Progress: CORE-04 (Lease recovery), CORE-06 (Noop diagnostics)
Not Started: CORE-01

Team: codex (active), claude_code (active), gemini (active)
Queue: 24 assigned, 2 in_progress, 268 done
Blockers: 3 open
```

Interpretation: Halfway through core items. Dispatch telemetry enables the
noop diagnostics work now in progress. CORE-01 (instance ID) is deferred.
Queue is draining normally. Blocker count low.

---

## Example at 83% (5/6 core items)

```
AUTO-M1 Milestone: 83% (5/6 core items complete)
Overall Project: 88%

Completed: CORE-01 (Instance ID support),
           CORE-02 (Instance-aware status visibility),
           CORE-03 (Lease schema),
           CORE-04 (Lease recovery),
           CORE-05 (Dispatch telemetry)
In Progress: CORE-06 (Noop diagnostics)
Not Started: (none)

Team: codex (active), claude_code (active), gemini (active)
Queue: 8 assigned, 1 in_progress, 285 done
Blockers: 1 open
```

Interpretation: One core item remaining. All agents active. Queue nearly
drained. Single blocker likely tied to the in-progress CORE-06 work. Close
to milestone completion -- operator should verify remaining acceptance
criteria.

---

## Queue Summary Line Format

```
Queue: {assigned} assigned, {in_progress} in_progress, {done} done
```

Values sourced from `orchestrator_status().queue_summary`:
- `assigned`: tasks waiting for a worker to claim
- `in_progress`: tasks actively being worked on (lease held)
- `done`: tasks that have been validated

## Team Summary Line Format

```
Team: {agent} ({status}), ...
```

Values sourced from `orchestrator_list_agents()`:
- `active`: heartbeating within threshold
- `idle`: connected but no claimed task
- `offline`: heartbeat age exceeds threshold

## Notes

- Core item percentages are always N/6 since AUTO-M1 has 6 core items.
- Overall project percentage includes all tasks (CORE, CORE-SUPPORT, OPS, QA).
- The two percentages diverge because overall includes non-core work.
- See [status-percent-interpretation.md](status-percent-interpretation.md) for
  detailed explanation of the divergence.

## References

- [milestone-communication-template.md](milestone-communication-template.md) -- Full update template
- [restart-milestone-checklist.md](restart-milestone-checklist.md) -- Acceptance gates
- [restart-milestone-burnup.md](restart-milestone-burnup.md) -- Progress tracking
- [status-percent-interpretation.md](status-percent-interpretation.md) -- % interpretation
