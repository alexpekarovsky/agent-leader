# Operator Alert Taxonomy

> Classification of alerts derived from watchdog, status, and dispatch
> diagnostics. Each alert type includes source, severity, trigger
> condition, and suggested operator action.

## Alert Categories

### Category 1: Timeout Alerts

| Alert | Source | Severity | Trigger | Action |
|-------|--------|----------|---------|--------|
| **CLI Timeout** | Worker/manager logs | High | `[AUTOPILOT] CLI timeout after Ns` in log output | Check agent process health; review task complexity; consider increasing `--cli-timeout` |
| **Heartbeat Timeout** | `orchestrator_list_agents` | Medium | `age_seconds > heartbeat_timeout_minutes * 60` | Verify agent process is running; check network connectivity; reconnect agent |
| **Lease Expiry** | `recover_expired_task_leases` event | High | `lease.expires_at < now` for in_progress task | Task will auto-requeue; check if worker crashed; review lease TTL settings |
| **Stale In-Progress** | `orchestrator_status` | Medium | Task in `in_progress` > 30 minutes without update | Check assigned agent; verify lease is valid; consider raising blocker |
| **Stale Reported** | `orchestrator_status` | Low | Task in `reported` > 10 minutes without validation | Manager cycle may need to run; check for validation errors |

### Category 2: No-Op / Dispatch Alerts

| Alert | Source | Severity | Trigger | Action |
|-------|--------|----------|---------|--------|
| **No Claimable Task** | `claim_next_task` returns null | Low | Agent polling but no tasks assigned to it | Normal if queue is empty; check task routing policy if unexpected |
| **Dispatch No-Op (Future)** | Dispatch telemetry events | Medium | Command sent but no ACK within timeout | Verify target agent is online; check audience targeting; review dispatch policy |
| **Manager Cycle No-Op** | `manager_cycle` result | Low | `pending_total=0` or no reports to process | Normal when queue is empty; check if tasks need creation |
| **Claim Override Ignored** | `claim_next_task` override path | Medium | Override set but target task not in `assigned` status | Task may have been claimed or moved; clear stale override |

### Category 3: Stale Instance Alerts

| Alert | Source | Severity | Trigger | Action |
|-------|--------|----------|---------|--------|
| **Agent Offline** | `orchestrator_list_agents` | High | `status=offline`, `age_seconds` exceeds threshold | Restart agent process; check infrastructure; reconnect via `connect_to_leader` |
| **Instance Stale** | `agent_instances` record | Medium | Instance `last_seen` beyond `heartbeat_timeout_minutes` | Agent may have restarted with new session; old instance is obsolete |
| **Lease Owner Stale** | Lease recovery events | High | Lease owner's instance is no longer the active instance | Lease will expire and task will requeue; new instance can re-claim |
| **Watchdog Stale Task** | Watchdog JSONL `kind=stale_task` | High | Task age exceeds configured timeout (assigned: 180s, in_progress: 900s, reported: 180s) | Review task owner; raise blocker if stuck; consider reassignment |

### Category 4: Queue / State Alerts

| Alert | Source | Severity | Trigger | Action |
|-------|--------|----------|---------|--------|
| **Task Count Regression** | `orchestrator_status.integrity` | Critical | Total task count decreased (possible data loss) | Investigate state file; check for concurrent writes; restore from backup |
| **State Corruption** | Watchdog JSONL `kind=state_corruption_detected` | Critical | bugs.json or blockers.json has wrong type (dict vs list) | Fix state file manually; check for race conditions |
| **Open Blocker** | `orchestrator_list_blockers(status=open)` | Medium-High | Blocker raised and unresolved | Review blocker question; make decision; resolve via `resolve_blocker` |
| **Open Bug** | `orchestrator_list_bugs(status=bug_open)` | High | Validation failure created a bug report | Review failed task; fix the issue; close bug when resolved |
| **Report Retry Queue** | `manager_cycle.report_retry_queue` | Medium | Reports queued but failing to submit | Check error messages; task may not exist or owner mismatch |

## Severity Scale

| Level | Meaning | Response Time |
|-------|---------|---------------|
| **Critical** | Data integrity at risk; immediate intervention needed | Immediate |
| **High** | Task progress blocked; agent down; lease expired | Within 5 minutes |
| **Medium** | Degraded performance; stale instances; pending decisions | Within 30 minutes |
| **Low** | Informational; expected transient state; no action needed | Monitor only |

## Source-to-Alert Mapping

| Source | Alert Types | Query Method |
|--------|------------|--------------|
| `orchestrator_status` | Stale in_progress/reported, task count regression, integrity warnings | Call `orchestrator_status` |
| `orchestrator_list_agents` | Agent offline, heartbeat timeout | `list_agents(active_only=false)` |
| `orchestrator_list_blockers` | Open blockers | `list_blockers(status=open)` |
| `orchestrator_list_bugs` | Open bugs | `list_bugs(status=bug_open)` |
| Watchdog JSONL | Stale task, state corruption | `log_check.sh --strict` or parse JSONL |
| Worker/Manager logs | CLI timeout | `log_check.sh` timeout marker scan |
| Event bus | Lease recovery, dispatch events | `poll_events` or bus JSONL |
| `manager_cycle` | Report retry failures, stale reassignment | Call `manager_cycle` |

## Suggested Monitoring Cadence

| Check | Frequency | Tool |
|-------|-----------|------|
| Agent heartbeat health | Every 60s | `orchestrator_list_agents` |
| Task pipeline status | Every 120s | `orchestrator_status` |
| Open blockers | Every 300s | `orchestrator_list_blockers(status=open)` |
| Watchdog diagnostics | Every 15s (built-in) | `watchdog_loop.sh` |
| Log sanity check | Every 600s | `log_check.sh` |
| Manager cycle | Every 20s (built-in) | `manager_loop.sh` |
