# Supervisor Prototype Acceptance Test Matrix

Minimal acceptance matrix for supervisor prototype readiness at the
restart milestone.  Each row is a pass/fail gate.

## Core lifecycle

| ID | Test | Pass criteria | Evidence |
|----|------|--------------|----------|
| L1 | Start all processes | 4 processes show `running` in status | `supervisor.sh status` output |
| L2 | Stop all processes | All 4 show `stopped`, PID files removed | `supervisor.sh status` after stop |
| L3 | Restart all processes | Stop + start completes, new PIDs assigned | Status before and after restart |
| L4 | Status with no processes | All 4 show `stopped`, exit code 0 | `supervisor.sh status` on clean system |
| L5 | Idempotent start | Second start skips already-running processes | Start twice, same PIDs |

## Recovery

| ID | Test | Pass criteria | Evidence |
|----|------|--------------|----------|
| R1 | Clean stale PIDs | Dead PIDs removed, running PIDs preserved | `clean` output + status after |
| R2 | Status detects dead process | Killed process shows `dead` | Kill one PID, check status |
| R3 | Restart after crash | All processes running after restart | Kill one, restart, status |
| R4 | Clean after reboot (simulated) | Fake stale PIDs removed | Write fake PID, clean, status |

## Logging and observability

| ID | Test | Pass criteria | Evidence |
|----|------|--------------|----------|
| O1 | Supervisor logs created | `supervisor-*.log` files exist after start | `ls .autopilot-logs/supervisor-*.log` |
| O2 | Per-cycle logs created | At least one `manager-*.log` after one cycle | `ls .autopilot-logs/manager-*.log` |
| O3 | Status shows restart count | `restarts=N` column in status output | `supervisor.sh status` output |
| O4 | Clean removes supervisor logs | `supervisor-*.log` files removed by clean | `clean` then `ls` |

## Error handling

| ID | Test | Pass criteria | Evidence |
|----|------|--------------|----------|
| E1 | Unknown command rejected | Exit code 1, usage message | `supervisor.sh badcmd` output |
| E2 | Unknown flag rejected | Exit code 1, error message | `supervisor.sh start --bad-flag` output |
| E3 | SIGTERM + SIGKILL fallback | Stuck process killed after 10s timeout | Stop with trap-ignoring process |

## Summary

| Category | Tests | Required pass |
|----------|-------|--------------|
| Core lifecycle | L1-L5 | All 5 |
| Recovery | R1-R4 | All 4 |
| Observability | O1-O4 | All 4 |
| Error handling | E1-E3 | All 3 |
| **Total** | **16** | **16** |

## Automated coverage

| Test | Covered by |
|------|-----------|
| L1-L5 | `tests/test_supervisor_lifecycle.py` |
| R1-R4 | `tests/test_supervisor_status_format.py` |
| O1-O4 | `tests/test_supervisor_lifecycle.py` |
| E1-E2 | `tests/test_supervisor_lifecycle.py` |
| E3 | Manual (requires signal trap) |

## References

- [supervisor-test-plan.md](supervisor-test-plan.md) — Full test plan with failure injection
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command reference
- [supervisor-demo-runbook.md](supervisor-demo-runbook.md) — Demo walkthrough
- [milestone-evidence-collection.md](milestone-evidence-collection.md) — Evidence capture
