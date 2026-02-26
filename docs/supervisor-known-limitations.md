# Supervisor Prototype Known Limitations

What the supervisor can and cannot solve before lease recovery and
deterministic dispatch land in AUTO-M1 core tasks.

## What the supervisor handles

| Capability | Status |
|-----------|--------|
| Start/stop all loop processes | Implemented |
| PID-based process tracking | Implemented |
| Status reporting (running/stopped/dead) | Implemented |
| Stale PID cleanup after crash | Implemented (`clean`) |
| Graceful shutdown (SIGTERM + SIGKILL fallback) | Implemented |
| Restart counter tracking | Implemented (counter file, no auto-restart) |
| Custom CLI timeouts and intervals | Implemented (flags) |
| Headless/CI operation without tmux | Implemented |

## What the supervisor does NOT handle

These limitations exist because the fixes belong in the orchestrator
engine, not the process manager.

### No auto-restart on crash

If a loop process exits unexpectedly, it stays dead until the operator
runs `supervisor.sh restart`.  The `--max-restarts` and `--backoff-*`
flags are reserved for future implementation.

**Workaround:** Monitor with `supervisor.sh status` periodically or
use the watchdog's stale-task detection to identify dead workers.

**Fix planned:** AUTO-M1-CORE-03 (auto-restart with exponential
backoff).

### No per-process restart

`supervisor.sh restart` stops and starts all 4 processes.  You cannot
restart just the claude worker without also restarting the manager.

**Workaround:** Stop all, then start all.  Or run individual loop
scripts directly with `nohup`.

**Fix planned:** Future supervisor enhancement (per-process
start/stop).

### No task lease recovery

If a worker dies mid-task, the task stays `in_progress` indefinitely.
The supervisor has no knowledge of orchestrator task state.

**Workaround:** The watchdog detects stale `in_progress` tasks via
`--inprogress-timeout` and emits `stale_task` events.  The manager
can then reassign via `reassign_stale_tasks`.

**Fix planned:** AUTO-M1-CORE-04 (task leases with automatic expiry
and requeue).

### No dispatch acknowledgment

The supervisor launches loop scripts but has no way to verify that
the CLI inside actually connected to the MCP server and began work.
A process may be "running" but stuck on initialization.

**Workaround:** Check per-cycle log files for output.  If the latest
log file is empty or missing, the CLI may not be working.

**Fix planned:** AUTO-M1-CORE-05/06 (deterministic dispatch with
`dispatch.command` / `dispatch.ack` / `dispatch.noop`).

### No instance-aware identity

The supervisor starts one process per role.  It does not support
multiple instances of the same CLI (e.g., two claude workers).  The
orchestrator identifies agents by name, not instance.

**Workaround:** Use the dual-CC workflow conventions
([dual-cc-operation.md](dual-cc-operation.md)) with manual
coordination.

**Fix planned:** AUTO-M1-CORE-01/02 (instance-aware presence with
`instance_id`).

### No PID reuse detection

If a supervised process dies and the OS reuses its PID,
`supervisor.sh status` may show `running` for a different process.

**Workaround:** Run `supervisor.sh clean` after unexpected crashes
to remove stale PIDs, then restart.

**Fix planned:** Store process start time alongside PID for
validation.

## Responsibility boundary

| Concern | Owner |
|---------|-------|
| Process lifecycle (start/stop/status) | Supervisor |
| Task lifecycle (claim/report/validate) | Orchestrator engine |
| Stale task detection | Watchdog |
| Task reassignment | Manager cycle |
| Dispatch reliability | Orchestrator events (future) |
| Instance identity | Orchestrator registration (future) |

The supervisor is a thin process manager.  It does not interact with
the orchestrator MCP server or read task/event state.  All
orchestration intelligence lives in the loop scripts and the engine.

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command reference
- [tmux-vs-supervisor.md](tmux-vs-supervisor.md) — Runtime comparison
- [roadmap.md](roadmap.md) — AUTO-M1 core task definitions
- [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) — Future dispatch events
- [dual-cc-operation.md](dual-cc-operation.md) — Multi-instance workaround
