# tmux vs Supervisor — Runtime Comparison

The autopilot system supports two runtime modes for launching and managing loop processes. This document compares their capabilities, limitations, and helps operators choose the right one.

## Feature Comparison

| Feature | tmux (`team_tmux.sh`) | Supervisor (`supervisor.sh`) |
|---------|----------------------|------------------------------|
| Visual monitoring | Live panes with scrollback | No visual — logs only |
| Process isolation | One pane per process | One background job per process |
| Manual interaction | Can type in any pane | Cannot interact with running loops |
| Log access | Pane scrollback + log files | Log files only |
| Status check | `tmux list-panes` | `supervisor.sh status` |
| Start/stop | `tmux kill-session` or Ctrl-C per pane | `supervisor.sh stop` |
| Restart single process | Ctrl-C + re-type command in pane | Stop all + start all (no per-process restart yet) |
| Process state tracking | None (tmux just runs commands) | PID files + restart counters |
| Stale process detection | Manual (`tmux list-panes`) | `supervisor.sh status` shows `dead` |
| Cleanup after crash | Kill session manually | `supervisor.sh clean` removes stale PIDs |
| Dry-run preview | `--dry-run` shows exact commands | No dry-run (uses same loop scripts) |
| Monitor window | Dedicated log tail pane | Not available |
| Requires tmux | Yes | No |
| Headless/CI compatible | Requires `tmux` binary | Yes — pure background processes |
| SSH disconnection | Session persists (tmux detach) | Processes persist (nohup) |

## When to Use tmux

**Best for**: Interactive development, debugging, and operator-attended sessions.

- You want to watch agent output in real time
- You need to manually intervene (Ctrl-C a stuck worker, type commands)
- You want pane scrollback for recent output without opening log files
- You're debugging a specific loop's behavior
- You have tmux available and are working from a terminal

```bash
# Preview what will launch
./scripts/autopilot/team_tmux.sh --dry-run

# Launch
./scripts/autopilot/team_tmux.sh

# Attach from another terminal
tmux attach -t agents-autopilot
```

## When to Use Supervisor

**Best for**: Unattended operation, CI pipelines, and headless servers.

- You want fire-and-forget background operation
- You're running on a server without tmux or a terminal
- You want PID-based process management (status, stop, clean)
- You need to integrate with system service managers
- You want clean startup/shutdown scripts for automation

```bash
# Start all processes
./scripts/autopilot/supervisor.sh start

# Check status
./scripts/autopilot/supervisor.sh status

# Stop everything
./scripts/autopilot/supervisor.sh stop
```

## Shared Infrastructure

Both runtimes use the same underlying loop scripts:

| Component | Script | Used by both |
|-----------|--------|:------------:|
| Manager loop | `manager_loop.sh` | Yes |
| Worker loop | `worker_loop.sh` | Yes |
| Watchdog loop | `watchdog_loop.sh` | Yes |
| Common helpers | `common.sh` | Yes |
| Log directory | `.autopilot-logs/` | Yes |
| State directory | `state/` | Yes |

The loop scripts are runtime-agnostic. They don't know or care whether they're running in a tmux pane or as a background process.

## Limitations of Each

### tmux limitations

- **No PID tracking**: tmux doesn't track process PIDs — you can't query "is the manager alive?" without checking the pane
- **No restart counter**: No built-in tracking of how many times a loop has been restarted
- **No programmatic control**: Starting/stopping requires tmux commands or manual pane interaction
- **No stale cleanup**: If tmux is killed abruptly (SIGKILL), there's no cleanup mechanism

### Supervisor limitations

- **No per-process restart**: `restart` stops and starts all 4 processes — can't restart just the claude worker
- **No auto-restart on crash**: If a loop process dies, it stays dead until the operator intervenes (future enhancement)
- **No visual output**: Can't see what agents are doing without tailing log files
- **No monitor window**: The `monitor_loop.sh` is not launched by the supervisor
- **Shared supervisor log**: Each process appends to `supervisor-{name}.log` — output can interleave

## Migration Path

### Today (MVP)

Both runtimes are available and interchangeable. Use whichever fits your workflow. They should not be run simultaneously for the same project (both would launch the same loop scripts, causing duplicate processes).

### Phase B (Instance-Aware Presence)

The supervisor will gain:
- `--worker-count N` for launching multiple workers of the same CLI type
- Per-instance PID tracking (`claude-01.pid`, `claude-02.pid`)
- Per-process restart via `supervisor.sh restart claude-01`

tmux will remain available but becomes less practical with many workers (too many panes).

### Phase C (Task Leases and Recovery)

The supervisor will gain:
- Auto-restart on crash with exponential backoff
- Health check integration (process responds to signal)
- Configurable per-process restart policy

At this point, the supervisor becomes the recommended runtime for production use.

### Phase D (Deterministic Dispatch)

No runtime changes needed — dispatch improvements are in the orchestrator engine, not the process manager.

## Switching Between Runtimes

To switch from tmux to supervisor:

```bash
# Stop tmux session
tmux kill-session -t agents-autopilot

# Start supervisor
./scripts/autopilot/supervisor.sh start
```

To switch from supervisor to tmux:

```bash
# Stop supervisor
./scripts/autopilot/supervisor.sh stop

# Launch tmux session
./scripts/autopilot/team_tmux.sh
```

No state migration is needed — both runtimes use the same `state/` directory and log location.

## References

- [docs/supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor command interface
- docs/supervisor-test-plan.md — Supervisor test scenarios
- [docs/headless-mvp-architecture.md](headless-mvp-architecture.md) — Component overview
- [docs/roadmap.md](roadmap.md) — Future architecture phases
