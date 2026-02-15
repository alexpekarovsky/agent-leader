When invoked, run the manager orchestration flow:

1. Call `mcp__orchestrator__orchestrator_bootstrap`.
2. Produce a 3-phase plan (research, implementation, validation).
3. Create tasks with `mcp__orchestrator__orchestrator_create_task`.
4. Assign backend to `claude_code`, frontend to `gemini` unless user specifies otherwise.
5. Return task IDs and owners.
