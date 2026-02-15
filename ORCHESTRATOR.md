# Configurable Multi-Agent Orchestrator (MCP)

## What this is
A local MCP server (`orchestrator_mcp_server.py`) that manages multi-agent software delivery loops in one repo:
- planning + task assignment
- worker reporting (`developed and tested`)
- manager validation
- bug-fix loop until pass
- architecture decisions with equal votes

## Architecture
- Control plane: `orchestrator_mcp_server.py`
- Core logic: `orchestrator/engine.py`
- Governance/routing: `orchestrator/policy.py`
- Event/state store: `bus/`, `state/`, `decisions/`

## Policies
- `config/policy.codex-manager.json`
- `config/policy.shared-governance.json`

Switch manager without code changes by using a different policy file.

## MCP tools
- `orchestrator_status`
- `orchestrator_bootstrap`
- `orchestrator_register_agent`
- `orchestrator_heartbeat`
- `orchestrator_list_agents`
- `orchestrator_create_task`
- `orchestrator_list_tasks`
- `orchestrator_get_tasks_for_agent`
- `orchestrator_claim_next_task`
- `orchestrator_update_task_status`
- `orchestrator_submit_report`
- `orchestrator_validate_task`
- `orchestrator_list_bugs`
- `orchestrator_publish_event`
- `orchestrator_poll_events`
- `orchestrator_ack_event`
- `orchestrator_get_agent_cursor`
- `orchestrator_decide_architecture`

## Install for agents
Use one command:
```bash
./scripts/install_orchestrator_mcp.sh --all
```

Or per agent:
```bash
./scripts/install_orchestrator_mcp.sh --claude
./scripts/install_orchestrator_mcp.sh --gemini
./scripts/install_orchestrator_mcp.sh --codex
```

Use shared-governance policy:
```bash
./scripts/install_orchestrator_mcp.sh --all --policy config/policy.shared-governance.json
```

## Smoke test
```bash
./scripts/smoke_test_orchestrator_mcp.sh
```

## End-to-end demo run
```bash
./scripts/demo_project_loop.sh
```

## Manual Sessions (Recommended)
Open 3 terminals in the project repo:
- manager: `codex`
- worker: `claude`
- worker: `gemini`

Workers then run one MCP action:
- `orchestrator_connect_to_leader`

Manager runs one MCP action:
- `orchestrator_connect_workers`

## End-to-end story
1. Codex (manager) receives: "research and plan 1,2,3 and work with Claude Code".
2. Codex calls:
   - `orchestrator_bootstrap`
   - `orchestrator_create_task` for backend (`owner=claude_code` by policy)
   - `orchestrator_create_task` for frontend (`owner=gemini` by policy)
3. Claude worker loop:
   - `orchestrator_claim_next_task(agent=claude_code)`
   - implement + test + commit
   - `orchestrator_submit_report(...)`
   - message: "developed and tested; please validate TASK-..."
4. Gemini does same for frontend.
5. Codex validates each report with `orchestrator_validate_task`:
   - pass -> task status `done`
   - fail -> bug opens automatically and worker loops again
6. If architecture dilemma appears, all three vote through `orchestrator_decide_architecture`; ADR is generated in `decisions/`.

## Pub/Sub Pattern
Use event tools for asynchronous coordination:
- Manager publishes coordination events via `orchestrator_publish_event` (optionally targeted with `audience`).
- Workers wait/read updates via `orchestrator_poll_events(agent=..., timeout_ms=...)`.
- Workers acknowledge processed events via `orchestrator_ack_event`.
- Cursor replay position can be inspected via `orchestrator_get_agent_cursor`.

Recommended worker loop:
1. `orchestrator_connect_to_leader` (one-shot attach)
2. `orchestrator_poll_events` (long-poll with timeout)
3. `orchestrator_claim_next_task`
4. implement/test/commit
5. `orchestrator_submit_report`
6. `orchestrator_ack_event` for processed coordination events
7. if no task claimed, return to step 2 (avoid claim tight-loops)

Tenant discovery lifecycle:
1. each agent calls `orchestrator_register_agent` once per session
2. each agent calls `orchestrator_heartbeat` periodically
3. manager uses `orchestrator_list_agents(active_only=true)` to discover pool members

## Worker report contract
Required fields:
- `task_id`
- `agent`
- `commit_sha`
- `status`
- `test_summary.command`
- `test_summary.passed`
- `test_summary.failed`

Example shape: `config/report.schema.json`

## Instruction files
- `AGENTS.md` (Codex manager behavior + trigger phrases)
- `CLAUDE.md` (Claude worker loop)
- `GEMINI.md` (Gemini worker loop)
- `.claude/commands/orch-plan.md`
- `.claude/commands/orch-report.md`
- `.gemini/commands/orch-worker.md`

## Notes
- This is MCP-native orchestration with A2A-style workflow semantics.
- If you later need strict A2A wire protocol, add an A2A gateway above this MCP control plane.
