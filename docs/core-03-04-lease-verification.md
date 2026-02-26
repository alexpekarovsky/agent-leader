# CORE-03/04 Lease Operator Observability Checklist

Validation checklist for observing lease issuance (CORE-03) and expiry
recovery (CORE-04) behavior from status, audit, and log outputs.

## CORE-03: Lease issuance on claim

### Success path

After a worker calls `claim_next_task`:

```
orchestrator_list_tasks(status="in_progress")
```

- [ ] Claimed task includes `lease` object in response
- [ ] `lease.lease_id` is a non-empty string
- [ ] `lease.expires_at` is in the future (claimed_at + TTL)
- [ ] `lease.attempt_index` is 1 (first claim)
- [ ] `lease.owner_instance_id` matches the claiming agent's instance

### Audit trail

```
orchestrator_list_audit_logs(limit=5)
```

- [ ] Audit shows `task.claimed` event with lease metadata
- [ ] Lease fields visible in audit payload

### Lease renewal

After worker heartbeat/renewal:

- [ ] `lease.renewed_at` updated to current time
- [ ] `lease.expires_at` extended
- [ ] Task remains `in_progress`

## CORE-04: Lease expiry and recovery

### Expiry detection

When a lease expires without renewal:

```
# Check watchdog output
ls -lt .autopilot-logs/watchdog-*.jsonl | head -1
# Look for lease_expired events
```

- [ ] Watchdog or manager emits `task.lease_expired` event
- [ ] Event includes `task_id` and `owner_instance_id`
- [ ] Task transitions from `in_progress` to `assigned`

### Auto-requeue

```
orchestrator_list_tasks(status="assigned")
```

- [ ] Expired task reappears in assigned queue
- [ ] `attempt_index` incremented (2 = second attempt)
- [ ] Task is claimable by any agent

### Repeated expiry → blocker

After `max_retries` expirations:

```
orchestrator_list_tasks(status="blocked")
orchestrator_list_blockers(status="open")
```

- [ ] Task transitions to `blocked` after max retries
- [ ] Auto-blocker raised with lease expiry reason
- [ ] Task is no longer claimable

### Recovery after report

After worker submits report:

```
orchestrator_list_tasks(status="reported")
```

- [ ] Lease is cleared/released from the task
- [ ] No expiry check fires after successful report
- [ ] Task progresses to validation normally

## Failure scenarios

| Scenario | Observable output | Expected behavior |
|----------|------------------|-------------------|
| Worker crash mid-task | Lease expires, task requeues | `assigned` with incremented attempt |
| Worker hangs past TTL | Same as crash | Same as crash |
| Network disconnect | Renewal fails, lease expires | Task requeues after expiry |
| Worker completes before expiry | Report clears lease | Normal flow |
| Concurrent claim race | Only one lease created | Atomic claim guarantee |

## Configuration to verify

```
orchestrator_status()
```

- [ ] `lease_ttl_seconds` visible in config (default: 600)
- [ ] `max_retries` visible (default: 3)

## References

- [lease-schema-test-plan.md](lease-schema-test-plan.md) — Test cases T1-T8
- [lease-operator-expectations.md](lease-operator-expectations.md) — Pre/post lease behavior
- [roadmap.md](roadmap.md) — Phase C task leases
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) — Event schema
