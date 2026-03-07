# Supervisor Troubleshooting

Common issues with the headless supervisor and how to resolve them.

## Stale PID Files

### Symptom

`supervisor.sh status` shows `dead` for one or more processes, or `start` says "already running" when the process is not actually running.

### Cause

PID file exists but the process exited (crash, manual kill, or system reboot).

### Fix

```bash
# Remove stale PIDs (only removes files for dead processes)
./scripts/autopilot/supervisor.sh clean

# Then restart
./scripts/autopilot/supervisor.sh start
```

### After a system reboot

PIDs from before the reboot may match different processes. Always clean first:

```bash
./scripts/autopilot/supervisor.sh clean
./scripts/autopilot/supervisor.sh start
```

## Missing Log Directory

### Symptom

Supervisor fails to start with a directory error, or no log files appear after start.

### Cause

`.autopilot-logs/` was deleted or never created.

### Fix

The supervisor creates the directory automatically on `start`. If it still fails:

```bash
mkdir -p .autopilot-logs .autopilot-pids
./scripts/autopilot/supervisor.sh start
```

## Missing PID Directory

### Symptom

`supervisor.sh status` shows all processes as `stopped` even though they're running.

### Cause

`.autopilot-pids/` was deleted while processes were running.

### Fix

```bash
# Find running loop processes
ps aux | grep -E '(manager|worker|watchdog)_loop'

# Kill them manually (note the PIDs from ps output)
kill <pid1> <pid2> <pid3> <pid4>

# Clean start
./scripts/autopilot/supervisor.sh start
```

## Process Won't Start

### Symptom

`supervisor.sh start` prints the start message but `status` shows `dead` immediately.

### Cause

The loop script itself is failing on startup. Common reasons:

| Cause | Diagnostic |
|-------|-----------|
| Missing CLI binary | `which codex`, `which claude`, `which gemini` |
| Missing common.sh | Check `scripts/autopilot/common.sh` exists |
| Permission denied | `chmod +x scripts/autopilot/*.sh` |
| Bad project root | Check `--project-root` path exists |

### Fix

1. Check the supervisor log for the failing process:
   ```bash
   cat .autopilot-logs/supervisor-manager.log
   cat .autopilot-logs/supervisor-claude.log
   ```

2. Try running the loop script directly to see the error:
   ```bash
   ./scripts/autopilot/manager_loop.sh --once --cli codex --project-root . --cli-timeout 5
   ```

3. Fix the underlying issue and restart.

## Restart Loop (Supervisor Keeps Restarting)

### Symptom

Supervisor restarts a process repeatedly because it crashes immediately after launch.

### Current behavior

The supervisor now includes monitor/restart behavior with bounded retry controls. If a process repeatedly fails, inspect its supervisor log and lane configuration before forcing more restarts.

### If you're in a repeated restart loop

Stop and diagnose:

```bash
./scripts/autopilot/supervisor.sh stop
cat .autopilot-logs/supervisor-<process>.log | tail -20
```

Common causes of repeated crashes:
- MCP server not running or misconfigured
- API key expired or rate limited
- Disk full (can't write logs)
- Corrupted state files

## Process Running But Not Making Progress

### Symptom

`status` shows `running` but no new log files appear, or tasks are not being claimed/completed.

### Cause

The loop script is alive but the CLI subprocess is hung or producing no output.

### Fix

1. Check when the last log file was created:
   ```bash
   ls -lt .autopilot-logs/manager-*.log | head -3
   ls -lt .autopilot-logs/worker-*.log | head -3
   ```

2. Check if the loop's `--cli-timeout` is too long (process is waiting for a slow CLI call):
   ```bash
   grep 'CLI timeout' .autopilot-logs/supervisor-manager.log
   ```

3. If truly stuck, kill and restart the specific process:
   ```bash
   kill "$(cat .autopilot-pids/claude.pid)"
   rm -f .autopilot-pids/claude.pid .autopilot-pids/claude.restarts
   # Restart just that worker:
   nohup ./scripts/autopilot/worker_loop.sh \
     --cli claude --agent claude_code --project-root . --cli-timeout 600 \
     >> .autopilot-logs/supervisor-claude.log 2>&1 &
   echo $! > .autopilot-pids/claude.pid
   echo 0 > .autopilot-pids/claude.restarts
   ```

## Cleanup/Reset

### Full reset (nuclear option)

Stop everything and remove all supervisor artifacts:

```bash
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/supervisor.sh clean
```

If `stop` fails (PIDs already stale):

```bash
./scripts/autopilot/supervisor.sh clean
# Verify nothing is running:
ps aux | grep -E '(manager|worker|watchdog)_loop'
```

### Partial cleanup (keep logs)

```bash
# Remove only PID files
rm -f .autopilot-pids/*.pid .autopilot-pids/*.restarts
rmdir .autopilot-pids 2>/dev/null
```

## Quick Diagnostic Checklist

```bash
# 1. Check process status
./scripts/autopilot/supervisor.sh status

# 2. Check recent logs
ls -lt .autopilot-logs/ | head -10

# 3. Check for errors in supervisor logs
grep -i 'error\|fail\|timeout' .autopilot-logs/supervisor-*.log | tail -10

# 4. Check orchestrator status
# (from a connected CLI session)
orchestrator_status()

# 5. Run log check
./scripts/autopilot/log_check.sh

# 6. Run smoke tests
./scripts/autopilot/smoke_test.sh
```

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command reference (AUTO-M1-OPS-01)
- supervisor-pidfile-format.md — PID file conventions
- [supervisor-process-model.md](supervisor-process-model.md) — Process lifecycle and failure modes
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — General autopilot troubleshooting
- incident-triage-order.md — Ordered triage steps
