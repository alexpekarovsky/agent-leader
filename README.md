# agent-leader

`agent-leader` is an MCP orchestration server for multi-agent software delivery (Codex manager + Claude/Gemini workers).

## What you get
- MCP control plane: tasks, reports, validation, bug loops, events.
- One-shot worker attach: `orchestrator_connect_to_leader`.
- One-shot manager activation gate: `orchestrator_connect_workers`.
- Manual workflow first (recommended).
- Legacy/demo files exist in this repo (`agatha-quest`, `setup.sh`, `server.py`) and are not required for core orchestrator usage.

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
cd /path/to/agent-leader
./scripts/install_agent_leader_mcp.sh --all
```

This binds all CLIs to this same repo as `ORCHESTRATOR_ROOT`.

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

### Terminal A: Codex manager
```bash
cd /path/to/agent-leader
codex
```
Prompt:
```text
You are the manager for this repo. Use agent-leader-orchestrator MCP. Bootstrap, connect workers, create milestones/tasks, delegate, validate in loop, and block only when user input is required.
```

### Terminal B: Claude worker
```bash
cd /path/to/agent-leader
claude
```
Prompt:
```text
connect to leader
```

### Terminal C: Gemini worker
```bash
cd /path/to/agent-leader
gemini
```
Prompt:
```text
connect to leader
```

### Manager activation gate
In Codex manager:
```text
Call orchestrator_connect_workers with source=codex workers=["claude_code","gemini"] timeout_seconds=90
```
Proceed only if:
- `status: connected`
- `missing: []`

### LLM install/run instruction (copy/paste)
```text
Install MCP server `agent-leader-orchestrator` from this repository with `./scripts/install_agent_leader_mcp.sh --all`, verify via `mcp list`, then call `orchestrator_status` and confirm `server=agent-leader-orchestrator` and `root` is this repository. Then run manager/worker flow (manager: bootstrap/connect_workers/create tasks; workers: connect to leader, claim, report, ask manager to validate).
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
- workers use `orchestrator_poll_events(timeout_ms=120000)`
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

## Troubleshooting
### Workers not active
- run `connect to leader` in each worker tab
- manager runs `orchestrator_connect_workers` again

### Wrong root
- run `orchestrator_status`
- reinstall MCP from this repo with `./scripts/install_agent_leader_mcp.sh --all`

### Gemini disconnected
- restart Gemini MCP/session, then run `connect to leader`

## Files
- Server: `orchestrator_mcp_server.py`
- Engine: `orchestrator/engine.py`
- Installer: `scripts/install_agent_leader_mcp.sh`
- Internal installer backend: `scripts/install_orchestrator_mcp.sh` (implementation detail)
- Roadmap: `ROADMAP.md`
