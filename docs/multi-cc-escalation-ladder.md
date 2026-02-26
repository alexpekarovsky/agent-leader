# Multi-CC Escalation Ladder

When to check status, publish an event, or raise a blocker during dual Claude Code operation in the restart milestone rollout.

## Escalation levels

| Level | Action | When to use | Cost |
|-------|--------|-------------|------|
| **L0 — Self-check** | Query orchestrator state locally | Routine: verify before acting | Low |
| **L1 — Status check** | Call `orchestrator_list_tasks` / `orchestrator_list_agents` | Something looks off but may be transient | Low |
| **L2 — Manager event** | Call `orchestrator_publish_event` with correction/sync type | Need the manager to adjust plan or re-prioritize | Medium |
| **L3 — Blocker** | Call `orchestrator_raise_blocker` | Cannot proceed without manager/operator decision | High |
| **L4 — Operator ping** | Manual intervention outside orchestrator | System-level issue (crashed process, disk full, credentials) | Highest |

## Scenario ladder

### 1. Duplicate claim suspicion

Both sessions claimed tasks but you suspect they got the same one.

| Step | Level | Action |
|------|-------|--------|
| Check | L0 | `orchestrator_get_tasks_for_agent(agent="claude_code", status="in_progress")` |
| If two tasks with same ID | L3 | `orchestrator_raise_blocker(question="Duplicate claim detected for TASK-xxx. Which session should keep it?")` |
| If different tasks | — | No issue; continue working |

**Example:**
```
orchestrator_get_tasks_for_agent(agent="claude_code", status="in_progress")
# Returns: [TASK-abc123, TASK-def456] — two different tasks, no collision
```

### 2. Unclear task ownership

A task is `in_progress` but you don't know which session is working on it.

| Step | Level | Action |
|------|-------|--------|
| Check task details | L1 | `orchestrator_list_tasks(status="in_progress")` — look at `updated_at` timestamps |
| Check recent worker logs | L0 | `tail .autopilot-logs/worker-claude_code-claude-*.log` for the task ID |
| If you can identify the session | — | Let it continue |
| If task is stale (>15 min, no log activity) | L2 | `orchestrator_publish_event(type="manager.sync", data={"concern": "TASK-xxx may be orphaned"})` |
| If task is very stale (>30 min) | L3 | `orchestrator_raise_blocker(question="TASK-xxx in_progress for 30+ min with no activity. Reassign?")` |

### 3. Stalled task queue

No new tasks are being completed.  Both workers appear idle or spinning.

| Step | Level | Action |
|------|-------|--------|
| Check queue | L1 | `orchestrator_list_tasks(status="assigned")` — are there tasks to claim? |
| Check worker status | L1 | `orchestrator_list_agents` — are workers `active`? |
| If tasks exist but workers aren't claiming | L2 | `orchestrator_publish_event(type="manager.execution_plan", data={"action": "workers should claim_next_task"})` |
| If no tasks exist | L2 | `orchestrator_publish_event(type="manager.sync", data={"concern": "Task queue empty. Create more tasks?"})` |
| If workers are `stale`/`disconnected` | L4 | Check supervisor: `supervisor.sh status`, restart if needed |

### 4. Claim override conflict

You set a `claim_override` but the wrong session picked it up.

| Step | Level | Action |
|------|-------|--------|
| Check current override | L0 | Look at claim override state (it's per-agent, not per-session) |
| If wrong session claimed | L1 | Check if the session is already working on it — interrupting wastes work |
| If task hasn't started | L2 | Set a new override for the intended task: `orchestrator_set_claim_override(agent="claude_code", task_id="TASK-correct", source="codex")` |
| If task is already in progress by wrong session | — | Let it finish; the report will be valid regardless of which session submits |

**Example:**
```
# CC1 was supposed to get TASK-aaa but CC2 claimed it
# If CC2 hasn't started real work yet:
orchestrator_update_task_status(task_id="TASK-aaa", status="assigned", source="codex")
orchestrator_set_claim_override(agent="claude_code", task_id="TASK-aaa", source="codex")
# Then have CC1 call claim_next_task
```

### 5. Git merge conflict between sessions

Both sessions committed to the same file and one push fails.

| Step | Level | Action |
|------|-------|--------|
| Detect | L0 | `git pull --rebase` fails with conflict markers |
| If conflict is in generated/state files | L0 | Accept incoming changes, recommit |
| If conflict is in source code | L3 | `orchestrator_raise_blocker(question="Git conflict in {file} between CC1 and CC2 work. Which version to keep?")` |
| If conflict is in docs only | L0 | Merge manually (docs rarely have semantic conflicts) |

### 6. Missing visibility fields (no instance_id)

You can't tell which session heartbeated last or which is actually active.

| Step | Level | Action |
|------|-------|--------|
| Check agent status | L1 | `orchestrator_list_agents` — shows one `claude_code` entry |
| Check `last_seen` age | L0 | If `last_seen` is very recent, at least one session is alive |
| If you need to know which session | L0 | Check supervisor: `supervisor.sh status` for the PID, then `ps` to see which terminal owns it |
| If both sessions seem dead | L4 | `supervisor.sh restart` or manually restart the worker loops |

**Example:**
```
# orchestrator_list_agents shows claude_code last_seen=2s ago
# This means at least one session heartbeated recently
# To find which: check .autopilot-logs/ for the most recent worker-claude_code-*.log
ls -lt .autopilot-logs/worker-claude_code-*.log | head -3
```

### 7. Report rejected (task already completed)

You submit a report but the task was already completed by the other session.

| Step | Level | Action |
|------|-------|--------|
| Check rejection reason | L0 | The submit_report response will indicate the task is already closed |
| If your work is wasted | L1 | Check if there's another task to claim: `orchestrator_claim_next_task` |
| If your work is valuable | L2 | `orchestrator_publish_event(type="manager.sync", data={"note": "Session completed TASK-xxx independently; commit SHA for reference: abc123"})` |

### 8. Watchdog flags claude_code as stale

The watchdog emits a `stale_task` record for a `claude_code` task.

| Step | Level | Action |
|------|-------|--------|
| Check if worker is running | L1 | `supervisor.sh status` — is claude `running`? |
| If running | L0 | The task may be genuinely large; check the worker log for activity |
| If dead | L4 | Restart: `supervisor.sh restart` |
| If running but log shows no recent output | L3 | `orchestrator_raise_blocker(question="claude_code worker running but not producing output for TASK-xxx. CLI may be hung.")` |

## Quick reference

| Scenario | First action | Escalate to |
|----------|-------------|-------------|
| Duplicate claim | L0: check task list | L3: blocker if confirmed |
| Unclear ownership | L1: check timestamps | L3: blocker if stale >30 min |
| Stalled queue | L1: check queue + agents | L4: restart if workers dead |
| Override conflict | L0: check override state | Let wrong session finish |
| Git conflict | L0: pull --rebase | L3: blocker for source conflicts |
| Missing visibility | L1: list agents | L4: restart if both dead |
| Rejected report | L0: read rejection | L1: claim next task |
| Stale alert | L1: check supervisor | L4: restart if dead |

## References

- [dual-cc-operation.md](dual-cc-operation.md) — Technical collision analysis
- [dual-cc-conventions.md](dual-cc-conventions.md) — Session labeling and claim etiquette
- [monitor-pane-interpretation.md](monitor-pane-interpretation.md) — Reading watchdog alerts
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor status and restart commands
