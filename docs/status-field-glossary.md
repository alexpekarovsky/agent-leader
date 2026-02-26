# Operator Status Field Glossary

Comprehensive reference for every status field surfaced by the orchestrator. Organized by category. Each entry includes the field name, data type, an example value, and how operators should interpret it.

---

## Task Status Fields

These values appear in the `status` field of task objects returned by `orchestrator_list_tasks`.

| Field        | Type   | Example          | Definition                                                                 | Operator Interpretation                                                  |
|--------------|--------|------------------|----------------------------------------------------------------------------|--------------------------------------------------------------------------|
| `assigned`   | string | `"assigned"`     | Task created and routed to an owner, but not yet claimed for execution.    | Normal queue state. If lingering, check if the owner agent is active.    |
| `in_progress`| string | `"in_progress"`  | Agent has claimed the task and is actively working on it.                  | Work underway. If stale (>30m), may indicate a stuck worker.            |
| `reported`   | string | `"reported"`     | Agent submitted a delivery report; awaiting manager validation.            | Needs manager review. Run manager cycle to validate.                     |
| `done`       | string | `"done"`         | Manager validated the report and closed the task.                          | Terminal state. No further action needed.                                |
| `blocked`    | string | `"blocked"`      | Agent raised a blocker; task cannot proceed until resolved.                | Operator input required. Check `orchestrator_list_blockers`.             |
| `bug_open`   | string | `"bug_open"`     | Manager validation failed; a bug was opened against this task.             | Rework needed. The owning agent must fix and re-report.                  |

---

## Agent Status Fields

Derived from heartbeat timestamps and registration state in `orchestrator_list_agents`.

| Field     | Type   | Example       | Definition                                                                       | Operator Interpretation                                              |
|-----------|--------|---------------|----------------------------------------------------------------------------------|----------------------------------------------------------------------|
| `active`  | string | `"active"`    | Agent heartbeat is within the configured timeout window.                         | Healthy. Agent is responsive and can claim tasks.                    |
| `offline` | string | `"offline"`   | Agent heartbeat exceeds 2x the timeout threshold.                                | Intervention needed. Agent process likely crashed or disconnected.   |
| `stale`   | string | `"stale"`     | Agent heartbeat exceeds 1x timeout but is within 2x. May recover on its own.    | Watch state. May self-recover; check again shortly.                  |
| `idle`    | string | `"idle"`      | Agent is active but not currently working on any task.                            | Available for work. Check if unassigned tasks exist.                 |

---

## Lease Fields

Present on tasks that have been claimed. Leases prevent duplicate work by granting exclusive ownership for a time window.

| Field               | Type     | Example                          | Definition                                                              | Operator Interpretation                                            |
|---------------------|----------|----------------------------------|-------------------------------------------------------------------------|---------------------------------------------------------------------|
| `lease_id`          | string   | `"lease-a1b2c3"`                 | Unique identifier for this lease grant.                                 | Reference key for audit trail and renewal tracking.                |
| `owner`             | string   | `"claude_code"`                  | Agent ID that holds the lease.                                          | Who is responsible for this task right now.                        |
| `owner_instance_id` | string   | `"cc-inst-7f3e"`                 | Specific instance of the owner agent (disambiguates multiple sessions). | Identifies which process/session holds the lease.                  |
| `issued_at`         | ISO 8601 | `"2026-02-26T10:05:00Z"`        | Timestamp when the lease was first granted.                             | How long ago the task was claimed.                                 |
| `expires_at`        | ISO 8601 | `"2026-02-26T10:35:00Z"`        | Timestamp when the lease will expire if not renewed.                    | Countdown to automatic requeue. Compare with current time.         |
| `renewed_at`        | ISO 8601 | `"2026-02-26T10:20:00Z"`        | Timestamp of the most recent lease renewal.                             | Confirms the worker is still active. Null if never renewed.        |
| `ttl_seconds`       | integer  | `1800`                           | Time-to-live for the lease in seconds (default 30 minutes).             | Controls how long a worker can hold a task without renewing.       |

---

## Instance Fields

Present in agent registration and discovery results. Used to distinguish multiple sessions of the same agent type.

| Field              | Type     | Example                              | Definition                                                                    | Operator Interpretation                                              |
|--------------------|----------|--------------------------------------|-------------------------------------------------------------------------------|----------------------------------------------------------------------|
| `instance_id`      | string   | `"cc-inst-7f3e"`                     | Unique identifier for this agent process/session.                             | Differentiates multiple running copies of the same agent.           |
| `agent_name`       | string   | `"claude_code"`                      | Logical agent identity (not instance-specific).                               | The agent type. Multiple instances may share this name.             |
| `role`             | string   | `"team_member"`                      | Agent role: `leader` or `team_member`.                                        | Leaders manage; team members execute. Usually one leader.           |
| `project_root`     | string   | `"/Users/alex/claude-multi-ai"`      | Working directory the agent is operating in.                                  | Must match across agents for same-project verification.             |
| `current_task_id`  | string   | `"task-42"`                          | Task the instance is currently working on. Null if idle.                      | Cross-reference with task list to verify consistency.               |
| `last_seen`        | ISO 8601 | `"2026-02-26T10:22:15Z"`            | Most recent heartbeat timestamp.                                              | Primary input for active/stale/offline determination.               |
| `verified`         | boolean  | `true`                               | Whether the agent passed identity verification.                               | Unverified agents cannot be trusted for task execution.             |
| `same_project`     | boolean  | `true`                               | Whether the agent's project_root matches the leader's project.                | False means the agent is working on a different codebase.           |

---

## Metric Fields

Returned by `orchestrator_status` and `orchestrator_live_status_report`. Aggregate health indicators.

| Field                          | Type    | Example  | Definition                                                                          | Operator Interpretation                                                  |
|--------------------------------|---------|----------|-------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| `completion_rate_percent`      | float   | `62.5`   | Percentage of total tasks in `done` status.                                         | Primary progress indicator. Compare against time elapsed.               |
| `avg_time_to_claim`           | string  | `"4m12s"`| Mean time from task `assigned` to `in_progress`.                                    | High values suggest agents are slow to poll or overloaded.              |
| `avg_time_to_report`          | string  | `"18m30s"`| Mean time from `in_progress` to `reported`.                                        | Measures average task execution duration.                               |
| `avg_time_to_validate`        | string  | `"2m05s"`| Mean time from `reported` to `done` (or `bug_open`).                               | Measures manager review latency. High = manager bottleneck.             |
| `stale_in_progress_over_30m`  | integer | `3`      | Count of tasks in `in_progress` for more than 30 minutes without a report.          | Potential stuck workers. Investigate these tasks directly.              |
| `open_bugs`                   | integer | `2`      | Count of tasks in `bug_open` status awaiting rework.                                | Rework backlog. Agents should prioritize these before new tasks.        |
| `open_blockers`               | integer | `5`      | Count of unresolved blockers requiring operator or user input.                      | Direct operator action needed. Higher count = more pipeline stall risk. |

---

## Quick Reference: Status Lifecycle

```
assigned  -->  in_progress  -->  reported  -->  done
                  |                  |
                  v                  v
               blocked          bug_open --> in_progress (rework)
```

- Tasks move left-to-right in the normal flow.
- `blocked` pauses a task until the blocker is resolved, then returns to `in_progress`.
- `bug_open` sends the task back to the owning agent for rework, then re-enters `in_progress`.
