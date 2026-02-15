# Multi-Agent Orchestration Rules

This project uses the `orchestrator` MCP server as the single source of truth for planning and delivery state.

## Roles
- `codex`: default manager/validator unless policy overrides it.
- `claude_code`: backend worker by default policy.
- `gemini`: frontend worker by default policy.

## Mandatory MCP-first behavior
- Never claim work is done without calling `orchestrator_submit_report`.
- Never assign work in plain text only; always create tasks with `orchestrator_create_task`.
- Always run `orchestrator_bootstrap` at start of a new project session.
- Before starting implementation, claim work with `orchestrator_claim_next_task` or set task status to `in_progress`.
- After manager validation failure, worker must treat returned bug as highest-priority fix loop.

## Trigger phrases
When user says phrases like these, execute the MCP workflow automatically:
- "research and plan"
- "work with Claude/Gemini"
- "split backend/frontend"
- "develop and test"
- "now check"

## Manager loop (Codex)
1. `orchestrator_bootstrap`
2. Create task breakdown with `orchestrator_create_task`
3. Poll progress via `orchestrator_list_tasks`
4. On worker report, run validation and call `orchestrator_validate_task`
5. If failed, communicate bug details and keep loop running until all tasks pass
6. For architecture dilemmas, call `orchestrator_decide_architecture` with equal votes

## Worker loop (Claude Code / Gemini)
1. `orchestrator_claim_next_task` with your agent id
2. Implement scoped changes only
3. Run tests
4. Commit locally
5. `orchestrator_submit_report` including commit SHA + test summary
6. Ask manager to validate

## Required worker report payload
- `task_id`
- `agent`
- `commit_sha`
- `status`
- `test_summary.command`
- `test_summary.passed`
- `test_summary.failed`
- `notes`
