# Lease Milestone — Operator Expectations

What changes once task leases (AUTO-M1-CORE-03/04) land, what to
expect before they ship, and how to handle the gap.

## Current behavior (pre-lease)

Tasks claimed by a worker stay `in_progress` indefinitely.  If the
worker dies or disconnects, the task remains stuck until the operator
or manager intervenes.

### Symptoms you may see today

| Symptom | Cause | Manual fix |
|---------|-------|------------|
| Task stuck in `in_progress` for hours | Worker crashed or timed out | `reassign_stale_tasks` or manual status update |
| Watchdog emits `stale_task` events | Task age exceeds `--inprogress-timeout` | Manager reads watchdog logs and reassigns |
| Worker claims task but produces no output | CLI initialization failure | Check supervisor status, restart the worker |
| Multiple workers idle while tasks are stuck | No automatic requeue | Manually block and reassign stuck tasks |

### How to recover today

1. Run `orchestrator_list_tasks(status="in_progress")` to find stuck tasks
2. Check if the owning worker is alive (`supervisor.sh status`)
3. If the worker is dead, reassign: `orchestrator_update_task_status(task_id, status="assigned", source="codex")`
4. Or let the manager cycle handle it: `orchestrator_reassign_stale_tasks()`

## Post-lease behavior (after AUTO-M1-CORE-03/04)

Each `claim_next_task` will attach a lease with an expiry timestamp.
When the lease expires without renewal, the task automatically
requeues.

### What improves

| Before leases | After leases |
|---------------|-------------|
| Stuck tasks require manual detection | Expired leases trigger automatic requeue |
| Watchdog timeout is advisory only | Lease expiry is enforced by the engine |
| Worker crash leaves orphaned tasks | Lease expires and task returns to queue |
| Manager must manually reassign | Engine requeues on expiry, manager just validates |
| Stale threshold is a guess | Lease duration is explicit per-claim |

### New operator actions

- **Lease duration tuning:** Configure default lease length per
  workstream (short for docs tasks, longer for complex backend work)
- **Lease renewal monitoring:** Workers renew leases via heartbeat;
  watch for renewal failures
- **Expired lease diagnostics:** New watchdog event type
  `lease_expired` with task and owner details

### What stays the same

- Supervisor start/stop/status commands unchanged
- Watchdog continues to emit `stale_task` events (now backed by
  lease data)
- Manager validation flow unchanged
- Report submission unchanged

## Timeline

| Phase | Feature | Status |
|-------|---------|--------|
| Current | Timeout-based stale detection | Shipped |
| AUTO-M1-CORE-03 | Task lease schema and claim integration | Planned |
| AUTO-M1-CORE-04 | Automatic lease expiry and requeue | Planned |
| Future | Per-workstream lease policies | Planned |

## References

- [roadmap.md](roadmap.md) — Phase C task leases
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — Current gaps
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) — Stale task events
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Manual recovery steps
