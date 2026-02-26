# Lease Schema Test Plan

Test plan for the task lease system defined in AUTO-M1-CORE-03 (lease schema + issuance) and AUTO-M1-CORE-04 (lease expiry recovery). This doc specifies the fields, transitions, and expected test evidence before implementation.

## Lease Fields

| Field | Type | Description | Set by |
|-------|------|-------------|--------|
| `lease_id` | string | Unique identifier for this lease | Engine on claim |
| `task_id` | string | Task this lease covers | Engine on claim |
| `owner_instance_id` | string | Instance that holds the lease (e.g., `claude_code#worker-01`) | Engine from claim context |
| `claimed_at` | ISO 8601 | When the lease was issued | Engine on claim |
| `expires_at` | ISO 8601 | When the lease expires if not renewed | Engine on claim (claimed_at + default TTL) |
| `renewed_at` | ISO 8601 | Last renewal timestamp | Engine on renew |
| `heartbeat_interval_seconds` | integer | Expected renewal frequency | Configuration (default: 120) |
| `attempt_index` | integer | How many times this task has been leased (1 = first attempt) | Engine, incremented on re-lease |

## Task State Transitions

### Normal flow (happy path)

```
assigned ──claim──► in_progress (lease issued)
                      │
                      ├──renew──► in_progress (lease renewed, expires_at updated)
                      │
                      └──report──► reported (lease released)
                                    │
                                    └──validate──► done (lease cleared)
```

### Expiry flow (worker crash/hang)

```
in_progress (lease expired)
  │
  ├─ attempt_index < max_retries
  │   └──► assigned (auto-requeue, attempt_index incremented)
  │
  └─ attempt_index >= max_retries
      └──► blocked (auto-blocker raised: "lease expired N times")
```

### Renewal flow

```
in_progress ──renew_lease(task_id)──► in_progress
  │                                     │
  │ expires_at = now + TTL              │ renewed_at = now
  │                                     │ expires_at = now + TTL
```

## Test Cases

### T1: Lease issuance on claim (AUTO-M1-CORE-03)

**Setup**: Create a task, assign to agent, call `claim_next_task`.

**Assert**:
- Returned task includes `lease` object
- `lease.lease_id` is a non-empty string
- `lease.task_id` matches the claimed task
- `lease.owner_instance_id` matches the claiming agent's instance
- `lease.claimed_at` is a valid ISO 8601 timestamp
- `lease.expires_at` is after `claimed_at` by the configured TTL
- `lease.attempt_index` is 1 (first attempt)
- Task status is `in_progress`

**Evidence**: Lease object in claim response; task record shows lease metadata.

### T2: Lease renewal extends expiry

**Setup**: Claim a task (lease issued), then call `renew_lease(task_id)`.

**Assert**:
- `renewed_at` is updated to current time
- `expires_at` is extended (new value > old value)
- Task remains `in_progress`
- `attempt_index` unchanged

**Evidence**: Updated lease object with new timestamps.

### T3: Lease expiry triggers requeue (AUTO-M1-CORE-04)

**Setup**: Claim a task, let the lease expire (mock time or use very short TTL), run expiry check.

**Assert**:
- Task transitions from `in_progress` to `assigned`
- `attempt_index` incremented to 2
- Diagnostic event `task.lease_expired` emitted with task ID and owner
- Task is claimable again by any agent

**Evidence**: Task status = `assigned`, audit log shows expiry event, bus has `task.lease_expired` event.

### T4: Repeated expiry raises blocker

**Setup**: Configure `max_retries = 2`. Claim, expire, re-claim, expire again.

**Assert**:
- After second expiry: task transitions to `blocked`
- Blocker auto-raised with message referencing repeated lease expiry
- Task is NOT claimable

**Evidence**: Task status = `blocked`, blocker exists with lease expiry reason.

### T5: Lease released on report submission

**Setup**: Claim a task, submit report with status `done`.

**Assert**:
- Lease is cleared/released from the task
- Task transitions to `reported`
- No expiry check fires after report

**Evidence**: Task record has no active lease; reported status confirmed.

### T6: Claim without instance_id uses fallback

**Setup**: Claim a task without providing `instance_id` in the agent context.

**Assert**:
- `owner_instance_id` falls back to `{agent_name}#default`
- Lease is otherwise issued normally

**Evidence**: Lease `owner_instance_id` matches fallback pattern.

### T7: Concurrent claim creates only one lease

**Setup**: Two agents call `claim_next_task` for the same task simultaneously.

**Assert**:
- Only one claim succeeds (atomic)
- Only one lease exists for the task
- Losing agent gets no lease for that task

**Evidence**: Only one lease in task record; second claim returns different task or empty.

### T8: Expiry check is idempotent

**Setup**: Run the expiry checker twice on the same expired lease.

**Assert**:
- First run transitions task and emits event
- Second run is a no-op (task already requeued)

**Evidence**: Only one `task.lease_expired` event; task remains `assigned` after second check.

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lease_ttl_seconds` | 600 | Time before lease expires without renewal |
| `heartbeat_interval_seconds` | 120 | Expected renewal frequency |
| `max_retries` | 3 | Expiry count before auto-blocking |

## Mapping to Implementation Tasks

| Test | Implemented by | Depends on |
|------|---------------|------------|
| T1, T2, T6, T7 | AUTO-M1-CORE-03 (lease schema + issuance) | AUTO-M1-CORE-01 (instance_id) |
| T3, T4, T5, T8 | AUTO-M1-CORE-04 (expiry recovery) | AUTO-M1-CORE-03 |

## References

- [roadmap.md](roadmap.md) — Phase C: Task Leases and Recovery
- [current-limitations-matrix.md](current-limitations-matrix.md) — "No task leases or expiry" limitation
- [restart-milestone-checklist.md](restart-milestone-checklist.md) — Lease recovery as post-restart validation step
