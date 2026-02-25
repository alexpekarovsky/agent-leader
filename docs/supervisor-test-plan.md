# Supervisor Prototype Test Plan

Test plan and failure-injection checklist for `scripts/autopilot/supervisor.sh`. Covers crash recovery, stale pid handling, log path behavior, backoff, and safe shutdown.

References: TASK-99c64b61 (supervisor prototype), TASK-28d9061a (clean command).

## Automated Tests (in smoke_test.sh)

These are already covered by the smoke test suite:

- [x] `supervisor.sh status` with no running processes shows all stopped
- [x] `supervisor.sh start` launches 4 processes with pidfiles
- [x] `supervisor.sh status` shows running with correct PIDs
- [x] `supervisor.sh stop` sends SIGTERM and cleans pidfiles
- [x] `supervisor.sh clean` removes stale pidfiles and supervisor logs

## Manual Test Checklist

### 1. Normal lifecycle

| Step | Command | Expected |
|------|---------|----------|
| Start | `supervisor.sh start` | 4 processes started, PID files created |
| Status | `supervisor.sh status` | All 4 show `running` with PIDs |
| Stop | `supervisor.sh stop` | All 4 stopped, PID files removed |
| Status after stop | `supervisor.sh status` | All 4 show `stopped` |

### 2. Crash recovery (stale PID)

| Step | Command | Expected |
|------|---------|----------|
| Start | `supervisor.sh start` | 4 processes started |
| Kill one process | `kill -9 $(cat .autopilot-pids/claude.pid)` | Claude worker dies |
| Status | `supervisor.sh status` | Claude shows `dead`, others `running` |
| Restart | `supervisor.sh restart` | All 4 stopped then restarted |
| Status | `supervisor.sh status` | All 4 show `running` with new PIDs |

### 3. Stale PID files after reboot

| Step | Command | Expected |
|------|---------|----------|
| Create fake stale PIDs | `echo 99999 > .autopilot-pids/manager.pid` | Stale pidfile exists |
| Status | `supervisor.sh status` | Manager shows `dead` (PID not running) |
| Clean | `supervisor.sh clean` | Stale pidfile removed, logged |
| Status | `supervisor.sh status` | Manager shows `stopped` |
| Start | `supervisor.sh start` | Fresh start succeeds |

### 4. Double start prevention

| Step | Command | Expected |
|------|---------|----------|
| Start | `supervisor.sh start` | 4 processes started |
| Start again | `supervisor.sh start` | Each process logs "already running", no duplicates |
| Status | `supervisor.sh status` | Still 4 processes, same PIDs as first start |
| Stop | `supervisor.sh stop` | Clean shutdown |

### 5. Log path collisions

| Step | Command | Expected |
|------|---------|----------|
| Start with custom log-dir | `supervisor.sh start --log-dir /tmp/test-logs` | Logs written to `/tmp/test-logs/supervisor-*.log` |
| Start second instance with same log-dir | `supervisor.sh start --pid-dir /tmp/test-pids2 --log-dir /tmp/test-logs` | Supervisor logs append, no corruption |
| Stop both | Stop each by pid-dir | Clean shutdown |

### 6. SIGTERM timeout and SIGKILL fallback

| Step | Command | Expected |
|------|---------|----------|
| Start | `supervisor.sh start` | 4 processes started |
| Make one process ignore SIGTERM | `trap '' TERM` in a child (manual) | Process won't exit on SIGTERM |
| Stop | `supervisor.sh stop` | Waits 10s per stuck process, then SIGKILL, logs WARN |
| Status | `supervisor.sh status` | All stopped |

### 7. Clean with running processes

| Step | Command | Expected |
|------|---------|----------|
| Start | `supervisor.sh start` | 4 processes started |
| Clean | `supervisor.sh clean` | Warns "still running" for each, does NOT remove pidfiles |
| Status | `supervisor.sh status` | All 4 still `running` |
| Stop then clean | `supervisor.sh stop && supervisor.sh clean` | Supervisor logs removed, pid dir cleaned |

### 8. Restart counter tracking

| Step | Command | Expected |
|------|---------|----------|
| Start | `supervisor.sh start` | `.restarts` files created with value `0` |
| Check | `cat .autopilot-pids/manager.restarts` | `0` |
| Stop | `supervisor.sh stop` | `.restarts` files removed |

## Failure Injection Scenarios

These test resilience against real-world failures:

### Disk full
- **Inject**: Fill disk or set quota on log dir
- **Expected**: Loop processes fail to write logs; supervisor start may fail if pidfile write fails
- **Recovery**: Free disk space, `supervisor.sh clean`, restart

### Permission denied on pid dir
- **Inject**: `chmod 000 .autopilot-pids`
- **Expected**: `supervisor.sh start` fails with clear error
- **Recovery**: Fix permissions, retry

### Corrupted PID file
- **Inject**: `echo "not-a-number" > .autopilot-pids/manager.pid`
- **Expected**: `supervisor.sh status` shows `dead` (kill -0 fails on non-numeric)
- **Recovery**: `supervisor.sh clean` removes invalid pidfile

### Process replaced (PID reuse)
- **Inject**: Kill a supervised process, wait for OS to reuse the PID
- **Expected**: `supervisor.sh status` may show `running` for wrong process
- **Mitigation**: This is a known MVP limitation. Future work: store process start time alongside PID.

### Concurrent supervisor commands
- **Inject**: Run `supervisor.sh start` and `supervisor.sh stop` simultaneously
- **Expected**: Race possible — pidfile may be written then immediately removed
- **Mitigation**: Avoid concurrent supervisor commands. Future work: pidfile locking.

## Future Enhancements (Not in MVP)

These are documented for planning but not tested yet:

- [ ] Auto-restart on crash with exponential backoff
- [ ] Process start time in pidfile for PID reuse detection
- [ ] Pidfile locking for concurrent command safety
- [ ] Health check integration (process responds to signal)
- [ ] Configurable per-process restart policy
