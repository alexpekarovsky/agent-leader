# Supervisor Log Naming Conventions

How supervisor log files relate to the existing `.autopilot-logs/` naming patterns. This doc prevents operator confusion when both supervisor logs and per-cycle loop logs coexist in the same directory.

## Two Log Categories

The `.autopilot-logs/` directory contains two categories of log files with different naming conventions:

| Category | Producer | Naming pattern | Lifecycle |
|----------|----------|---------------|-----------|
| **Per-cycle logs** | Loop scripts (`manager_loop.sh`, `worker_loop.sh`, `watchdog_loop.sh`) | `{role}-{cli/agent}-{timestamp}.{ext}` | One file per iteration; auto-pruned by `--max-logs` |
| **Supervisor logs** | `supervisor.sh` | `supervisor-{process}.log` | One file per process; appended across restarts; not auto-pruned |

## Per-Cycle Log Naming (Loop Scripts)

These files capture the output of a single CLI invocation during one loop iteration.

```
manager-codex-20260224-143022.log        # Manager cycle at 14:30:22
worker-claude_code-claude-20260224-143105.log  # Worker cycle at 14:31:05
watchdog-20260224-143200.jsonl           # Watchdog cycle at 14:32:00
```

Pattern: `{role}-{identifiers}-{YYYYMMDD-HHMMSS}.{ext}`

Key properties:
- **Timestamped**: each iteration creates a new file
- **Auto-pruned**: loops delete oldest files when count exceeds `--max-logs`
- **Format varies**: manager/worker use plain text (`.log`), watchdog uses JSONL (`.jsonl`)

## Supervisor Log Naming

These files capture the combined stdout/stderr of a background process managed by `supervisor.sh`.

```
supervisor-manager.log     # Manager process output
supervisor-claude.log      # Claude Code worker process output
supervisor-gemini.log      # Gemini worker process output
supervisor-watchdog.log    # Watchdog process output
```

Pattern: `supervisor-{process}.log`

Key properties:
- **Not timestamped**: one fixed-name file per process
- **Appended**: output accumulates across restarts (via `nohup >>`)
- **Not auto-pruned**: only removed by `supervisor.sh clean`
- **Always plain text**: contains the loop script's stderr output (cycle metadata, errors)

### What supervisor logs contain

Supervisor logs capture the loop script's stderr — the structured cycle lines that don't go into per-cycle log files:

```
[2026-02-24 14:30:22] [INFO] manager cycle=3 cli=codex project=/path/to/project
[2026-02-24 14:31:05] [INFO] worker cycle=7 agent=claude_code cli=claude project=/path/to/project
[2026-02-24 14:32:00] [ERROR] manager cycle timed out after 300s; see .autopilot-logs/manager-codex-20260224-143000.log
```

In tmux mode, these lines appear directly in the pane. In supervisor mode, they're captured in the supervisor log file instead.

## Side-by-Side Comparison

| Property | Per-cycle logs | Supervisor logs |
|----------|---------------|----------------|
| Producer | Loop scripts | `supervisor.sh` via `nohup` |
| Naming | Timestamped, multi-segment | Fixed name, `supervisor-` prefix |
| One file per... | Iteration | Process (entire lifetime) |
| Content | CLI output (one cycle) | Loop stderr (all cycles) |
| Growth | Bounded by `--max-logs` | Unbounded until `clean` |
| Format | `.log` or `.jsonl` | `.log` only |
| Pruning | Automatic (per-loop) | Manual (`supervisor.sh clean`) |

## Avoiding Confusion

### "Which log do I read?"

| Question | Read this |
|----------|-----------|
| What did the CLI produce last cycle? | Latest per-cycle log (`manager-codex-*.log` or `worker-*-*.log`) |
| Did the loop crash or restart? | Supervisor log (`supervisor-manager.log`) |
| Are there stale tasks? | Latest watchdog JSONL (`watchdog-*.jsonl`) |
| How many timeouts occurred? | `grep 'CLI timeout' .autopilot-logs/*.log` or `log_check.sh` |

### "Why are there so many files?"

Per-cycle logs accumulate one file per iteration (every 1-5 minutes). At default retention (`--max-logs 200`), expect up to 200 files per loop prefix. This is normal. The pruning mechanism keeps it bounded.

Supervisor logs are only 4 files total (one per process). They grow in size, not count.

### File listing with mixed types

```bash
# Show only per-cycle logs (timestamped):
ls .autopilot-logs/manager-*.log .autopilot-logs/worker-*.log .autopilot-logs/watchdog-*.jsonl

# Show only supervisor logs:
ls .autopilot-logs/supervisor-*.log

# Count by category:
echo "Per-cycle: $(ls .autopilot-logs/{manager,worker}-*.log .autopilot-logs/watchdog-*.jsonl 2>/dev/null | wc -l)"
echo "Supervisor: $(ls .autopilot-logs/supervisor-*.log 2>/dev/null | wc -l)"
```

## PID and Restart Counter Files

`supervisor.sh` also creates metadata files in `.autopilot-pids/` (not in `.autopilot-logs/`):

| Pattern | Content |
|---------|---------|
| `{process}.pid` | Process ID of the running background job |
| `{process}.restarts` | Restart count (integer) |

These are cleaned up by `supervisor.sh clean` alongside the supervisor log files.

## References

- [log-file-taxonomy.md](log-file-taxonomy.md) — Full log naming patterns and JSONL schema
- [log-retention-tuning.md](log-retention-tuning.md) — Per-loop retention configuration
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor commands including `clean`
