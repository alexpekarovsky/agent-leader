# Supervisor Prototype Smoke Test Checklist

Repeatable checklist for manually verifying `scripts/autopilot/supervisor.sh` start/stop/status and worker recovery.  Run from the project root (`/Users/alex/claude-multi-ai`).

## Prerequisites

- [ ] Bash 4+ available (`bash --version`)
- [ ] `scripts/autopilot/supervisor.sh` is executable (`chmod +x` if needed)
- [ ] `scripts/autopilot/common.sh` exists (sourced by supervisor)
- [ ] Loop scripts exist: `manager_loop.sh`, `worker_loop.sh`, `watchdog_loop.sh`
- [ ] No leftover PID dir: `ls .autopilot-pids/` should show "No such file or directory"
- [ ] No leftover supervisor logs: `ls .autopilot-logs/supervisor-*.log` should show no matches

## 1. Clean-state start

| Step | Command | Expected output |
|------|---------|-----------------|
| Start | `./scripts/autopilot/supervisor.sh start` | 4 `[INFO] started …` lines, `Supervisor started. PID dir: …` |
| Verify PIDs | `ls .autopilot-pids/*.pid` | `manager.pid claude.pid gemini.pid watchdog.pid` |
| Verify restart counters | `cat .autopilot-pids/manager.restarts` | `0` |
| Status | `./scripts/autopilot/supervisor.sh status` | All 4 show `running` with PIDs and `restarts=0` |

**Pass criteria:** All 4 processes listed as `running`, PID files and `.restarts` files present.

## 2. Double-start idempotency

| Step | Command | Expected output |
|------|---------|-----------------|
| Start again | `./scripts/autopilot/supervisor.sh start` | Each process logs `already running (pid=…)` |
| Status | `./scripts/autopilot/supervisor.sh status` | Same PIDs as step 1, no duplicates |

**Pass criteria:** No new processes spawned; original PIDs unchanged.

## 3. Status output format

| Step | Command | Expected output |
|------|---------|-----------------|
| Status | `./scripts/autopilot/supervisor.sh status` | Header lines: `Autopilot supervisor status`, `Project:`, `PID dir:`, `Log dir:` |
| Column check | (inspect output) | Columns: name, status, `pid=`, `restarts=` |

**Pass criteria:** Output matches format in `supervisor-cli-spec.md`.

## 4. Clean stop

| Step | Command | Expected output |
|------|---------|-----------------|
| Stop | `./scripts/autopilot/supervisor.sh stop` | 4 `[INFO] stopping/stopped …` lines, `All processes stopped.` |
| Verify PIDs removed | `ls .autopilot-pids/*.pid 2>/dev/null` | No output (files removed) |
| Status | `./scripts/autopilot/supervisor.sh status` | All 4 show `stopped`, `pid=-` |

**Pass criteria:** All PID files and `.restarts` files removed, status shows `stopped`.

## 5. Worker crash recovery (stale PID)

| Step | Command | Expected output |
|------|---------|-----------------|
| Start | `./scripts/autopilot/supervisor.sh start` | 4 processes started |
| Kill claude worker | `kill -9 $(cat .autopilot-pids/claude.pid)` | Process killed |
| Status | `./scripts/autopilot/supervisor.sh status` | Claude shows `dead`, other 3 show `running` |
| Restart | `./scripts/autopilot/supervisor.sh restart` | All stopped then restarted |
| Status | `./scripts/autopilot/supervisor.sh status` | All 4 show `running` with new PIDs |
| Stop | `./scripts/autopilot/supervisor.sh stop` | Clean shutdown |

**Pass criteria:** Dead process detected, restart brings all processes back.

## 6. Stale PID file cleanup

| Step | Command | Expected output |
|------|---------|-----------------|
| Create stale PID dir | `mkdir -p .autopilot-pids` | Directory created |
| Create fake PID | `echo 99999 > .autopilot-pids/manager.pid` | Stale pidfile |
| Status | `./scripts/autopilot/supervisor.sh status` | Manager shows `dead` (PID 99999 not running) |
| Clean | `./scripts/autopilot/supervisor.sh clean` | `removed stale pidfile for manager` |
| Status | `./scripts/autopilot/supervisor.sh status` | Manager shows `stopped` |

**Pass criteria:** Stale PID file detected and removed by `clean`.

## 7. Clean with running processes (safety check)

| Step | Command | Expected output |
|------|---------|-----------------|
| Start | `./scripts/autopilot/supervisor.sh start` | 4 processes started |
| Clean (while running) | `./scripts/autopilot/supervisor.sh clean` | `WARN` per process: "still running … stop it first" |
| Status | `./scripts/autopilot/supervisor.sh status` | All 4 still `running` (not removed) |
| Stop | `./scripts/autopilot/supervisor.sh stop` | Clean shutdown |
| Clean | `./scripts/autopilot/supervisor.sh clean` | Supervisor logs removed |

**Pass criteria:** `clean` refuses to remove PID files for live processes.

## 8. Unknown command / bad flag

| Step | Command | Expected output |
|------|---------|-----------------|
| Unknown command | `./scripts/autopilot/supervisor.sh bogus` | Usage message, exit code 1 |
| Unknown flag | `./scripts/autopilot/supervisor.sh start --bad-flag` | `ERROR Unknown arg`, exit code 1 |

**Pass criteria:** Both exit with code 1 and print a clear error.

## 9. Supervisor log files

| Step | Command | Expected output |
|------|---------|-----------------|
| Start | `./scripts/autopilot/supervisor.sh start` | Processes started |
| Check logs exist | `ls .autopilot-logs/supervisor-*.log` | 4 log files |
| Check log content | `head -5 .autopilot-logs/supervisor-claude.log` | Worker loop output visible |
| Stop | `./scripts/autopilot/supervisor.sh stop` | Clean shutdown |
| Clean logs | `./scripts/autopilot/supervisor.sh clean` | `removed 4 supervisor log file(s)` |
| Verify removed | `ls .autopilot-logs/supervisor-*.log 2>/dev/null` | No output |

**Pass criteria:** Supervisor logs captured during run and cleaned by `clean`.

## Final cleanup

```bash
./scripts/autopilot/supervisor.sh stop 2>/dev/null || true
./scripts/autopilot/supervisor.sh clean 2>/dev/null || true
```

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Full command and flag reference
- [supervisor-test-plan.md](supervisor-test-plan.md) — Extended test plan with failure injection
- [supervisor-restart-backoff-tuning.md](supervisor-restart-backoff-tuning.md) — Tuning profiles
