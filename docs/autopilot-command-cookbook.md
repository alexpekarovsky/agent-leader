# Autopilot Command Cookbook

Copy-paste one-liners for common autopilot operations.  All commands
assume you are in the project root directory.

## Preview & launch

```bash
# Preview tmux session plan (no tmux required)
./scripts/autopilot/team_tmux.sh --dry-run

# Preview with custom timeouts
./scripts/autopilot/team_tmux.sh --dry-run \
  --session my-session \
  --manager-cli-timeout 120 \
  --worker-cli-timeout 300

# Launch the full autopilot session
./scripts/autopilot/team_tmux.sh

# Launch with custom session name and log directory
./scripts/autopilot/team_tmux.sh --session my-run --log-dir /tmp/autopilot-logs
```

## Attach & observe

```bash
# Attach to the running session
tmux attach -t agents-autopilot

# Peek at a specific pane without attaching
tmux capture-pane -t agents-autopilot:manager.0 -p   # manager
tmux capture-pane -t agents-autopilot:manager.1 -p   # claude worker
tmux capture-pane -t agents-autopilot:manager.2 -p   # gemini worker
tmux capture-pane -t agents-autopilot:manager.3 -p   # watchdog

# Dump full scrollback to file
tmux capture-pane -t agents-autopilot:manager.0 -pS - > /tmp/manager-output.txt
```

## One-shot diagnostics

```bash
# Run watchdog once and inspect output
./scripts/autopilot/watchdog_loop.sh --once --log-dir /tmp/wd-check
cat /tmp/wd-check/watchdog-*.jsonl | python3 -m json.tool

# Run manager once with short timeout (useful for testing)
./scripts/autopilot/manager_loop.sh --once --cli-timeout 30 --log-dir /tmp/mgr-check

# Run worker once with short timeout
./scripts/autopilot/worker_loop.sh --once \
  --cli claude --agent claude_code \
  --cli-timeout 30 --log-dir /tmp/wkr-check
```

## Log inspection

```bash
# Quick log sanity check
./scripts/autopilot/log_check.sh --log-dir .autopilot-logs --max-age-minutes 60

# Strict check (fails on malformed JSONL)
./scripts/autopilot/log_check.sh --log-dir .autopilot-logs --strict --max-age-minutes 60

# List recent log files
ls -lt .autopilot-logs/ | head -20

# Tail the latest manager log
tail -f .autopilot-logs/manager-codex-*.log | tail -1

# Search watchdog logs for stale tasks
grep '"kind": "stale_task"' .autopilot-logs/watchdog-*.jsonl
```

## Shutdown

```bash
# Kill the entire autopilot session
tmux kill-session -t agents-autopilot

# Kill just one pane (e.g., claude worker) and leave others running
tmux kill-pane -t agents-autopilot:manager.1
```

## Testing

```bash
# Run the shell smoke test suite
bash scripts/autopilot/smoke_test.sh

# Run Python unit tests
python3 -m unittest discover tests -v

# Run a single test file
python3 -m unittest tests.test_team_tmux_dryrun -v
```

## Supervisor (alternative to tmux)

```bash
# Full team: start all processes (manager + claude + gemini + watchdog)
./scripts/autopilot/supervisor.sh start

# Check supervisor status
./scripts/autopilot/supervisor.sh status

# Stop all processes
./scripts/autopilot/supervisor.sh stop

# Clean up stale PIDs and supervisor logs
./scripts/autopilot/supervisor.sh clean
```

## Supervisor startup profiles

The supervisor always starts all 4 processes.  For reduced profiles,
run individual loops directly:

```bash
# Profile: docs-only (manager + one claude worker + watchdog)
./scripts/autopilot/manager_loop.sh \
  --cli codex --cli-timeout 300 --log-dir .autopilot-logs &
./scripts/autopilot/worker_loop.sh \
  --cli claude --agent claude_code --cli-timeout 600 --log-dir .autopilot-logs &
./scripts/autopilot/watchdog_loop.sh \
  --log-dir .autopilot-logs &

# Profile: smoke-only (manager + watchdog, no workers)
./scripts/autopilot/manager_loop.sh \
  --cli codex --cli-timeout 120 --log-dir .autopilot-logs &
./scripts/autopilot/watchdog_loop.sh \
  --log-dir .autopilot-logs &

# Profile: full team via supervisor (all 4 processes)
./scripts/autopilot/supervisor.sh start

# Profile: full team with custom timeouts
./scripts/autopilot/supervisor.sh start \
  --manager-cli-timeout 120 --worker-cli-timeout 300
```

## References

- [quickstart-headless-mvp.md](quickstart-headless-mvp.md) — Getting started guide
- [operator-runbook.md](operator-runbook.md) — Detailed operational procedures
- [tmux-pane-cheatsheet.md](tmux-pane-cheatsheet.md) — Pane index reference
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Common issues
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor command reference
