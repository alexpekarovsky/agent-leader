# Monitor Pane Interpretation Guide

How to read output from the autopilot loop scripts and when to escalate.

## Log file naming

Each loop script writes timestamped log files to `.autopilot-logs/`:

| Script | Log pattern | Example |
|--------|------------|---------|
| `manager_loop.sh` | `manager-{cli}-{timestamp}.log` | `manager-codex-20260226-001500.log` |
| `worker_loop.sh` | `worker-{agent}-{cli}-{timestamp}.log` | `worker-claude_code-claude-20260226-001530.log` |
| `watchdog_loop.sh` | `watchdog-{timestamp}.jsonl` | `watchdog-20260226-001515.jsonl` |
| `monitor_loop.sh` | (displays to terminal, no file) | — |
| `supervisor.sh` | `supervisor-{process}.log` | `supervisor-claude.log` |

## Normal output patterns

### Manager loop (`manager_loop.sh`)

```
[INFO] manager cycle=1 cli=codex project=/Users/alex/claude-multi-ai
[INFO] manager cycle complete; log=.autopilot-logs/manager-codex-20260226-001500.log
```

**Healthy signs:**
- `cycle=N` increments each iteration
- `manager cycle complete` appears after each cycle
- Cycle time stays under `--cli-timeout` (default 300s)

### Worker loop (`worker_loop.sh`)

```
[INFO] worker cycle=1 agent=claude_code cli=claude project=/Users/alex/claude-multi-ai
[INFO] worker cycle complete agent=claude_code; log=.autopilot-logs/worker-claude_code-claude-20260226-001530.log
```

**Healthy signs:**
- `cycle=N` increments
- `worker cycle complete` appears
- Worker logs contain task claim and report submission activity

### Watchdog (`watchdog_loop.sh`)

```
[INFO] watchdog cycle=1 project=/Users/alex/claude-multi-ai log=.autopilot-logs/watchdog-20260226-001515.jsonl
```

The watchdog writes JSONL records.  An empty `.jsonl` file means no issues detected.  Records appear only when problems are found.

### Monitor pane (`monitor_loop.sh`)

```
project=/Users/alex/claude-multi-ai

manager-codex-20260226-001500.log
worker-claude_code-claude-20260226-001530.log
watchdog-20260226-001515.jsonl
```

Shows the 10 most recent log files.  A growing list means loops are active.

## Warning and error patterns

### Timeout

```
[ERROR] manager cycle timed out after 300s; see .autopilot-logs/manager-codex-20260226-002000.log
[ERROR] worker cycle timed out agent=claude_code after 600s; see .autopilot-logs/worker-claude_code-claude-20260226-002100.log
```

**Meaning:** The CLI invocation exceeded `--cli-timeout`.  The process was killed by `timeout(1)`.

**Action:**
1. Check the referenced log file for what the CLI was doing when killed
2. If the task is complex, increase `--cli-timeout` (or use the unattended tuning profile)
3. The task may remain `in_progress` in the orchestrator — check with `orchestrator_list_tasks(status="in_progress")`

### CLI failure

```
[ERROR] manager cycle failed rc=1; see .autopilot-logs/manager-codex-20260226-002000.log
[ERROR] worker cycle failed agent=gemini rc=1; see .autopilot-logs/worker-gemini-gemini-20260226-002100.log
```

**Meaning:** The CLI exited with a non-zero code.  Common causes: API rate limit, network error, missing CLI binary.

**Action:**
1. Read the referenced log file for the error message
2. Check if the CLI binary is available (`which codex`, `which claude`, `which gemini`)
3. Check API key / credential configuration
4. The loop will retry on the next cycle

### Worker idle (no tasks)

When the worker log contains "idle", the worker found no claimable tasks.

**Action:** Normal during low-task periods.  Check `orchestrator_list_tasks` to verify tasks exist and are in a claimable state (`assigned` or unowned).

## Watchdog JSONL records

### `stale_task`

```json
{"timestamp": "2026-02-26T00:15:00Z", "kind": "stale_task", "task_id": "TASK-abc123", "owner": "claude_code", "status": "in_progress", "age_seconds": 1200, "timeout_seconds": 900}
```

**Meaning:** A task has been in its current status longer than the timeout threshold.

| Status | Default timeout | Escalation |
|--------|----------------|------------|
| `assigned` | 180s | Task was assigned but never claimed — check if the worker is running |
| `in_progress` | 900s | Task has been worked on for 15+ min — check if the worker is stuck or if the task is genuinely large |
| `reported` | 180s | Report was submitted but not validated — check if the manager cycle is running |

**Action:**
1. Run `orchestrator_list_tasks(status="in_progress")` to see current state
2. Check the worker's recent logs for errors or timeouts
3. If the worker is genuinely stuck, consider `orchestrator_reassign_stale_tasks`

### `state_corruption_detected`

```json
{"timestamp": "2026-02-26T00:15:00Z", "kind": "state_corruption_detected", "path": "state/bugs.json", "previous_type": "dict", "expected_type": "list"}
```

**Meaning:** A state file has an unexpected data type (e.g., dict instead of list).

**Action:**
1. Back up the corrupted file
2. Check recent commits that modified `state/` files
3. Fix the file manually or restore from a known-good state
4. This is rare and usually indicates a bug in a tool or concurrent write conflict

## No output / stalled loop

If a loop's log files stop appearing (no new timestamps in `.autopilot-logs/`):

1. **Check supervisor status:** `./scripts/autopilot/supervisor.sh status` — look for `dead` or `stopped`
2. **Check process directly:** `ps aux | grep manager_loop` (or `worker_loop`, `watchdog_loop`)
3. **Check supervisor log:** `tail .autopilot-logs/supervisor-claude.log` for the last error
4. **Restart if needed:** `./scripts/autopilot/supervisor.sh restart`

## When to escalate to orchestrator tools

| Symptom | Escalation command |
|---------|-------------------|
| Task stuck `in_progress` for >15 min | `orchestrator_list_tasks(status="in_progress")` |
| Worker reports idle but tasks exist | `orchestrator_get_tasks_for_agent(agent="claude_code")` |
| Manager not validating reports | `orchestrator_list_tasks(status="reported")` |
| Agent shows stale/disconnected | `orchestrator_list_agents` |
| Open blockers not being resolved | `orchestrator_list_blockers(status="open")` |
| Suspected duplicate tasks | `orchestrator_dedupe_tasks` |

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor commands and status values
- [supervisor-smoke-test-checklist.md](supervisor-smoke-test-checklist.md) — Manual verification steps
- [supervisor-restart-backoff-tuning.md](supervisor-restart-backoff-tuning.md) — Timeout tuning profiles
- [operator-runbook.md](operator-runbook.md) — Operational procedures
