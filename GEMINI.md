# Gemini Worker Profile

You are usually `gemini` worker for frontend tasks in this repo.

## Always do this
1. Register once per session with `orchestrator_register_agent(agent=gemini)` and periodic `orchestrator_heartbeat`.
2. Wait on `orchestrator_poll_events(agent=gemini, timeout_ms=120000)`.
3. Only after a relevant task/manager event, call `orchestrator_claim_next_task(agent=gemini)`.
4. If no task, return to long-polling; do not tight-loop claims.
5. If task exists, implement scope, run tests, commit.
6. Submit `orchestrator_submit_report` with structured test results.
7. End with: "developed and tested; please validate TASK-...".

## Non-negotiable
- Never mark done without MCP report.
- Keep changes scoped to assigned task.
- Include exact test command and pass/fail counts.
