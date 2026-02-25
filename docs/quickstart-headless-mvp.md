# Headless MVP Quickstart

Shortest path to running the autopilot team without manual prompting.

## 1. Verify MCP install

```bash
ls ~/.local/share/agent-leader/current/orchestrator_mcp_server.py
```

If missing, install:

```bash
./scripts/install_agent_leader_mcp.sh --all
```

## 2. Dry run

```bash
./scripts/autopilot/team_tmux.sh --dry-run
```

Check that `--project-root` and `--log-dir` point where you expect.

## 3. Launch

```bash
./scripts/autopilot/team_tmux.sh
tmux attach -t agents-autopilot
```

Or without tmux:

```bash
./scripts/autopilot/supervisor.sh start
./scripts/autopilot/supervisor.sh status
```

## 4. Monitor

Pane layout (tmux `manager` window):

| Pane | Process |
|------|---------|
| 0 | Manager (codex) |
| 1 | Claude worker |
| 2 | Gemini worker |
| 3 | Watchdog |

Check logs:

```bash
# Log health summary
./scripts/autopilot/log_check.sh

# Latest watchdog diagnostics
grep '"stale_task"' .autopilot-logs/watchdog-*.jsonl | tail -5

# Latest manager output
cat "$(ls -t .autopilot-logs/manager-*.log | head -1)"
```

## 5. Restart one worker

```bash
# Kill claude worker (pane 1), then restart
tmux send-keys -t agents-autopilot:manager.1 C-c
tmux send-keys -t agents-autopilot:manager.1 \
  "./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code --project-root $(pwd) --interval 25 --cli-timeout 600 --log-dir .autopilot-logs" Enter
```

No orchestrator state reset needed.

## 6. Stop

```bash
# tmux
tmux kill-session -t agents-autopilot

# supervisor
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/supervisor.sh clean
```

## 7. Interpret timeout logs

When you see this in a log file:

```
[AUTOPILOT] CLI timeout after 300s for codex
```

It means the CLI call exceeded `--cli-timeout`. The loop logged the timeout, skipped the cycle, and continued. Common causes:

- CLI is unresponsive or rate-limited
- Task is too complex for the timeout window
- MCP server is unreachable

Fix: increase `--cli-timeout` or check CLI health (`codex --version`, `claude --version`).

The loop stderr also shows:

```
[ERROR] manager cycle timed out after 300s; see .autopilot-logs/manager-codex-20260225-120000.log
```

This is informational — the loop will retry on the next cycle.

## References

- [README.md](../README.md#autopilot-autonomous-loops) — Autopilot overview
- [docs/operator-runbook.md](operator-runbook.md) — Full operational procedures
- [docs/swarm-mode.md](swarm-mode.md) — Future multi-instance capabilities
