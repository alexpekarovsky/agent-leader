# Glossary: Ambiguous Status Terms

> Concrete examples and recommended wording for commonly confused terms
> in operator reports and dashboard output.

## Terms

### 1. active
**Definition:** Agent has heartbeated within timeout window.
**Example:** `"status": "active", "last_seen": "2026-02-26T15:32:46+00:00"`
**Recommended wording:** "claude_code is **active** (last seen 30s ago)"

### 2. stale
**Definition:** Agent entry exists but heartbeat has exceeded timeout.
**Example:** `"status": "stale", "last_seen": "2026-02-21T22:20:20+00:00"`
**Recommended wording:** "gemini is **stale** (last seen 5 days ago — likely offline)"

### 3. offline
**Definition:** Agent not in `active_agents` list. May still appear in `agent_instances`.
**Recommended wording:** "gemini is **offline** — not responding to heartbeats"
**Differs from stale:** Offline is the operator-facing summary; stale is the system status.

### 4. idle
**Definition:** Agent is active but not working on a task (`current_task_id: null`).
**Recommended wording:** "claude_code is **idle** — waiting for task assignment"

### 5. blocked
**Definition (task):** Task cannot proceed due to an unresolved dependency or question.
**Example:** `"status": "blocked"` in task record
**Recommended wording:** "TASK-xyz is **blocked** — waiting on blocker resolution"
**Note:** Distinct from agent being offline.

### 6. reported
**Definition:** Agent submitted a completion report; awaiting manager validation.
**Example:** `"status": "reported"` in task record
**Recommended wording:** "TASK-xyz is **reported** — pending manager review"
**Note:** Task is not yet done until validated.

### 7. in_progress
**Definition:** Task has been claimed and agent is working on it.
**Recommended wording:** "TASK-xyz is **in progress** by claude_code"
**Warning:** If agent is stale but task is in_progress, the task may be stuck.

### 8. done
**Definition:** Task report was validated and accepted by manager.
**Recommended wording:** "TASK-xyz is **done** — validated at [timestamp]"

### 9. bug_open
**Definition:** Task report was rejected; a bug was filed for the agent to fix.
**Recommended wording:** "TASK-xyz has an **open bug** — needs rework by [owner]"

### 10. assigned
**Definition:** Task created and routed to an owner but not yet claimed.
**Recommended wording:** "TASK-xyz is **assigned** to gemini — not yet started"
**Warning:** Long-lived assigned status may indicate offline agent.

### 11. verified (identity)
**Definition:** Agent connection passed identity verification (same project, matching metadata).
**Recommended wording:** "claude_code **verified** — same project, identity confirmed"

### 12. instance_id
**Definition:** Unique identifier for a specific running instance of an agent.
**Recommended wording:** "claude_code instance **cc#worker-01**"
**Note:** `#default` suffix means legacy client without explicit identity.

## Wording Alignment

All terms above match the values returned by `orchestrator_status()`,
`list_tasks()`, `list_agents()`, and `list_agent_instances()`.
