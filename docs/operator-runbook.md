# Operator Runbook — Autopilot Launch / Restart / Recovery

## Prerequisites

- Python 3.10+
- CLI tools installed: `codex`, `claude`, `gemini` (whichever agents you plan to use)
- `tmux` (for tmux-based launches; not required for individual loops)
- MCP server installed to `current` target via `scripts/install_agent_leader_mcp.sh`

## 1. Project Scope Verification

Before launching, confirm the MCP server points to the correct project root.

### Check installed MCP path

```bash
# Claude Code
claude mcp list | grep agent-leader

# Gemini
gemini mcp list | grep agent-leader
```

The server command should resolve to `~/.local/share/agent-leader/current/orchestrator_mcp_server.py`.

### Check project-scoped config

If using a project-scoped `.mcp.json`, verify `ORCHESTRATOR_ROOT` matches your project:

```bash
cat .mcp.json | python3 -m json.tool
```

Look for the `ORCHESTRATOR_ROOT` environment variable — it must be an absolute path to the project directory you want orchestrated.

### Verify project root alignment

```bash
# From your project directory:
python3 -c "
from pathlib import Path
import json
mcp = json.loads(Path('.mcp.json').read_text())
server = mcp.get('mcpServers', {}).get('agent-leader-orchestrator', {})
env = server.get('env', {})
print('Root:', env.get('ORCHESTRATOR_ROOT', '(not set)'))
print('Expected root:', env.get('ORCHESTRATOR_EXPECTED_ROOT', '(not set)'))
"
```

Both values should point to your project directory.

## 2. Dry Run

Always dry-run before launching to review the tmux session plan:

```bash
./scripts/autopilot/team_tmux.sh --dry-run
```

With a different project root:

```bash
./scripts/autopilot/team_tmux.sh --dry-run --project-root /path/to/project
```

Review the output: it shows the exact `tmux` commands that would be executed with the resolved paths and timeouts. Confirm the `--project-root`, `--log-dir`, and `--cli-timeout` values look correct before proceeding.

## 3. Launch

### Full team via tmux

```bash
./scripts/autopilot/team_tmux.sh
```

With custom settings:

```bash
./scripts/autopilot/team_tmux.sh \
  --project-root /path/to/project \
  --session my-session \
  --manager-interval 30 \
  --worker-interval 40 \
  --manager-cli-timeout 300 \
  --worker-cli-timeout 600 \
  --log-dir /path/to/logs
```

### Attach to the session

```bash
tmux attach -t agents-autopilot
```

The session has two windows:
- **manager** — 4 panes (manager, claude worker, gemini worker, watchdog) in tiled layout
- **monitor** — live log tail

### Individual loops (without tmux)

Run any loop standalone:

```bash
# Manager only
./scripts/autopilot/manager_loop.sh --cli codex --project-root . --interval 20

# Single worker
./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code --project-root . --interval 25

# Watchdog only
./scripts/autopilot/watchdog_loop.sh --project-root . --interval 15
```

Add `--once` to run a single cycle (useful for debugging).

## 4. Restart a Single Worker

### Identify the tmux pane

```bash
# List panes in the manager window
tmux list-panes -t agents-autopilot:manager
```

Pane layout (default):
- `0` — manager (codex)
- `1` — claude worker
- `2` — gemini worker
- `3` — watchdog

### Kill and restart a pane

```bash
# Kill the claude worker pane (pane 1)
tmux send-keys -t agents-autopilot:manager.1 C-c

# Restart it
tmux send-keys -t agents-autopilot:manager.1 \
  "./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code --project-root /path/to/project --interval 25 --cli-timeout 600 --log-dir .autopilot-logs" Enter
```

### Restart manager

```bash
tmux send-keys -t agents-autopilot:manager.0 C-c
tmux send-keys -t agents-autopilot:manager.0 \
  "./scripts/autopilot/manager_loop.sh --cli codex --project-root /path/to/project --interval 20 --cli-timeout 300 --log-dir .autopilot-logs" Enter
```

Restarting a worker or manager does **not** require resetting orchestrator state. The loop will reconnect and resume from the current task board.

## 5. Inspect Logs

### Log directory

All logs go to `.autopilot-logs/` (or the path set via `--log-dir`):

```bash
ls -lt .autopilot-logs/ | head -20
```

### Log file naming

| Pattern | Source |
|---------|--------|
| `manager-codex-YYYYMMDD-HHMMSS.log` | Manager cycle output |
| `worker-claude_code-claude-YYYYMMDD-HHMMSS.log` | Claude worker cycle output |
| `worker-gemini-gemini-YYYYMMDD-HHMMSS.log` | Gemini worker cycle output |
| `watchdog-YYYYMMDD-HHMMSS.jsonl` | Watchdog diagnostics |

### Read latest manager log

```bash
cat "$(ls -t .autopilot-logs/manager-*.log | head -1)"
```

### Read watchdog diagnostics

```bash
# Latest watchdog JSONL
cat "$(ls -t .autopilot-logs/watchdog-*.jsonl | head -1)" | python3 -m json.tool --no-ensure-ascii
```

### Filter for stale tasks

```bash
grep '"stale_task"' .autopilot-logs/watchdog-*.jsonl | tail -5
```

### Filter for state corruption

```bash
grep '"state_corruption_detected"' .autopilot-logs/watchdog-*.jsonl | tail -5
```

### Log retention

Each loop prunes its own log files automatically. Defaults:
- Manager: 200 files
- Worker: 200 files per agent
- Watchdog: 400 files

Override with `--max-logs N`.

## 6. Stale Task Recovery

### Check for stale tasks via orchestrator

Use the MCP tools in any connected CLI session:

```
orchestrator_list_tasks(status="in_progress")
orchestrator_list_tasks(status="assigned")
```

### Reassign stale tasks

```
orchestrator_reassign_stale_tasks(stale_after_seconds=600)
```

This moves tasks owned by stale agents back to `assigned` for re-claim.

### Manual task status fix

If a task is stuck in `in_progress` after a crash:

```
orchestrator_update_task_status(task_id="TASK-xxx", status="assigned", source="operator")
```

### Check blockers

```
orchestrator_list_blockers(status="open")
```

Resolve a blocker:

```
orchestrator_resolve_blocker(blocker_id="BLK-xxx", resolution="manual fix applied", source="operator")
```

## 7. Safe Shutdown

### Stop the entire tmux session

```bash
tmux kill-session -t agents-autopilot
```

### Stop individual panes gracefully

Send Ctrl-C to each pane — the loops will exit after the current cycle completes:

```bash
tmux send-keys -t agents-autopilot:manager.0 C-c
tmux send-keys -t agents-autopilot:manager.1 C-c
tmux send-keys -t agents-autopilot:manager.2 C-c
tmux send-keys -t agents-autopilot:manager.3 C-c
```

Note: if a CLI call is in progress, Ctrl-C will wait for the current `--cli-timeout` to expire. To force-kill immediately, use `tmux kill-pane -t agents-autopilot:manager.N`.

## 8. Troubleshooting

### Parity Smoke Test

If you suspect an issue between your interactive environment and the headless runner (e.g., missing tasks, stuck agents, unreadable status), run the MCP parity smoke test tool to check the health of the integration:

```
orchestrator_parity_smoke()
```

**Expected JSON Response:**
```json
{
  "overall_status": "pass",
  "checks": [
    { "name": "engine_loaded", "status": "pass", "reason": "Engine loaded successfully.", "action": null },
    { "name": "leader_assigned", "status": "pass", "reason": "Leader is codex.", "action": null },
    { "name": "task_listing", "status": "pass", "reason": "Found 373 tasks.", "action": null },
    { "name": "headless_status_script", "status": "pass", "reason": "Headless status script is present and executable.", "action": null }
  ]
}
```
If a check fails, the `"action"` field will recommend remediation steps.

### CLI timeout logs

When a CLI call exceeds `--cli-timeout`, the log file will contain:

```
[AUTOPILOT] CLI timeout after Ns for <cli>
```

The loop itself exits with code 124 for that cycle, logs the error, and continues to the next cycle. If you see frequent timeouts:

1. Check if the CLI is responsive: `codex --version`, `claude --version`
2. Increase `--cli-timeout` (default: manager 300s, worker 600s)
3. Check if the MCP server is running and reachable

### "Missing required command" error

The loop calls `require_cmd` on startup. If the CLI binary is not in `$PATH`:

```
[ERROR] Missing required command: codex
```

Fix: install the CLI or adjust `$PATH` before launching.

### "Session already exists" error

```
Session already exists: agents-autopilot
```

A tmux session with the same name is already running. Either attach to it (`tmux attach -t agents-autopilot`) or kill it first (`tmux kill-session -t agents-autopilot`).

### Project mismatch on connect

If a worker reports `project_mismatch` when connecting to the leader:

1. The worker's `cwd` doesn't match the orchestrator's `ORCHESTRATOR_ROOT`
2. Fix: ensure `--project-root` matches the root configured in `.mcp.json` or the MCP server env
3. Restart the affected worker with the correct `--project-root`

### State corruption

The watchdog detects corrupted `bugs.json`/`blockers.json` (e.g., `{}` instead of `[]`) and emits `state_corruption_detected` diagnostics. The orchestrator engine's `_read_json_list` auto-repairs these on next access. If corruption persists:

```bash
# Manually fix a corrupted state file
echo '[]' > state/bugs.json
echo '[]' > state/blockers.json
```

## 9. Smoke Tests

Run the built-in smoke test to verify all scripts work:

```bash
./scripts/autopilot/smoke_test.sh
```

This tests dry-run, timeout paths, watchdog JSONL emission, corruption detection, and log pruning without requiring real CLI agents.
