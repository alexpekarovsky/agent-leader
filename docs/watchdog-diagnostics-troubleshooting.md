# Watchdog Diagnostics Troubleshooting

How to interpret watchdog JSONL diagnostics and what operator actions to take for each kind.

## Reading Watchdog Output

Watchdog logs are written to `.autopilot-logs/watchdog-{YYYYMMDD-HHMMSS}.jsonl`. Each line is a JSON object with a `kind` field identifying the diagnostic type.

```bash
# View latest diagnostics
cat "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)" | python3 -m json.tool

# Filter by kind
grep '"stale_task"' .autopilot-logs/watchdog-*.jsonl | tail -10
grep '"state_corruption_detected"' .autopilot-logs/watchdog-*.jsonl | tail -5
```

## Diagnostic: `stale_task`

A task has been in a non-terminal status longer than its configured timeout.

### Example entry

```json
{
  "timestamp": "2026-02-25T14:30:00+00:00",
  "kind": "stale_task",
  "task_id": "TASK-abc123",
  "owner": "claude_code",
  "status": "in_progress",
  "age_seconds": 1200,
  "timeout_seconds": 900,
  "title": "Implement feature X"
}
```

### Interpreting by status

| Status | Default timeout | What it means | Likely cause |
|--------|----------------|---------------|--------------|
| `assigned` | 180s | Task assigned but not claimed | Worker hasn't started; may be idle or crashed |
| `in_progress` | 900s | Task claimed but not reported | Worker is stuck, crashed, or the task is very complex |
| `reported` | 180s | Report submitted but not validated | Manager hasn't run a validation cycle |

Tasks in `done` or `blocked` status are never flagged as stale.

### Operator actions by status

**Stale `assigned` task:**
1. Check if the assigned worker is alive: `supervisor.sh status` or check the tmux pane
2. If the worker is running, it may be working on a different task — wait for it to finish
3. If the worker is dead, restart it and the task will be claimed on the next cycle
4. If needed, reassign: `orchestrator_reassign_stale_tasks(stale_after_seconds=300)`

**Stale `in_progress` task:**
1. Check the worker's log file for errors or timeout markers
2. If the worker crashed: restart it. The task stays `in_progress` — the watchdog will keep flagging it
3. To reset the task for re-claim: `orchestrator_update_task_status(task_id="TASK-xxx", status="assigned", source="operator")`
4. If the task is genuinely complex and the worker is still working, increase the timeout: `--inprogress-timeout 1800`

**Stale `reported` task:**
1. Check if the manager loop is running
2. The manager should validate on its next cycle — this is usually transient
3. If the manager is stuck, restart it
4. Manual validation: `orchestrator_validate_task(task_id="TASK-xxx", passed=true, notes="manual", source="operator")`

### When stale tasks are expected

- During initial startup — tasks get assigned before workers connect
- After a restart — previously in-progress tasks haven't been re-claimed yet
- With long-running tasks — increase timeouts rather than treating every flag as an error

## Diagnostic: `state_corruption_detected`

A state file contains an unexpected data type (e.g., a dict `{}` where a list `[]` is expected).

### Example entry

```json
{
  "timestamp": "2026-02-25T14:30:00+00:00",
  "kind": "state_corruption_detected",
  "path": "/path/to/project/state/bugs.json",
  "previous_type": "dict",
  "expected_type": "list"
}
```

### Files checked

The watchdog checks `state/bugs.json` and `state/blockers.json`. Both should contain JSON arrays (`[]`).

### What causes corruption

| Cause | Description |
|-------|-------------|
| Concurrent writes | Two MCP calls writing to the same file simultaneously (rare) |
| Partial write | Process killed mid-write, leaving truncated JSON |
| Manual editing | Operator accidentally wrote `{}` instead of `[]` |

### Operator actions

**Usually no action needed.** The orchestrator engine's `_read_json_list` method auto-repairs corrupted list files on the next MCP read. It detects dict-where-list-expected and converts to a list containing the dict.

If corruption persists across multiple watchdog cycles:

1. Stop all loops: `supervisor.sh stop` or `tmux kill-session -t agents-autopilot`
2. Fix manually:
   ```bash
   echo '[]' > state/bugs.json
   echo '[]' > state/blockers.json
   ```
3. Restart loops

### Verifying repair

After the engine auto-repairs, the next watchdog cycle should show no `state_corruption_detected` entries. Check:

```bash
# Latest watchdog file should have no corruption entries
grep '"state_corruption_detected"' "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)"
```

No output = no corruption.

## Watchdog Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--assigned-timeout` | 180 | Seconds before flagging assigned tasks |
| `--inprogress-timeout` | 900 | Seconds before flagging in-progress tasks |
| `--reported-timeout` | 180 | Seconds before flagging reported tasks |
| `--interval` | 15 | Seconds between watchdog cycles |
| `--max-logs` | 400 | Maximum watchdog JSONL files to retain |

## Using log_check.sh for Diagnostics

The `log_check.sh` script provides a summary view of watchdog diagnostics:

```bash
./scripts/autopilot/log_check.sh
```

This shows:
- Count and kinds of recent diagnostics
- Malformed JSONL detection
- Stale log age warnings

Use `--strict` for CI validation (exits non-zero on errors).

## References

- [docs/log-file-taxonomy.md](log-file-taxonomy.md) — JSONL format and field descriptions
- [docs/troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Broader troubleshooting tables
- [docs/operator-runbook.md](operator-runbook.md) — Stale task recovery procedures
