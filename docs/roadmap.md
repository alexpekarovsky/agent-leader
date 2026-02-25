# Robust "Work Until Done" Roadmap

This roadmap defines the next architecture step for `agent-leader` using the current orchestrator + autopilot loops as the base layer.

Goal: run multi-agent projects with minimal manual ping-pong while preserving auditability, project isolation, and explicit failure handling.

## Scope

This plan targets:

- long-running autonomous project execution (`leader + workers + watchdog`)
- reliable progress until completion or explicit blocker
- per-project isolation
- observability good enough to debug stalls quickly

This plan does not assume a single CLI vendor. It treats Codex, Claude Code, and Gemini as interchangeable worker adapters with different strengths.

## Current Baseline (What We Have)

Building blocks already in place:

- orchestrator MCP server with task, blocker, bug, event, and audit state
- project-scoped MCP config (`.mcp.json`)
- manager cycle and worker claim/report flow
- autopilot shell loops (`manager_loop.sh`, `worker_loop.sh`, `watchdog_loop.sh`)
- tmux launcher (`team_tmux.sh`) and monitor loop
- state self-healing for corrupted `bugs.json` / `blockers.json` list files
- dry-run launcher mode for reviewable operations

Known limitations in the current baseline:

- agent status is name-based (`codex`, `claude_code`, `gemini`), not instance-based
- no lease/expiry on `in_progress` tasks
- no deterministic command/ack/result contract for manager dispatch
- hidden stalls are still possible (timeouts improved, but state model is not lease-driven)
- observability is split across status, events, logs, and file state

## Definition of "Work Until Done"

A project is "work until done" capable when:

- tasks continue moving without manual reconnect/dispatch nudges
- worker silence becomes a timeout event, not ambiguous inactivity
- stuck tasks automatically recover (requeue, blocker, or explicit failure)
- operator can see who is running, on what project, on what task, and why idle
- completion is determined by acceptance criteria, not manual guesswork

## Target Architecture

### 1. Server-Centric Control Plane

Move reliability decisions into orchestrator server state and policy, not prompt wording.

Responsibilities:

- task routing
- lease issuance and expiry
- timeout policy
- retry limits/backoff
- report queue and validation scheduling
- per-project status snapshots
- diagnostics emission

Workers become thin executors that claim, execute, report, and heartbeat.

### 2. Agent Instance Model (Not Just Agent Names)

Add instance-level identity records.

Proposed fields:

- `agent_name` (`codex`, `claude_code`, `gemini`)
- `instance_id` (stable unique per running loop, e.g. `claude_code#worker-01`)
- `role` (`leader`, `worker`, `watchdog`, `qa`)
- `project_root`
- `cwd`
- `client`
- `model`
- `server_version`
- `status` (`online`, `idle`, `working`, `blocked`, `stale`, `offline`)
- `current_task_id`
- `last_heartbeat_at`
- `last_event_at`
- `last_claim_attempt_at`
- `last_report_at`
- `capabilities` (tags such as `frontend`, `backend`, `qa`, `art`)

Why:

- supports multiple worker instances per CLI
- removes ambiguity when one `gemini` process dies and another is still alive
- improves status/reporting and reassignment logic

### 3. Task Leases (Core Reliability Primitive)

Every task claim should issue a lease.

Proposed lease fields:

- `lease_id`
- `task_id`
- `owner_instance_id`
- `claimed_at`
- `expires_at`
- `renewed_at`
- `heartbeat_interval_seconds`
- `attempt_index`

Rules:

- worker must renew lease while task is `in_progress`
- lease expiry automatically transitions task to `assigned` or `retry_wait`
- lease expiry emits diagnostic event (`task.lease_expired`)
- repeated expiry can auto-raise blocker or bug based on policy

This eliminates indefinite `in_progress` stalls when an LLM loop hangs or exits.

### 4. Deterministic Dispatch Contract

Split generic event bus usage into explicit orchestration message types:

- `dispatch.command`
- `dispatch.ack`
- `worker.progress`
- `worker.result`
- `worker.error`
- `watchdog.alert`
- `manager.decision`

Each manager dispatch should have a correlation ID and expected outcome window.

Example flow:

1. Manager emits `dispatch.command` (`claim_next`, correlation ID)
2. Worker emits `dispatch.ack`
3. Worker either emits `worker.progress` / `worker.result` or `worker.error`
4. Timeout watcher emits `dispatch.noop` if neither ack nor claim occurs in time

This closes the "manager sent instruction but nothing happened" gap.

### 5. Status and Observability (Operator-First)

Add a consistent status surface per project.

Required views:

- project summary (`pending`, `in_progress`, `reported`, `blocked`, `done`, `bug_open`)
- active agent-instance table (project, role, status, current task, last heartbeat)
- stale task table (age, owner, timeout reason, next action)
- recent diagnostics (claim no-op, lease expiry, report timeout, scope mismatch)
- per-task timeline (assignment -> claim -> progress -> report -> validate)

Design rule:

- every visible failure state must have an explicit reason string

### 6. Supervisor Layer (Beyond tmux MVP)

`tmux` remains useful for operator visibility, but production reliability should come from a supervisor.

Recommended path:

- Phase 1: tmux MVP (current)
- Phase 2: supervisor script/process with restart policy and backoff
- Phase 3: platform-native service mode (`launchd`/`systemd`)

Supervisor responsibilities:

- process lifecycle
- auto-restart on crash
- exponential backoff on repeated failure
- health pings
- stdout/stderr capture
- log retention policy

### 7. CLI Adapter Abstraction

Normalize vendor-specific CLI behavior behind adapters.

Adapter contract:

- `run_prompt(prompt, cwd, timeout)`
- `exit_code`
- `timed_out`
- `stdout/stderr capture`
- metadata extraction (`client`, `model`, `session`)

Benefits:

- isolates breaking CLI syntax changes
- enables per-vendor flags without changing orchestration logic
- simplifies testing via mock adapters

## Implementation Plan (Detailed)

### Phase A: Harden Current MVP (v0.1.x)

Objective: remove common operator pain without changing core state schema too much.

Tasks:

1. Add per-cycle CLI timeouts for manager and workers
2. Add explicit timeout logging markers in autopilot outputs
3. Standardize manager loop startup prompt (leader heartbeat + role set)
4. Add log retention controls to all loops
5. Expand watchdog diagnostics for:
   - stale `assigned`
   - stale `in_progress`
   - stale `reported`
   - state corruption detection
6. Add operator runbook docs for launch/restart/recovery

Acceptance criteria:

- no loop can block forever on a CLI call
- tmux launcher dry-run output is reviewable and reproducible
- watchdog produces machine-parseable JSONL diagnostics
- restarting a single worker does not require resetting orchestrator state

Status:

- In progress (timeouts/logging/watchdog/tmux improvements are already implemented)

### Phase B: Instance-Aware Presence (v0.2.0)

Objective: make status and routing track real running processes.

Tasks:

1. Add `instance_id` to registration/heartbeat/connect payloads
2. Persist instance records per project
3. Update status output to show instance table
4. Update stale detection to operate on instances, not only agent names
5. Support multiple worker instances per agent type safely

Acceptance criteria:

- status can distinguish `gemini#worker-01` vs `gemini#worker-02`
- stale one instance does not mark all `gemini` workers offline
- task ownership references `owner_instance_id` when claimed

### Phase C: Task Leases and Recovery (v0.2.x)

Objective: eliminate stuck `in_progress` tasks due to disconnects/hangs.

Tasks:

1. Add lease object schema and persistence
2. Issue lease on claim
3. Add `renew_lease` and lease heartbeat path
4. Add lease expiry watcher in manager cycle/watchdog
5. Auto-requeue or `retry_wait` on lease expiry (policy-driven)
6. Add diagnostics for lease expiry and repeated expiry

Acceptance criteria:

- killing a worker process while a task is `in_progress` recovers the task automatically
- no manual DB/file edits required for recovery
- status and audit clearly show lease expiry reason and next action

### Phase D: Deterministic Dispatch + No-Op Diagnostics (v0.3.0)

Objective: turn "silent nothing happened" into explicit observable events.

Tasks:

1. Add dispatch command schema with correlation IDs
2. Require worker ack for actionable commands
3. Add command timeout policy and `dispatch.noop`
4. Add claim attempt telemetry (`attempted_at`, `outcome`, `reason`)
5. Add report timeout telemetry and diagnostics
6. Update manager loop prompts and docs to use deterministic commands

Acceptance criteria:

- every dispatch has one of: `ack`, `result`, `error`, `noop`
- manager can detect no-op without manual inspection
- logs and status show correlation IDs for troubleshooting

### Phase E: Completion Engine (v0.4.0)

Objective: run projects from backlog to "done" with milestone gates and retries.

Tasks:

1. Add milestone/phase definitions and completion criteria
2. Add "run until done" mode in manager cycle policy
3. Add retry budget per task and escalation thresholds
4. Add automatic blocker escalation for repeated failure
5. Add QA gate policy integration (test/build requirements by workstream)
6. Add final completion summary and artifact checklist

Acceptance criteria:

- manager can continue dispatching until no runnable tasks remain
- completion stops only on:
  - all tasks done and validated
  - open blockers requiring user decision
  - fatal policy breach / repeated failures beyond budget

### Phase E.5: Swarm Mode (v0.4.x)

Objective: support "team mode" for a single agent family (for example, multiple Claude Code workers) so a task can be completed by a coordinated worker pool instead of one instance.

Prerequisites:

- Phase B instance-aware presence (`instance_id`)
- Phase C task leases (to avoid stuck child tasks)
- Phase D deterministic dispatch/ack/no-op diagnostics (for fan-out reliability)

Tasks:

1. Add instance pool tracking for agent families (`claude_code#worker-01`, `claude_code#worker-02`, etc.)
2. Add parent/child task model (decomposition + aggregation metadata)
3. Add manager fan-out helpers for subtask creation and routing
4. Allow multiple instances of the same agent family to claim child tasks safely
5. Add fan-in completion gate:
   - all child tasks done
   - aggregation/merge step complete
   - QA/validation pass
6. Add conflict/retry policy for overlapping edits or failed child subtasks
7. Add status/observability support for swarm runs (parent progress + child progress by instance)

Acceptance criteria:

- at least two `claude_code` instances can work child tasks under one parent task concurrently
- parent task remains open until child completion + aggregation gate pass
- stale/disconnected swarm worker recovers via lease expiry without corrupting swarm state
- status clearly shows swarm parent, child tasks, and per-instance ownership

### Phase F: Supervisor Runtime (v0.5.0)

Objective: replace tmux as reliability foundation while keeping tmux as optional console.

Tasks:

1. Implement supervisor process with config file
2. Manage leader/worker/watchdog subprocesses
3. Add restart/backoff policy and crash counters
4. Add `supervisor status`, `supervisor restart worker-2`, etc.
5. Keep `team_tmux.sh` as optional observability UI, not required runtime

Acceptance criteria:

- autonomous run survives terminal disconnects and process crashes
- operators can inspect and restart individual workers without manual shell choreography

## Testing Strategy (What We Need Before Moving Phases)

### Unit Tests (Python orchestrator)

Expand `tests/test_orchestrator_reliability.py` to cover:

- corrupted `bugs.json` / `blockers.json` self-healing
- project-scope enforcement on assignment/reassignment
- lease expiry requeue transitions
- dispatch timeout -> `dispatch.noop`
- reported queue visibility vs manager validation timing

### Script/Loop Tests (Shell)

Add script tests or smoke scripts for:

- `team_tmux.sh --dry-run`
- manager/worker loop timeout behavior (fake adapter command sleeps > timeout)
- log pruning behavior
- watchdog diagnostics JSONL schema

### Integration Tests (End-to-End)

Run in temp project roots with mock adapters:

- leader + 2 workers + watchdog
- task assignment -> claim -> report -> validate
- worker hang mid-task -> lease expiry -> recovery
- malformed state files -> self-heal + diagnostic
- cross-project task mismatch never assigned to wrong worker

## Operational Runbook (Interim)

Until supervisor mode exists:

1. Install MCP to `current` and restart CLIs in the target project
2. Confirm `.mcp.json` points to the correct project root
3. Run `team_tmux.sh --dry-run` and review generated commands
4. Launch `team_tmux.sh`
5. Attach to tmux and monitor `.autopilot-logs`
6. Use `orchestrator_status` and `orchestrator_list_blockers` as truth, not pane output alone

## Immediate Next Work (Post-This Roadmap)

Recommended implementation order:

1. Instance-aware presence model
2. Lease-based task claims and expiry
3. Deterministic dispatch/ack/result/no-op events
4. Status v2 (instance table + stale diagnostics)
5. Swarm Mode parent/child task support (Claude Code team mode)
6. Supervisor runtime

This sequence gives the highest reliability gains early while preserving the current tool and workflow shape.
