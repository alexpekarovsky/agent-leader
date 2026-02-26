# Supervisor Prototype Process Model

How the non-tmux supervisor (`supervisor.sh`) manages autopilot loop processes. This doc covers the process lifecycle, restart/backoff expectations, and coexistence with the tmux MVP.

## Process Architecture

The supervisor manages 4 background processes:

```
supervisor.sh (operator runs manually)
  │
  ├── manager    → manager_loop.sh --cli codex
  ├── claude     → worker_loop.sh --cli claude --agent claude_code
  ├── gemini     → worker_loop.sh --cli gemini --agent gemini
  └── watchdog   → watchdog_loop.sh
```

Each process is launched with `nohup` and runs in the background. The supervisor does not stay running as a daemon — it executes a command and exits.

## Process Lifecycle

### Startup

```
supervisor.sh start
  ├── Creates .autopilot-logs/ and .autopilot-pids/
  ├── For each process:
  │   ├── Check if PID file exists and process is alive → skip
  │   └── Launch with nohup, write PID file, init restart counter to 0
  └── Prints PID directory and status hint
```

### Running state

While processes run:
- Each loop script iterates independently (manager, workers, watchdog)
- Loop stderr goes to `supervisor-{process}.log`
- Per-cycle CLI output goes to timestamped log files
- No parent process monitors children (fire-and-forget)

### Shutdown

```
supervisor.sh stop
  ├── For each process:
  │   ├── Read PID from .pid file
  │   ├── Send SIGTERM
  │   ├── Wait up to 10s for exit
  │   ├── If still alive: send SIGKILL
  │   └── Remove .pid and .restarts files
  └── Prints completion message
```

### Restart

```
supervisor.sh restart
  └── Calls stop, waits 1s, then calls start
```

Restart stops all 4 processes and starts all 4. There is no per-process restart in the current prototype.

## MVP Limitations

| Limitation | Impact | Workaround |
|-----------|--------|------------|
| No auto-restart | Crashed process stays down until operator intervenes | Monitor via `status`; manual restart |
| No per-process restart | `restart` cycles all 4 processes | Stop/start individually via `kill`/`nohup` |
| No health check | `status` only checks PID liveness via `kill -0` | Check logs for recent output; run `log_check.sh` |
| PID reuse after reboot | Stale PID may match a different process | Run `clean` after reboot |
| No backoff enforcement | Restart counter is tracked but not enforced | Operator monitors `restarts` field in status |
| Fire-and-forget launch | No parent process watching children | Operator must check `status` periodically |

### What backoff tracking looks like today

The supervisor initializes a `.restarts` file per process (set to `0` on start). The current prototype does not auto-restart, so the counter never increments automatically. It's a placeholder for future auto-restart with exponential backoff.

Configuration flags (for future use):

| Flag | Default | Description |
|------|---------|-------------|
| `--max-restarts` | 5 | Maximum restart attempts before giving up |
| `--backoff-base` | 10 | Initial backoff delay in seconds |
| `--backoff-max` | 120 | Maximum backoff delay in seconds |

## Failure Modes

### Process crash

1. Loop script exits (error, panic, or signal)
2. PID file remains with the dead PID
3. `supervisor.sh status` shows `dead` for that process
4. Operator must manually restart

### Process hang

1. Loop script is alive but not making progress (stuck CLI call)
2. `supervisor.sh status` shows `running` (PID is alive)
3. Operator must check logs for timeouts or stale output
4. The loop's internal `--cli-timeout` will eventually kill the hung CLI subprocess

### Network/API failure

1. CLI calls fail due to network or rate limiting
2. Loop logs the error and retries on next iteration
3. Supervisor is unaware — it only tracks PID liveness

## Coexistence with tmux

The supervisor and tmux launcher (`team_tmux.sh`) serve different purposes and should not run simultaneously for the same project.

| Aspect | tmux (`team_tmux.sh`) | Supervisor (`supervisor.sh`) |
|--------|----------------------|----------------------------|
| Visibility | Panes show live output | Logs to files only |
| Interaction | Can attach and type in panes | No interactive access |
| Process control | `tmux kill-pane` per pane | `stop` kills all at once |
| Terminal requirement | Needs tmux installed | No terminal dependency |
| SSH disconnect survival | Survives with tmux detach | Survives via nohup |
| Per-process restart | Kill and re-run in pane | Not supported (restart = all) |

### When to use which

| Scenario | Use |
|----------|-----|
| Active development with operator monitoring | tmux |
| Headless/unattended operation | Supervisor |
| CI/CD environments | Supervisor |
| Debugging a specific loop | tmux (for live pane output) |
| Demo/presentation | tmux (visible to audience) |

### Switching between them

```bash
# From tmux to supervisor:
tmux kill-session -t agents-autopilot
./scripts/autopilot/supervisor.sh start

# From supervisor to tmux:
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/team_tmux.sh
```

Never run both at the same time — they would launch duplicate loop processes.

## Future: Auto-Restart Supervisor (Phase F)

The roadmap Phase F supervisor will add:

- Automatic restart on process exit (with backoff)
- Per-process restart commands
- Health check beyond PID liveness
- Process start time tracking (prevents PID reuse issues)
- Configuration file support

See [roadmap.md](roadmap.md) Phase F for details.

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command and flag reference
- supervisor-pidfile-format.md — PID file format and stale handling
- [supervisor-startup-profiles.md](supervisor-startup-profiles.md) — Startup configurations
- [tmux-vs-supervisor.md](tmux-vs-supervisor.md) — Feature comparison
- [roadmap.md](roadmap.md) — Phase F supervisor runtime
