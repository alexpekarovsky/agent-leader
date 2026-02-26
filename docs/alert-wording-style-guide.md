# Dashboard Alert Wording Style Guide

Conventions for writing operator-facing alert messages on the orchestrator
dashboard. Consistent wording helps operators scan alerts quickly and take
the right action.

---

## Severity Tone

| Severity | Tone | Characteristics |
|----------|------|-----------------|
| CRITICAL | Urgent, imperative | Short sentences. Commands. All-caps severity tag. Immediate action required. |
| HIGH | Direct, actionable | Clear cause and effect. Specific next step. Response within minutes. |
| MEDIUM | Informational, monitoring | States the condition. Suggests investigation. No immediate emergency. |
| LOW | Passive, optional | Notes a transient or expected state. Monitor only. No action unless persistent. |

---

## Tense Rules

| Situation | Tense | Example |
|-----------|-------|---------|
| Current state | Present | "Agent offline", "Lease expired", "Queue jammed" |
| Past event | Past | "Lease expired at 15:42:30Z", "Task regressed from done to assigned" |
| Required action | Imperative | "Restart agent", "Review blocker", "Check state file" |
| Projected impact | Future | "Task will requeue after lease expiry" |

---

## Specificity Requirements

Every alert MUST include:

1. **Entity ID**: TASK-xxx, BLK-xxx, LEASE-xxx, or agent name
2. **Timestamp or age**: when the event occurred or how long ago
3. **Threshold** (if applicable): what limit was exceeded
4. **Action verb**: what the operator should do

---

## Action Wording

Start the action line with an imperative verb:

| Verb | Use for |
|------|---------|
| Check | Verify a condition or status |
| Review | Examine details before deciding |
| Restart | Bring a process back online |
| Resolve | Close a blocker or bug |
| Reassign | Move a task to a different owner |
| Clear | Remove stale overrides or retry queue entries |
| Inspect | Look at raw state files or logs |
| Investigate | Determine root cause of an anomaly |

---

## Alert Wording Patterns

### 1. Agent Offline

```
ALERT  [HIGH]  Agent offline: gemini                 [AGENTS - 5s ago]
  gemini  last_seen: 2d 3h ago  status: offline
  Action: Restart gemini process. Run connect_to_leader to re-register.
```

### 2. Stale Task

```
ALERT  [HIGH]  Stale task: TASK-dc0af9ac             [WATCHDOG - 15s ago]
  Status: in_progress  Owner: claude_code  Age: 45m 12s
  Threshold: 15m (900s)  Exceeded by: 30m 12s
  Action: Check claude_code heartbeat. Raise blocker or reassign via
          reassign_stale_tasks(source="operator").
```

### 3. Lease Expiry

```
ALERT  [HIGH]  Lease expired: LEASE-e5f6a7b8         [BUS - 12s ago]
  Task: TASK-a1b2c3d4  Owner: claude_code
  Expired at: 2026-02-26T15:42:30Z  TTL was: 600s
  Task requeued to assigned status.
  Action: Check if claude_code crashed. Task available for re-claim.
```

### 4. Blocker Spike

```
ALERT  [MEDIUM]  Blocker count elevated: 10 open     [STATUS - 3s ago]
  High: 3  Medium: 5  Low: 2
  Oldest unresolved: BLK-0cbfcffb (2d 4h)
  Action: Review open blockers. Resolve high-severity items first.
          Run: orchestrator_list_blockers(status=open)
```

### 5. Queue Jam

```
ALERT  [HIGH]  Queue jam: 0 tasks progressing        [STATUS - 2s ago]
  Assigned: 38  In progress: 0  Active agents: 2
  Last task claimed: 22m ago
  Action: Check agent claim loops. Verify MCP connectivity.
          Run: orchestrator_list_agents() to confirm agent status.
```

### 6. CLI Timeout

```
ALERT  [HIGH]  CLI timeout in worker log              [WATCHDOG - 10s ago]
  Log: worker-claude-20260226-154230.log
  Count: 2 timeouts  Message: "[AUTOPILOT] CLI timeout after 600s"
  Action: Check task complexity. Increase --cli-timeout if task is
          legitimately large. Investigate if agent is stuck in a loop.
```

### 7. State Corruption

```
ALERT  [CRITICAL]  State corruption detected          [WATCHDOG - 1s ago]
  File: state/bugs.json  Expected: array  Found: object
  Action: IMMEDIATE -- Fix state file manually. Stop all agents before
          editing. Check for concurrent write race conditions.
          Back up current state before making changes.
```

### 8. Task Regression

```
ALERT  [CRITICAL]  Task count regression              [STATUS - 1s ago]
  Previous: 187 tasks  Current: 185 tasks  Delta: -2
  Action: IMMEDIATE -- Possible data loss in state/tasks.json.
          Inspect file for truncation or corruption.
          Check for concurrent writes. Restore from backup if needed.
```

### 9. Report Retry

```
ALERT  [MEDIUM]  Report retry queue active            [STATUS - 8s ago]
  Pending: 1  Failed: 0
  TASK-e1212236  Error: "Task not found"  Attempts: 3
  Next retry: 2026-02-26T15:56:48Z
  Action: Check if task exists. Clear retry entry if task was deleted.
          Run: orchestrator_list_tasks() to verify task ID.
```

### 10. Dispatch Noop

```
ALERT  [MEDIUM]  Dispatch noop: TASK-f028e203        [BUS - 20s ago]
  Reason: ack_timeout  Budget: 30s  Elapsed: 32s
  Target: claude_code  Correlation: corr-9a2b3c4d
  Action: Check if target agent is online and responsive.
          Review dispatch telemetry for pattern of missed ACKs.
          Run: orchestrator_list_agents() to verify agent health.
```

---

## Anti-Patterns

Avoid these common mistakes in alert wording:

### Vague wording

```
BAD:   ALERT  Something went wrong with a task
GOOD:  ALERT  [HIGH]  Stale task: TASK-dc0af9ac  Age: 45m 12s
```

### Missing entity IDs

```
BAD:   ALERT  A blocker was raised
GOOD:  ALERT  [MEDIUM]  Blocker raised: BLK-44748b57 on TASK-3cb6bab0
```

### Passive voice with no action

```
BAD:   ALERT  The agent was found to be offline
GOOD:  ALERT  [HIGH]  Agent offline: gemini. Restart and reconnect.
```

### No action line

```
BAD:   ALERT  [HIGH]  Lease expired: LEASE-e5f6a7b8
       (nothing else)
GOOD:  ALERT  [HIGH]  Lease expired: LEASE-e5f6a7b8
       Task: TASK-a1b2c3d4 requeued. Check if owner crashed.
```

### Missing threshold or timestamp

```
BAD:   ALERT  Task has been running too long
GOOD:  ALERT  [HIGH]  Stale task: TASK-dc0af9ac  Age: 45m  Threshold: 15m
```

### Overly verbose explanation

```
BAD:   ALERT  It appears that the task TASK-dc0af9ac which is owned by
       claude_code has been in the in_progress state for a period of time
       that exceeds the configured timeout threshold, which might indicate
       that the agent has become unresponsive or encountered an error...

GOOD:  ALERT  [HIGH]  Stale task: TASK-dc0af9ac  Owner: claude_code
       Age: 45m  Threshold: 15m
       Action: Check agent. Reassign if unresponsive.
```

---

## Alert Template

```
ALERT  [{SEVERITY}]  {Title}: {Entity ID}            [{SOURCE} - {age}]
  {Key details: status, owner, threshold, timestamp}
  Action: {Imperative verb} {specific instruction}.
          {Optional second step}.
```

## Checklist for New Alerts

- [ ] Severity tag is present and matches the tone guide
- [ ] Entity ID (TASK-xxx, BLK-xxx, LEASE-xxx, agent name) is included
- [ ] Timestamp or age is specified
- [ ] Threshold is shown (if the alert is triggered by exceeding a limit)
- [ ] Action line starts with an imperative verb
- [ ] Source tag identifies where the alert data comes from
- [ ] No passive voice in the action line
- [ ] Alert fits in 4-6 lines maximum

## References

- [operator-alert-taxonomy.md](operator-alert-taxonomy.md) -- Alert classification
- [dashboard-alert-panel-examples.md](dashboard-alert-panel-examples.md) -- Panel mock-ups
- [monitor-symptom-matrix.md](monitor-symptom-matrix.md) -- Symptom to action mapping
- [incident-triage-order.md](incident-triage-order.md) -- Triage sequence
