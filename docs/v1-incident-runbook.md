# v1.0 Incident, Recovery, and Resume Runbook

Focused incident response procedures for the agent-leader orchestrator.
For general launch/restart operations, see [operator-runbook.md](operator-runbook.md).

---

## 1. Stale Task Recovery

### Symptoms

- Tasks stuck in `in_progress` for >15 minutes
- Watchdog JSONL emits `kind: stale_task` entries
- `orchestrator_status` shows tasks with stale owners
- Workers idle despite assigned tasks existing

### Diagnosis

```bash
# 1. Check watchdog for stale task alerts
grep '"stale_task"' .autopilot-logs/watchdog-*.jsonl | tail -10

# 2. List in-progress tasks via MCP (from any connected CLI)
orchestrator_list_tasks(status="in_progress")

# 3. Check which agents are actually alive
orchestrator_list_agents(active_only=false)
```

Compare task owners against active agents. If the owner's `last_seen` is
stale (>600s), the task is orphaned.

### Automated Recovery

The manager cycle includes automatic stale reassignment. To trigger it
manually:

```
# Reassign tasks from agents not seen in 600s (default threshold)
orchestrator_reassign_stale_tasks(stale_after_seconds=600)
```

This moves `in_progress` and `blocked` tasks from stale owners back to
`assigned` status, sets `degraded_comm=true`, and emits an event so the
next active worker can claim them.

For expired leases specifically:

```
orchestrator_recover_expired_task_leases()
```

This requeues any task whose lease TTL has elapsed, regardless of agent
heartbeat status.

### Manual Recovery

If automated reassignment doesn't apply (e.g., the agent is technically
alive but hung):

```
# Reset a specific task to assigned (available for re-claim)
orchestrator_update_task_status(
  task_id="TASK-xxx",
  status="assigned",
  source="operator",
  note="manual recovery: worker hung"
)
```

### Post-Recovery Verification

```
# Confirm the task is back in the queue
orchestrator_list_tasks(status="assigned")

# Watch the next worker cycle claim it
# (check worker logs within ~30s)
ls -lt .autopilot-logs/worker-*.log | head -3
```

### Prevention

- **Lease renewal**: Workers should call `orchestrator_renew_task_lease`
  during long-running tasks (default TTL is 300s)
- **Heartbeat**: Workers must call `orchestrator_heartbeat` at least once
  per `heartbeat_timeout_minutes` (default 10)
- **Watchdog**: Keep `watchdog_loop.sh` running; it detects stale tasks
  at thresholds of 180s (assigned), 900s (in_progress), and 180s (reported)

---

## 2. Agent Reconnection After Crash

### Symptoms

- Agent process exited unexpectedly (OOM, signal, CLI crash)
- `orchestrator_list_agents` shows agent as stale or offline
- Worker pane in tmux shows exit code or blank
- No new log files appearing for the agent

### Diagnosis

```bash
# 1. Check if the process is still running
ps aux | grep -E '(manager|worker|watchdog)_loop'

# 2. Check the agent's last log
ls -lt .autopilot-logs/worker-claude_code-*.log | head -3
cat "$(ls -t .autopilot-logs/worker-claude_code-claude-*.log | head -1)" | tail -30

# 3. Check supervisor status (if using supervisor mode)
./scripts/autopilot/supervisor.sh status

# 4. Check agent status in orchestrator
orchestrator_list_agents(active_only=false)
```

### Recovery: tmux Mode

```bash
# Identify the pane (default layout: 0=manager, 1=claude, 2=gemini, 3=watchdog)
tmux list-panes -t agents-autopilot:manager

# Restart the crashed worker
tmux send-keys -t agents-autopilot:manager.1 \
  "./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code \
   --project-root /path/to/project --interval 25 --cli-timeout 600 \
   --log-dir .autopilot-logs" Enter
```

### Recovery: Supervisor Mode

```bash
# If supervisor detects the crash, it auto-restarts (bounded retries)
# Check if restart happened:
./scripts/autopilot/supervisor.sh status

# If the process shows 'dead' — stale PID file
./scripts/autopilot/supervisor.sh clean
./scripts/autopilot/supervisor.sh start
```

If the supervisor is in a restart loop (repeated crash-on-start):

```bash
# Stop everything first
./scripts/autopilot/supervisor.sh stop

# Check the supervisor log for root cause
cat .autopilot-logs/supervisor-claude.log | tail -20

# Common causes:
# - API key expired or rate-limited
# - MCP server not running
# - Disk full (can't write logs)
# - Corrupted state files (see section 3)
```

### Recovery: Standalone Worker

```bash
# Restart a single worker outside tmux/supervisor
./scripts/autopilot/worker_loop.sh \
  --cli claude --agent claude_code \
  --project-root /path/to/project \
  --interval 25 --cli-timeout 600
```

### What Happens on Reconnection

1. The worker loop calls `orchestrator_connect_to_leader(agent, metadata)`
2. The engine verifies the agent's `project_root` matches `ORCHESTRATOR_ROOT`
3. A new `instance_id` is assigned for the new session
4. The old instance is marked stale; its in-progress tasks become
   eligible for reassignment via `reassign_stale_tasks`
5. The worker resumes polling and claiming from the current queue

No manual state cleanup is needed after reconnection. The orchestrator
handles instance transitions automatically.

### Reconnection Failures

| Error | Cause | Fix |
|-------|-------|-----|
| `project_mismatch` | Worker `cwd` doesn't match `ORCHESTRATOR_ROOT` | Pass correct `--project-root` |
| `identity_verification_failed` | Metadata incomplete | Ensure metadata includes `client`, `model`, `cwd`, `session_id` |
| CLI hangs on connect | MCP server unreachable | Check `claude mcp list \| grep agent-leader`; reinstall if missing |

---

## 3. State Corruption Detection and Repair

### State File Inventory

| File | Expected Format | Location |
|------|----------------|----------|
| `tasks.json` | JSON array `[...]` | `state/tasks.json` |
| `agents.json` | JSON object `{...}` | `state/agents.json` |
| `bugs.json` | JSON array `[...]` | `state/bugs.json` |
| `blockers.json` | JSON array `[...]` | `state/blockers.json` |
| `consults.json` | JSON array `[...]` | `state/consults.json` |
| `roles.json` | JSON object `{...}` | `state/roles.json` |
| `event_cursors.json` | JSON object `{...}` | `state/event_cursors.json` |
| `schema_meta.json` | JSON object `{...}` | `state/schema_meta.json` |
| `events.jsonl` | JSONL (one object per line) | `bus/events.jsonl` |
| `audit.jsonl` | JSONL (one object per line) | `bus/audit.jsonl` |

### Detection

#### Automatic (Watchdog)

The watchdog loop reads state files every 15s and emits diagnostics:

```bash
# Check for corruption alerts
grep '"state_corruption_detected"' .autopilot-logs/watchdog-*.jsonl | tail -5
```

#### Automatic (Engine)

The engine's `_read_json_list()` auto-repairs type mismatches on read:
- If a list-type file (bugs, blockers) contains `{}`, it returns `[]`
- This is a soft heal — the file on disk may still be wrong until next write

#### Manual Check

```bash
# Validate all state files parse correctly
python3 -c "
import json, sys
from pathlib import Path
errors = []
for f in Path('state').glob('*.json'):
    try:
        data = json.loads(f.read_text())
        kind = type(data).__name__
        print(f'  OK  {f.name} ({kind}, {len(data)} entries)')
    except Exception as e:
        errors.append(f)
        print(f'FAIL  {f.name}: {e}')
if errors:
    print(f'\n{len(errors)} corrupted file(s) found')
    sys.exit(1)
else:
    print('\nAll state files valid')
"
```

### Repair

#### Type Mismatch (dict where list expected)

```bash
# Fix bugs.json or blockers.json containing {} instead of []
echo '[]' > state/bugs.json
echo '[]' > state/blockers.json
```

#### Truncated or Malformed JSON

```bash
# Back up first
cp state/tasks.json state/tasks.json.bak

# If the file is salvageable, try Python repair
python3 -c "
import json
from pathlib import Path
f = Path('state/tasks.json')
raw = f.read_text().strip()
# Try parsing as-is
try:
    data = json.loads(raw)
    print(f'File is valid ({len(data)} entries)')
except json.JSONDecodeError as e:
    print(f'Parse error at position {e.pos}: {e.msg}')
    # Common fix: truncated array — try adding closing bracket
    if raw and not raw.endswith(']'):
        try:
            data = json.loads(raw + ']')
            f.write_text(json.dumps(data, indent=2))
            print(f'Repaired by closing array ({len(data)} entries)')
        except:
            print('Cannot auto-repair; restore from backup')
"
```

#### Complete File Loss

If `tasks.json` is deleted or empty, the orchestrator will start with an
empty task list. To restore from git:

```bash
git checkout HEAD -- state/tasks.json
```

Or from the event bus audit trail (last resort):

```bash
# The bus/audit.jsonl contains all state mutations
# Review it to reconstruct state if needed
tail -100 bus/audit.jsonl | python3 -m json.tool
```

### Concurrency Protection

State files are protected by `fcntl.flock()` on `state/.state.lock`.
Corruption typically occurs when:

- Multiple MCP server instances write to the same state directory
- A process is killed mid-write (SIGKILL during JSON serialization)
- Disk runs out of space during a write

**Prevention**: ensure only one MCP server instance manages each state
directory. Check with:

```bash
# Look for multiple orchestrator processes
ps aux | grep orchestrator_mcp_server | grep -v grep
```

### Schema Migration After Repair

If you manually edited state files, verify schema version consistency:

```python
from orchestrator.migration import detect_schema_version, migrate_state
from pathlib import Path

version = detect_schema_version(Path("state"))
print(f"Current schema version: {version}")

# Re-run migration if needed (idempotent)
report = migrate_state(Path("state"), Path("bus"))
print(report)
```

---

## 4. Budget Exhaustion and Headless Restart

### How Budget Works

Each worker/manager loop tracks a daily call budget via counter files:

- **Location**: `.autopilot-logs/.budget-<key>-<YYYYMMDD>.count`
- **Default budget**: 100 calls/day per worker, 200 calls/day for manager
- **Reset**: automatic at midnight (new date = new counter file)
- **Behavior on exhaustion**: loop exits cleanly with a WARN log

### Detecting Budget Exhaustion

```bash
# Check current budget counters
cat .autopilot-logs/.budget-*-$(date '+%Y%m%d').count 2>/dev/null

# Check if a worker exited due to budget
grep 'daily call budget exhausted' .autopilot-logs/worker-*.log | tail -5
grep 'daily call budget exhausted' .autopilot-logs/manager-*.log | tail -5

# Check supervisor — exhausted workers show as 'dead'
./scripts/autopilot/supervisor.sh status
```

### Recovery Options

#### Option A: Wait for Daily Reset

Budget resets at midnight (new date). No action needed — the next day's
first cycle starts a fresh counter. The supervisor will restart the
process automatically if configured.

#### Option B: Increase Budget and Restart

```bash
# Stop the exhausted worker
tmux send-keys -t agents-autopilot:manager.1 C-c

# Restart with a higher budget
tmux send-keys -t agents-autopilot:manager.1 \
  "./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code \
   --project-root /path/to/project --daily-call-budget 200 \
   --interval 25 --cli-timeout 600 --log-dir .autopilot-logs" Enter
```

#### Option C: Reset Today's Counter

```bash
# Find and reset the counter file
echo 0 > ".autopilot-logs/.budget-worker-claude-claude_code-$(date '+%Y%m%d').count"

# Then restart the worker loop
```

### Headless Swarm Restart After Failure

When the entire headless swarm needs to be restarted (e.g., after a
system reboot, general failure, or configuration change):

#### Via MCP Tools

```
# Check current status
orchestrator_headless_status()

# Stop all processes
orchestrator_headless_stop()

# Clean stale artifacts
orchestrator_headless_clean()

# Restart
orchestrator_headless_start()

# Or combined restart (stop + start)
orchestrator_headless_restart()
```

#### Via Supervisor Script

```bash
# Check what's running
./scripts/autopilot/supervisor.sh status

# Clean restart
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/supervisor.sh clean    # remove stale PIDs
./scripts/autopilot/supervisor.sh start

# Or use the tmux launcher for a fresh session
tmux kill-session -t agents-autopilot 2>/dev/null
./scripts/autopilot/team_tmux.sh --project-root /path/to/project
```

#### After System Reboot

PIDs from before the reboot are invalid. Always clean first:

```bash
./scripts/autopilot/supervisor.sh clean
./scripts/autopilot/supervisor.sh start
```

#### Post-Restart Verification

After any restart, verify the swarm is healthy:

```bash
# 1. Process-level health
./scripts/autopilot/supervisor.sh status

# 2. Orchestrator integration health
orchestrator_parity_smoke()

# 3. Agent connectivity
orchestrator_list_agents(active_only=true)

# 4. Task pipeline
orchestrator_list_tasks(status="in_progress")
orchestrator_list_tasks(status="assigned")

# 5. Check for orphaned tasks from before the restart
orchestrator_reassign_stale_tasks(stale_after_seconds=600)
```

---

## 5. Blocker Escalation

### When to Raise a Blocker

Workers raise blockers when they cannot proceed without a decision:

- Missing credentials or API keys
- Ambiguous requirements needing manager clarification
- Dependency on another task that must complete first
- Test infrastructure unavailable

### Raising a Blocker (Worker)

```
orchestrator_raise_blocker(
  task_id="TASK-xxx",
  agent="claude_code",
  question="API key for staging environment expired; need rotation",
  severity="high"
)
```

The task moves to `blocked` status. The event bus notifies the manager.

### Resolving a Blocker (Manager/Operator)

```
# List open blockers
orchestrator_list_blockers(status="open")

# Resolve with a decision
orchestrator_resolve_blocker(
  blocker_id="BLK-xxx",
  resolution="Key rotated; new value deployed to CI env vars",
  source="operator"
)
```

The task moves back to `assigned`, and the next worker cycle can reclaim it.

### Auto-Resolution

The manager cycle auto-resolves certain meta-blockers:

- **Watchdog blockers**: raised by automated stale detection
- **Stale task blockers**: from reassignment events
- **Project mismatch blockers**: from connection failures

These are resolved by `orchestrator_auto_resolve_stale_blockers()` during
the manager cycle. No operator action needed for these types.

### Stuck Blockers

If a blocker remains open for >30 minutes:

1. Check `orchestrator_list_blockers(status="open")` for the question
2. Determine if it requires human intervention (credentials, external service)
3. If it's a false positive, resolve it manually
4. If it needs human action, handle the root cause, then resolve the blocker

---

## 6. Quick Reference: Incident Triage Order

When something is wrong and you're not sure what, follow this order:

```
1. orchestrator_parity_smoke()          # Overall health check
2. ./scripts/autopilot/supervisor.sh status  # Process health
3. orchestrator_list_agents(active_only=false)  # Agent health
4. orchestrator_list_blockers(status="open")    # Stuck tasks
5. orchestrator_list_tasks(status="in_progress")  # Active work
6. grep '"stale_task"' .autopilot-logs/watchdog-*.jsonl | tail -5  # Stale alerts
7. ./scripts/autopilot/log_check.sh --strict    # Log health
```

If `parity_smoke` passes and agents are active, the system is healthy.
Work through the remaining checks only if something is failing.

---

## References

- [operator-runbook.md](operator-runbook.md) -- Launch, restart, general operations
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) -- Symptom-based lookup matrix
- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) -- Supervisor-specific issues
- [state-migration-runbook.md](state-migration-runbook.md) -- Schema versioning and migration
- [lease-operator-expectations.md](lease-operator-expectations.md) -- Lease lifecycle reference
- [operator-alert-taxonomy.md](operator-alert-taxonomy.md) -- Alert classification and severity
