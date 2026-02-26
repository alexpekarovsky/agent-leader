# Dashboard Alert Panel Mock Examples

> Mock examples for the operator dashboard alert panel, showing real alert
> scenarios using data from watchdog, status, and event bus sources.

## Example 1: Stale Agent (High Severity)

```
ALERT  [HIGH]  Agent Offline                    [AGENTS - 5s ago]
  gemini  last_seen: 2d 3h ago  status: offline
  Action: Agent has not sent a heartbeat in over 2 days.
          Restart gemini process and run connect_to_leader.
```

**Source**: `orchestrator_list_agents(active_only=false)` where `age_seconds > 172800`
**Trigger**: `status=offline` AND `age_seconds > heartbeat_timeout_minutes * 60`

---

## Example 2: Lease Expiry Recovery (High Severity)

```
ALERT  [HIGH]  Lease Expired + Requeued         [BUS - 12s ago]
  TASK-a1b2c3d4  "Add dispatch telemetry tests"
  Owner: claude_code  Instance: sess-abc-001
  Lease LEASE-e5f6a7b8 expired at 15:42:30Z
  Task requeued to "assigned" — available for re-claim
  Action: Check if claude_code worker crashed. Task will be
          picked up by the next available worker.
```

**Source**: Event bus `task.lease_recovered` event payload
**Trigger**: `recover_expired_task_leases()` finds expired lease

---

## Example 3: Watchdog Stale Task (High Severity)

```
ALERT  [HIGH]  Stale Task Detected              [WATCHDOG - 15s ago]
  TASK-dc0af9ac  status: in_progress  age: 45m 12s
  Owner: codex  Timeout threshold: 15m (900s)
  Action: Task has been in_progress for 3x the timeout.
          Raise blocker or reassign via manager_cycle.
```

**Source**: Watchdog JSONL `kind=stale_task` entry
**Trigger**: `age_seconds > inprogress_timeout` (default 900s)

---

## Example 4: Open Blocker Queue (Medium Severity)

```
ALERT  [MEDIUM]  3 Open Blockers                [STATUS - 3s ago]
  BLK-0cbfcffb  [high]  TASK-ba1b2ee1  gemini
    "Watchdog marked this task stale. Reassign or close?"
    Age: 2d 4h  Options: keep_owner | reassign | close_obsolete

  BLK-44748b57  [medium]  TASK-3cb6bab0  claude_code
    "docs/supervisor-troubleshooting.md does not exist yet"
    Age: 15h  Options: create doc first | skip task

  BLK-1938f365  [high]  TASK-e75fb59d  codex
    "Watchdog marked this task stale. Resume, defer, or reassign?"
    Age: 2d 4h  Options: resume_now | defer | reassign

  Action: Review and resolve blockers to unblock task progress.
```

**Source**: `orchestrator_list_blockers(status=open)`
**Trigger**: Any blocker with `status=open`

---

## Example 5: CLI Timeout in Worker Log (High Severity)

```
ALERT  [HIGH]  CLI Timeout                      [WATCHDOG - 10s ago]
  worker-claude-20260226-154230.log
  2 timeout(s) detected: "[AUTOPILOT] CLI timeout after 600s"
  Action: Worker CLI exceeded 600s timeout. Check task complexity.
          Consider increasing --cli-timeout if task is legitimately
          large, or investigate if agent is stuck.
```

**Source**: `log_check.sh` timeout marker scan in worker logs
**Trigger**: Log line matching `[AUTOPILOT] CLI timeout`

---

## Example 6: Task Count Regression (Critical Severity)

```
ALERT  [CRITICAL]  Task Count Regression         [STATUS - 1s ago]
  Previous: 187 tasks  Current: 185 tasks  Delta: -2
  Integrity warning: "task_count decreased from 187 to 185"
  Action: IMMEDIATE — possible data loss in tasks.json.
          Check for concurrent writes. Inspect state/tasks.json.
          Restore from backup if needed.
```

**Source**: `orchestrator_status.integrity.warnings`
**Trigger**: `task_count` decreased between status calls

---

## Example 7: Report Retry Queue Failures (Medium Severity)

```
ALERT  [MEDIUM]  Report Retry Queue              [STATUS - 8s ago]
  1 pending retry, 0 failed
  RPTQ-b3a01a01  TASK-e1212236  "Task not found"
    Attempts: 3  Next retry: 15:56:48Z
  Action: Task may have been deleted or ID is incorrect.
          Check if task exists. Clear retry queue if obsolete.
```

**Source**: `manager_cycle.report_retry_queue`
**Trigger**: Retry queue has `pending > 0`

---

## Example 8: Stale In-Progress Warning (Medium Severity)

```
ALERT  [MEDIUM]  Stale In-Progress Tasks         [STATUS - 2s ago]
  2 tasks in_progress > 30 minutes without update
  TASK-53733337  owner: claude_code  age: 42m
  TASK-82466844  owner: claude_code  age: 38m
  Action: Check claude_code worker status. Tasks may be
          actively worked on (check heartbeat) or stuck.
```

**Source**: `orchestrator_status.metrics.reliability.stale_in_progress_over_30m`
**Trigger**: Count > 0

---

## Example 9: Dispatch No-Op (Future - Phase D)

```
ALERT  [MEDIUM]  Dispatch No-Op                  [BUS - future]
  dispatch.noop for TASK-f028e203
  Reason: ack_timeout  Budget: 30s  Elapsed: 32s
  Target: claude_code  Correlation: corr-9a2b
  Action: Target agent did not ACK command within timeout.
          Verify agent is online and not overloaded.
          (Requires Phase D deterministic dispatch)
```

**Source**: Future dispatch telemetry `dispatch.noop` event
**Note**: This alert type requires Phase D implementation. Currently
shown as a planned example — not yet available in the event bus.

---

## Alert Panel Layout

```
+----------------------------------------------------------+
| ALERTS                              Last refresh: 2s ago |
|                                                          |
| [CRITICAL] Task Count Regression     [STATUS]     1s ago |
| [HIGH]     Agent Offline: gemini     [AGENTS]     5s ago |
| [HIGH]     Lease Expired: TASK-a1b2  [BUS]       12s ago |
| [HIGH]     2 CLI Timeouts            [WATCHDOG]  10s ago |
| [HIGH]     Stale Task: TASK-dc0a     [WATCHDOG]  15s ago |
| [MEDIUM]   3 Open Blockers           [STATUS]     3s ago |
| [MEDIUM]   2 Stale In-Progress       [STATUS]     2s ago |
| [MEDIUM]   1 Report Retry Pending    [STATUS]     8s ago |
| [LOW]      No claimable tasks        [STATUS]     2s ago |
+----------------------------------------------------------+
```
