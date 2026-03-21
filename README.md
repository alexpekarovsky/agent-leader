# agent-leader

`agent-leader` is an MCP orchestration server for multi-agent software delivery (Codex manager + Claude/Gemini team members).

## Supported platforms and clients
- First-class installer support: `Codex CLI`, `Claude Code`, `Gemini CLI`.
- Any other MCP-compatible LLM client can use this server via manual stdio MCP config (see "Install for any MCP client").
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
- Manager project-context correction: `orchestrator_set_agent_project_context`.
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
- `~/.local/share/agent-leader/current`
It refuses ephemeral `--server-root` paths under `/tmp` unless you pass `--allow-ephemeral`.

Important installer flags:
- `--mode project|global` (default: `project`)
- `--confirm-global` (required with `--mode global`)
- `--replace-legacy` (explicitly remove legacy MCP name `orchestrator`)
- `--rollback <backup-id>` (restore config backup from failed/previous install)

## Install for any MCP client (manual stdio config)
If your LLM client supports MCP stdio servers but is not one of the built-in installers, use this flow.

1) Install/update latest server bits from this repo:
```bash
cd /path/to/repo
./scripts/install_agent_leader_mcp.sh --all --project-root "$(pwd)"
```

2) Add this MCP server entry to your client config:
```bash
env ORCHESTRATOR_ROOT=/path/to/repo ORCHESTRATOR_EXPECTED_ROOT=/path/to/repo ORCHESTRATOR_POLICY=$HOME/.local/share/agent-leader/current/config/policy.codex-manager.json python3 $HOME/.local/share/agent-leader/current/orchestrator_mcp_server.py
```

Server name to use in your client:
- `agent-leader-orchestrator`

Notes:
- Replace `/path/to/repo` with your actual project root.
- Restart the LLM client session after adding/updating the MCP entry.

## Verify install
```bash
claude mcp list | rg "agent-leader-orchestrator"
codex mcp list | rg "agent-leader-orchestrator"
gemini mcp list | rg "agent-leader-orchestrator"
```

In any agent, call `orchestrator_status` and verify:
- `server = agent-leader-orchestrator`
- `version = 0.1.0` (or current release string)
- `protocol_version = 2024-11-05`
- `root_name = <project folder name>`
- `agent_connection_contexts` shows per-agent `project_root` and `cwd`

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

### Project context override (manager-only recovery)
If an agent is connected but bound to the wrong project metadata, use:
```text
Call orchestrator_set_agent_project_context with agent="gemini" project_root="/Users/alex/Projects/retro-mystery" cwd="/Users/alex/Projects/retro-mystery" source="codex"
```
Or override directly during connect:
```text
Call orchestrator_connect_to_leader with agent="gemini" source="codex" project_override="/Users/alex/Projects/retro-mystery"
```
Notes:
- `project_override` is manager-only and rewrites `project_root`/`cwd` for identity checks.
- Non-manager `project_override` requests are rejected.

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
- `orchestrator_connect_to_leader` does not claim tasks; workers must call `orchestrator_claim_next_task`
- team members use `orchestrator_poll_events(timeout_ms=120000)`
- team member presence is auto-refreshed by normal team member actions (`poll_events`, `claim_next_task`, `submit_report`, `ack_event`)
- after ~10 minutes without keepalive, orchestrator emits `agent.stale_reconnect_required` with instructions to rerun handshake (`connect to leader` + `connect_team_members`)
- avoid rapid `claim_next_task` loops when idle
- manager uses `orchestrator_connect_team_members` instead of repeated manual ping events

## Leader/Builder Matrix
+-----------------------------+---------------------------+---------------------------+---------------------------+
| Project Type                | Best Leader               | Primary Builder           | Secondary Builder         |
+-----------------------------+---------------------------+---------------------------+---------------------------+
| Backend/API platform        | Codex CLI                 | Claude Code               | Gemini CLI                |
| Frontend product UI         | Codex CLI                 | Gemini CLI                | Claude Code               |
| Full-stack startup sprint   | Codex CLI                 | Claude Code               | Gemini CLI                |
| Enterprise/compliance stack | Claude Code or Codex CLI  | Claude Code               | Gemini CLI                |
| Research/prototyping        | Gemini CLI                | Gemini CLI                | Codex CLI                 |
| DevOps/SRE automation       | Codex CLI                 | Claude Code               | Gemini CLI                |
| Data/ML experimentation     | Gemini CLI                | Gemini CLI                | Codex CLI                 |
| Security hardening          | Codex CLI                 | Claude Code               | Gemini CLI                |
| Content/art-heavy app       | Codex CLI                 | Gemini CLI                | Claude Code               |
+-----------------------------+---------------------------+---------------------------+---------------------------+

Default universal setup:

1. Codex CLI as manager/integration gate.
2. Claude Code for critical engineering paths.
3. Gemini CLI for parallel exploration, UI/content, and fast variants.

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
- check `agent_connection_contexts` (and `live_status_text`) for each agent's `project_root` and `cwd`
- if an agent is mismatched, run `orchestrator_set_agent_project_context` from manager
- reinstall MCP from this repo with `./scripts/install_agent_leader_mcp.sh --all`

### Gemini disconnected
- restart Gemini MCP/session, then run `connect to leader`
- `orchestrator_connect_to_leader` now auto-fills missing Gemini identity fields (`permissions_mode`, `sandbox_mode`, `session_id`, `connection_id`, `server_version`, `verification_source`) when possible.
- `cwd` / `project_root` are still required to match the active project root for `same_project` verification.

## Autopilot (Autonomous Loops)

Autopilot scripts run manager/worker/watchdog cycles in a loop without manual prompting.

### Quick start (tmux)
```bash
# Preview what will launch
./scripts/autopilot/team_tmux.sh --dry-run

# Launch all 4 loops in a tmux session
./scripts/autopilot/team_tmux.sh

# Attach
tmux attach -t agents-autopilot
```

### Quick start (supervisor, no tmux)
```bash
./scripts/autopilot/supervisor.sh start
./scripts/autopilot/supervisor.sh status
./scripts/autopilot/supervisor.sh stop
./scripts/autopilot/supervisor.sh clean    # remove stale pids + supervisor logs
```

### Quick start (MCP-only headless control)
Use MCP tools instead of shell wrappers when driving runtime directly from Codex/Claude/Gemini:

1. `orchestrator_headless_start`  
2. `orchestrator_headless_status`  
3. `orchestrator_headless_stop`  

`orchestrator_headless_start` accepts the same topology knobs as the supervisor path (`leader_agent`, team ids, per-agent project roots, intervals/timeouts, optional extra workers).

### Quick start (Headless + Live TUI Dashboard)
Run headless team with a terminal dashboard that tracks tasks/agents/reviews/LOC in real time and auto-stops processes at completion:

```bash
./scripts/autopilot/headless_tui_run.py \
  --project-root /Users/alex/Projects/agent-leader \
  --feature "my-feature" \
  --seed \
  --task "Implement API endpoint" \
  --task "Add tests" \
  --task "Run review gate"
```

What this does:
- seeds tasks (optional `--seed`)
- starts supervisor with low-burn + event-driven settings
- opens `scripts/autopilot/dashboard_tui.py` in foreground
- when project open-tasks reach zero, dashboard shows `100%` and auto-runs `stop` + `clean` to avoid token leakage

Useful flags:
- `--leader-agent claude_code|codex|gemini`
- `--daily-call-budget 120`
- `--max-idle-cycles 30`
- `--refresh-seconds 2.0`

### Policy bundles
Preset policies are available under `config/`:

- `policy.strict-qa.json`
- `policy.prototype-fast.json`
- `policy.balanced.json`

Select a preset by setting `ORCHESTRATOR_POLICY` in your MCP server env or shell before launching the orchestrator.

### Smoke tests
Verify all autopilot scripts work without real CLI agents:
```bash
./scripts/autopilot/smoke_test.sh
```

This tests dry-run output, manager/worker timeout paths (with stub CLIs), watchdog JSONL emission, state corruption detection, log pruning, and live tmux session launch/teardown (skipped if tmux is unavailable).

### Log inspection
```bash
# Check log health
./scripts/autopilot/log_check.sh

# Strict mode (exits non-zero on errors)
./scripts/autopilot/log_check.sh --strict

# Latest watchdog diagnostics
grep '"stale_task"' .autopilot-logs/watchdog-*.jsonl | tail -5
```

See [docs/operator-runbook.md](docs/operator-runbook.md) for detailed launch, restart, recovery, and troubleshooting procedures.

## Files
- Server: `orchestrator_mcp_server.py`
- Engine: `orchestrator/engine.py`
- Installer: `scripts/install_agent_leader_mcp.sh`
- Doctor: `scripts/doctor.sh`
- Autopilot: `scripts/autopilot/` (manager/worker/watchdog loops, tmux launcher, supervisor, smoke tests)
- Roadmap: `docs/roadmap.md`
- Operator Runbook: `docs/operator-runbook.md`

## MCP Tools Reference
This is the complete tool contract exposed by `agent-leader-orchestrator`.

### System and Roles
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_guide` | Returns orchestration playbook and required manager/team member sequences. | none | Guidance object with sequences and report contract. |
| `orchestrator_status` | Returns current system status. Default output redacts absolute paths. | none | Server/version/protocol identity, runtime path hints, `root_name`, `policy_name`, manager, counts, active agents, roles, `health`, `live_status_text` (human-readable status block with agent `project_root`/`cwd`), structured `live_status`, `agent_connection_contexts`, `active_agent_contexts`, and `recommended_status_cadence_seconds` (default 600). |
| `orchestrator_health` | Returns runtime health and identity details for MCP server process. | none | `status`, server name/version/protocol, runtime paths, uptime, logging flags. |
| `orchestrator_get_roles` | Reads runtime role assignment. | none | `leader`, `team_members`, `default_leader`. |
| `orchestrator_set_role` | Sets runtime role for an agent. | `agent`, `role` (`leader` or `team_member`), optional `source` | Updated role map. |
| `orchestrator_list_audit_logs` | Reads append-only MCP audit records. | optional `limit`, `tool`, `status` | Filtered audit entries from `bus/audit.jsonl`. |
| `orchestrator_live_status_report` | Builds standardized progress report text and structured metrics. | optional percent/task overrides | `report_text`, structured report fields, recommended cadence. |

Audit categories in `bus/audit.jsonl`:
- `mcp_tool_call`: every tool invocation result.
- `mcp_tool_debug_trace`: high-detail per-tool traces while debug window is active.
- `mcp_transport_message`: inbound/outbound MCP JSON-RPC traffic (requests, responses, notifications) for transport-level visibility.

Visibility note:
- The orchestrator can log all MCP traffic it receives/sends, but it cannot automatically log chat text that never traverses MCP.
- Set `ORCHESTRATOR_AUDIT_TRANSPORT_LOGS=1` (default) to keep transport logging enabled.

### Presence and Connection
| Tool | Purpose | Key Inputs | Returns |
|---|---|---|---|
| `orchestrator_register_agent` | Registers agent in tenant pool. | `agent`, optional `metadata` | Agent entry with `last_seen`/metadata. |
| `orchestrator_heartbeat` | Updates presence metadata and `last_seen`. | `agent`, optional `metadata` | Updated agent entry. |
| `orchestrator_connect_team_members` | Manager handshake. Counts connected only if verified and same-project. | `source`, `team_members`, optional timeouts | `status`, `connected`, `missing`, per-agent `diagnostics`. |
| `orchestrator_connect_to_leader` | Team member attach + verification + optional announce. Supports manager-only project context override for recovery. | `agent`, optional `metadata`, `status`, `announce`, `source`, optional `project_override` | `connected`, `verified`, `reason`, `identity`, manager, `auto_claimed_task` (always `null`), `project_override_applied`. |
| `orchestrator_set_agent_project_context` | Leader-only correction for agent project metadata used by same-project checks. | `agent`, `project_root`, optional `cwd`, `source` | `ok`, normalized project context, refreshed `identity`. |
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

## MCP Tool Contract Freeze (v1.0)

The file `tools.json` at the project root is the **frozen MCP tool contract**. It captures every tool name, description, and `inputSchema` as of v1.0.0.

### Rules

1. **No silent schema changes.** Adding, removing, or modifying any tool (name, description, or inputSchema) **must** be accompanied by a `contract_version` bump in `tools.json`.
2. **Contract test gate.** The test suite (`tests/test_mcp_tool_contract.py`) validates that the live server matches `tools.json` exactly. CI will fail on any drift.
3. **Version bumps follow semver:**
   - **Patch** (1.0.x): description-only changes, no schema impact.
   - **Minor** (1.x.0): new tools added (backwards-compatible).
   - **Major** (x.0.0): tools removed or inputSchema breaking changes.
4. **Regenerating the contract:** After intentional changes, run:
   ```bash
   python3 -c "
   import sys, json; sys.path.insert(0, '.')
   from orchestrator_mcp_server import handle_tools_list
   result = handle_tools_list('regen')
   tools = result['result']['tools']
   contract = {'contract_version': 'X.Y.Z', 'description': 'Frozen MCP tool contract for agent-leader-orchestrator. Any schema change requires a version bump.', 'tool_count': len(tools), 'tools': {t['name']: {'description': t['description'], 'inputSchema': t['inputSchema']} for t in tools}}
   print(json.dumps(contract, indent=2))
   " > tools.json
   ```
   Replace `X.Y.Z` with the new version, then run `pytest tests/test_mcp_tool_contract.py` to confirm.
