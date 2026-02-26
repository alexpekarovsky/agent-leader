# Monitor Pane Symptom Matrix

Symptom-to-action mapping for what you see in the monitor pane (or log directory) during autopilot operation. Each row tells you what the symptom means and whether to retry or escalate.

## Symptom Matrix

| # | Symptom | Likely cause | Action | Retry or Escalate |
|---|---------|-------------|--------|-------------------|
| 1 | No new log files appearing | Loop process exited or never started | Check `supervisor.sh status`; restart dead processes | Retry: restart the loop |
| 2 | Log files appearing but all contain timeout markers | CLI binary not responding or API down | Run `codex --version` / `claude --version`; check API status | Escalate: if CLI/API broken |
| 3 | Manager log files stop but worker logs continue | Manager loop crashed | Restart manager: `supervisor.sh restart` or re-run `manager_loop.sh` | Retry: restart manager |
| 4 | Worker log files stop but manager continues | Worker loop crashed | Check `supervisor.sh status` for dead worker; restart | Retry: restart worker |
| 5 | Watchdog JSONL shows `stale_task` entries | Task stuck longer than threshold | `orchestrator_list_tasks(status="in_progress")` — check owner | Retry: wait one more cycle; Escalate: if persistent |
| 6 | Watchdog JSONL shows `state_corruption_detected` | Concurrent write or crash mid-write | Usually auto-repaired on next MCP read; check `orchestrator_status()` | Retry: auto-heals; Escalate: if repeated |
| 7 | All logs have same timestamp (no new cycles) | All loops stopped or interval too long | Check all processes; verify `--interval` settings | Escalate: restart all loops |
| 8 | Log directory is empty | Loops never started or `--log-dir` mismatch | Verify `--log-dir` path matches; check if processes are running | Escalate: fix config and restart |
| 9 | Manager log shows "no tasks to assign" repeatedly | Task queue is empty or all tasks are done/blocked | `orchestrator_list_tasks()` — check if work remains | Retry: create new tasks or unblock |
| 10 | Worker log shows MCP connection errors | MCP server down or `.mcp.json` misconfigured | Check MCP server process; verify `.mcp.json` paths | Escalate: fix MCP config |
| 11 | Worker log shows "project_mismatch" | Worker's project root doesn't match MCP server | Align `--project-root` with `ORCHESTRATOR_ROOT` in `.mcp.json` | Escalate: fix paths, restart |
| 12 | Multiple timeout markers in consecutive manager logs | Manager cycle too complex or API rate limited | Increase `--cli-timeout`; check API quota | Retry: increase timeout; Escalate: if rate limited |
| 13 | Log files growing rapidly (hundreds per hour) | Interval too short or tasks finishing very fast | Check `--interval` setting; review `--max-logs` retention | Retry: increase interval |
| 14 | Supervisor log shows repeated start/stop cycles | Operator or script restarting in a loop | Check for cron jobs or wrapper scripts triggering restarts | Escalate: identify restart source |

## Verification Commands

When you see a symptom, use these commands to verify the state:

### Process status

```bash
# Supervisor mode
./scripts/autopilot/supervisor.sh status

# tmux mode
tmux list-panes -t agents-autopilot -F '#{pane_index} #{pane_current_command}'
```

### Orchestrator state

```bash
# From a connected CLI session:
orchestrator_status()
orchestrator_list_tasks(status="in_progress")
orchestrator_list_tasks(status="assigned")
orchestrator_list_blockers()
```

### Log inspection

```bash
# Most recent files by type
ls -lt .autopilot-logs/manager-*.log | head -3
ls -lt .autopilot-logs/worker-*.log | head -3
ls -lt .autopilot-logs/watchdog-*.jsonl | head -1

# Count timeouts
grep -c '\[AUTOPILOT\] CLI timeout' .autopilot-logs/*.log

# Full diagnostic summary
./scripts/autopilot/log_check.sh
```

## Decision Flowchart

```
Monitor shows a problem
  │
  ├─ No new log files?
  │   └─ Check process status → restart dead loops
  │
  ├─ Timeout markers in logs?
  │   ├─ First occurrence? → Wait for next cycle (may be transient)
  │   └─ Repeated? → Check CLI health, increase timeout
  │
  ├─ Stale tasks in watchdog?
  │   ├─ Owner alive? → Task may be legitimately complex; wait
  │   └─ Owner dead? → Restart owner, reassign task
  │
  ├─ MCP errors in logs?
  │   └─ Check MCP server → fix config → restart
  │
  └─ Everything looks normal?
      └─ Monitor for another cycle
```

## References

- [incident-triage-order.md](incident-triage-order.md) — Detailed 6-step triage procedure
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Symptom/cause/action tables
- [timeout-semantics.md](timeout-semantics.md) — When timeouts are expected vs unexpected
- [log-file-taxonomy.md](log-file-taxonomy.md) — Log file naming and review order
- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) — Supervisor-specific issues
