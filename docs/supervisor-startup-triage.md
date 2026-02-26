# Supervisor Startup Failure Triage

First-response steps when `supervisor.sh start` fails. Check these scenarios in order.

## Scenario 1: Command not found

**Symptom**: `supervisor.sh: command not found` or `No such file or directory`

**Detection**:
```bash
ls -la scripts/autopilot/supervisor.sh
```

**Fix**:
```bash
# If the script exists but isn't executable:
chmod +x scripts/autopilot/supervisor.sh

# If running from wrong directory:
cd /path/to/claude-multi-ai
./scripts/autopilot/supervisor.sh start
```

## Scenario 2: common.sh missing or broken

**Symptom**: `source: scripts/autopilot/common.sh: No such file or directory`

**Detection**:
```bash
ls -la scripts/autopilot/common.sh
bash -n scripts/autopilot/common.sh  # syntax check
```

**Fix**:
```bash
# If file is missing, it may not have been checked out:
git checkout -- scripts/autopilot/common.sh

# If syntax error:
bash -n scripts/autopilot/common.sh  # shows the error location
```

## Scenario 3: CLI binary not found

**Symptom**: Process starts but immediately exits. Supervisor log shows `command not found` for codex, claude, or gemini.

**Detection**:
```bash
which codex
which claude
which gemini
```

**Fix**:
- Install the missing CLI
- Or check `$PATH` — CLIs may be installed in a location not on the supervisor's PATH
- If running via `nohup`, the PATH may differ from your interactive shell

## Scenario 4: Project root doesn't exist

**Symptom**: `--project-root` path is wrong. Logs show file-not-found errors for state files.

**Detection**:
```bash
ls -la /path/specified/as/project-root/
ls -la /path/specified/as/project-root/.mcp.json
```

**Fix**:
```bash
# Use the correct project root:
./scripts/autopilot/supervisor.sh start --project-root /correct/path

# Or run from the project root (default uses current dir):
cd /correct/path
./scripts/autopilot/supervisor.sh start
```

## Scenario 5: Permission denied on log/PID directories

**Symptom**: `mkdir: cannot create directory '.autopilot-logs': Permission denied`

**Detection**:
```bash
ls -la .autopilot-logs/ .autopilot-pids/
touch .autopilot-logs/test-write 2>&1  # test write access
```

**Fix**:
```bash
# Fix permissions:
chmod 755 .autopilot-logs .autopilot-pids

# Or use custom directories with correct permissions:
./scripts/autopilot/supervisor.sh start \
  --log-dir /tmp/autopilot-logs \
  --pid-dir /tmp/autopilot-pids
```

## Scenario 6: Stale PID files blocking start

**Symptom**: `supervisor.sh start` says processes are "already running" but they're not.

**Detection**:
```bash
./scripts/autopilot/supervisor.sh status
# Shows "running" but no actual process
cat .autopilot-pids/*.pid
ps -p $(cat .autopilot-pids/manager.pid 2>/dev/null) 2>&1
```

**Fix**:
```bash
./scripts/autopilot/supervisor.sh clean
./scripts/autopilot/supervisor.sh start
```

## Scenario 7: MCP server not configured

**Symptom**: Loops start but immediately fail with MCP connection errors.

**Detection**:
```bash
cat .mcp.json  # check MCP config exists and is valid JSON
cat .autopilot-logs/supervisor-manager.log | tail -5
```

**Fix**:
- Ensure `.mcp.json` is present and points to the correct orchestrator server
- Verify the MCP server process is running
- Check that `ORCHESTRATOR_ROOT` in the MCP config matches `--project-root`

## Scenario 8: Port or socket conflict

**Symptom**: MCP server fails to bind. Multiple supervisor instances competing.

**Detection**:
```bash
# Check for other supervisor instances:
ps aux | grep supervisor.sh
ps aux | grep -E '(manager|worker|watchdog)_loop'
```

**Fix**:
```bash
# Stop all existing instances:
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/supervisor.sh clean

# Kill any orphaned processes:
pkill -f 'manager_loop.sh'
pkill -f 'worker_loop.sh'
pkill -f 'watchdog_loop.sh'

# Restart cleanly:
./scripts/autopilot/supervisor.sh start
```

## Quick Triage Checklist

```bash
# Run these in order when start fails:

# 1. Script exists and is executable?
ls -la scripts/autopilot/supervisor.sh

# 2. Common.sh is intact?
bash -n scripts/autopilot/common.sh

# 3. CLIs are installed?
which codex && which claude && which gemini

# 4. Project root is valid?
ls .mcp.json

# 5. Directories are writable?
mkdir -p .autopilot-logs .autopilot-pids

# 6. No stale PIDs?
./scripts/autopilot/supervisor.sh clean

# 7. No competing processes?
ps aux | grep -E '(manager|worker|watchdog)_loop'

# 8. Try starting:
./scripts/autopilot/supervisor.sh start
./scripts/autopilot/supervisor.sh status
```

## References

- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) — General troubleshooting
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command reference
- [supervisor-pidfile-format.md](supervisor-pidfile-format.md) — PID file conventions
