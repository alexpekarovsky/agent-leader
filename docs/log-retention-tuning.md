# Log Retention Tuning

How to configure log file retention for autopilot loops. Each loop prunes its own logs after every iteration using the `prune_old_logs` helper from `common.sh`.

## Default Retention Limits

| Loop | Flag | Default | Prefix pattern |
|------|------|---------|----------------|
| Manager | `--max-logs` | 200 | `manager-*` |
| Worker | `--max-logs` | 200 | `worker-{agent}-*` |
| Watchdog | `--max-logs` | 400 | `watchdog-*` |

Supervisor logs (`supervisor-*.log`) are not auto-pruned. Use `supervisor.sh clean` to remove them.

## Setting Custom Limits

### Individual loops

```bash
# Manager with 50 log files max
./scripts/autopilot/manager_loop.sh --cli codex --project-root . --max-logs 50

# Worker with 100 log files max
./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code --project-root . --max-logs 100

# Watchdog with 200 files max
./scripts/autopilot/watchdog_loop.sh --project-root . --max-logs 200
```

### Via team_tmux.sh

`team_tmux.sh` does not pass `--max-logs` to loop scripts — they use their defaults. To customize, run loops individually or modify the script.

### Via supervisor.sh

`supervisor.sh` also uses loop script defaults. Custom retention requires modifying `proc_cmd()` in the script or running loops individually.

## How Pruning Works

After each iteration, the loop calls:

```bash
prune_old_logs "$LOG_DIR" "$PREFIX" "$MAX_LOG_FILES"
```

The `prune_old_logs` function (in `common.sh`):

1. Lists all files matching `{prefix}*` in the log directory
2. Sorts by modification time (newest first)
3. If count exceeds `--max-logs`, deletes the oldest files
4. Leaves the newest `--max-logs` files intact

### Key behaviors

- **Per-prefix isolation**: Manager pruning only touches `manager-*` files. Worker pruning only touches `worker-{agent}-*` files. They never interfere with each other.
- **Newest-first retention**: The most recent files are always kept.
- **Post-iteration only**: Pruning happens after each loop cycle completes, not continuously.
- **No global limit**: There is no combined limit across all loop types. Each loop manages its own files independently.

## Sizing Guidelines

| Scenario | Recommended `--max-logs` | Rationale |
|----------|--------------------------|-----------|
| Development/debugging | 20-50 | Low volume, fast iteration |
| Normal operation | 200 (default) | Covers several hours of history |
| Long-running unattended | 400-1000 | Preserves more history for post-incident review |
| CI/testing | 3-10 | Minimize disk usage in ephemeral environments |

### Disk usage estimation

Each manager/worker log is typically 1-50 KB (depends on CLI output volume). Watchdog JSONL files are usually under 5 KB each.

At default limits:
- Manager: ~200 files x ~20 KB = ~4 MB
- Worker (per agent): ~200 files x ~30 KB = ~6 MB
- Watchdog: ~400 files x ~3 KB = ~1.2 MB
- **Total**: ~15-20 MB for a typical setup

## Verifying Retention

Check current file counts:

```bash
ls .autopilot-logs/manager-*.log 2>/dev/null | wc -l
ls .autopilot-logs/worker-claude_code-*.log 2>/dev/null | wc -l
ls .autopilot-logs/watchdog-*.jsonl 2>/dev/null | wc -l
```

Run `log_check.sh` for a summary:

```bash
./scripts/autopilot/log_check.sh
```

## References

- [docs/log-file-taxonomy.md](log-file-taxonomy.md) — Log naming patterns and formats
- [docs/operator-runbook.md](operator-runbook.md) — Log inspection procedures
- [docs/supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor clean command
