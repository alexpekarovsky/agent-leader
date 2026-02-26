# Supervisor Crash-Loop Diagnosis Runbook

First-response actions when a supervisor process keeps crashing
immediately after start.

## Crash-loop indicators

- `supervisor.sh status` shows `dead` within seconds of `start`
- Supervisor log file is empty or contains only one startup line
- Repeated `stop` + `start` cycles don't fix the problem
- Restart counter (`.restarts` file) would increment each cycle
  (currently always 0 in the prototype)

## Diagnosis flow

### Step 1: Check supervisor log

```bash
cat .autopilot-logs/supervisor-{process}.log
```

Look for:
- `Missing required command:` — CLI binary not on PATH
- `Permission denied` — script or directory not accessible
- Python tracebacks — inline script errors
- Empty file — process died before producing output

### Step 2: Run the loop script directly

```bash
# Test manager loop
./scripts/autopilot/manager_loop.sh --once \
  --cli codex --project-root . --cli-timeout 30

# Test worker loop
./scripts/autopilot/worker_loop.sh --once \
  --cli claude --agent claude_code --project-root . --cli-timeout 30

# Test watchdog loop
./scripts/autopilot/watchdog_loop.sh --once \
  --log-dir .autopilot-logs --project-root .
```

If the loop script fails here, the error will be visible directly.

### Step 3: Check CLI availability

```bash
which codex && codex --version
which claude && claude --version
which gemini && gemini --version
```

If any CLI is missing, install it or update `$PATH`.

### Step 4: Check MCP configuration

```bash
cat .mcp.json | python3 -m json.tool
```

Verify the `agent-leader-orchestrator` entry exists with correct
`ORCHESTRATOR_ROOT` matching your project root.

### Step 5: Check disk and permissions

```bash
# Disk space
df -h .

# Directory permissions
ls -ld .autopilot-pids .autopilot-logs

# Write test
touch .autopilot-logs/.test && rm .autopilot-logs/.test
```

### Step 6: Check for port/resource conflicts

```bash
# Check if MCP server port is in use
lsof -i :3000 2>/dev/null  # adjust port if different

# Check if another supervisor is running
ps aux | grep supervisor
```

## Common root causes

| Cause | Indicator | Fix |
|-------|-----------|-----|
| Missing CLI | `require_cmd` error in log | Install CLI or fix PATH |
| Bad MCP config | Connection error in log | Fix `.mcp.json` |
| Disk full | Write errors in log | Free disk space |
| Permission denied | Permission errors | `chmod` / `chown` |
| Wrong project root | `project_mismatch` error | Fix `--project-root` |
| Rate limiting | Repeated timeout errors | Increase CLI timeouts |

## Recovery after diagnosis

```bash
# 1. Fix the underlying issue (install CLI, fix config, etc.)

# 2. Clean up stale state
./scripts/autopilot/supervisor.sh clean

# 3. Restart
./scripts/autopilot/supervisor.sh start

# 4. Verify
./scripts/autopilot/supervisor.sh status
```

## When to escalate

Escalate if:
- Loop script runs fine directly but crashes under supervisor
- Error messages reference internal supervisor or nohup issues
- Multiple processes crash simultaneously with different errors
- Crash persists after fixing all identifiable causes

## References

- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) — Full troubleshooting guide
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command reference
- [supervisor-file-permissions.md](supervisor-file-permissions.md) — Permission checklist
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Broader autopilot troubleshooting
