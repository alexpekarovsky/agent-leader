# Restart Milestone Checklist

Operator checklist for reaching "near-automatic mode" — the point where restarting loops requires minimal manual intervention. This checklist tracks the AUTO-M1 milestone tasks, their acceptance gates, and post-restart validation steps.

## What "Near-Automatic Mode" Means

After completing the AUTO-M1 milestone, the system supports:

- **Instance-aware status**: each running loop has a unique `instance_id`, so `orchestrator_status()` can distinguish individual workers
- **Supervisor lifecycle**: `supervisor.sh start/stop/status/restart/clean` manages processes without tmux
- **Documented recovery**: operator runbook, troubleshooting tables, and incident triage cover all common restart scenarios

## Milestone Tasks

### Core Infrastructure

| Task ID | Title | Status | Key Acceptance Check |
|---------|-------|--------|---------------------|
| TASK-13a1fc1d | AUTO-M1-CORE-01 Instance ID support | Done | `instance_id` persisted in agent metadata; backward-compatible with old clients |

### Operations

| Task ID | Title | Status | Key Acceptance Check |
|---------|-------|--------|---------------------|
| TASK-439df85f | AUTO-M1-OPS-01 Supervisor prototype | Done | `supervisor.sh` supports start/stop/status with PID/log metadata |
| TASK-b67894d8 | AUTO-M1-OPS-02 Supervisor docs bundle | Done | CLI spec and failure checklist committed under `docs/` |
| TASK-1926cd03 | AUTO-M1-OPS-03 Supervisor smoke test | Done | Smoke test covers start/status/stop lifecycle with artifact verification |
| TASK-035a1655 | AUTO-M1-OPS-04 Dual-CC workflow doc | Done | Interim dual-CC workflow documented with caveats |
| TASK-936a3c5f | AUTO-M1-OPS-05 Docs consistency checker | Done | Checker scripts validate command snippets and paths in milestone docs |
| TASK-f80d5756 | AUTO-M1-OPS-06 Supervisor cleanup command | Done | `supervisor.sh clean` removes stale PID/log metadata safely |
| TASK-1ea47cf6 | AUTO-M1-OPS-08 Restart milestone checklist | In Progress | This document |

## Pre-Restart Checklist

Before restarting loops (after a crash, upgrade, or config change):

1. **Check orchestrator status**
   ```bash
   # From any connected CLI session:
   orchestrator_status()
   ```
   Verify: active agents list, task status counts, open blockers.

2. **Check for stuck tasks**
   ```bash
   orchestrator_list_tasks(status="in_progress")
   ```
   If tasks have been `in_progress` for longer than `--inprogress-timeout` (default 900s), they may need reassignment after restart.

3. **Save any in-progress work**
   ```bash
   git stash   # if uncommitted changes exist
   ```

4. **Stop running loops**
   ```bash
   # Supervisor mode:
   ./scripts/autopilot/supervisor.sh stop

   # tmux mode:
   tmux kill-session -t agents-autopilot
   ```

5. **Clean stale artifacts** (optional, after crashes)
   ```bash
   ./scripts/autopilot/supervisor.sh clean
   ```

## Restart Procedure

### Using supervisor

```bash
./scripts/autopilot/supervisor.sh start
./scripts/autopilot/supervisor.sh status
```

### Using tmux

```bash
# Review commands first:
./scripts/autopilot/team_tmux.sh --dry-run

# Launch:
./scripts/autopilot/team_tmux.sh
```

## Post-Restart Validation Steps

Run these checks after every restart to confirm the system is healthy.

### Step 1: Verify instance-aware status

```bash
orchestrator_status()
```

Expected:
- All agents appear in `active_agents` with their `instance_id`
- `last_heartbeat` timestamps are recent (within last 60s)
- No stale entries from the previous session

### Step 2: Verify lease recovery behavior

```bash
orchestrator_list_tasks(status="in_progress")
```

Expected:
- Tasks that were `in_progress` before restart are either:
  - Resumed by the restarted worker (same owner), or
  - Available for reassignment if the previous owner is gone

If tasks are stuck:
```bash
# Reassign tasks from stale workers:
reassign_stale_tasks(source="operator", stale_after_seconds=300)
```

### Step 3: Verify supervisor start/stop/status

```bash
./scripts/autopilot/supervisor.sh status
```

Expected output for each process:
```
[STATUS] manager: running (pid=XXXXX)
[STATUS] claude: running (pid=XXXXX)
[STATUS] gemini: running (pid=XXXXX)
[STATUS] watchdog: running (pid=XXXXX)
```

If any process shows `dead` or `stopped`, check its log:
```bash
cat .autopilot-logs/supervisor-<process>.log
```

### Step 4: Verify log output is flowing

```bash
# Check that new log files are being created:
ls -lt .autopilot-logs/ | head -5

# Run log check for a summary:
./scripts/autopilot/log_check.sh
```

Expected: new log files with timestamps after the restart time.

### Step 5: Verify task flow

```bash
orchestrator_list_tasks(status="assigned")
```

Expected: assigned tasks are being claimed by workers within 1-2 cycles (60-120s).

If tasks remain `assigned` after several minutes:
- Check worker logs for errors (see [incident-triage-order.md](incident-triage-order.md) Step 5)
- Verify MCP server connectivity

## Smoke Test

Run the full smoke test suite to validate system integrity:

```bash
./scripts/autopilot/smoke_test.sh
```

All tests should pass. If any fail, check the specific test section output for diagnostics.

## When to Restart

| Situation | Action | Validation needed |
|-----------|--------|-------------------|
| Worker crashed (tmux pane shows shell prompt) | Restart that pane's loop script | Steps 1-2 |
| Supervisor shows `dead` process | `supervisor.sh restart` | Steps 1-3 |
| MCP server updated | Stop all loops, restart MCP, restart loops | Steps 1-5 |
| Config change (`.mcp.json`, timeouts) | Stop all loops, restart | Steps 1-5 |
| System reboot | `supervisor.sh clean`, then `start` | Steps 1-5 + smoke test |
| Code deployment | Stop loops, pull changes, restart | Steps 1-5 + smoke test |

## References

- [operator-runbook.md](operator-runbook.md) — Standard operating procedures
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor command interface
- [incident-triage-order.md](incident-triage-order.md) — Ordered triage when things go wrong
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Symptom/cause/action tables
- [current-limitations-matrix.md](current-limitations-matrix.md) — Known limitations and workarounds
- [roadmap.md](roadmap.md) — Architecture roadmap (Phases A-F)
