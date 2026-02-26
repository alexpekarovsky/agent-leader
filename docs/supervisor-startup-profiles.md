# Supervisor Startup Profiles

Example `supervisor.sh` startup commands for different team configurations. Each profile shows the command and which processes run.

## Full Team (Default)

All 4 processes: manager + 2 workers + watchdog.

```bash
./scripts/autopilot/supervisor.sh start
```

| Process | Loop script | CLI | Agent |
|---------|------------|-----|-------|
| manager | `manager_loop.sh` | codex | codex |
| claude | `worker_loop.sh` | claude | claude_code |
| gemini | `worker_loop.sh` | gemini | gemini |
| watchdog | `watchdog_loop.sh` | — | — |

Default timeouts: manager 300s, workers 600s.

### With custom timeouts

```bash
./scripts/autopilot/supervisor.sh start \
  --manager-cli-timeout 120 \
  --worker-cli-timeout 900
```

### With custom intervals

```bash
./scripts/autopilot/supervisor.sh start \
  --manager-interval 30 \
  --worker-interval 40
```

### With custom project root

```bash
./scripts/autopilot/supervisor.sh start \
  --project-root /path/to/target/project \
  --log-dir /path/to/target/project/.autopilot-logs \
  --pid-dir /path/to/target/project/.autopilot-pids
```

## Docs-Only Profile

For documentation-heavy sprints where only Claude Code writes docs and the manager validates.

```bash
# Start only manager + claude worker + watchdog
# (gemini worker not needed for docs-only work)
./scripts/autopilot/supervisor.sh start
# Then stop gemini:
./scripts/autopilot/supervisor.sh stop  # stops all
```

> **Note**: The current supervisor starts all 4 processes together. To run a subset, launch loops individually:

```bash
# Manager
nohup ./scripts/autopilot/manager_loop.sh \
  --cli codex --project-root . --cli-timeout 300 \
  >> .autopilot-logs/supervisor-manager.log 2>&1 &

# Claude worker only
nohup ./scripts/autopilot/worker_loop.sh \
  --cli claude --agent claude_code --project-root . --cli-timeout 600 \
  >> .autopilot-logs/supervisor-claude.log 2>&1 &

# Watchdog
nohup ./scripts/autopilot/watchdog_loop.sh \
  --project-root . --interval 15 \
  >> .autopilot-logs/supervisor-watchdog.log 2>&1 &
```

## Smoke-Only Profile

For running smoke tests and validation without live CLI agents. Uses `--once` mode.

```bash
# Manager single cycle
./scripts/autopilot/manager_loop.sh --once --cli codex --project-root . --cli-timeout 2

# Worker single cycle
./scripts/autopilot/worker_loop.sh --once --cli claude --agent claude_code --project-root . --cli-timeout 2

# Watchdog single cycle
./scripts/autopilot/watchdog_loop.sh --once --project-root .
```

No supervisor needed — each loop runs once and exits.

## Milestone Demo Profile

Minimal setup for demonstrating AUTO-M1 milestone features (instance-aware status, supervisor lifecycle).

```bash
# Step 1: Start supervisor
./scripts/autopilot/supervisor.sh start

# Step 2: Verify all processes
./scripts/autopilot/supervisor.sh status

# Step 3: Check instance-aware status
# (from a connected CLI session)
orchestrator_status()

# Step 4: Stop and clean
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/supervisor.sh clean
```

## Extended Timeout Profile

For complex tasks (large refactors, multi-file test suites).

```bash
./scripts/autopilot/supervisor.sh start \
  --manager-cli-timeout 600 \
  --worker-cli-timeout 1200 \
  --manager-interval 30 \
  --worker-interval 60
```

## Crash Recovery Profile

After a crash or unexpected shutdown.

```bash
# Step 1: Clean stale PIDs
./scripts/autopilot/supervisor.sh clean

# Step 2: Restart
./scripts/autopilot/supervisor.sh start

# Step 3: Verify
./scripts/autopilot/supervisor.sh status

# Step 4: Check for stuck tasks
# (from a connected CLI session)
orchestrator_list_tasks(status="in_progress")
```

See [post-restart-verification.md](post-restart-verification.md) for the full verification flowchart.

## Profile Comparison

| Profile | Processes | Manager timeout | Worker timeout | Use case |
|---------|-----------|----------------|----------------|----------|
| Full team | 4 | 300s | 600s | Normal operation |
| Docs-only | 3 | 300s | 600s | Documentation sprints |
| Smoke-only | 1-3 (--once) | 2s | 2s | Testing and validation |
| Milestone demo | 4 | 300s | 600s | Feature demonstrations |
| Extended timeout | 4 | 600s | 1200s | Complex tasks |
| Crash recovery | 4 | 300s | 600s | Post-crash restart |

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Full command and flag reference
- [tmux-vs-supervisor.md](tmux-vs-supervisor.md) — When to use supervisor vs tmux
- [post-restart-verification.md](post-restart-verification.md) — Post-restart validation steps
- [timeout-semantics.md](timeout-semantics.md) — Timeout tuning guidelines
