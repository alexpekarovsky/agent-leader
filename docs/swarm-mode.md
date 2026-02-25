# Swarm Mode — Prerequisites and Operator Guide

Swarm mode is the target operating model where multiple agent instances run autonomously across one or more projects, with the orchestrator handling task routing, failure recovery, and completion tracking without manual intervention.

This document distinguishes what works today (MVP) from what swarm mode requires, and what operators should expect at each stage.

## Current MVP Capabilities

The current system supports a single-team autopilot configuration:

- **1 manager** (codex) running `manager_loop.sh`
- **1 claude worker** running `worker_loop.sh`
- **1 gemini worker** running `worker_loop.sh`
- **1 watchdog** running `watchdog_loop.sh`

### What works today

| Capability | Status |
|-----------|--------|
| Task creation and assignment by workstream | Working |
| Worker claim/report/validate cycle | Working |
| CLI timeout with explicit log markers | Working |
| Watchdog stale-task and corruption detection | Working |
| tmux launcher with dry-run preview | Working |
| Non-tmux supervisor (start/stop/status) | Working |
| Log rotation per loop | Working |
| State self-healing (corrupted list files) | Working |
| Smoke tests for all script paths | Working |
| Project-scoped MCP isolation | Working |

### What does NOT work yet

| Limitation | Impact |
|-----------|--------|
| Agent identity is name-based, not instance-based | Cannot run 2 claude workers safely |
| No task leases or expiry | Crashed worker leaves task stuck in `in_progress` forever |
| No deterministic dispatch contract | Manager sends events but cannot confirm worker received them |
| No automatic restart on crash | Supervisor starts processes but does not auto-restart on failure |
| Stale task reassignment is manual or watchdog-assisted | Requires operator or manager prompt to act on watchdog diagnostics |
| No cross-project orchestration | Each project needs its own MCP server instance |

## Swarm Mode Prerequisites

Swarm mode requires completing roadmap Phases B through D (see [docs/roadmap.md](roadmap.md)):

### Phase B: Instance-Aware Presence

**Why required**: Today, if you start two claude workers, they both register as `claude_code` and overwrite each other's status. Swarm mode needs each running process to have a unique identity.

**What changes**:
- Each worker loop generates a stable `instance_id` (e.g., `claude_code#worker-01`)
- Heartbeat and connect payloads include `instance_id`
- Status output shows an instance table, not just agent names
- Stale detection operates per-instance

**Operator impact**: You will be able to run `./supervisor.sh start` with multiple workers of the same CLI type and see each one independently in status output.

### Phase C: Task Leases and Recovery

**Why required**: Today, if a worker process dies mid-task, the task stays `in_progress` indefinitely. The watchdog detects it as stale, but recovery requires manual intervention or a manager prompt that happens to act on the diagnostic.

**What changes**:
- Every `claim_next_task` issues a lease with `expires_at`
- Workers must renew leases via heartbeat while working
- Expired leases automatically requeue tasks to `assigned` or `retry_wait`
- Repeated expiry escalates to blocker or bug

**Operator impact**: Killing a worker mid-task will self-recover. No manual state file edits needed. Status will show lease expiry reason and countdown.

### Phase D: Deterministic Dispatch

**Why required**: Today, the manager publishes events (execution plans, sync reminders) but has no way to confirm workers received or acted on them. Silent failures are invisible.

**What changes**:
- Manager dispatch includes a correlation ID and expected response window
- Workers must acknowledge actionable commands
- Timeout without ack emits `dispatch.noop` diagnostic
- Manager can distinguish "worker is slow" from "worker never saw the command"

**Operator impact**: Status will show pending dispatches and their resolution state. No more ambiguous "nothing happened" gaps.

## What Operators Can Do Today

### Single-team autopilot (recommended)

Launch a single team (1 manager + 1 claude + 1 gemini + 1 watchdog) per project:

```bash
# Preview
./scripts/autopilot/team_tmux.sh --dry-run --project-root /path/to/project

# Launch
./scripts/autopilot/team_tmux.sh --project-root /path/to/project

# Or without tmux
./scripts/autopilot/supervisor.sh start --project-root /path/to/project
```

### Monitor progress

```bash
# Check status
./scripts/autopilot/supervisor.sh status

# Watch logs
ls -lt .autopilot-logs/ | head -10

# Check watchdog diagnostics
grep '"stale_task"' .autopilot-logs/watchdog-*.jsonl | tail -5
```

### Recover from stalls

```bash
# In any CLI session connected to the orchestrator:
orchestrator_list_tasks(status="in_progress")
orchestrator_reassign_stale_tasks(stale_after_seconds=600)
```

See [docs/operator-runbook.md](operator-runbook.md) for detailed commands.

### What operators should NOT attempt today

- **Running multiple workers with the same agent name** — They will overwrite each other's identity and create task ownership confusion. Wait for Phase B (instance-aware presence).

- **Leaving crashed workers unattended for hours** — Without leases, stuck `in_progress` tasks won't self-recover. Check watchdog logs and reassign manually.

- **Running the same orchestrator across multiple projects simultaneously** — Each project needs its own MCP server instance with a separate `ORCHESTRATOR_ROOT`. Cross-project routing is not supported.

- **Assuming workers received manager events** — Without dispatch ack, event delivery is best-effort. If a worker appears idle after a manager cycle, check its logs directly.

## Swarm Mode Target State

When Phases B-D are complete, the system will support:

- Multiple worker instances per CLI type (e.g., 3 claude workers + 2 gemini workers)
- Automatic crash recovery via lease expiry and task requeue
- Observable dispatch with correlation tracking
- Operator status showing per-instance state, current task, and lease countdown
- Completion detection based on acceptance criteria, not manual inspection

The supervisor and tmux launcher will be updated to support configurable worker counts. The orchestrator server remains the single source of truth for all state.

## References

- [docs/roadmap.md](roadmap.md) — Full architecture roadmap with phase details
- [docs/operator-runbook.md](operator-runbook.md) — Current operational procedures
