# Dashboard Degraded-Mode Alert Bundles

Cascading failure scenarios that the dashboard should detect and surface as a single bundled alert, rather than flooding the operator with individual signals. Each bundle includes root cause, cascade chain, source provenance, and suggested operator actions.

---

## Bundle 1: Worker Offline Cascade

**Trigger:** Agent heartbeat exceeds 2x timeout threshold.

### Cascade Chain

1. Agent `gemini` offline (17h, last_seen stale)
2. 52 tasks stuck in `assigned` status owned by `gemini`
3. No frontend progress (0 tasks claimed or reported in 17h)
4. Frontend milestone stalled at previous checkpoint

### Source Provenance

| Signal                  | Source Tool                  |
|-------------------------|-----------------------------|
| Agent offline           | `orchestrator_list_agents`   |
| Stuck tasks             | `orchestrator_list_tasks`    |
| No progress             | `orchestrator_live_status_report` |
| Milestone stall         | `orchestrator_status`        |

### Operator Next Actions

1. **Restart gemini** -- check process health, re-register if needed.
2. **Reassign tasks** -- run `orchestrator_reassign_stale_tasks` (shortcut `r`) to redistribute the 52 stuck tasks to active workers.
3. **Pause frontend workstream** -- if no other agent can cover frontend, mark the workstream as paused to avoid misleading progress percentages.

---

## Bundle 2: Blocker Spike

**Trigger:** Open blocker count exceeds 10.

### Cascade Chain

1. 10+ open blockers accumulate (unresolved manager/user decisions)
2. Task throughput drops -- blocked tasks cannot progress
3. Multiple agents idle, waiting on blocker resolution
4. Overall completion rate stalls

### Source Provenance

| Signal                  | Source Tool                     |
|-------------------------|---------------------------------|
| Open blocker count      | `orchestrator_list_blockers`    |
| Idle agents             | `orchestrator_list_agents`      |
| Throughput drop         | `orchestrator_status` (metrics) |

### Operator Next Actions

1. **Triage by severity** -- list blockers with `orchestrator_list_blockers(status=open)` (shortcut `b`), sort by severity (high/medium/low).
2. **Batch-resolve low-severity** -- answer simple questions in bulk to free agents quickly.
3. **Escalate high-severity** -- flag blockers that require user or stakeholder input and resolve them first.

---

## Bundle 3: Queue Jam

**Trigger:** High ratio of assigned tasks to in_progress tasks.

### Cascade Chain

1. 50+ tasks in `assigned` status, 0 tasks in `in_progress`
2. Workers are not calling `orchestrator_claim_next_task`
3. Possible causes: policy routing misconfiguration, agents stuck in previous task, or agents not polling
4. Pipeline stalled despite full queue

### Source Provenance

| Signal                  | Source Tool                    |
|-------------------------|--------------------------------|
| Task status counts      | `orchestrator_list_tasks`      |
| Agent activity          | `orchestrator_list_agents`     |
| Claim history           | `orchestrator_list_audit_logs` |

### Operator Next Actions

1. **Check agent heartbeats** -- run `orchestrator_list_agents` (shortcut `a`) to verify workers are alive.
2. **Verify routing policy** -- confirm workstream-to-agent mapping is correct and agents have tasks they can claim.
3. **Run manager cycle** -- execute `orchestrator_manager_cycle` (shortcut `m`) to auto-reconnect stale agents and summarize remaining work.
4. **Manual claim override** -- use `orchestrator_set_claim_override` to force a specific agent to pick up a specific task.

---

## Bundle 4: Lease Expiry Storm

**Trigger:** Multiple task leases expiring within the same time window.

### Cascade Chain

1. Several leases expire simultaneously (workers crashed or unresponsive)
2. Tasks requeue back to `assigned` and become claimable again
3. Multiple agents may claim the same requeued tasks, risking duplicate work
4. Conflicting commits or wasted compute

### Source Provenance

| Signal                  | Source Tool                     |
|-------------------------|---------------------------------|
| Lease expiry events     | `orchestrator_list_audit_logs`  |
| Task status churn       | `orchestrator_list_tasks`       |
| Agent health            | `orchestrator_list_agents`      |
| Duplicate claims        | `orchestrator_list_audit_logs`  |

### Operator Next Actions

1. **Check worker health** -- verify agents are running and responsive via heartbeat timestamps.
2. **Tune lease TTL** -- if leases expire too quickly for the workload, increase `ttl_seconds` to reduce false expirations.
3. **Investigate infrastructure** -- simultaneous expiry usually points to a shared failure (network, host, resource exhaustion).
4. **Run manager cycle** -- use `orchestrator_manager_cycle` (shortcut `m`) to recover expired leases and re-validate task state.

---

## Alert Severity Mapping

| Bundle               | Severity  | Auto-recoverable | Operator Input Required |
|-----------------------|-----------|-------------------|-------------------------|
| Worker Offline        | High      | Partial (reassign)| Yes (restart agent)     |
| Blocker Spike         | High      | No                | Yes (resolve blockers)  |
| Queue Jam             | Medium    | Partial (manager) | Yes (diagnose cause)    |
| Lease Expiry Storm    | Medium    | Partial (requeue) | Yes (tune/investigate)  |
