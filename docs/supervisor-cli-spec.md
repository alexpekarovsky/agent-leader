# Supervisor CLI Interface Spec

Command interface for `scripts/autopilot/supervisor.sh` — the non-tmux process manager for autopilot loops.

## Synopsis

```
supervisor.sh <command> [options]
```

## Commands

### `start`

Start all 4 autopilot processes as background jobs with `nohup`.

| Behavior | Detail |
|----------|--------|
| Processes launched | manager, claude, gemini, watchdog |
| Idempotent | Yes — skips processes that are already running |
| Creates | PID files in `--pid-dir`, restart counter files, supervisor logs in `--log-dir` |
| Output | Prints PID dir path and status check hint |

```
$ supervisor.sh start
[INFO] starting all processes (project=/path/to/project)
[INFO] started manager pid=12345 log=.autopilot-logs/supervisor-manager.log
[INFO] started claude pid=12346 log=.autopilot-logs/supervisor-claude.log
[INFO] started gemini pid=12347 log=.autopilot-logs/supervisor-gemini.log
[INFO] started watchdog pid=12348 log=.autopilot-logs/supervisor-watchdog.log
Supervisor started. PID dir: .autopilot-pids
```

### `stop`

Stop all running processes. Sends SIGTERM, waits up to 10 seconds per process, then SIGKILL if still alive.

| Behavior | Detail |
|----------|--------|
| Signal sequence | SIGTERM → 10s wait → SIGKILL (if needed) |
| Cleans up | Removes PID files and restart counter files |
| Missing process | Logs "not running" and continues |
| SIGKILL fallback | Logs `WARN` when SIGKILL is required |

```
$ supervisor.sh stop
[INFO] stopping all processes
[INFO] stopping manager pid=12345
[INFO] stopped manager pid=12345
...
All processes stopped.
```

### `status`

Display the state of all 4 processes.

| Status value | Meaning |
|-------------|---------|
| `running` | PID file exists and process is alive (`kill -0` succeeds) |
| `stopped` | No PID file exists |
| `dead` | PID file exists but process is not alive (stale PID) |

Output columns: process name, status, PID, restart count.

```
$ supervisor.sh status
Autopilot supervisor status
Project: /path/to/project
PID dir: .autopilot-pids
Log dir: .autopilot-logs

  manager     running   pid=12345     restarts=0
  claude      running   pid=12346     restarts=0
  gemini      dead      pid=99999     restarts=0
  watchdog    stopped   pid=-         restarts=0
```

### `restart`

Stop all processes, wait 1 second, then start all processes. Equivalent to `stop && sleep 1 && start`.

### `clean`

Remove stale PID files and supervisor log files. Safe to run after `stop` or after a system reboot leaves orphaned PID files.

| Behavior | Detail |
|----------|--------|
| Stale PID detection | Checks `kill -0` on each PID — removes file if process is not alive |
| Running process | Logs `WARN` and skips (does NOT remove PID files for live processes) |
| Supervisor logs | Removes all `supervisor-*.log` files from the log directory |
| PID directory | Removes PID directory if empty after cleanup |
| Restart counters | Removes `.restarts` files alongside stale PIDs |

```
$ supervisor.sh clean
[INFO] removed stale pidfile for gemini (pid=99999)
[INFO] removed 4 supervisor log file(s)
Cleaned 5 file(s).
```

If nothing to clean:
```
$ supervisor.sh clean
Nothing to clean.
```

## Options

All options apply to every command.

| Flag | Default | Description |
|------|---------|-------------|
| `--project-root DIR` | Repository root | Project root directory passed to all loop scripts |
| `--log-dir DIR` | `{project-root}/.autopilot-logs` | Directory for all log files |
| `--pid-dir DIR` | `{project-root}/.autopilot-pids` | Directory for PID files |
| `--manager-cli-timeout N` | `300` | Manager CLI timeout in seconds |
| `--worker-cli-timeout N` | `600` | Worker CLI timeout in seconds |
| `--manager-interval N` | `20` | Seconds between manager loop iterations |
| `--worker-interval N` | `25` | Seconds between worker loop iterations |
| `--max-restarts N` | `5` | Max restarts before giving up (reserved for future auto-restart) |
| `--backoff-base N` | `10` | Base backoff seconds on restart (reserved for future auto-restart) |
| `--backoff-max N` | `120` | Max backoff seconds (reserved for future auto-restart) |

## Managed Processes

| Name | Loop script | CLI | Agent identity |
|------|------------|-----|----------------|
| `manager` | `manager_loop.sh` | codex | codex (leader) |
| `claude` | `worker_loop.sh` | claude | claude_code |
| `gemini` | `worker_loop.sh` | gemini | gemini |
| `watchdog` | `watchdog_loop.sh` | python3 (inline) | none (read-only) |

## File Layout

```
.autopilot-pids/
  manager.pid           # PID of the manager background process
  manager.restarts      # Restart counter (currently always 0)
  claude.pid
  claude.restarts
  gemini.pid
  gemini.restarts
  watchdog.pid
  watchdog.restarts

.autopilot-logs/
  supervisor-manager.log    # Captured stdout/stderr of the manager loop process
  supervisor-claude.log
  supervisor-gemini.log
  supervisor-watchdog.log
```

## Error Cases

| Scenario | Behavior |
|----------|----------|
| Start with processes already running | Logs "already running" per process, no duplicates created |
| Stop with no processes running | Logs "not running" per process, exits cleanly |
| Stop when process ignores SIGTERM | Waits 10s then sends SIGKILL, logs WARN |
| Status with stale PID file | Shows `dead` status |
| Clean with processes still running | Logs WARN per running process, does NOT remove their PID files |
| Clean with no PID directory | Exits with "Nothing to clean" |
| Unknown command | Prints usage and exits with code 1 |
| Unknown option | Logs ERROR and exits with code 1 |
| Missing CLI binary | Detected by loop script's `require_cmd`, process exits immediately |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Unknown command or unknown option |

Note: Individual process failures during `start` do not cause a non-zero exit code from the supervisor itself — the process may fail after backgrounding. Use `status` to verify.

## References

- docs/supervisor-test-plan.md — Manual test scenarios and failure injection
- [docs/headless-mvp-architecture.md](headless-mvp-architecture.md) — Component overview
- [docs/operator-runbook.md](operator-runbook.md) — Operational procedures
