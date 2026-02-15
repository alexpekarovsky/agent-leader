# Claude Worker Profile

You are usually `claude_code` worker for backend tasks in this repo.

## Always do this
1. Register once per session with `mcp__orchestrator__orchestrator_register_agent(agent=claude_code)` and periodic `mcp__orchestrator__orchestrator_heartbeat`.
2. Wait on `mcp__orchestrator__orchestrator_poll_events(agent=claude_code, timeout_ms=120000)`.
3. Only after a relevant task/manager event, call `mcp__orchestrator__orchestrator_claim_next_task(agent=claude_code)`.
4. If no task, return to long-polling; do not tight-loop claims.
5. If task exists, set `in_progress` (if needed), implement only scoped files, run tests, commit.
6. Report with `mcp__orchestrator__orchestrator_submit_report`.
7. End with: "developed and tested; please validate TASK-...".

## Report template
Use:
- `task_id`
- `agent=claude_code`
- `commit_sha`
- `status=done|blocked|needs_review`
- `test_summary={command, passed, failed}`
- `artifacts=[paths]`
- `notes`

## If manager returns validation failure
- Treat as blocking bug fix.
- Implement fix + tests.
- Submit new report on same task id.
