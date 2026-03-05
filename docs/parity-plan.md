# Parity Plan: UX and Operator Flow Unification

This document defines the unified command vocabulary, status reporting requirements, and operator journey examples to ensure parity between **Interactive** (manual) and **Headless** (autopilot) orchestration modes.

## 1. Unified Command Vocabulary

The goal is to use consistent terminology whether interacting via a prompt or a shell script. We standardize on the **MCP Tool Names** as the canonical vocabulary.

### Canonical Actions

| Concept | Interactive (Prompt) | Headless (CLI/Script) |
| :--- | :--- | :--- |
| **Bootstrap** | `orchestrator_bootstrap` | `manager_loop.sh --bootstrap` |
| **Connect** | `orchestrator_connect_to_leader` | `worker_loop.sh --start` |
| **Manager Cycle** | `orchestrator_manager_cycle` | `manager_loop.sh --once` |
| **Task Claim** | `orchestrator_claim_next_task` | (Automatic in worker loop) |
| **Task Report** | `orchestrator_submit_report` | (Automatic in worker loop) |
| **Status Check** | `orchestrator_status` | `headless_status.sh` |
| **Reassign Stale**| `orchestrator_reassign_stale_tasks`| `watchdog_loop.sh --reassign` |
| **Raise Blocker** | `orchestrator_raise_blocker` | (Detected or loop-driven) |

### Recommended Aliases (Mental Model)

- **"Sync"**: Running a manager cycle to validate reports and update task board.
- **"Pulse"**: One iteration of a worker loop (poll, claim, act, report).
- **"Lane"**: A specific workstream or role (e.g., `default`, `wingman/qa`).

## 2. Status & Reporting Parity

To maintain a consistent mental model, both modes must expose the same data points in the same priority.

### Unified Status Block (`live_status_text`)

The `orchestrator_status` MCP tool and `headless_status.sh` MUST both provide a "Ready-to-Paste" status block. This block allows an operator to quickly inform the LLM of the current state.

**Required Schema for Status Block:**
```text
ORCHESTRATOR STATUS: [Active/Idle]
PROJECT: [Path]
LEADER: [Agent] | TEAM: [Agent1, Agent2, ...]
PIPELINE: [Total] Tasks | [Assigned] Assigned | [In Progress] IP | [Reported] Review | [Done] Done
BLOCKERS: [Count] Open | BUGS: [Count] Open
WINGMAN LANE: [Agent] [Status] | [Count] Tasks Awaiting Review
```

### Logging Parity

- **Worker Logs:** Every worker cycle must log a `WORKER_PULSE` event with `task_id`, `status`, and `duration`.
- **Manager Logs:** Every manager cycle must log a `MANAGER_SYNC` event with `validated_tasks_count` and `new_plans_count`.
- **Audit Correlation:** All logs in `.autopilot-logs/` should include the `session_id` or `instance_id` to correlate with the central `bus/audit.jsonl`.

## 3. Operator Journeys

### Scenario A: Starting the Team
- **Interactive:**
  1. Open Codex: "You are leader. Bootstrap the project."
  2. Open Claude: "Connect to leader as team member."
  3. Open Gemini: "Connect to leader as team member."
- **Headless:**
  1. `./scripts/autopilot/team_tmux.sh`
  2. `tmux attach -t agents-autopilot`

### Scenario B: Fixing a Stuck Task
- **Interactive:**
  1. "Show in-progress tasks."
  2. "Reassign TASK-123 to unassigned."
- **Headless:**
  1. `./scripts/autopilot/headless_status.sh` (Identify stale task)
  2. `./scripts/autopilot/watchdog_loop.sh --once` (Triggers auto-reassignment)

### Scenario C: Wingman Review Flow
1. **Worker** submits report (`status="reported"`).
2. **Wingman** loop sees task in `reported` status.
3. **Wingman** claims task, performs QA, and updates status to `done` or `bug_open`.
4. **Manager** cycle validates and closes the loop.

## 5. Headless Execution Path Upgrades (v0.2+)

Concrete upgrades to bring headless execution to parity with interactive control and safety.

### Upgrade A: Supervisor Auto-Restart & Health (Effort: 2h)
- **Change:** Implement a `monitor` loop in `Supervisor` that checks for `dead` processes and restarts them with exponential backoff.
- **Diagnostics:** Write `restart_reason` to `.restarts` file for better debugging.
- **Smoke Test:** Kill a `worker_loop` process and verify supervisor restarts it within 30s.

### Upgrade B: Role/Instance Safety in common.sh (Effort: 1h)
- **Change:** Update `run_cli_prompt` to inject `ORCHESTRATOR_INSTANCE_ID` and `ORCHESTRATOR_ROLE` environment variables into the CLI subprocess.
- **Safety:** Verify the agent identity before execution to prevent cross-session task theft.
- **Smoke Test:** Run `run_cli_prompt` with a mismatched agent name and verify it fails with an error log.

### Upgrade C: Loop Error Reporting & Recovery (Effort: 2h)
- **Change:** If `run_cli_prompt` fails (non-zero rc or timeout), the loop should automatically call `orchestrator_publish_event` with a `task.error` or `worker.failed` payload.
- **Visibility:** This ensures the manager/leader sees the failure even if the log file isn't inspected manually.
- **Smoke Test:** Simulate a CLI failure (e.g. invalid command) and verify an error event appears in `bus/audit.jsonl`.

### Upgrade D: Unified Headless Status CLI (Effort: 1h)
- **Change:** Merge `headless_status.sh` logic into `supervisor.sh status --live` to reduce script fragmentation.
- **Parity:** Ensure the output is identical to `orchestrator_status` `live_status_text`.
- **Smoke Test:** Compare `supervisor.sh status --live` output with `orchestrator_status` tool output.

## 6. Implementation Timeline

| Phase | Milestone | Effort | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Unified status UX and recovery actions | 4h | [x] Done |
| **Phase 2** | Supervisor health & auto-restart | 2h | [ ] Planned |
| **Phase 3** | Role/Instance safety hardening | 1h | [ ] Planned |
| **Phase 4** | Automated error event emission | 2h | [ ] Planned |
