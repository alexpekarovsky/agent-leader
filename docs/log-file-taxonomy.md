# Autopilot Log File Taxonomy

All autopilot logs are written to `.autopilot-logs/` in the project root. Each loop writes its own files with a distinct prefix and format.

## File Naming Patterns

| Pattern | Producer | Format | Example |
|---------|----------|--------|---------|
| `manager-{cli}-{timestamp}.log` | `manager_loop.sh` | Plain text (CLI stdout/stderr) | `manager-codex-20260224-143022.log` |
| `worker-{agent}-{cli}-{timestamp}.log` | `worker_loop.sh` | Plain text (CLI stdout/stderr) | `worker-claude_code-claude-20260224-143105.log` |
| `watchdog-{timestamp}.jsonl` | `watchdog_loop.sh` | JSONL (machine-parseable) | `watchdog-20260224-143200.jsonl` |
| `supervisor-{process}.log` | `supervisor.sh` | Plain text (background process output) | `supervisor-manager.log` |

### Timestamp format

All timestamps in filenames use `YYYYMMDD-HHMMSS` local time from `date '+%Y%m%d-%H%M%S'`.

### Agent and CLI fields

- **{cli}**: The CLI binary used (`codex`, `claude`, `gemini`)
- **{agent}**: The orchestrator agent identity (`claude_code`, `codex`, `gemini`)
- Manager logs always use `codex` as the CLI
- Worker logs include both the agent name and CLI binary since they can differ

## Plain Text Logs (manager, worker)

Manager and worker logs capture the raw stdout/stderr of the CLI process for one cycle. They contain whatever the CLI agent produced during that iteration — MCP tool calls, code output, reasoning text, and error messages.

### Timeout markers

When a CLI process exceeds its timeout (`--cli-timeout`, default 300s for manager, 600s for worker), the log ends with:

```
[AUTOPILOT] CLI timeout after {seconds}s for {cli}
```

This marker is machine-detectable. The `log_check.sh` script counts timeout occurrences across recent log files. Frequent timeouts indicate a stuck agent or overly complex task.

### Loop stderr lines

Each loop iteration also writes a structured stderr line (not captured in the log file) with cycle metadata:

```
[2026-02-24 14:30:22] [INFO] manager cycle=3 cli=codex project=/path/to/project
[2026-02-24 14:31:05] [INFO] worker cycle=7 agent=claude_code cli=claude project=/path/to/project
```

These appear in the terminal (tmux pane) or supervisor log, not in the per-cycle log files.

## JSONL Logs (watchdog)

Watchdog logs use one JSON object per line. Each record has:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 UTC timestamp |
| `kind` | string | Diagnostic type (see below) |
| *(varies)* | | Kind-specific payload fields |

### Diagnostic kinds

**`stale_task`** — A task has exceeded its status-specific age threshold.

| Field | Description |
|-------|-------------|
| `task_id` | Task identifier (e.g., `TASK-abc123`) |
| `owner` | Agent assigned to the task |
| `status` | Current task status (`assigned`, `in_progress`, `reported`) |
| `age_seconds` | How long the task has been in this status |
| `timeout_seconds` | The threshold that was exceeded |
| `title` | Task title for quick identification |

Default timeouts: `assigned` 180s, `in_progress` 900s, `reported` 180s. Configurable via `--assigned-timeout`, `--inprogress-timeout`, `--reported-timeout`.

Tasks in `done` or `blocked` status are never flagged as stale.

**`state_corruption_detected`** — A state file (`bugs.json` or `blockers.json`) contains an unexpected type (e.g., a dict where a list is expected).

| Field | Description |
|-------|-------------|
| `path` | Full path to the corrupted file |
| `previous_type` | Actual Python type found (e.g., `dict`) |
| `expected_type` | Expected type (`list`) |

The watchdog is read-only and never writes to state files. Corruption is self-healed by the engine on the next MCP read.

## Log Pruning

Each loop prunes its own log files after every iteration using `prune_old_logs()` from `common.sh`. This keeps the total file count per prefix at or below `--max-logs` (default 200 for manager/worker, 400 for watchdog).

Pruning behavior:
- Files matching the loop's prefix are sorted by modification time (newest first)
- Files beyond the limit are deleted oldest-first
- Pruning is per-prefix, not global — each loop only touches its own files
- The `--max-logs` flag controls the per-prefix limit for each loop script

Supervisor logs (`supervisor-*.log`) are not auto-pruned by loops. Use `supervisor.sh clean` to remove them after stopping processes.

## Operator Review Order

During an incident, review logs in this order:

1. **Watchdog JSONL** (`watchdog-*.jsonl`) — Check for `stale_task` and `state_corruption_detected` entries. These give the fastest machine-readable view of system health. Use `jq` or `log_check.sh` for parsing.

2. **Manager logs** (`manager-codex-*.log`) — Read the most recent file to see the last manager cycle. Look for task creation, validation results, execution plan events, and timeout markers.

3. **Worker logs** (`worker-{agent}-*.log`) — Check the most recent file for the stuck/failing agent. Look for MCP errors, test failures, blocker messages, and timeout markers.

4. **Supervisor logs** (`supervisor-*.log`) — Only relevant when using the non-tmux supervisor. Shows process start/stop events and any startup errors.

### Quick inspection commands

```bash
# Latest watchdog diagnostics
cat .autopilot-logs/watchdog-*.jsonl | tail -20 | jq .

# Count timeouts across all logs
grep -c '\[AUTOPILOT\] CLI timeout' .autopilot-logs/*.log

# Full diagnostic report
./scripts/autopilot/log_check.sh

# Strict mode (for CI or pre-merge checks)
./scripts/autopilot/log_check.sh --strict
```

## References

- [docs/operator-runbook.md](operator-runbook.md) — Operational procedures including log inspection
- [docs/troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Symptom/cause/action tables
- [docs/headless-mvp-architecture.md](headless-mvp-architecture.md) — Component diagram and data flow
