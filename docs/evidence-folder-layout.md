# Evidence Folder Layout

Recommended folder and file structure for storing AUTO-M1 milestone
validation evidence.  Each file maps to a milestone task so reviewers
can locate proof independently.

## Top-level structure

```
evidence/
  auto-m1/
    supervisor/          # Supervisor lifecycle artifacts
    tests/               # Smoke and unit test output
    dry-run/             # Dry-run command output
    watchdog/            # Watchdog diagnostics
    orchestrator/        # MCP state snapshots
    logs/                # Selected log excerpts
```

## File naming convention

```
{category}/{task-or-step}-{description}.{ext}
```

Use lowercase, hyphens for spaces, and `.txt` for captured terminal
output or `.jsonl` for structured logs.

## File layout by category

### supervisor/

| File | Source command | Milestone task |
|------|--------------|----------------|
| `status-initial.txt` | `supervisor.sh status` (before start) | Lifecycle: clean initial state |
| `start.txt` | `supervisor.sh start` | Lifecycle: process launch |
| `status-running.txt` | `supervisor.sh status` (after start) | Lifecycle: running state |
| `stop.txt` | `supervisor.sh stop` | Lifecycle: clean shutdown |
| `status-stopped.txt` | `supervisor.sh status` (after stop) | Lifecycle: post-stop state |
| `clean.txt` | `supervisor.sh clean` | Lifecycle: artifact removal |

### tests/

| File | Source command | Milestone task |
|------|--------------|----------------|
| `unit-tests.txt` | `python3 -m unittest discover tests -v` | Python test suite |
| `smoke-tests.txt` | `bash scripts/autopilot/smoke_test.sh` | Shell smoke tests |

### dry-run/

| File | Source command | Milestone task |
|------|--------------|----------------|
| `default.txt` | `team_tmux.sh --dry-run` | Default command rendering |
| `custom-timeouts.txt` | `team_tmux.sh --dry-run --manager-cli-timeout 120 --worker-cli-timeout 300` | Timeout propagation |

### watchdog/

| File | Source command | Milestone task |
|------|--------------|----------------|
| `one-shot.jsonl` | `watchdog_loop.sh --once --log-dir /tmp/wd` | Stale-task detection |
| `log-check.txt` | `log_check.sh --strict --log-dir .autopilot-logs` | JSONL well-formedness |

### orchestrator/

| File | Source command | Milestone task |
|------|--------------|----------------|
| `agents.txt` | `orchestrator_list_agents()` | Agent registration |
| `tasks.txt` | `orchestrator_list_tasks()` | Task board state |
| `blockers.txt` | `orchestrator_list_blockers(status="open")` | Open blockers |
| `audit-tail.txt` | `orchestrator_list_audit_logs(limit=20)` | Recent audit trail |

### logs/

| File | Source | Milestone task |
|------|--------|----------------|
| `supervisor-manager.log` | `.autopilot-logs/supervisor-manager.log` | Supervisor log capture |
| `latest-manager-cycle.log` | Most recent `manager-*.log` | Manager cycle output |
| `latest-watchdog.jsonl` | Most recent `watchdog-*.jsonl` | Watchdog cycle output |

## Capture script

```bash
#!/usr/bin/env bash
set -euo pipefail
DIR="evidence/auto-m1"

mkdir -p "$DIR"/{supervisor,tests,dry-run,watchdog,orchestrator,logs}

# Supervisor lifecycle
./scripts/autopilot/supervisor.sh status > "$DIR/supervisor/status-initial.txt" 2>&1
./scripts/autopilot/supervisor.sh start > "$DIR/supervisor/start.txt" 2>&1
sleep 2
./scripts/autopilot/supervisor.sh status > "$DIR/supervisor/status-running.txt" 2>&1
./scripts/autopilot/supervisor.sh stop > "$DIR/supervisor/stop.txt" 2>&1
./scripts/autopilot/supervisor.sh status > "$DIR/supervisor/status-stopped.txt" 2>&1
./scripts/autopilot/supervisor.sh clean > "$DIR/supervisor/clean.txt" 2>&1

# Tests
python3 -m unittest discover tests -v > "$DIR/tests/unit-tests.txt" 2>&1 || true
bash scripts/autopilot/smoke_test.sh > "$DIR/tests/smoke-tests.txt" 2>&1 || true

# Dry-run
./scripts/autopilot/team_tmux.sh --dry-run > "$DIR/dry-run/default.txt" 2>&1
./scripts/autopilot/team_tmux.sh --dry-run \
  --manager-cli-timeout 120 \
  --worker-cli-timeout 300 > "$DIR/dry-run/custom-timeouts.txt" 2>&1

echo "Evidence captured in $DIR/"
ls -R "$DIR/"
```

## Signoff checklist

After capturing evidence, verify:

- [ ] All `supervisor/` files are non-empty
- [ ] `tests/unit-tests.txt` shows no failures
- [ ] `tests/smoke-tests.txt` shows all scripts accessible
- [ ] `dry-run/` files show correct timeout values
- [ ] `watchdog/` files contain valid JSONL (if watchdog ran)
- [ ] `orchestrator/` files show expected agent/task state

## References

- [milestone-evidence-collection.md](milestone-evidence-collection.md) — Evidence checklist
- [supervisor-demo-runbook.md](supervisor-demo-runbook.md) — Demo flow steps
- [autopilot-test-map.md](autopilot-test-map.md) — Test coverage map
