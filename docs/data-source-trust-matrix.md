# Data Source Trust Matrix

> Ranks every data source by authority scope, freshness, and reliability.
> Use this matrix to decide which source to trust when two sources
> disagree about the same entity.

## Trust Matrix

| Source | Authority For | Freshness | Reliability | Conflict Resolution |
|--------|--------------|-----------|-------------|---------------------|
| **`orchestrator_status`** | Point-in-time task/agent counts, completion percentage, phase breakdown, integrity checks | Real-time (computed on each call from state files) | High -- reads directly from `tasks.json` and `agents.json` | Authoritative for aggregate counts. If a computed field (e.g., completion %) disagrees with a manual count of `list_tasks`, recompute from `list_tasks`. |
| **`orchestrator_list_tasks`** | Per-task detail: id, title, status, owner, timestamps (created, claimed, reported, validated), lease fields | Real-time (direct read from `tasks.json`) | High -- single source of truth for individual task state | Authoritative for per-task status. Always trust over summary counts if they disagree. |
| **`orchestrator_list_agents`** | Agent presence: name, instance_id, status, last_seen, task_counts, verified flag | Real-time (direct read from `agents.json`) | High -- single source of truth for agent registration | Authoritative for agent online/offline determination. Trust over watchdog inferences about agent health. |
| **Audit logs** (`list_audit_logs`, `bus/audit.jsonl`) | Historical tool calls: what was called, when, with what args, and the result (ok/error) | Retroactive (append-only, up to ~400 queryable entries) | High -- append-only log, immutable once written | Authoritative for "what happened." If status shows a state that audit says was never reached, suspect a race condition or state file issue. |
| **Watchdog JSONL** (`.autopilot-logs/watchdog-*.jsonl`) | Staleness detection (`stale_task`) and state integrity (`state_corruption_detected`) | Interval-based (default 15s cycle) | Medium -- can miss events between intervals; age heuristics may produce false positives when leases are valid | Advisory, not authoritative. Always cross-check against `list_tasks` lease fields and `list_agents` heartbeat before acting on a watchdog alert. |
| **Event bus** (`bus/events.jsonl`) | Event sequence: dispatch events, lease recovery, manager sync, noop diagnostics, correlation chains | Real-time append (events written as they occur) | High -- append-only, ordered by sequence ID | Authoritative for event ordering and correlation. Use `correlation_id` to thread related events. If event bus shows a dispatch but audit has no matching claim, the claim may have failed silently. |
| **Synthetic / Computed** (dashboard-derived values) | Aggregations: avg blocker age, completion rate, agent utilization, alert severity rankings | Depends on input source freshness | Medium -- only as reliable as its inputs; computation logic may have bugs | Never authoritative. Always trace back to the underlying source when a synthetic value looks wrong. |

## Conflict Resolution: Discrepancy Examples

### 1. Status count disagrees with list_tasks

**Scenario:** `orchestrator_status` reports `in_progress: 5` but
`orchestrator_list_tasks(status=in_progress)` returns 4 tasks.

**Resolution:** Trust `list_tasks`. The status endpoint computes counts from
the same state file, but a race condition during a concurrent write (e.g.,
manager cycle validating a task mid-query) can cause a momentary mismatch.
Re-query after 5 seconds; if still mismatched, inspect `tasks.json` directly.

### 2. Watchdog flags stale task, but lease is valid

**Scenario:** Watchdog JSONL contains `stale_task` for TASK-xxx
(`age_seconds: 1024`), but `list_tasks` shows the task with
`lease.expires_at` in the future and `lease.renewed_at` within the last 60s.

**Resolution:** Trust the lease. Watchdog uses `updated_at` age, which does
not account for lease renewals. The agent is actively renewing its lease,
meaning it is alive and working. No action needed. See
[status-discrepancy-scenarios.md](status-discrepancy-scenarios.md) Scenario 1.

### 3. Audit shows report submitted, status still says in_progress

**Scenario:** Audit log has `orchestrator_submit_report` with `status: ok`
for TASK-xxx, but `list_tasks` still shows the task as `in_progress`.

**Resolution:** Check timing. The task lifecycle is
`in_progress -> reported -> done`. If queried between the report submission
and the next manager cycle validation, the task may still appear as
`in_progress`. Wait 30 seconds and re-query. If still stuck, check the
manager cycle audit entry for a rejection (failed tests, owner mismatch).
See [status-discrepancy-scenarios.md](status-discrepancy-scenarios.md)
Scenario 3.

### 4. Agent shows active in list_agents, but watchdog sees no recent logs

**Scenario:** `list_agents` reports `claude_code` as active
(`last_seen: 8s ago`), but no new worker log files exist in
`.autopilot-logs/` for 30+ minutes.

**Resolution:** Check the task queue. If no tasks are assigned to the agent,
idle is expected -- the agent is heartbeating but has nothing to work on.
If tasks are assigned, check `claim_next_task` audit entries. A "No claimable
task" response confirms the queue is empty for that agent. If assigned tasks
exist and no claims are happening, restart the worker loop.

### 5. Event bus shows dispatch noop, audit shows successful claim

**Scenario:** `bus/events.jsonl` contains a `dispatch.noop` for agent X /
task Y, but audit log shows a successful `claim_next_task` by agent X for
task Y shortly after.

**Resolution:** The noop was emitted for a previous claim override that
expired. The agent later claimed the task through the normal claim flow.
Compare timestamps: the noop should predate the claim. Compare
`correlation_id` values: they should differ. No action needed if the task is
now `in_progress` with the correct owner. See
[status-discrepancy-scenarios.md](status-discrepancy-scenarios.md) Scenario 7.

### 6. Status shows 0 open blockers, but blocked tasks exist

**Scenario:** `orchestrator_status` reports `blocker_count: 0`, but
`list_tasks` returns tasks with `status: blocked`.

**Resolution:** This is a state inconsistency. Blockers were resolved
(removed from `blockers.json`), but the corresponding tasks were not moved
from `blocked` back to `assigned`. Inspect `state/blockers.json` for each
blocked task's `task_id` -- if no matching open blocker exists, the task is
orphaned. Manager should call `update_task_status(task_id, "assigned")`
to unblock. See
[status-discrepancy-scenarios.md](status-discrepancy-scenarios.md) Scenario 4.

### 7. Two sources report different agent instance counts

**Scenario:** `orchestrator_status` `.active_agents` shows 2 agents, but
`orchestrator_list_agents(active_only=true)` returns 3 entries.

**Resolution:** Trust `list_agents`. The status endpoint may apply a
different staleness threshold or deduplication rule than `list_agents`.
Check each agent's `last_seen` timestamp against the configured
`heartbeat_timeout_minutes`. An agent right at the threshold boundary can
appear in one view but not the other depending on query timing.

## Resolution Priority Order

When investigating any discrepancy, query sources in this order:

1. **`orchestrator_list_tasks`** -- ground truth for per-task state
2. **`orchestrator_list_agents`** -- ground truth for agent presence
3. **`orchestrator_status`** -- aggregated view (useful but derived)
4. **Audit logs** -- causal chain of what actions were taken
5. **Event bus** -- fine-grained event sequence with correlation IDs
6. **Watchdog JSONL** -- periodic diagnostic snapshots (advisory)
7. **Synthetic / computed** -- never trust without verifying inputs

## Quick Reference: When to Trust What

| Question | Trust This Source | Not This One |
|----------|-----------------|--------------|
| "What status is task X?" | `list_tasks` | `status` counts |
| "Is agent Y online?" | `list_agents` | Watchdog log absence |
| "Did action Z happen?" | Audit log | Status snapshot |
| "What order did events occur?" | Event bus | Watchdog timestamps |
| "Is task X genuinely stale?" | `list_tasks` lease fields | Watchdog `age_seconds` alone |
| "How many tasks are done?" | `list_tasks` (count yourself) | `status` `.task_status_counts` if mismatch suspected |

## References

- [status-discrepancy-scenarios.md](status-discrepancy-scenarios.md) --
  detailed walkthroughs of 7 discrepancy scenarios
- [dashboard-provenance-labels.md](dashboard-provenance-labels.md) --
  provenance labels shown on dashboard panels
- [operator-alert-taxonomy.md](operator-alert-taxonomy.md) -- alert
  classification with source mapping
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) -- watchdog event
  kinds and parsing guidance
