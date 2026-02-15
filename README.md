# agent-leader

`agent-leader` is an MCP orchestration server for multi-agent software delivery (Codex manager + Claude/Gemini team members).

## Supported platforms and clients
- Supported agent CLIs: `Codex CLI`, `Claude Code`, `Gemini CLI` (only).
- This project is currently tested on `macOS`.
- Linux may work but is not officially validated yet.
- Windows is not currently supported in this setup.

## In plain language
`agent-leader` helps multiple AI coding agents work on one software project like a real team instead of random parallel chats.

It gives you:
- one manager agent that plans and delegates work
- team member agents that implement tasks and report results
- one shared system of record for task state, reports, blockers, bugs, and decisions

So instead of "who did what?" or "did anyone validate this?", everything is tracked through the same control plane.

## What you get
- MCP control plane: tasks, reports, validation, bug loops, events.
- One-shot team member attach: `orchestrator_connect_to_leader`.
- Optional manager readiness gate: `orchestrator_connect_team_members`.
- Runtime role control: `orchestrator_set_role` / `orchestrator_get_roles`.
- Manual workflow first (recommended).

## How it works (general flow)
1. Team members attach to the leader (`connect to leader`) with identity payload.
2. Manager confirms team members are live (optional handshake).
3. Manager creates tasks and assigns them.
4. Team members implement, run tests, commit, and submit structured reports.
5. Manager validates reports:
  - pass -> task closes
  - fail -> bug opens and team member loops on fix
6. Repeat until all tasks are done.

This creates a predictable delivery loop instead of ad-hoc prompting.

## Role Control (Leader / Team Member)
Default leader is `codex` from policy.

You can switch leader at runtime using MCP:
```text
Call orchestrator_set_role with agent=\"gemini\" role=\"leader\" source=\"codex\"
Call orchestrator_set_role with agent=\"codex\" role=\"team_member\" source=\"gemini\"
Call orchestrator_get_roles
```

## Why this is powerful
- Reliability: every task has a lifecycle, not just chat text.
- Accountability: reports include commit SHA + test outcomes.
- Speed with control: team members can execute in parallel while manager keeps quality gates.
- Fewer coordination failures: shared event/task state reduces missed handoffs.
- Scalable team pattern: same flow works as you add more agents/tools later.

## MCP server name
- `agent-leader-orchestrator`

## Prerequisites
- `python3` (3.10+)
- `codex`
- `claude`
- `gemini`
- all CLIs authenticated

## Install (single project mode)
Run inside this repository:

```bash
cd /path/to/repo
./scripts/install_agent_leader_mcp.sh --all
```

This binds all CLIs to this same project/repo as `ORCHESTRATOR_ROOT`.
All participating agents (manager + team members) must operate on that same project root.
By default, installer deploys the MCP server to a stable location:
- `~/.local/share/agent-leader/<version>`
It refuses ephemeral `--server-root` paths under `/tmp` unless you pass `--allow-ephemeral`.

Important installer flags:
- `--mode project|global` (default: `project`)
- `--confirm-global` (required with `--mode global`)
- `--replace-legacy` (explicitly remove legacy MCP name `orchestrator`)
- `--rollback <backup-id>` (restore config backup from failed/previous install)

## Verify install
```bash
claude mcp list | rg "agent-leader-orchestrator"
codex mcp list | rg "agent-leader-orchestrator"
gemini mcp list | rg "agent-leader-orchestrator"
```

In any agent, call `orchestrator_status` and verify:
- `server = agent-leader-orchestrator`
- `root_name = <project folder name>`

For full path debugging only:
- set `ORCHESTRATOR_STATUS_VERBOSE_PATHS=1`
- then `orchestrator_status` includes `root` and `policy` absolute paths.

## Doctor Check
Run post-install verification against actual MCP client bindings:
```bash
./scripts/doctor.sh --all --project-root /path/to/repo
```
This checks:
- MCP entry exists per CLI
- registered command path exists
- server responds to JSON-RPC health call

## Exact run workflow (manual, recommended)
Open 3 terminals in this repo.
Important: all 3 terminals must be in the same project/repo folder.

### Terminal A: Codex manager
```bash
cd /path/to/repo
codex
```
Prompt:
```text
You are the manager for this repo. Use agent-leader-orchestrator MCP. Bootstrap, create milestones/tasks, delegate, validate in loop, and block only when user input is required.
```

### Terminal B: Claude team member
```bash
cd /path/to/repo
claude
```
Prompt:
```text
connect to leader with metadata: client, model, cwd, permissions_mode, sandbox_mode, session_id, connection_id, server_version, verification_source
```

### Terminal C: Gemini team member
```bash
cd /path/to/repo
gemini
```
Prompt:
```text
connect to leader with metadata: client, model, cwd, permissions_mode, sandbox_mode, session_id, connection_id, server_version, verification_source
```

### Connection handshake (single place)
In Codex manager:
```text
Call orchestrator_connect_team_members with source=codex team_members=["claude_code","gemini"] timeout_seconds=90
```
Proceed only if:
- `status: connected`
- `missing: []`
If `status: timeout`, inspect `diagnostics` in the response for per-team member reason (`not_registered`, `no_recent_heartbeat`, task activity hints).
Only verified same-project team members are counted as connected.

### LLM install/run instruction (copy/paste)
```text
Install MCP server `agent-leader-orchestrator` from this repository with `./scripts/install_agent_leader_mcp.sh --all`, verify via `mcp list`, then call `orchestrator_status` and confirm `server=agent-leader-orchestrator` and `root` is this repository. Then run manager/team member flow (team members connect to leader; manager performs the connection handshake once; then manager bootstraps/creates tasks; team members claim/report; manager validates).
```

### 10-minute status updates
In Codex manager, every 10 minutes call:
```text
Call orchestrator_live_status_report
```
Use `report_text` directly in chat. If you want fixed manual percentages, pass overrides:
```text
Call orchestrator_live_status_report with overall_percent=14 phase_1_percent=35 phase_2_percent=0 phase_3_percent=0 backend_task_id="TASK-52e72f6f" backend_percent=30 frontend_task_id="TASK-25dd31a9" frontend_percent=25 qa_percent=6
```

## Token usage guidance
To minimize token burn:
- team members call `orchestrator_connect_to_leader` once at session start
- `orchestrator_connect_to_leader` now auto-claims one available task for that team member by default
- team members use `orchestrator_poll_events(timeout_ms=120000)`
- team member presence is auto-refreshed by normal team member actions (`poll_events`, `claim_next_task`, `submit_report`, `ack_event`)
- after ~10 minutes without keepalive, orchestrator emits `agent.stale_reconnect_required` with instructions to rerun handshake (`connect to leader` + `connect_team_members`)
- avoid rapid `claim_next_task` loops when idle
- manager uses `orchestrator_connect_team_members` instead of repeated manual ping events

## Auditing and Traceability
You now have append-only audit logs for operations:
- MCP tool-call audit log: `bus/audit.jsonl`
- Collaboration event log: `bus/events.jsonl`
- Task/blocker/bug state: `state/tasks.json`, `state/blockers.json`, `state/bugs.json`
- Installer audit log: `state/install_audit.jsonl`

Use MCP to query recent tool-call audit records:
```text
Call orchestrator_list_audit_logs with limit=200
```
Optional filters:
```text
Call orchestrator_list_audit_logs with tool="orchestrator_submit_report" status="ok" limit=100
```

## Safety and permission modes
Preferred mode:
- keep normal approval/sandbox settings

High-risk no-restrictions modes:
- Codex: `--dangerously-bypass-approvals-and-sandbox`
- Claude: `--dangerously-skip-permissions`
- Gemini: `--approval-mode yolo`

Use no-restrictions only in trusted local environments.

Example startup commands (no restrictions):
```bash
# Terminal A
cd /path/to/repo && codex --dangerously-bypass-approvals-and-sandbox

# Terminal B
cd /path/to/repo && claude --dangerously-skip-permissions

# Terminal C
cd /path/to/repo && gemini --approval-mode yolo
```

## Prompt Examples
Manager prompt example:
```text
Use agent-leader-orchestrator. After connection handshake, bootstrap, create a 3-phase plan, split backend to claude_code and frontend to gemini, enforce reports with tests/commit SHA, validate each task, open bugs on failure, and continue until all tasks are done.
```

Team member prompt example:
```text
connect to leader. Then wait for tasks, implement only assigned scope, run tests, submit orchestrator report with commit SHA and pass/fail counts, and ask manager to validate.
```

## Troubleshooting
### Team members not active
- run `connect to leader` in each team member tab
- manager runs `orchestrator_connect_team_members` again
- if still timing out, use returned `diagnostics` to identify which team member is stale/unregistered

### Blocker resolved but team member offline
- when manager resolves a blocker and owner is offline/stale, task is moved to `assigned` (not `in_progress`) and marked `degraded_comm`
- this prevents false progress signals; team member should reconnect and claim task again

### Wrong root
- run `orchestrator_status`
- reinstall MCP from this repo with `./scripts/install_agent_leader_mcp.sh --all`

### Gemini disconnected
- restart Gemini MCP/session, then run `connect to leader`

## Files
- Server: `orchestrator_mcp_server.py`
- Engine: `orchestrator/engine.py`
- Installer: `scripts/install_agent_leader_mcp.sh`
- Doctor: `scripts/doctor.sh`
- Roadmap: `ROADMAP.md`

## MCP Tools Reference
This is the complete tool contract exposed by `agent-leader-orchestrator`.

### System and Roles
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_guide` | Returns orchestration playbook and required manager/team member sequences. | none | Guidance object with sequences and report contract. |
| `orchestrator_status` | Returns current system status. Default output redacts absolute paths. | none | Server/version, `root_name`, `policy_name`, manager, counts, active agents, roles, `live_status_text` (human-readable status block), structured `live_status`, and `recommended_status_cadence_seconds` (default 600). |
| `orchestrator_get_roles` | Reads runtime role assignment. | none | `leader`, `team_members`, `default_leader`. |
| `orchestrator_set_role` | Sets runtime role for an agent. | `agent`, `role` (`leader` or `team_member`), optional `source` | Updated role map. |
| `orchestrator_list_audit_logs` | Reads append-only MCP audit records. | optional `limit`, `tool`, `status` | Filtered audit entries from `bus/audit.jsonl`. |
| `orchestrator_live_status_report` | Builds standardized progress report text and structured metrics. | optional percent/task overrides | `report_text`, structured report fields, recommended cadence. |

### Presence and Connection
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_register_agent` | Registers agent in tenant pool. | `agent`, optional `metadata` | Agent entry with `last_seen`/metadata. |
| `orchestrator_heartbeat` | Updates presence metadata and `last_seen`. | `agent`, optional `metadata` | Updated agent entry. |
| `orchestrator_connect_team_members` | Manager handshake. Counts connected only if verified and same-project. | `source`, `team_members`, optional timeouts | `status`, `connected`, `missing`, per-agent `diagnostics`. |
| `orchestrator_connect_to_leader` | Team member attach + verification + optional announce + auto-claim attempt. | `agent`, optional `metadata`, `status`, `announce`, `source` | `connected`, `verified`, `reason`, `identity`, manager, optional auto-claimed task. |
| `orchestrator_list_agents` | Lists registered agents with verification identity details. | optional `active_only`, `stale_after_seconds` | Agent list with identity fields and `verified` status. |
| `orchestrator_discover_agents` | Lists registered + inferred agents with identity/verification details. | optional `active_only`, `stale_after_seconds` | Discovery object with counts and combined list. |

Compatibility note:
- Legacy alias `orchestrator_connect_workers` is still accepted, but `orchestrator_connect_team_members` is the canonical name.

### Planning and Tasks
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_bootstrap` | Initializes runtime files/state for a session. | none | `ok`, policy, manager. |
| `orchestrator_create_task` | Creates routed task (or returns existing open duplicate). | `title`, `workstream`, optional `description`, `acceptance_criteria`, `owner` | Task object; may include `deduplicated=true`. |
| `orchestrator_dedupe_tasks` | Closes duplicate open tasks and keeps canonical oldest task. | optional `source` | Deduped count and mappings. |
| `orchestrator_list_tasks` | Lists tasks, optionally filtered. | optional `status`, `owner` | Task array. |
| `orchestrator_get_tasks_for_agent` | Lists tasks for one owner/agent. | `agent`, optional `status` | Task array. |
| `orchestrator_claim_next_task` | Claims next eligible task for agent (honors manager override first). | `agent` | Task object or no-task retry hint. |
| `orchestrator_set_claim_override` | Forces next claim for an agent to a specific task. | `agent`, `task_id`, optional `source` | Override confirmation. |
| `orchestrator_update_task_status` | Sets task lifecycle status with note. | `task_id`, `status`, `source`, optional `note` | Updated task. |

### Delivery, Validation, and Bugs
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_submit_report` | Submits delivery report for task owner. | `task_id`, `agent`, `commit_sha`, `status`, `test_summary`, optional `artifacts`, `notes` | Stored report payload. |
| `orchestrator_validate_task` | Manager pass/fail validation. | `task_id`, `passed`, `notes` | Validation result; fail opens bug loop. |
| `orchestrator_list_bugs` | Lists bugs (optionally filtered). | optional `status`, `owner` | Bug array. |

### Blockers and Decisions
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_raise_blocker` | Raises structured blocker and marks task blocked. | `task_id`, `agent`, `question`, optional `options`, `severity` | Blocker object. |
| `orchestrator_list_blockers` | Lists blockers. | optional `status`, `agent` | Blocker array. |
| `orchestrator_resolve_blocker` | Resolves blocker and resumes task safely. | `blocker_id`, `resolution`, `source` | Updated blocker. |
| `orchestrator_decide_architecture` | Records equal-rights architecture decision to ADR file. | `topic`, `options`, `votes`, optional `rationale` | Decision path. |

### Event Bus and Coordination
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_publish_event` | Publishes event (broadcast or targeted). | `type`, `source`, optional `payload`, `audience` | Event record. |
| `orchestrator_poll_events` | Polls events with optional long-poll and cursor handling. | `agent`, optional `cursor`, `limit`, `timeout_ms`, `auto_advance` | Polled events + cursor info. |
| `orchestrator_ack_event` | Acknowledges event by id for an agent. | `agent`, `event_id` | Ack result. |
| `orchestrator_get_agent_cursor` | Gets current cursor offset for agent event stream. | `agent` | Cursor value. |

### Manager Automation and Recovery
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_manager_cycle` | Runs one manager automation cycle (validate reports first, then summarize pending). Also auto-attempts reconnect for stale team members with active tasks before fallback reassignment/requeue. | optional `strict` | Processed reports, `auto_connect` result, by-owner summary, blockers, stale reassignments/requeues. |
| `orchestrator_reassign_stale_tasks` | Reassigns stale-owner tasks to active team members to continue flow. | optional `source`, `stale_after_seconds`, `include_blocked` | Reassignment summary and details. |
