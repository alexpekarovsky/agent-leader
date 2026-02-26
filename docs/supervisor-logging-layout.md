# Supervisor Logging Layout

Filesystem layout and naming conventions for supervisor logs, PID files, and health snapshots.

## Directory structure

```
{project-root}/
├── .autopilot-logs/                    # All log output (--log-dir)
│   ├── manager-codex-{ts}.log          # Manager loop per-cycle logs
│   ├── worker-claude_code-claude-{ts}.log  # Claude worker per-cycle logs
│   ├── worker-gemini-gemini-{ts}.log   # Gemini worker per-cycle logs
│   ├── watchdog-{ts}.jsonl             # Watchdog health check records
│   ├── supervisor-manager.log          # Supervisor captured stdout for manager process
│   ├── supervisor-claude.log           # Supervisor captured stdout for claude process
│   ├── supervisor-gemini.log           # Supervisor captured stdout for gemini process
│   └── supervisor-watchdog.log         # Supervisor captured stdout for watchdog process
│
├── .autopilot-pids/                    # PID tracking (--pid-dir)
│   ├── manager.pid                     # Manager process PID
│   ├── manager.restarts                # Manager restart counter (currently always 0)
│   ├── claude.pid
│   ├── claude.restarts
│   ├── gemini.pid
│   ├── gemini.restarts
│   ├── watchdog.pid
│   └── watchdog.restarts
│
└── state/                              # Orchestrator state (managed by engine)
    ├── tasks.json
    ├── agents.json
    ├── bugs.json
    ├── blockers.json
    └── events.json
```

## File naming conventions

### Timestamp format

All per-cycle logs use the pattern `{ts}` where:

```
ts = YYYYMMDD-HHMMSS    (local time, from date '+%Y%m%d-%H%M%S')
```

Example: `20260226-001530`

### Loop logs

| Script | Pattern | Example |
|--------|---------|---------|
| `manager_loop.sh` | `manager-{cli}-{ts}.log` | `manager-codex-20260226-001500.log` |
| `worker_loop.sh` | `worker-{agent}-{cli}-{ts}.log` | `worker-claude_code-claude-20260226-001530.log` |
| `watchdog_loop.sh` | `watchdog-{ts}.jsonl` | `watchdog-20260226-001515.jsonl` |

Naming is deterministic: given the CLI/agent identity and the cycle start time, the filename is unique.

### Supervisor process logs

| Process | Filename |
|---------|----------|
| manager | `supervisor-manager.log` |
| claude | `supervisor-claude.log` |
| gemini | `supervisor-gemini.log` |
| watchdog | `supervisor-watchdog.log` |

These are append-mode captured stdout/stderr from `nohup`.  They grow until `supervisor.sh clean` is run.

### PID files

| Process | PID file | Restart counter |
|---------|----------|-----------------|
| manager | `manager.pid` | `manager.restarts` |
| claude | `claude.pid` | `claude.restarts` |
| gemini | `gemini.pid` | `gemini.restarts` |
| watchdog | `watchdog.pid` | `watchdog.restarts` |

PID files contain a single integer (the process ID).  Restart counter files contain a single integer (currently always `0`, reserved for auto-restart).

## Cleanup and pruning

### Automatic pruning (per-cycle logs)

Each loop script calls `prune_old_logs` after every cycle to cap the number of per-cycle log files:

| Script | Prefix | Default max files |
|--------|--------|------------------|
| `manager_loop.sh` | `manager-` | 200 (`--max-logs`) |
| `worker_loop.sh` | `worker-{agent}-` | 200 (`--max-logs`) |
| `watchdog_loop.sh` | `watchdog-` | 400 (`--max-logs`) |

Pruning deletes the oldest files (by name sort) when the count exceeds the limit.

### Manual cleanup (`supervisor.sh clean`)

The `clean` command removes:
1. **Stale PID files** — PID files where the process is no longer running (`kill -0` fails)
2. **Restart counter files** — removed alongside their stale PID files
3. **Supervisor process logs** — all `supervisor-*.log` files from the log directory
4. **Empty PID directory** — removed with `rmdir` if no files remain

`clean` does NOT remove per-cycle loop logs (`manager-*.log`, `worker-*.log`, `watchdog-*.jsonl`).  These are managed by automatic pruning.

### Full cleanup

To remove all autopilot artifacts:

```bash
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/supervisor.sh clean
rm -rf .autopilot-logs/ .autopilot-pids/
```

## Disk space considerations

| Component | Growth rate | Control |
|-----------|------------|---------|
| Per-cycle logs | ~1 file per interval (20-25s) | `--max-logs` caps total count |
| Supervisor logs | Continuous append while running | `supervisor.sh clean` after stop |
| Watchdog JSONL | ~1 file per 15s interval | `--max-logs 400` default |
| PID files | Fixed (4 files + 4 counters) | Removed by `stop` or `clean` |

With defaults, the log directory stabilizes around 800 files (200 manager + 200 claude worker + 200 gemini worker + 400 watchdog).  At ~10KB per file, this is approximately 8MB.

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — CLI options including `--log-dir` and `--pid-dir`
- [monitor-pane-interpretation.md](monitor-pane-interpretation.md) — How to read log output
- [supervisor-smoke-test-checklist.md](supervisor-smoke-test-checklist.md) — Verifying log behavior
