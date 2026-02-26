# CORE Milestone Acceptance Report Template

Tracks acceptance status for CORE-02 through CORE-06 milestones.
Use one copy of this template per acceptance cycle. Each CORE item
is signed off independently; the rollup percentage reflects overall
CORE-milestone progress, not overall project progress.

## Summary

| Field | Value |
|-------|-------|
| Report date | _YYYY-MM-DD_ |
| Reviewer | _operator name_ |
| Cycle | _e.g., sprint-12, weekly-2026-02-26_ |
| Accepted | _N / 6_ |
| Milestone % | _computed below_ |

---

## Individual CORE Acceptance

### CORE-02: Instance-Aware Status

| Field | Value |
|-------|-------|
| Status | `not_started` / `in_progress` / `accepted` |
| Weight | ~17% |
| Task IDs | _e.g., TASK-abc123, TASK-def456_ |
| Commit SHAs | _e.g., a1b2c3d_ |
| Tests passed | _e.g., 12 passed, 0 failed_ |
| Log snapshot | _path or link to log evidence_ |
| Acceptance date | _YYYY-MM-DD or pending_ |
| Notes | _any caveats or conditions_ |

**Acceptance criteria:**
- [ ] `orchestrator_list_agents` returns `instance_id` for every registered agent
- [ ] `status` field reflects active/offline/stale correctly based on heartbeat age
- [ ] `verified` and `same_project` fields populate for connected agents
- [ ] `heartbeat_timeout_minutes` is configurable and respected

---

### CORE-03: Lease Schema

| Field | Value |
|-------|-------|
| Status | `not_started` / `in_progress` / `accepted` |
| Weight | ~17% |
| Task IDs | _e.g., TASK-abc123_ |
| Commit SHAs | _e.g., b2c3d4e_ |
| Tests passed | _e.g., 8 passed, 0 failed_ |
| Log snapshot | _path or link_ |
| Acceptance date | _YYYY-MM-DD or pending_ |
| Notes | |

**Acceptance criteria:**
- [ ] `orchestrator_claim_next_task` returns a lease record with `lease_id`, `owner_instance_id`, `expires_at`
- [ ] `issued_at` and `ttl_seconds` are populated on every new lease
- [ ] `attempt_index` starts at 1 and increments on re-lease
- [ ] Lease renewal updates `renewed_at` and extends `expires_at`

---

### CORE-04: Lease Expiry Recovery

| Field | Value |
|-------|-------|
| Status | `not_started` / `in_progress` / `accepted` |
| Weight | ~17% |
| Task IDs | _e.g., TASK-abc123_ |
| Commit SHAs | _e.g., c3d4e5f_ |
| Tests passed | _e.g., 6 passed, 0 failed_ |
| Log snapshot | _path or link_ |
| Acceptance date | _YYYY-MM-DD or pending_ |
| Notes | |

**Acceptance criteria:**
- [ ] Manager cycle detects expired leases (expires_at < now)
- [ ] Expired tasks requeue to `assigned` with incremented `attempt_index`
- [ ] Tasks exceeding `max_retries` move to `blocked` with a note
- [ ] Recovery runs idempotently (no double-requeue on concurrent cycles)

---

### CORE-05: Dispatch Telemetry

| Field | Value |
|-------|-------|
| Status | `not_started` / `in_progress` / `accepted` |
| Weight | ~17% |
| Task IDs | _e.g., TASK-abc123_ |
| Commit SHAs | _e.g., d4e5f6a_ |
| Tests passed | _e.g., 10 passed, 0 failed_ |
| Log snapshot | _path or link_ |
| Acceptance date | _YYYY-MM-DD or pending_ |
| Notes | |

**Acceptance criteria:**
- [ ] `dispatch.command` events include `correlation_id` and `target` (instance-aware)
- [ ] `dispatch.ack` events echo the `correlation_id` back to manager
- [ ] Audience filtering delivers events only to targeted agents
- [ ] Event bus cursor advances correctly with `auto_advance`

---

### CORE-06: Noop Diagnostics

| Field | Value |
|-------|-------|
| Status | `not_started` / `in_progress` / `accepted` |
| Weight | ~17% |
| Task IDs | _e.g., TASK-abc123_ |
| Commit SHAs | _e.g., e5f6a7b_ |
| Tests passed | _e.g., 5 passed, 0 failed_ |
| Log snapshot | _path or link_ |
| Acceptance date | _YYYY-MM-DD or pending_ |
| Notes | |

**Acceptance criteria:**
- [ ] `dispatch.noop` emitted when command times out without ack
- [ ] Noop event contains the original `correlation_id` for tracing
- [ ] Manager logs noop events with diagnostic context (target agent, timeout, task_id)
- [ ] Consecutive noops for the same agent trigger a stale-agent warning

---

## Rollup Calculation

Each CORE milestone carries approximately equal weight. The formula:

```
milestone_percent = (count_of_accepted_cores / 6) * 100
```

| Accepted count | Milestone % |
|----------------|-------------|
| 0 / 6 | 0% |
| 1 / 6 | 17% |
| 2 / 6 | 33% |
| 3 / 6 | 50% |
| 4 / 6 | 67% |
| 5 / 6 | 83% |
| 6 / 6 | 100% |

### Milestone % vs. Project %

These numbers are **not** the same:

- **Milestone %** reflects only CORE-02..06 acceptance progress.
- **Project %** (shown in `orchestrator_live_status_report`) includes all
  workstreams: backend, frontend, QA, devops, and non-CORE tasks.

Do not conflate milestone % with the `overall_percent` field in status
reports. Milestone % feeds into the CORE component of project %, but
other workstreams contribute independently.

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Reviewer | | | |
| Tech lead | | | |
| Operator | | | |
