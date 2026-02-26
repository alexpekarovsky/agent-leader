# Dashboard Alert Wording Style Guide

> Wording conventions for operator alerts in future dashboard output.
> Consistent severity tone and actionable phrasing.

## Severity Levels

| Level | Tone | When |
|---|---|---|
| **INFO** | Neutral, informational | Normal state changes, heartbeats |
| **WARN** | Cautious, attention needed | Approaching thresholds, single stale agent |
| **ERROR** | Urgent, action required | Task stuck, agent offline with claimed work |
| **CRITICAL** | Immediate action | State corruption, all workers offline |

## Alert Wording Patterns

### 1. Stale Agent
```
WARN: gemini stale — last heartbeat 15m ago. 0 tasks at risk.
ERROR: gemini stale — last heartbeat 2h ago. 3 tasks need reassignment.
```
**Source:** `list_agent_instances()` → `last_seen` delta

### 2. Agent Offline
```
WARN: gemini offline — no heartbeat in 10m.
ERROR: gemini offline with 5 assigned tasks. Consider mirroring to active agents.
```
**Source:** `orchestrator_status()` → `active_agents` missing

### 3. Task Timeout (In-Progress)
```
WARN: TASK-abc in_progress for 30m+ by claude_code. Check for stuck execution.
```
**Source:** `.autopilot-logs/watchdog-*.jsonl` → `stale_task` event

### 4. Task Timeout (Reported)
```
WARN: TASK-xyz reported 15m ago — pending validation. Manager cycle may be delayed.
```
**Source:** Watchdog → `stale_task` with status=reported

### 5. Blocker Spike
```
WARN: 3 new blockers raised in last hour. Triage queue growing.
ERROR: 10+ open blockers. Pipeline velocity at risk.
```
**Source:** `list_blockers()` → count + timestamps

### 6. Queue Jam (Assigned Backlog)
```
WARN: 50+ tasks assigned but unclaimed. Check for offline agents.
INFO: Queue cleared — all assigned tasks claimed.
```
**Source:** `task_status_counts.assigned`

### 7. Bug Filed
```
WARN: BUG-xyz filed against TASK-abc (claude_code). Report rejected — needs rework.
```
**Source:** `auto_manager_cycle` → `bug_id`

### 8. Lease Expiry
```
WARN: Lease expired on TASK-abc. Task requeued to assigned.
ERROR: Lease expired on TASK-abc. Owner stale — blocker created.
```
**Source:** `recover_expired_task_leases` event

### 9. Dispatch Noop
```
WARN: Dispatch noop — ack_timeout on TASK-abc targeting claude_code (31s elapsed).
ERROR: Dispatch noop — no_available_worker for backend workstream.
```
**Source:** `dispatch.noop` event → `reason` field

### 10. State Corruption
```
CRITICAL: State corruption detected in tasks.json — expected list, found dict. Manual intervention required.
```
**Source:** Watchdog → `state_corruption_detected` event

### 11. Manager Cycle Rejection
```
WARN: Report for TASK-abc rejected — 2 test failures. Bug filed.
INFO: Report for TASK-abc accepted — auto-validated.
```
**Source:** `auto_manager_cycle` response

### 12. All Workers Offline
```
CRITICAL: No active team members. All agents stale. Pipeline halted.
```
**Source:** `active_agents` = empty

## Style Rules

1. **Lead with severity** — WARN/ERROR/CRITICAL prefix
2. **Name the agent and task** — always include identifiers
3. **State the impact** — "3 tasks at risk", "pipeline halted"
4. **Suggest action** — "Consider mirroring", "Check for stuck execution"
5. **Include time context** — "15m ago", "in last hour"
