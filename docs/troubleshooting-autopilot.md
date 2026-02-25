# Autopilot Troubleshooting Matrix

Symptom-based lookup for common autopilot failures in the current MVP.

## Timeouts and CLI Failures

| Symptom | Cause | Action |
|---------|-------|--------|
| `[AUTOPILOT] CLI timeout after Ns` in log file | CLI call exceeded `--cli-timeout` | Increase `--cli-timeout` or check CLI responsiveness (`codex --version`) |
| `manager cycle timed out after Ns` in stderr | Manager codex call exceeded timeout | Check if MCP server is reachable; increase `--manager-cli-timeout` |
| `worker cycle timed out agent=X after Ns` in stderr | Worker CLI hung or task too complex | Check worker CLI health; increase `--worker-cli-timeout` |
| `worker cycle failed agent=X rc=N` (non-124) | CLI exited with error | Read the worker log file for CLI error output |
| Frequent timeouts across all loops | MCP server down or rate limiting | Verify MCP server: `claude mcp list \| grep agent-leader`; restart CLIs |

## MCP and Connection Issues

| Symptom | Cause | Action |
|---------|-------|--------|
| `Missing required command: codex` on startup | CLI binary not in `$PATH` | Install the CLI or fix `$PATH` before launching |
| `project_mismatch` on `connect_to_leader` | Worker `cwd` doesn't match `ORCHESTRATOR_ROOT` | Ensure `--project-root` matches the root in `.mcp.json` or MCP server env |
| `orchestrator_status` shows wrong `root_name` | MCP server started with wrong `ORCHESTRATOR_ROOT` | Reinstall: `./scripts/install_agent_leader_mcp.sh --all --project-root /correct/path` |
| MCP tools not available in CLI session | MCP server not registered for this CLI | Run `claude mcp list` / `gemini mcp list` to verify; reinstall if missing |
| `orchestrator_bootstrap` fails or returns error | State directory permissions or disk space | Check write permissions on `state/` dir; verify disk space |

## Project Root Mismatches

| Symptom | Cause | Action |
|---------|-------|--------|
| Tasks created but workers can't claim | Workers connected to different project root | Run `orchestrator_status` and check `agent_connection_contexts` |
| `same_project: false` in connect response | Worker `cwd` doesn't match orchestrator root | Pass correct `--project-root` to worker loop |
| `.mcp.json` exists but wrong `ORCHESTRATOR_ROOT` | Stale project config | Edit `.mcp.json` and update `ORCHESTRATOR_ROOT` to correct absolute path |
| Manager sets project context but workers still mismatch | Workers need to reconnect after context change | Restart affected worker loops with correct `--project-root` |

## Stale Tasks and Reassignment

| Symptom | Cause | Action |
|---------|-------|--------|
| Tasks stuck in `in_progress` indefinitely | Worker crashed or disconnected mid-task | Run `orchestrator_update_task_status(task_id, "assigned", "operator")` |
| `degraded_comm` flag on tasks | Task was reassigned from a stale owner | Normal behavior; new owner will claim on next cycle |
| Watchdog reports `stale_task` but nothing happens | Manager hasn't acted on watchdog diagnostics | Manager prompt includes step 7 to inspect watchdog logs; or manually run `orchestrator_reassign_stale_tasks` |
| Tasks reassigned to codex (manager) unexpectedly | All workers are stale; manager is only active agent | Restart worker loops; they will reconnect and claim reassigned tasks |
| `No claimable task` despite assigned tasks existing | Tasks assigned to other agents or all tasks blocked | Check `orchestrator_list_tasks(status="assigned")` for owner field |

## State Corruption

| Symptom | Cause | Action |
|---------|-------|--------|
| Watchdog emits `state_corruption_detected` | `bugs.json` or `blockers.json` contains `{}` instead of `[]` | Engine auto-heals on next read via `_read_json_list`; no manual action needed |
| Repeated corruption after auto-heal | External process writing bad state | Check for concurrent state writers; only one MCP server should manage state |
| `json.JSONDecodeError` in watchdog logs | Truncated or malformed state file | Manually fix: `echo '[]' > state/bugs.json` |
| Task list empty unexpectedly | `tasks.json` corrupted or deleted | Check `state/tasks.json` exists and contains valid JSON array |

## tmux Session Issues

| Symptom | Cause | Action |
|---------|-------|--------|
| `Session already exists: agents-autopilot` | Previous session still running | `tmux attach -t agents-autopilot` or `tmux kill-session -t agents-autopilot` |
| `tmux is required` error | tmux not installed | Install tmux or use `./scripts/autopilot/supervisor.sh` instead |
| Pane shows blank or exited | Loop process crashed | Check supervisor log; restart pane (see [operator-runbook.md](operator-runbook.md) section 4) |
| Monitor window shows errors | `codex mcp list` or log dir missing | Informational only; does not affect autopilot operation |

## Supervisor Issues

| Symptom | Cause | Action |
|---------|-------|--------|
| `status` shows `dead` for a process | Process crashed after start | Run `supervisor.sh stop` then `supervisor.sh start` |
| Stale pidfiles after reboot | PIDs from previous boot no longer valid | Run `supervisor.sh clean` to remove stale pidfiles |
| `supervisor.sh stop` hangs for 10s per process | Process not responding to SIGTERM | Normal — supervisor waits 10s then sends SIGKILL |
| Logs accumulating in `.autopilot-logs/` | Normal operation | Loops auto-prune per `--max-logs`; run `supervisor.sh clean` for supervisor logs |

## Diagnostic Commands

Quick checks to run when something seems wrong:

```bash
# Overall log health
./scripts/autopilot/log_check.sh

# Strict mode (exits non-zero on problems)
./scripts/autopilot/log_check.sh --strict

# Check all scripts work
./scripts/autopilot/smoke_test.sh

# Check orchestrator state (from any connected CLI)
orchestrator_status
orchestrator_list_tasks
orchestrator_list_blockers(status="open")
orchestrator_list_agents(active_only=false)
```

## References

- [docs/operator-runbook.md](operator-runbook.md) — Full operational procedures
- [docs/quickstart-headless-mvp.md](quickstart-headless-mvp.md) — Quickstart guide
- [README.md](../README.md#autopilot-autonomous-loops) — Autopilot overview
