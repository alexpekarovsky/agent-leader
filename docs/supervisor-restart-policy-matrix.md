# Supervisor Restart/Backoff Policy Matrix

Default restart and backoff behavior for the supervisor prototype across worker exit scenarios.

> **Note:** Auto-restart is not yet implemented (AUTO-M1-CORE-03).
> This matrix documents the intended policy so operators can plan
> around it.  Current MVP behavior is manual restart only.

## Exit type classification

| Exit type | Detection | Example cause |
|-----------|-----------|---------------|
| **Success** | `rc=0` | Normal cycle completion, worker prints "idle" |
| **Error** | `rc=1` (non-zero, non-timeout) | API error, missing credentials, bad state file |
| **Timeout** | `rc=124` (from `timeout(1)`) | CLI hung on a large task, network stall |
| **Crash** | Process disappears (SIGKILL, OOM, segfault) | Out-of-memory kill, unhandled signal |

## Policy matrix

| Exit type | MVP behavior | Planned auto-restart behavior | Restart delay | Counts toward `--max-restarts`? |
|-----------|-------------|-------------------------------|---------------|-------------------------------|
| Success | Loop sleeps `--interval`, runs next cycle | Same (no restart needed) | `sleep_with_jitter(interval)` | No |
| Error | Loop sleeps `--interval`, retries next cycle | Restart with backoff | `backoff_base * 2^(n-1)`, capped at `backoff_max` | Yes |
| Timeout | Loop logs ERROR, sleeps `--interval`, retries | Restart with backoff | `backoff_base * 2^(n-1)`, capped at `backoff_max` | Yes |
| Crash | Process stays dead; supervisor shows `dead` | Supervisor detects via `kill -0`, restarts with backoff | `backoff_base * 2^(n-1)`, capped at `backoff_max` | Yes |

## Default thresholds

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `--max-restarts` | `5` | After 5 consecutive failures, give up on the process |
| `--backoff-base` | `10` | First restart delay: 10 seconds |
| `--backoff-max` | `120` | Maximum restart delay: 2 minutes |
| `--manager-interval` | `20` | Normal cycle interval for manager (between successful cycles) |
| `--worker-interval` | `25` | Normal cycle interval for workers |

## Transient vs repeated failures

| Scenario | Classification | Policy response |
|----------|---------------|-----------------|
| Single API rate-limit error, next cycle succeeds | Transient | Counter resets after success; no backoff accumulation |
| 3 consecutive timeouts on different tasks | Repeated | Backoff escalates: 10s → 20s → 40s; 3 of 5 restarts used |
| 5 consecutive crashes (e.g., missing binary) | Persistent | Process marked as failed after 5th attempt; operator must intervene |
| Success → error → success → error | Intermittent | Counter resets on each success; backoff stays at base level |

### Counter reset rule (planned)

The restart counter resets to 0 after a successful cycle.  This means:
- A process that fails once and then recovers does not accumulate toward `--max-restarts`
- Only **consecutive** failures count
- The backoff delay also resets to `--backoff-base` after success

## Per-process behavior

| Process | Exit on success | Exit on error | Timeout source |
|---------|----------------|---------------|----------------|
| manager | Continues loop | Continues loop, logs ERROR | `--manager-cli-timeout` (300s) |
| claude worker | Continues loop | Continues loop, logs ERROR | `--worker-cli-timeout` (600s) |
| gemini worker | Continues loop | Continues loop, logs ERROR | `--worker-cli-timeout` (600s) |
| watchdog | Continues loop | Continues loop, logs ERROR | No CLI timeout (inline python) |

All processes use `sleep_with_jitter(interval)` between cycles, which adds 0-4 random seconds to the base interval to prevent thundering herd.

## Provisional decisions

These policy choices are provisional and may change based on operational experience:

| Decision | Current choice | Rationale | Alternative considered |
|----------|---------------|-----------|----------------------|
| Counter reset on success | Reset to 0 | Avoid punishing transient failures | Keep counter, decay over time |
| Backoff formula | Exponential (base × 2^n) | Simple, well-understood | Linear, jittered exponential |
| Max restarts scope | Per-process | Independent failure domains | Global across all processes |
| Watchdog restart policy | Same as workers | Uniform policy | No restart (watchdog is read-only) |

## Operator actions when max-restarts is reached

When a process exhausts its restart budget:

1. `supervisor.sh status` shows the process as `dead` with `restarts=5`
2. Check the last supervisor log: `tail .autopilot-logs/supervisor-{process}.log`
3. Check the last cycle log for the root cause
4. Fix the underlying issue (restore credentials, free disk, fix state)
5. `supervisor.sh restart` to reset all counters and start fresh

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Flag defaults and command behavior
- [supervisor-restart-backoff-tuning.md](supervisor-restart-backoff-tuning.md) — Fast-test vs unattended profiles
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — Auto-restart not yet implemented
- [monitor-pane-interpretation.md](monitor-pane-interpretation.md) — Reading error patterns in logs
