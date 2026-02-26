# Stale vs Offline Quick-Check Guide

Operator reference for distinguishing agent health states based on heartbeat age. Use this when the dashboard shows an agent in a non-active state and you need to decide what to do.

---

## Decision Tree

```
1. Read agent's last_seen timestamp
   |
   v
2. Compute age_seconds = now - last_seen
   |
   +-- age_seconds < heartbeat_timeout (600s default)
   |     --> ACTIVE (green)
   |     Action: None. Agent is healthy.
   |
   +-- age_seconds >= heartbeat_timeout
   |   AND age_seconds < 2x heartbeat_timeout (1200s)
   |     --> STALE (orange)
   |     Action: Wait and re-check. Agent may self-recover.
   |
   +-- age_seconds >= 2x heartbeat_timeout (1200s)
         --> OFFLINE (red)
         Action: Intervene. Restart agent or reassign its tasks.
```

---

## Thresholds Table

Default `heartbeat_timeout` = 600 seconds (10 minutes).

| State    | Condition                     | Age Range (default) | Color  | Recovery Likelihood |
|----------|-------------------------------|---------------------|--------|---------------------|
| Active   | age < timeout                 | 0 -- 599s           | Green  | N/A (healthy)       |
| Stale    | timeout <= age < 2x timeout   | 600 -- 1199s        | Orange | Moderate            |
| Offline  | age >= 2x timeout             | 1200s+              | Red    | Low without restart  |

---

## Example Status Rows

### Active Agent

```
agent: claude_code
instance_id: cc-inst-7f3e
last_seen: 2026-02-26T10:28:00Z    (45s ago)
status: active
current_task: task-42
```

Interpretation: Healthy. Last heartbeat 45 seconds ago. Currently working on task-42. No action needed.

### Stale Agent

```
agent: gemini
instance_id: gem-inst-a1b2
last_seen: 2026-02-26T10:16:00Z    (12m ago)
status: stale
current_task: task-19
```

Interpretation: Heartbeat is 12 minutes old (exceeds 10m timeout but under 20m). Agent may be in a long operation or experiencing transient issues. Re-check in 5 minutes before intervening.

### Offline Agent

```
agent: gemini
instance_id: gem-inst-a1b2
last_seen: 2026-02-25T17:00:00Z    (17h ago)
status: offline
current_task: task-19
```

Interpretation: Last heartbeat was 17 hours ago. Agent is down. Tasks owned by this agent are stuck and will not progress without intervention.

---

## Follow-Up Actions by State

| State   | Immediate Action                        | If No Improvement After Re-Check         |
|---------|-----------------------------------------|------------------------------------------|
| Active  | None                                    | N/A                                      |
| Stale   | Wait 5 minutes, re-check heartbeat     | Verify agent process is running. Check logs for errors. |
| Offline | Check if agent process is alive         | Restart agent. Run `orchestrator_reassign_stale_tasks` (shortcut `r`) to move its tasks to healthy workers. |

---

## Operator Checklist for Offline Agents

1. **Verify process** -- Is the agent process still running on the host? Check with `ps`, `tmux`, or supervisor status.
2. **Check logs** -- Look for crash traces, OOM errors, or network failures in the agent's log output.
3. **Attempt restart** -- Re-launch the agent. It should re-register and pick up where it left off via `orchestrator_connect_to_leader`.
4. **Reassign tasks** -- If restart is not possible or will take time, run `orchestrator_reassign_stale_tasks` to redistribute owned tasks to active agents.
5. **Verify recovery** -- After restart, confirm the agent appears as `active` in `orchestrator_list_agents` and is claiming tasks again.

---

## Common Pitfalls

- **Stale is not offline.** Do not immediately reassign tasks for stale agents. They often recover within a few minutes (long-running tool calls, network blips).
- **Clock skew.** If the operator's clock differs from the orchestrator's clock, age calculations will be wrong. Ensure NTP is synchronized.
- **Multiple instances.** An agent name may have multiple instances. One instance being offline does not mean the agent is entirely down. Check all instances before escalating.
- **Lease vs heartbeat.** Task leases and agent heartbeats are independent timers. An agent can be active (healthy heartbeat) but have an expired lease if it forgot to renew. Check both.
