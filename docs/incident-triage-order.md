# Incident Triage Order

When something goes wrong with the autopilot system, inspect these in order. Each step narrows the problem before going deeper.

## Step 1: Check orchestrator status

```bash
# In any connected CLI session:
orchestrator_status()
```

Look at:
- **active_agents**: Which agents are online? Missing agents = crashed loops
- **task_status_counts**: Are tasks accumulating in `in_progress` or `reported`?
- **open blockers**: High count may indicate systemic issues

**Branch:**
- If an agent is missing from active_agents → go to Step 4 (check process state)
- If tasks are piling up in `reported` → manager isn't validating (go to Step 5)
- If everything looks normal → the issue may be resolved; re-check the symptom

## Step 2: Check in-progress tasks

```bash
orchestrator_list_tasks(status="in_progress")
```

Look at:
- **age**: How long has each task been in progress? Compare against `--inprogress-timeout` (default 900s)
- **owner**: Which agent owns the stuck task?
- **title**: Is it a legitimately complex task or something that should have finished quickly?

**Branch:**
- Task stuck for hours with no worker activity → worker crashed (go to Step 4)
- Task recently claimed and worker is active → task may just be complex; wait
- Multiple tasks stuck on same owner → that agent is definitely down

## Step 3: Check watchdog diagnostics

```bash
# Latest watchdog file
cat "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)" | python3 -m json.tool

# Or use log_check for a summary
./scripts/autopilot/log_check.sh
```

Look at:
- **stale_task** entries: Which tasks are stale and for how long?
- **state_corruption_detected**: Any corrupted state files?

**Branch:**
- `stale_task` with `status: assigned` → worker never claimed it (check worker logs)
- `stale_task` with `status: in_progress` → worker crashed mid-task (restart + reassign)
- `state_corruption_detected` → usually auto-repaired; manual fix if persistent (see [watchdog-diagnostics-troubleshooting.md](watchdog-diagnostics-troubleshooting.md))

## Step 4: Check process state

### With supervisor:

```bash
./scripts/autopilot/supervisor.sh status
```

| Status | Meaning | Action |
|--------|---------|--------|
| `running` | Process alive | Check its logs (Step 5) |
| `dead` | Process crashed | Restart: `supervisor.sh restart` |
| `stopped` | Not started | Start: `supervisor.sh start` |

### With tmux:

```bash
tmux list-panes -t agents-autopilot:manager
```

If a pane shows a shell prompt instead of a running loop, the process exited.

**Branch:**
- Process is dead → restart it, then check if stuck tasks self-recover
- Process is alive → it's running but not making progress (go to Step 5)

## Step 5: Check loop logs

```bash
# Most recent manager log
cat "$(ls -t .autopilot-logs/manager-codex-*.log | head -1)"

# Most recent worker log for the stuck agent
cat "$(ls -t .autopilot-logs/worker-claude_code-claude-*.log | head -1)"
```

Look for:
- **`[AUTOPILOT] CLI timeout`**: The CLI exceeded its timeout — task was too complex or the CLI is hung
- **MCP errors**: Connection failures, tool call errors
- **Test failures**: Worker ran tests but they failed
- **Empty log**: Worker started but produced no output — CLI may have crashed immediately

**Branch:**
- Timeout markers → increase `--cli-timeout` or break the task into smaller pieces
- MCP errors → check if the MCP server is running (`orchestrator_status`)
- Test failures → the worker is working but the code has bugs; let the bug loop handle it
- Empty log → check CLI installation: `claude --version`, `codex --version`

## Step 6: Check audit log (last resort)

```bash
# Recent audit entries
tail -20 state/bus/audit.jsonl | python3 -m json.tool
```

The audit log records every MCP tool call with arguments and results. Use this to trace exactly what happened — which agent called what, in what order, and what the engine returned.

## Quick Decision Tree

```
Symptom: No progress being made
│
├─ orchestrator_status shows missing agent?
│  └─ YES → Restart the agent's loop process
│
├─ Tasks stuck in in_progress?
│  ├─ Worker alive? → Check worker logs for errors/timeouts
│  └─ Worker dead? → Restart worker, reassign task
│
├─ Tasks stuck in reported?
│  ├─ Manager alive? → Check manager logs
│  └─ Manager dead? → Restart manager
│
├─ Tasks stuck in assigned?
│  ├─ Worker alive? → Worker may be busy; check its current task
│  └─ Worker dead? → Restart worker
│
└─ All agents running, tasks flowing?
   └─ Issue may be transient → monitor for another cycle
```

## Common Failure Classes

### Timeout (most common)

**Symptom**: `[AUTOPILOT] CLI timeout after Ns` in logs
**Cause**: Task too complex, CLI overloaded, or MCP server slow
**Fix**: Increase `--cli-timeout`, or break task into subtasks

### Scope mismatch

**Symptom**: Worker reports `project_mismatch` or `not_verified` on connect
**Cause**: Worker's `--project-root` doesn't match MCP server's `ORCHESTRATOR_ROOT`
**Fix**: Align paths in `.mcp.json` and loop invocation

### Stale task accumulation

**Symptom**: Watchdog shows many `stale_task` entries across multiple statuses
**Cause**: Loops crashed and weren't restarted
**Fix**: `supervisor.sh restart` or `tmux kill-session` + relaunch

### State corruption

**Symptom**: `state_corruption_detected` in watchdog JSONL
**Cause**: Concurrent writes or process killed mid-write
**Fix**: Usually auto-repairs. If persistent: stop loops, `echo '[]' > state/bugs.json`, restart

## References

- [docs/watchdog-diagnostics-troubleshooting.md](watchdog-diagnostics-troubleshooting.md) — Detailed diagnostic interpretation
- [docs/troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Symptom/cause/action tables
- [docs/operator-runbook.md](operator-runbook.md) — Standard operating procedures
- [docs/log-file-taxonomy.md](log-file-taxonomy.md) — Log file naming and review order
