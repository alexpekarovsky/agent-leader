# agent-leader

`agent-leader` is an MCP orchestration server for multi-agent software delivery (Codex manager + Claude/Gemini workers).

## Supported platforms and clients
- Supported agent CLIs: `Codex CLI`, `Claude Code`, `Gemini CLI` (only).
- This project is currently tested on `macOS`.
- Linux may work but is not officially validated yet.
- Windows is not currently supported in this setup.

## In plain language
`agent-leader` helps multiple AI coding agents work on one software project like a real team instead of random parallel chats.

It gives you:
- one manager agent that plans and delegates work
- worker agents that implement tasks and report results
- one shared system of record for task state, reports, blockers, bugs, and decisions

So instead of "who did what?" or "did anyone validate this?", everything is tracked through the same control plane.

## What you get
- MCP control plane: tasks, reports, validation, bug loops, events.
- One-shot worker attach: `orchestrator_connect_to_leader`.
- Optional manager readiness gate: `orchestrator_connect_workers`.
- Manual workflow first (recommended).

## How it works (general flow)
1. Workers attach to the leader (`connect to leader`).
2. Manager confirms workers are live (optional handshake).
3. Manager creates tasks and assigns them.
4. Workers implement, run tests, commit, and submit structured reports.
5. Manager validates reports:
  - pass -> task closes
  - fail -> bug opens and worker loops on fix
6. Repeat until all tasks are done.

This creates a predictable delivery loop instead of ad-hoc prompting.

## Why this is powerful
- Reliability: every task has a lifecycle, not just chat text.
- Accountability: reports include commit SHA + test outcomes.
- Speed with control: workers can execute in parallel while manager keeps quality gates.
- Fewer coordination failures: shared event/task state reduces missed handoffs.
- Scalable team pattern: same flow works as you add more agents/tools later.

## MCP server name
- `agent-leader-orchestrator`

## Prerequisites
- `python3` (3.10+)
- `codex`
- `claude`
- `gemini`
- all CLIs authenticated

## Install (single project mode)
Run inside this repository:

```bash
cd /path/to/repo
./scripts/install_agent_leader_mcp.sh --all
```

This binds all CLIs to this same project/repo as `ORCHESTRATOR_ROOT`.
All participating agents (manager + workers) must operate on that same project root.

## Verify install
```bash
claude mcp list | rg "agent-leader-orchestrator"
codex mcp list | rg "agent-leader-orchestrator"
gemini mcp list | rg "agent-leader-orchestrator"
```

In any agent, call `orchestrator_status` and verify:
- `server = agent-leader-orchestrator`
- `root = <this repo path>`

## Exact run workflow (manual, recommended)
Open 3 terminals in this repo.
Important: all 3 terminals must be in the same project/repo folder.

### Terminal A: Codex manager
```bash
cd /path/to/repo
codex
```
Prompt:
```text
You are the manager for this repo. Use agent-leader-orchestrator MCP. Bootstrap, create milestones/tasks, delegate, validate in loop, and block only when user input is required.
```

### Terminal B: Claude worker
```bash
cd /path/to/repo
claude
```
Prompt:
```text
connect to leader
```

### Terminal C: Gemini worker
```bash
cd /path/to/repo
gemini
```
Prompt:
```text
connect to leader
```

### Connection handshake (single place)
In Codex manager:
```text
Call orchestrator_connect_workers with source=codex workers=["claude_code","gemini"] timeout_seconds=90
```
Proceed only if:
- `status: connected`
- `missing: []`
If `status: timeout`, inspect `diagnostics` in the response for per-worker reason (`not_registered`, `no_recent_heartbeat`, task activity hints).

### LLM install/run instruction (copy/paste)
```text
Install MCP server `agent-leader-orchestrator` from this repository with `./scripts/install_agent_leader_mcp.sh --all`, verify via `mcp list`, then call `orchestrator_status` and confirm `server=agent-leader-orchestrator` and `root` is this repository. Then run manager/worker flow (workers connect to leader; manager performs the connection handshake once; then manager bootstraps/creates tasks; workers claim/report; manager validates).
```

### 10-minute status updates
In Codex manager, every 10 minutes call:
```text
Call orchestrator_live_status_report
```
Use `report_text` directly in chat. If you want fixed manual percentages, pass overrides:
```text
Call orchestrator_live_status_report with overall_percent=14 phase_1_percent=35 phase_2_percent=0 phase_3_percent=0 backend_task_id="TASK-52e72f6f" backend_percent=30 frontend_task_id="TASK-25dd31a9" frontend_percent=25 qa_percent=6
```

## Token usage guidance
To minimize token burn:
- workers call `orchestrator_connect_to_leader` once at session start
- `orchestrator_connect_to_leader` now auto-claims one available task for that worker by default
- workers use `orchestrator_poll_events(timeout_ms=120000)`
- worker presence is auto-refreshed by normal worker actions (`poll_events`, `claim_next_task`, `submit_report`, `ack_event`)
- after ~10 minutes without keepalive, orchestrator emits `agent.stale_reconnect_required` with instructions to rerun handshake (`connect to leader` + `connect_workers`)
- avoid rapid `claim_next_task` loops when idle
- manager uses `orchestrator_connect_workers` instead of repeated manual ping events

## Safety and permission modes
Preferred mode:
- keep normal approval/sandbox settings

High-risk no-restrictions modes:
- Codex: `--dangerously-bypass-approvals-and-sandbox`
- Claude: `--dangerously-skip-permissions`
- Gemini: `--approval-mode yolo`

Use no-restrictions only in trusted local environments.

Example startup commands (no restrictions):
```bash
# Terminal A
cd /path/to/repo && codex --dangerously-bypass-approvals-and-sandbox

# Terminal B
cd /path/to/repo && claude --dangerously-skip-permissions

# Terminal C
cd /path/to/repo && gemini --approval-mode yolo
```

## Prompt Examples
Manager prompt example:
```text
Use agent-leader-orchestrator. After connection handshake, bootstrap, create a 3-phase plan, split backend to claude_code and frontend to gemini, enforce reports with tests/commit SHA, validate each task, open bugs on failure, and continue until all tasks are done.
```

Worker prompt example:
```text
connect to leader. Then wait for tasks, implement only assigned scope, run tests, submit orchestrator report with commit SHA and pass/fail counts, and ask manager to validate.
```

## Troubleshooting
### Workers not active
- run `connect to leader` in each worker tab
- manager runs `orchestrator_connect_workers` again
- if still timing out, use returned `diagnostics` to identify which worker is stale/unregistered

### Blocker resolved but worker offline
- when manager resolves a blocker and owner is offline/stale, task is moved to `assigned` (not `in_progress`) and marked `degraded_comm`
- this prevents false progress signals; worker should reconnect and claim task again

### Wrong root
- run `orchestrator_status`
- reinstall MCP from this repo with `./scripts/install_agent_leader_mcp.sh --all`

### Gemini disconnected
- restart Gemini MCP/session, then run `connect to leader`

## Files
- Server: `orchestrator_mcp_server.py`
- Engine: `orchestrator/engine.py`
- Installer: `scripts/install_agent_leader_mcp.sh`
- Roadmap: `ROADMAP.md`
