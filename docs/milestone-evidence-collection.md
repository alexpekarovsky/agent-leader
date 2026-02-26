# Milestone Acceptance Evidence Collection

What to capture for AUTO-M1 signoff.  Each artifact maps to a
milestone task so reviewers can verify independently.

## Evidence checklist

### 1. Supervisor lifecycle

| Artifact | Command | Proves |
|----------|---------|--------|
| Status output (all stopped) | `./scripts/autopilot/supervisor.sh status` | Clean initial state |
| Status output (all running) | `./scripts/autopilot/supervisor.sh start && ... status` | Processes launch correctly |
| Status output (after stop) | `./scripts/autopilot/supervisor.sh stop && ... status` | Clean shutdown |
| Clean output | `./scripts/autopilot/supervisor.sh clean` | Stale artifact removal |

### 2. Smoke test results

| Artifact | Command | Proves |
|----------|---------|--------|
| Shell smoke test output | `bash scripts/autopilot/smoke_test.sh` | All script paths work |
| Python test output | `python3 -m unittest discover tests -v` | Unit tests pass |

### 3. Dry-run output

| Artifact | Command | Proves |
|----------|---------|--------|
| Default dry-run | `./scripts/autopilot/team_tmux.sh --dry-run` | Correct command rendering |
| Custom timeout dry-run | `... --dry-run --manager-cli-timeout 120 --worker-cli-timeout 300` | Timeout propagation |

### 4. Watchdog diagnostics

| Artifact | Command | Proves |
|----------|---------|--------|
| One-shot JSONL | `./scripts/autopilot/watchdog_loop.sh --once --log-dir /tmp/wd` | Stale-task detection works |
| Log check (strict) | `./scripts/autopilot/log_check.sh --strict --log-dir .autopilot-logs` | JSONL well-formed |

### 5. Orchestrator state (via MCP)

| Artifact | How to capture | Proves |
|----------|---------------|--------|
| Agent registration | `orchestrator_list_agents()` | All agents verified |
| Task board | `orchestrator_list_tasks()` | No orphaned tasks |
| Open blockers | `orchestrator_list_blockers(status="open")` | No unresolved blockers |
| Audit tail | `orchestrator_list_audit_logs(limit=20)` | Recent activity visible |

### 6. Instance-aware status (Phase B — future)

| Artifact | How to capture | Proves |
|----------|---------------|--------|
| Per-instance registration | `orchestrator_list_agents()` with instance IDs | Instances distinguishable |
| Lease expiry recovery | Watchdog JSONL + task status after timeout | Auto-requeue works |
| No-op manager cycle | `orchestrator_manager_cycle(strict=true)` | Stable state post-restart |

> Skip these until AUTO-M1-CORE-01/02 ship.  Mark as N/A in signoff.

## How to save evidence

```bash
# Create evidence directory
mkdir -p evidence/auto-m1

# Capture supervisor lifecycle
./scripts/autopilot/supervisor.sh status > evidence/auto-m1/status-initial.txt 2>&1
./scripts/autopilot/supervisor.sh start >> evidence/auto-m1/start.txt 2>&1
./scripts/autopilot/supervisor.sh status > evidence/auto-m1/status-running.txt 2>&1
./scripts/autopilot/supervisor.sh stop >> evidence/auto-m1/stop.txt 2>&1

# Capture test results
python3 -m unittest discover tests -v > evidence/auto-m1/unit-tests.txt 2>&1
bash scripts/autopilot/smoke_test.sh > evidence/auto-m1/smoke-tests.txt 2>&1
```

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor commands
- [post-restart-validation-plan.md](post-restart-validation-plan.md) — Automated checks
- [autopilot-test-map.md](autopilot-test-map.md) — Test coverage map
