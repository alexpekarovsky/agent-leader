# Post-Restart Verification Flowchart

Manual verification steps after restarting autopilot loops. Follow this flowchart in order — each step confirms a prerequisite for the next.

> **Note**: These steps are manual until an automated validation script is built. See [restart-milestone-checklist.md](restart-milestone-checklist.md) for the broader restart context.

## Flowchart

```
START: Loops restarted
  │
  ▼
┌─────────────────────────────┐
│ Step 1: Status Check        │
│ orchestrator_status()       │
├─────────────────────────────┤
│ All agents in active_agents?│
│  YES ──► Step 2             │
│  NO  ──► Fix: restart       │
│          missing loop       │
└─────────────────────────────┘
  │
  ▼
┌─────────────────────────────┐
│ Step 2: Supervisor Check    │
│ supervisor.sh status        │
├─────────────────────────────┤
│ All processes "running"?    │
│  YES ──► Step 3             │
│  NO  ──► Fix: check log     │
│          supervisor-X.log   │
│          then restart       │
└─────────────────────────────┘
  │
  ▼
┌─────────────────────────────┐
│ Step 3: Task Recovery       │
│ list_tasks(in_progress)     │
├─────────────────────────────┤
│ Stuck tasks from before     │
│ restart?                    │
│  YES ──► reassign_stale     │
│          _tasks(300s)       │
│  NO  ──► Step 4             │
└─────────────────────────────┘
  │
  ▼
┌─────────────────────────────┐
│ Step 4: Log Flow Check      │
│ ls -lt .autopilot-logs/     │
├─────────────────────────────┤
│ New log files appearing?    │
│  YES ──► Step 5             │
│  NO  ──► Fix: loops may     │
│          have exited        │
│          silently; re-check │
│          Step 2             │
└─────────────────────────────┘
  │
  ▼
┌─────────────────────────────┐
│ Step 5: Task Flow Check     │
│ list_tasks(assigned)        │
│ Wait 2 minutes, re-check   │
├─────────────────────────────┤
│ Assigned tasks getting      │
│ claimed?                    │
│  YES ──► DONE: System       │
│          healthy             │
│  NO  ──► Fix: check worker  │
│          logs for MCP errors │
└─────────────────────────────┘
```

## Step-by-Step Table

| Step | Command | What to check | Pass condition | Fail action |
|------|---------|---------------|----------------|-------------|
| 1. Status check | `orchestrator_status()` | `active_agents` list | All expected agents present with recent heartbeats | Restart the missing agent's loop |
| 2. Supervisor check | `./scripts/autopilot/supervisor.sh status` | Process status per line | All 4 processes show `running` | Read `supervisor-{process}.log` for crash reason; restart |
| 3. Task recovery | `orchestrator_list_tasks(status="in_progress")` | Age of in-progress tasks | No tasks older than `--inprogress-timeout` | `reassign_stale_tasks(source="operator", stale_after_seconds=300)` |
| 4. Log flow | `ls -lt .autopilot-logs/ \| head -5` | File timestamps | New files created after restart time | Loop exited silently; go back to Step 2 |
| 5. Task flow | `orchestrator_list_tasks(status="assigned")` (check twice, 2 min apart) | Assigned count decreasing | Workers are claiming tasks | Check worker logs for MCP or connectivity errors |

## Quick Copy-Paste Commands

```bash
# Step 1
orchestrator_status()

# Step 2
./scripts/autopilot/supervisor.sh status

# Step 3
orchestrator_list_tasks(status="in_progress")

# Step 4
ls -lt .autopilot-logs/ | head -10

# Step 5
orchestrator_list_tasks(status="assigned")

# If Step 3 finds stuck tasks:
reassign_stale_tasks(source="operator", stale_after_seconds=300)

# Full diagnostic summary:
./scripts/autopilot/log_check.sh
```

## When to Use This Flowchart

| Scenario | Run full flowchart? |
|----------|-------------------|
| Routine restart (config change) | Yes — all 5 steps |
| Single worker crash + restart | Steps 1, 3, 5 only |
| System reboot | Yes — all 5 steps + smoke test |
| MCP server restart | Yes — all 5 steps |
| After `supervisor.sh clean` | Steps 1-2 only (no tasks affected) |

## Future: Automated Validation Script

These manual steps will be automated in a future `post_restart_check.sh` script that:

1. Calls `orchestrator_status` and parses the JSON output
2. Runs `supervisor.sh status` and checks for non-running processes
3. Detects stuck tasks and offers reassignment
4. Monitors log directory for new file creation
5. Waits for task claim activity and reports pass/fail

Until then, use this flowchart for manual verification.

## References

- [restart-milestone-checklist.md](restart-milestone-checklist.md) — Full restart procedure and milestone context
- [incident-triage-order.md](incident-triage-order.md) — When things go wrong after restart
- [operator-runbook.md](operator-runbook.md) — Standard operating procedures
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor command reference
