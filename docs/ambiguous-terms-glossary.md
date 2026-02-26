# Ambiguous Terms Glossary

Glossary for commonly confused orchestrator status terms. Use the recommended wording in operator reports and dashboards to avoid misinterpretation.

## 1. active vs idle

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **active** | Agent heartbeat is recent (within `stale_after_seconds` threshold) | Agent is connected and communicating |
| **idle** | Agent is active but has no task in `in_progress` state | Agent is connected, waiting for work |

**Recommended wording:**
- "claude_code is **active**, working on TASK-abc123"
- "gemini is **idle** (active, no claimed task)"

**Do not say:** "gemini is active" when it has no task -- use "idle" to signal it is available for assignment.

## 2. stale vs offline

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **stale** | Heartbeat age is approaching or just past the threshold | Borderline -- agent may recover without intervention |
| **offline** | Heartbeat age is clearly past the threshold (2x or more) | Agent is gone and tasks need reassignment |

**Recommended wording:**
- "gemini heartbeat is **stale** (last seen 620s ago, threshold 600s) -- monitoring"
- "gemini is **offline** (last seen 1800s ago) -- reassigning tasks"

**Do not say:** "offline" for a borderline case. Wait for a clear gap before declaring offline and triggering reassignment.

## 3. blocked vs bug_open

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **blocked** | Agent raised a blocker (`orchestrator_raise_blocker`) and cannot continue | Work stopped pending operator/user input |
| **bug_open** | Manager validation failed (`orchestrator_validate_task` with `passed=false`) | Deliverable rejected, agent must fix and resubmit |

**Recommended wording:**
- "TASK-abc is **blocked**: agent needs API credentials (blocker BLK-001)"
- "TASK-abc has a **bug_open**: validation found missing error handling"

**Do not say:** "blocked" when validation failed. The agent is not waiting for input -- it has work to redo.

## 4. reported vs done

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **reported** | Agent submitted a delivery report via `orchestrator_submit_report` | Work is complete from the agent's perspective, awaiting review |
| **done** | Manager validated and accepted the report via `orchestrator_validate_task(passed=true)` | Task is fully closed |

**Recommended wording:**
- "TASK-abc is **reported** -- awaiting manager validation"
- "TASK-abc is **done** -- validated and closed"

**Do not say:** "done" until the manager has validated. A reported task may still fail validation and reopen as bug_open.

## 5. assigned vs in_progress

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **assigned** | Task is queued for an agent but not yet claimed | Agent has not called `orchestrator_claim_next_task` |
| **in_progress** | Agent claimed the task and is actively working | Claim succeeded, lease issued |

**Recommended wording:**
- "TASK-abc is **assigned** to claude_code (not yet claimed)"
- "TASK-abc is **in_progress** -- claude_code claimed at 14:03"

**Do not say:** "in progress" for an unclaimed task. If many tasks are assigned but none are in_progress, investigate whether the agent is claiming work.

## 6. lease vs heartbeat

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **lease** | Task-level ownership token with an expiry time | Binds a specific task to a specific agent for a time window |
| **heartbeat** | Agent-level presence signal updated periodically | Confirms the agent process is alive, independent of any task |

**Recommended wording:**
- "TASK-abc **lease** expires at 14:20 (owned by claude_code)"
- "claude_code **heartbeat** last seen 10s ago"

**Do not say:** "heartbeat expired" when you mean a task lease expired. A lease can expire while the agent heartbeat is healthy (agent alive but task timed out).

## 7. instance vs agent

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **instance** | A specific session connection (e.g., one Claude Code terminal) | Distinguishes CC1 from CC2 when both share the `claude_code` identity |
| **agent** | The logical identity registered in the orchestrator (e.g., `claude_code`) | Used in task ownership, routing policy, and reports |

**Recommended wording:**
- "Two **instances** of claude_code are active (CC1 on backend, CC2 on docs)"
- "The **agent** claude_code owns 4 tasks in the queue"

**Do not say:** "two agents" when you mean two sessions of the same agent. Until instance_id ships (Phase B), use CC1/CC2/CC3 labels per [multi-cc-conventions.md](multi-cc-conventions.md).

## 8. verified vs same_project

| Term | Definition | When it applies |
|------|-----------|-----------------|
| **verified** | Full identity check passed during `orchestrator_connect_to_leader` | Agent provided valid metadata: client, model, cwd, session_id, etc. |
| **same_project** | Agent's `project_root` matches the manager's project root | Confirms the agent is working on the correct codebase |

**Recommended wording:**
- "gemini is **verified** (identity payload validated)"
- "gemini is **not same_project** -- project_root points to /Users/alex/other-repo"

**Do not say:** "verified" when you only checked project_root. An agent can be same_project but not verified (metadata incomplete), or verified but not same_project (connected to the wrong repo).

## Quick Reference Table

| Confused pair | Key distinction |
|--------------|-----------------|
| active / idle | idle is a subset of active (connected but no task) |
| stale / offline | stale is borderline; offline is clearly gone |
| blocked / bug_open | blocked = waiting for input; bug_open = failed validation |
| reported / done | reported = awaiting review; done = review passed |
| assigned / in_progress | assigned = queued; in_progress = claimed |
| lease / heartbeat | lease = task scope; heartbeat = agent scope |
| instance / agent | instance = session; agent = logical identity |
| verified / same_project | verified = full identity check; same_project = cwd match |
