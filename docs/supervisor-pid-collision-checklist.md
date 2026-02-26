# Supervisor PID/Lock Collision Handling Checklist

Collision scenarios for PID and lock files during supervisor prototype
operation, with detection and cleanup steps.

## Scenario 1: Stale PID after crash

**Cause**: Process crashed, PID file remains with dead PID.

**Detection**:
```bash
./scripts/autopilot/supervisor.sh status
# Shows: claude  dead  pid=12346
```

**Cleanup**:
```bash
./scripts/autopilot/supervisor.sh clean
./scripts/autopilot/supervisor.sh start
```

## Scenario 2: PID reuse after reboot

**Cause**: OS reassigned the PID to an unrelated process after reboot.

**Detection**:
```bash
./scripts/autopilot/supervisor.sh status
# Shows: claude  running  pid=12346  (but it's actually a different process)
```

**Cleanup**:
```bash
# Always clean after reboot before starting
./scripts/autopilot/supervisor.sh stop   # sends SIGTERM to wrong process — avoid
./scripts/autopilot/supervisor.sh clean  # safe: checks kill -0 only
./scripts/autopilot/supervisor.sh start
```

**Prevention**: Run `clean` before `start` after any reboot.

## Scenario 3: Duplicate supervisor instances

**Cause**: Operator runs `supervisor.sh start` twice with the same `--pid-dir`.

**Detection**:
```bash
./scripts/autopilot/supervisor.sh status
# Shows all running — second start was no-op (idempotent)
```

**Impact**: None — `start` skips processes that are already running.

## Scenario 4: Conflicting PID directories

**Cause**: Two supervisors started with different `--pid-dir` but same loop scripts.

**Detection**: Two sets of loop processes running simultaneously. Check:
```bash
ps aux | grep -E '(manager|worker|watchdog)_loop'
```

**Cleanup**:
```bash
# Stop both supervisor instances
./scripts/autopilot/supervisor.sh stop --pid-dir .autopilot-pids
./scripts/autopilot/supervisor.sh stop --pid-dir /tmp/other-pids
```

**Prevention**: Use one `--pid-dir` per project.

## Scenario 5: PID file with invalid content

**Cause**: Corrupted write or manual edit.

**Detection**:
```bash
cat .autopilot-pids/manager.pid
# Shows: not-a-number
./scripts/autopilot/supervisor.sh status
# Shows: manager  dead
```

**Cleanup**:
```bash
./scripts/autopilot/supervisor.sh clean
```

## Scenario 6: Permission denied on PID directory

**Cause**: Directory permissions changed or created by different user.

**Detection**:
```bash
./scripts/autopilot/supervisor.sh start
# Error writing PID file
```

**Cleanup**:
```bash
chmod 755 .autopilot-pids
# Or use a different directory:
./scripts/autopilot/supervisor.sh start --pid-dir /tmp/my-pids
```

## Quick reference

| Scenario | Symptom | Fix |
|----------|---------|-----|
| Stale PID | `dead` in status | `clean` then `start` |
| PID reuse | `running` but wrong process | `clean` then `start` |
| Duplicate supervisor | No issue (idempotent) | None needed |
| Conflicting pid-dirs | Double processes | Stop both, use one pid-dir |
| Invalid PID content | `dead` in status | `clean` then `start` |
| Permission denied | Start fails | Fix permissions or use alt dir |

## References

- [supervisor-state-directory-layout.md](supervisor-state-directory-layout.md) — State directory proposal
- [supervisor-pidfile-format.md](supervisor-pidfile-format.md) — PID file spec
- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) — General troubleshooting
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command reference
