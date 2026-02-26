# CORE-03/04 Lease Operator Verification Checklist

Verification for AUTO-M1-CORE-03 (lease issuance on claim) and
AUTO-M1-CORE-04 (lease expiry recovery).

## Step 1: Claim a task, verify lease in response

```
orchestrator_claim_next_task(agent="claude_code")
```

- [ ] Response includes a `lease` object
- [ ] `lease.lease_id` is a non-empty string
- [ ] `lease.expires_at` is in the future (claimed_at + TTL)
- [ ] `lease.attempt_index` is 1 (first claim of this task)

### Expected lease fields

| Field | Type | Example | Check |
|-------|------|---------|-------|
| `lease_id` | string | `lease-abc123` | Non-empty, unique |
| `expires_at` | ISO 8601 | `2026-02-26T00:20:00Z` | Future timestamp |
| `attempt_index` | integer | `1` | Starts at 1 |
| `owner_instance_id` | string | `claude_code#worker-01` | Matches claiming agent |

## Step 2: Verify task record has lease metadata

```
orchestrator_list_tasks(status="in_progress")
```

- [ ] Claimed task entry includes lease metadata
- [ ] `lease_id` matches the value from Step 1
- [ ] `expires_at` matches the value from Step 1
- [ ] Task `owner` matches the claiming agent

## Step 3: Let lease expire, verify requeue

Let the lease expire without renewing or submitting a report.

```
# Wait for lease TTL to pass, then:
orchestrator_list_tasks(status="assigned")
```

- [ ] Expired task reappears in `assigned` status
- [ ] `attempt_index` is now 2 (incremented from 1)
- [ ] Task is claimable by any agent
- [ ] Previous lease is cleared from the task

## Step 4: Verify stale_task event from watchdog

```bash
cat "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)"
```

- [ ] Watchdog emitted a `stale_task` or `task.lease_expired` event
- [ ] Event includes the correct `task_id`
- [ ] Event includes `owner_instance_id` of the expired lease holder

## Step 5: Verify repeated expiry triggers blocker

Claim and let the task expire `max_retries` times (default: 3).

```
orchestrator_list_tasks(status="blocked")
orchestrator_list_blockers(status="open")
```

- [ ] After `max_retries` expirations, task moves to `blocked`
- [ ] `attempt_index` equals `max_retries`
- [ ] An auto-blocker is raised with lease expiry reason
- [ ] Task is no longer claimable

## Step 6: Submit report, verify lease released

Claim a fresh task and submit a report before lease expires.

```
orchestrator_submit_report(
  task_id="TASK-xxx", agent="claude_code",
  commit_sha="abc123", status="done",
  test_summary={"command": "pytest", "passed": 5, "failed": 0}
)
```

- [ ] Report accepted normally
- [ ] Lease is cleared from the task record
- [ ] No expiry event fires after successful report
- [ ] Task progresses to `reported` status

## Observable outputs summary

| Output | Where to check | What to look for |
|--------|---------------|-----------------|
| Task status | `orchestrator_list_tasks` | Status transitions: in_progress -> assigned (expiry) or reported (success) |
| Audit log | `orchestrator_list_audit_logs(limit=10)` | `task.claimed` with lease, `task.lease_expired`, `task.reported` |
| Watchdog JSONL | `.autopilot-logs/watchdog-*.jsonl` | `stale_task` and `task.lease_expired` entries |
| Blocker list | `orchestrator_list_blockers(status="open")` | Auto-blocker after max retries |

## References

- [lease-schema-test-plan.md](lease-schema-test-plan.md) -- Lease fields and state transitions
- [lease-operator-expectations.md](lease-operator-expectations.md) -- Pre/post lease behavior
- [restart-milestone-checklist.md](restart-milestone-checklist.md) -- Post-restart validation context
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) -- Watchdog event schema
