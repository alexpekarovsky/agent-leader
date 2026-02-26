# Supervisor Prototype State Directory Layout

Expected directories and files for the supervisor prototype, covering
creation, update, and removal lifecycle.

## Directory structure

```
{project-root}/
  .autopilot-pids/              # PID tracking directory
    manager.pid                 # Manager process PID
    manager.restarts            # Manager restart counter
    claude.pid                  # Claude worker PID
    claude.restarts             # Claude restart counter
    gemini.pid                  # Gemini worker PID
    gemini.restarts             # Gemini restart counter
    watchdog.pid                # Watchdog process PID
    watchdog.restarts           # Watchdog restart counter

  .autopilot-logs/              # Log output directory
    supervisor-manager.log      # Manager nohup stdout/stderr
    supervisor-claude.log       # Claude worker nohup stdout/stderr
    supervisor-gemini.log       # Gemini worker nohup stdout/stderr
    supervisor-watchdog.log     # Watchdog nohup stdout/stderr
    manager-YYYY-MM-DD-HHMMSS.log    # Per-cycle manager logs
    claude-YYYY-MM-DD-HHMMSS.log     # Per-cycle worker logs
    gemini-YYYY-MM-DD-HHMMSS.log     # Per-cycle worker logs
    watchdog-YYYY-MM-DD-HHMMSS.jsonl  # Per-cycle watchdog JSONL
```

## File lifecycle

### PID files (`.autopilot-pids/*.pid`)

| Event | Action | Command |
|-------|--------|---------|
| Created | `supervisor.sh start` writes PID after `nohup` launch | Automatic |
| Read | `supervisor.sh status` reads PID and checks `kill -0` | Automatic |
| Removed | `supervisor.sh stop` removes after process exits | Automatic |
| Stale cleanup | `supervisor.sh clean` removes if `kill -0` fails | Manual |

**Content**: Single line containing the numeric PID (e.g., `12345`).

### Restart counter files (`.autopilot-pids/*.restarts`)

| Event | Action | Command |
|-------|--------|---------|
| Created | `supervisor.sh start` writes `0` | Automatic |
| Updated | Future auto-restart increments on each restart | Not yet implemented |
| Removed | `supervisor.sh stop` removes alongside PID file | Automatic |
| Stale cleanup | `supervisor.sh clean` removes alongside stale PID | Manual |

**Content**: Single line containing a non-negative integer (e.g., `0`).

### Supervisor logs (`.autopilot-logs/supervisor-*.log`)

| Event | Action | Command |
|-------|--------|---------|
| Created | `supervisor.sh start` redirects nohup output | Automatic |
| Appended | Loop script stdout/stderr captured continuously | Automatic |
| Removed | `supervisor.sh clean` removes all supervisor logs | Manual |

### Per-cycle logs (`.autopilot-logs/{role}-*.log`)

| Event | Action | Command |
|-------|--------|---------|
| Created | Loop script writes one file per cycle iteration | Automatic |
| Pruned | `prune_old_logs` removes oldest beyond `--max-logs` | Automatic |
| Removed | Not removed by supervisor commands | Manual cleanup |

## Collision handling

### Concurrent supervisors

Running two supervisors with the same `--pid-dir` is unsupported.
The second `start` will see existing PID files and skip processes
("already running").

To run two independent supervisor instances, use separate directories:

```bash
# Instance A
supervisor.sh start --pid-dir .pids-a --log-dir .logs-a

# Instance B
supervisor.sh start --pid-dir .pids-b --log-dir .logs-b
```

### Shared log directory

Multiple supervisors can write to the same `--log-dir` if they use
different `--pid-dir` values.  Supervisor log filenames include the
process role, so they will overwrite each other.  Use separate log
directories for independent instances.

### PID reuse after crash

If a process dies and the OS reuses its PID, `supervisor.sh status`
may show `running` for a different process.  This is a known
limitation.  Run `supervisor.sh clean` after crashes to reset.

## Path configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--pid-dir` | `{project-root}/.autopilot-pids` | PID and restart counter storage |
| `--log-dir` | `{project-root}/.autopilot-logs` | All log file storage |
| `--project-root` | Repository root | Base for default paths |

Both directories are created automatically by `supervisor.sh start`
if they don't exist.

## Checklist

After supervisor start:

- [ ] `.autopilot-pids/` exists with 4 `.pid` files and 4 `.restarts` files
- [ ] `.autopilot-logs/` exists with 4 `supervisor-*.log` files
- [ ] Each `.pid` file contains a numeric PID
- [ ] Each `.restarts` file contains `0`
- [ ] `kill -0 $(cat .autopilot-pids/manager.pid)` succeeds

After supervisor stop:

- [ ] `.autopilot-pids/` is empty or removed
- [ ] No `.pid` or `.restarts` files remain
- [ ] Supervisor logs still exist (not removed by stop)

After supervisor clean:

- [ ] Stale `.pid` files removed (dead processes only)
- [ ] `supervisor-*.log` files removed
- [ ] Running process PID files preserved (with WARN)

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command and flag reference
- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) — Stale PID recovery
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — PID reuse limitation
