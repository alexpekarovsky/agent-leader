# Supervisor Log Review Checklist (Per Shift)

Recurring checklist for reviewing supervisor and autopilot logs at shift
boundaries. Run through this list at the start and end of each operator shift.

## Log files to check

| File pattern | Location | What it tells you |
|-------------|----------|-------------------|
| `supervisor-*.log` | `.autopilot-logs/` | Process start/stop/crash events |
| `manager-codex-*.log` | `.autopilot-logs/` | Manager cycle output and errors |
| `worker-*-*.log` | `.autopilot-logs/` | Worker claim/report activity and errors |
| `watchdog-*.jsonl` | `.autopilot-logs/` | Stale tasks, state corruption, lease events |

## Quick commands

```bash
# 1. Latest supervisor log (per process)
tail -20 .autopilot-logs/supervisor-claude.log

# 2. Latest manager log
tail -30 "$(ls -t .autopilot-logs/manager-codex-*.log | head -1)"

# 3. Latest worker logs
tail -30 "$(ls -t .autopilot-logs/worker-claude_code-*.log | head -1)"

# 4. Watchdog issues (non-empty = problems found)
cat "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)"

# 5. Supervisor process status
./scripts/autopilot/supervisor.sh status

# 6. Count errors across recent logs
grep -c '\[ERROR\]' .autopilot-logs/manager-codex-*.log .autopilot-logs/worker-*-*.log 2>/dev/null
```

## Healthy patterns

- [ ] `cycle=N` values increment steadily in manager and worker logs
- [ ] `cycle complete` appears after each cycle
- [ ] Supervisor status shows all processes `running`
- [ ] Watchdog JSONL file is empty (no issues detected)
- [ ] No `[ERROR]` lines in the most recent manager/worker logs
- [ ] New log files appearing at expected intervals

## Warning patterns

| Pattern | Severity | Meaning |
|---------|----------|---------|
| `[ERROR]` | Medium | CLI failure or timeout in a cycle |
| `timed out after` | Medium | CLI exceeded `--cli-timeout` |
| `dead` (in supervisor status) | High | Process crashed and is not running |
| `stale_task` (in watchdog JSONL) | Medium | Task stuck past timeout threshold |
| `state_corruption_detected` | High | State file has wrong data type |

## Escalation thresholds

| Condition | Action |
|-----------|--------|
| 1 timeout in recent logs | Note it; likely transient |
| >2 timeouts in the same shift | Investigate: check task complexity, increase `--cli-timeout`, or break tasks |
| Any `state_corruption_detected` | Immediate: back up state files, check recent writes, fix or restore |
| `dead` process in supervisor status | Restart: `./scripts/autopilot/supervisor.sh restart` |
| >3 `stale_task` entries for same owner | Check if worker is alive; consider `orchestrator_reassign_stale_tasks` |
| `cycle=` stops incrementing | Process may be hung; check PID, restart if needed |

## Shift handoff notes

After completing the checklist, record:

- [ ] Number of errors seen this shift
- [ ] Any processes restarted and why
- [ ] Tasks that required manual intervention
- [ ] Open issues for the next shift

## References

- [monitor-pane-interpretation.md](monitor-pane-interpretation.md) -- Log patterns and escalation commands
- [supervisor-cli-spec.md](supervisor-cli-spec.md) -- Supervisor commands and status values
- [incident-triage-order.md](incident-triage-order.md) -- Step-by-step triage when issues are found
- [log-file-taxonomy.md](log-file-taxonomy.md) -- Full log file naming reference
