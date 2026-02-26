# Supervisor Prototype Demo Runbook

Step-by-step flow for demonstrating the supervisor during milestone
review.  Each step shows the command and expected output.

## Prerequisites

- Project root: `cd /path/to/claude-multi-ai`
- CLI stubs or real CLIs (`codex`, `claude`, `gemini`) on PATH
- No existing supervisor session running

## Demo flow

### 1. Verify clean state

```bash
./scripts/autopilot/supervisor.sh status --pid-dir .autopilot-pids --log-dir .autopilot-logs
```

**Expected:**
```
Autopilot supervisor status
Project: /path/to/claude-multi-ai
PID dir: .autopilot-pids
Log dir: .autopilot-logs

  manager     stopped   pid=-         restarts=0
  claude      stopped   pid=-         restarts=0
  gemini      stopped   pid=-         restarts=0
  watchdog    stopped   pid=-         restarts=0
```

### 2. Start all processes

```bash
./scripts/autopilot/supervisor.sh start
```

**Expected:**
```
[INFO] starting all processes (project=/path/to/claude-multi-ai)
[INFO] started manager pid=NNNNN log=.autopilot-logs/supervisor-manager.log
[INFO] started claude pid=NNNNN log=.autopilot-logs/supervisor-claude.log
[INFO] started gemini pid=NNNNN log=.autopilot-logs/supervisor-gemini.log
[INFO] started watchdog pid=NNNNN log=.autopilot-logs/supervisor-watchdog.log
Supervisor started. PID dir: .autopilot-pids
```

### 3. Check status

```bash
./scripts/autopilot/supervisor.sh status
```

**Expected:** All 4 processes show `running` with numeric PIDs.

### 4. Inspect logs

```bash
# List supervisor logs
ls -la .autopilot-logs/supervisor-*.log

# Tail manager supervisor log
tail -20 .autopilot-logs/supervisor-manager.log

# Check for recent per-cycle logs
ls -lt .autopilot-logs/manager-*.log | head -5
ls -lt .autopilot-logs/watchdog-*.jsonl | head -5
```

**Expected:** Supervisor logs exist and contain loop output. Per-cycle
logs appear as the loops iterate.

### 5. Stop all processes

```bash
./scripts/autopilot/supervisor.sh stop
```

**Expected:**
```
[INFO] stopping all processes
[INFO] stopping manager pid=NNNNN
[INFO] stopped manager pid=NNNNN
...
All processes stopped.
```

### 6. Verify clean shutdown

```bash
./scripts/autopilot/supervisor.sh status
```

**Expected:** All 4 show `stopped`, no PID files remain.

### 7. Clean up artifacts

```bash
./scripts/autopilot/supervisor.sh clean
```

**Expected:** Supervisor log files removed, PID directory cleaned.

## Quick one-liner demo

For a fast end-to-end demo without pausing between steps:

```bash
./scripts/autopilot/supervisor.sh start && \
  sleep 2 && \
  ./scripts/autopilot/supervisor.sh status && \
  ./scripts/autopilot/supervisor.sh stop && \
  ./scripts/autopilot/supervisor.sh clean
```

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Full command reference
- [supervisor-test-plan.md](supervisor-test-plan.md) — Test scenarios
- [milestone-evidence-collection.md](milestone-evidence-collection.md) — Evidence capture
