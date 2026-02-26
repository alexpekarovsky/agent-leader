# Timeout Semantics — Expected vs Unexpected

CLI timeouts in the autopilot system are a normal control mechanism, not always errors. This document explains when timeouts are expected, when they indicate problems, and what to do in each case.

## How Timeouts Work

Each loop invokes a CLI agent (codex, claude, gemini) via `run_cli_prompt()` in `common.sh`. If the CLI doesn't exit within `--cli-timeout` seconds, the process is killed and a timeout marker is written to the log:

```
[AUTOPILOT] CLI timeout after 300s for codex
```

The loop itself continues to the next iteration — a timeout does not stop the loop.

## Expected Timeouts

### Smoke tests

Smoke tests intentionally use very short timeouts (1-2 seconds) with stub CLIs that sleep forever. The timeout is the *intended exit mechanism* — it proves the timeout path works correctly.

```bash
# From smoke_test.sh: 2s timeout with sleeping stub
./scripts/autopilot/manager_loop.sh --once --cli-timeout 2
```

Seeing `[AUTOPILOT] CLI timeout` in smoke test logs is **correct behavior**, not a failure.

### First iteration after startup

The first CLI call in a new session often takes longer due to:
- Model loading and initialization
- MCP server connection setup
- Initial state bootstrapping

A timeout on the first iteration is common and usually resolves by the second cycle. Consider setting `--cli-timeout` to accommodate cold starts.

### Complex tasks

Some tasks legitimately take longer than the default timeout:
- Large code refactors
- Multi-file test suites
- Tasks requiring extensive research

For these, increase `--worker-cli-timeout` rather than treating timeouts as errors.

## Unexpected Timeouts

### Repeated timeouts on consecutive cycles

If the same loop times out on every cycle, something is wrong:

| Possible cause | Diagnostic |
|---------------|------------|
| CLI binary not responding | Run `claude --version` or `codex --version` manually |
| MCP server down | Check `orchestrator_status()` from another session |
| API rate limiting | Check CLI error output in the log file |
| Network issues | Check connectivity to API endpoints |

### Timeout on previously fast operations

If a manager cycle that normally takes 30s suddenly times out at 300s:

1. Check the log file for partial output — what was the CLI doing when it timed out?
2. Check if the task board has grown significantly (more tasks = longer manager cycles)
3. Check if a large number of reports are pending validation

### Worker timeout with no task progress

If a worker times out but the task status hasn't changed:

1. The worker may have started but never called any MCP tools
2. Check the worker log for reasoning/planning output before the timeout
3. The task may be too vague — add clearer acceptance criteria

## Timeout Configuration

| Flag | Applies to | Default | Recommended range |
|------|-----------|---------|-------------------|
| `--cli-timeout` (manager_loop) | Manager CLI calls | 300s | 120-600s |
| `--cli-timeout` (worker_loop) | Worker CLI calls | 600s | 300-1200s |
| `--manager-cli-timeout` (supervisor/tmux) | Manager via launcher | 300s | 120-600s |
| `--worker-cli-timeout` (supervisor/tmux) | Worker via launcher | 600s | 300-1200s |

### Tuning guidelines

- **Too short**: Frequent timeouts interrupt legitimate work, waste compute
- **Too long**: Stuck CLI processes block the loop for too long before recovery
- **Default (300s/600s)**: Good for most tasks; increase for known complex workloads

## Timeout in Logs

### Where the marker appears

The timeout marker `[AUTOPILOT] CLI timeout after Ns for <cli>` is written to the per-cycle log file in `.autopilot-logs/`. It's the last line in that log file since the CLI was killed.

### Loop stderr output

The loop also logs to stderr (visible in tmux panes or supervisor logs):

```
[2026-02-25 14:30:22] [ERROR] manager cycle timed out after 300s; see .autopilot-logs/manager-codex-20260225-143022.log
```

### Counting timeouts

```bash
# Count timeouts across all recent logs
grep -c '\[AUTOPILOT\] CLI timeout' .autopilot-logs/*.log

# Use log_check for a summary
./scripts/autopilot/log_check.sh
```

## Operator Actions

### For expected timeouts (smoke tests, first iteration)

No action needed. The loop handles it automatically.

### For intermittent timeouts

1. Check if the task was completed despite the timeout (sometimes the CLI finishes but the process cleanup races)
2. Let the next iteration retry — many issues are transient
3. If timeouts persist, check the causes table above

### For persistent timeouts

1. Increase `--cli-timeout` if tasks are legitimately complex
2. Check CLI health: `codex --version`, `claude --version`
3. Check MCP server connectivity
4. Check API quotas and rate limits
5. Restart the affected loop

## References

- [docs/log-file-taxonomy.md](log-file-taxonomy.md) — Timeout marker format and location
- [docs/troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Timeout troubleshooting rows
- docs/incident-triage-order.md — Timeout as a failure class
