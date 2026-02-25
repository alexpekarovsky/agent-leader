# Headless MVP Architecture

## Component Overview

```
┌─────────────────────────────────────────────────────┐
│                   tmux session                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ manager  │ │ claude   │ │ gemini   │ │watchdog│ │
│  │ loop     │ │ worker   │ │ worker   │ │ loop   │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       │             │            │            │      │
└───────┼─────────────┼────────────┼────────────┼──────┘
        │             │            │            │
        ▼             ▼            ▼            │
   ┌─────────────────────────────────────┐      │
   │     Orchestrator MCP Server         │      │
   │  ┌───────────────────────────────┐  │      │
   │  │        Engine (engine.py)     │  │      │
   │  │  tasks │ bugs │ blockers │ bus│  │      │
   │  └───────────────────────────────┘  │      │
   └──────────────┬──────────────────────┘      │
                  │                             │
                  ▼                             ▼
            state/ directory              .autopilot-logs/
         tasks.json                     watchdog-*.jsonl
         bugs.json                      manager-*.log
         blockers.json                  worker-*.log
         bus/events.jsonl
         bus/audit.jsonl
```

## Component Responsibilities

| Component | Script | Responsibility |
|-----------|--------|----------------|
| **Manager loop** | `manager_loop.sh` | Runs codex CLI in a cycle: set role, heartbeat, bootstrap, run manager_cycle, validate reports, inspect watchdog diagnostics, publish execution plans. One cycle per iteration. |
| **Worker loop** | `worker_loop.sh` | Runs claude/gemini CLI in a cycle: connect to leader, poll events, claim next task, implement, run tests, submit report or raise blocker. One task attempt per iteration. |
| **Watchdog loop** | `watchdog_loop.sh` | Inspects `state/` files directly (no MCP): detects stale tasks by status/age, detects state corruption (dict where list expected), emits JSONL diagnostics. No writes to state. |
| **tmux launcher** | `team_tmux.sh` | Creates a tmux session with 4 panes (manager, claude, gemini, watchdog) and a monitor window. Supports `--dry-run` for preview. |
| **Monitor loop** | `monitor_loop.sh` | Displays log tail and MCP status in the monitor tmux window. Informational only. |
| **Supervisor** | `supervisor.sh` | Manages loops as background processes with pidfiles. Supports start/stop/status/restart/clean without tmux. |
| **Log checker** | `log_check.sh` | Inspects `.autopilot-logs/` for per-loop file presence/age, JSONL validity, timeout frequency. Strict mode for CI. |
| **Smoke tests** | `smoke_test.sh` | Validates all scripts with stub CLIs: dry-run, timeout paths, watchdog diagnostics, log retention, tmux launch/teardown, log_check modes. |
| **MCP server** | `orchestrator_mcp_server.py` | Exposes orchestrator engine over MCP stdio protocol. Routes CLI tool calls to engine methods. |
| **Engine** | `orchestrator/engine.py` | Core state machine: task lifecycle, claim/report/validate, blockers, bugs, events, audit, self-healing. Single source of truth. |

## Data Flow

### Manager cycle

```
manager_loop.sh
  → codex CLI (with prompt)
    → MCP: orchestrator_set_role, orchestrator_heartbeat
    → MCP: orchestrator_bootstrap (if needed)
    → MCP: orchestrator_manager_cycle (validate reports, summarize)
    → MCP: orchestrator_list_blockers
    → reads .autopilot-logs/watchdog-*.jsonl (file I/O)
    → MCP: orchestrator_publish_event (execution plans)
  → writes manager-*.log
```

### Worker cycle

```
worker_loop.sh
  → claude/gemini CLI (with prompt)
    → MCP: orchestrator_connect_to_leader
    → MCP: orchestrator_poll_events
    → MCP: orchestrator_claim_next_task
    → (implement task, run tests, git commit)
    → MCP: orchestrator_submit_report
    OR
    → MCP: orchestrator_raise_blocker
  → writes worker-*.log
```

### Watchdog cycle

```
watchdog_loop.sh
  → python3 inline script
    → reads state/tasks.json (file I/O, no MCP)
    → reads state/bugs.json, blockers.json
    → detects stale tasks (age > timeout per status)
    → detects state corruption (non-list types)
    → emits JSONL diagnostics
  → writes watchdog-*.jsonl
```

### Key data boundary

- **MCP tools**: All task/blocker/bug/event mutations go through the MCP server
- **File reads**: Watchdog reads state files directly (read-only) for independence from MCP
- **Logs**: Each loop writes its own log files; log_check.sh reads them for diagnostics

## Current MVP Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| Name-based agent identity | Can't run 2 claude workers | Use one worker per CLI type |
| No task leases | Crashed worker leaves task stuck | Watchdog detects; operator or manager reassigns |
| No dispatch ack | Manager can't confirm worker received event | Check worker logs directly |
| No auto-restart | Crashed loop stays down | Operator restarts via tmux pane or supervisor |
| Watchdog is read-only | Can't auto-fix state, only report | Engine self-heals on next MCP read |
| Single MCP server per project | No cross-project routing | Run separate MCP server per project |
| Log pruning is per-loop | No global retention policy | Each loop prunes its own prefix |

## References

- [docs/roadmap.md](roadmap.md) — Future architecture phases
- [docs/operator-runbook.md](operator-runbook.md) — Operational procedures
- [docs/swarm-mode.md](swarm-mode.md) — Multi-instance future state
