# Release Notes

## v0.1.0 - First Public Release
Date: 2026-02-15

### Highlights
- Released `agent-leader` as a public MCP orchestration project.
- Added manager/worker collaboration flow for `codex`, `claude_code`, and `gemini`.
- Added one-shot worker attach: `orchestrator_connect_to_leader`.
- Added one-shot manager worker gate: `orchestrator_connect_workers`.
- Added live progress summary tool: `orchestrator_live_status_report`.

### Core Components
- MCP server: `orchestrator_mcp_server.py`
- Orchestration engine: `orchestrator/engine.py`
- Install entrypoint: `scripts/install_agent_leader_mcp.sh`

### Documentation
- Updated `README.md` for fast install + exact run flow.
- Added `ROADMAP.md` with upcoming milestones.

### Notes
- Legacy/demo files remain in repo (`agatha-quest`, `setup.sh`, `server.py`) and are not required for core orchestrator usage.
