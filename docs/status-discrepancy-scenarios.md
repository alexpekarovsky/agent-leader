# Discrepancy Scenarios Across Status, Audit, and Watchdog

## Overview

Three data sources may report conflicting information about the same entity:

| Source | What It Knows | Update Frequency | Authoritative For |
|---|---|---|---|
| **orchestrator_status()** | Live state from tasks.json, agents.json | On-demand (per MCP call) | Current task/agent status |
| **Audit log** (bus/audit.jsonl) | Historical MCP tool call results | Append-only on each tool call | What happened and when |
| **Watchdog JSONL** (.autopilot-logs/watchdog-*.jsonl) | Periodic diagnostic snapshots | Every 15s (configurable) | Age-based staleness detection |

Discrepancies arise because these sources have different update cadences, different scopes, and different definitions of "stale" or "active."

---

## Discrepancy Scenario 1: Watchdog Flags Stale Task, Status Shows Active Lease

**Symptoms:**
- Watchdog JSONL contains `stale_task` entry for TASK-xxx (age > 900s)
- `orchestrator_status()` shows TASK-xxx as `in_progress` with a valid (non-expired) lease

**Root Cause:**
Watchdog checks `updated_at` age against `INPROGRESS_TIMEOUT` (900s default). The orchestrator lease system checks `lease.expires_at`. A task can have an old `updated_at` but a recently renewed lease — the agent is actively renewing but not updating task metadata.

**Resolution Order:**
1. Check `lease.renewed_at` on the task — if recently renewed, the task is healthy
2. Check agent heartbeat — if the owner is active, lease renewal is working
3. If both are stale, escalate to manager for `recover_expired_task_leases`

**Verdict:** Watchdog false positive. Trust the lease `expires_at` over watchdog age heuristic.

---

## Discrepancy Scenario 2: Status Shows Agent Active, Watchdog Shows No Recent Logs

**Symptoms:**
- `list_agents()` shows `claude_code` as active (recent heartbeat)
- No new worker log files in `.autopilot-logs/worker-claude_code-*.log` for 30+ minutes
- Watchdog runs normally but reports no stale tasks for that agent

**Root Cause:**
The agent is sending heartbeats (keeping presence active) but is not claiming or working on tasks. This can happen when:
- All tasks for the agent are done (queue empty)
- The agent is blocked waiting for event polling
- The worker_loop.sh exited but the MCP connection remains open

**Resolution Order:**
1. Check if any tasks are assigned to the agent — if none, idle is expected
2. Check `claim_next_task` response — "No claimable task" confirms queue empty
3. Check audit log for recent tool calls from the agent
4. If tasks exist but agent isn't claiming, restart the worker loop

**Verdict:** Not a discrepancy if queue is empty. Investigate if assigned tasks exist.

---

## Discrepancy Scenario 3: Audit Shows Report Submitted, Status Shows Task Still `in_progress`

**Symptoms:**
- Audit log entry: `orchestrator_submit_report` for TASK-xxx with `status: ok`
- `orchestrator_status()` still shows TASK-xxx as `in_progress` (not `reported`)

**Root Cause:**
Possible causes ranked by likelihood:
1. **Race condition** — Status was queried between report submission and auto-manager-cycle validation. The task transitions: `in_progress` → `reported` → `done`, and the status query caught it mid-transition.
2. **Report rejected** — Auto-manager-cycle rejected the report (failed tests, missing commit_sha). The task reverts to `in_progress` or `bug_open`.
3. **State file corruption** — The write to tasks.json failed or was overwritten by a concurrent writer.

**Resolution Order:**
1. Check audit log for the auto-manager-cycle result following the report — look for `task.validated_accepted` or `task.validated_rejected`
2. Check `bus/reports/TASK-xxx.json` — does the report file exist and contain valid test_summary?
3. Re-query status after 30s — if the task advanced, it was a timing issue
4. If stuck, check for `state_guard` audit entries (task count shrink rejection)

**Verdict:** Usually timing. Check manager cycle result in audit log before escalating.

---

## Discrepancy Scenario 4: Status Shows 0 Blockers, Watchdog Shows Stale Blocked Tasks

**Symptoms:**
- `orchestrator_status()` reports `blocker_count: 0`
- Watchdog flags tasks with `status: blocked` and high age

**Root Cause:**
Blockers can be resolved (removed from `state/blockers.json`) while tasks remain in `blocked` status if the resolution didn't also update the task status. This is a state inconsistency:
- Blocker was resolved via `resolve_blocker` (sets blocker status to `resolved`)
- But no follow-up action moved the task from `blocked` → `assigned`

**Resolution Order:**
1. List all blocked tasks: check `state/tasks.json` for `status: blocked`
2. For each, check `state/blockers.json` for matching `task_id` with `status: open`
3. If no open blocker exists for a blocked task, the task needs manual unblock
4. Manager should call `set_task_status(task_id, "assigned", source)` to unblock orphaned tasks

**Verdict:** State inconsistency. Manager action required to reconcile.

---

## Discrepancy Scenario 5: Audit Shows Agent Connected, Status Shows Agent Offline

**Symptoms:**
- Audit log has recent `orchestrator_connect_to_leader` entry for `gemini` with `connected: true`
- `list_agents(active_only=True)` does not include `gemini`

**Root Cause:**
Connection succeeded but the agent's identity verification failed the `same_project` check. Possible causes:
1. Agent connected with a different `cwd` or `project_root` than the orchestrator root
2. Agent sent heartbeat but metadata was incomplete (missing required verification fields)
3. Heartbeat timeout expired after connection — agent connected but stopped heartbeating

**Resolution Order:**
1. Check the connect audit entry's `identity` object — look for `verified: false` or `same_project: false`
2. Check `state/agents.json` for the agent's `metadata` — verify `cwd` matches orchestrator root
3. Check `last_seen` timestamp — if older than heartbeat timeout, agent stopped heartbeating
4. If `same_project: false`, the agent is running from a different directory — restart with correct `cwd`

**Verdict:** Identity verification issue. Check `same_project` and `verified` flags in the connection response.

---

## Discrepancy Scenario 6: Multiple Watchdog Cycles Show Same Stale Task

**Symptoms:**
- Consecutive watchdog JSONL files all flag TASK-xxx as `stale_task`
- Task status hasn't changed across multiple cycles (15s intervals)

**Root Cause:**
Watchdog is correctly detecting the stale task, but no recovery action has been taken. The watchdog is a passive observer — it does not trigger recovery. Recovery requires:
- Manager calling `recover_expired_task_leases` (for lease-based recovery)
- Manager calling `reassign_stale_tasks` (for task reassignment)
- Manual operator intervention

**Resolution Order:**
1. Check if the task's lease is expired via `state/tasks.json` → `lease.expires_at`
2. If lease expired, call `recover_expired_task_leases` from the manager
3. If lease is valid but task is stale, the agent may be working slowly — check worker logs
4. If agent is offline and lease is valid, wait for lease expiry then recover
5. Escalate to operator if task has been stale for > 2x the `INPROGRESS_TIMEOUT`

**Verdict:** Expected behavior — watchdog detects but doesn't act. Manager or operator must initiate recovery.

---

## Discrepancy Scenario 7: Event Bus Shows dispatch.noop, Audit Shows Successful Claim

**Symptoms:**
- `bus/events.jsonl` contains a `dispatch.noop` for agent X, task Y
- Audit log shows a successful `claim_next_task` by agent X for task Y

**Root Cause:**
The noop was emitted for a *previous* claim override that timed out. The agent later claimed the task through normal claim flow (not via the override). The correlation_id on the noop references the stale override, not the successful claim.

**Resolution Order:**
1. Compare timestamps — the noop should predate the successful claim
2. Check correlation_ids — noop's correlation_id should differ from the claim event
3. If noop came *after* the claim, check for a second override that was set after the first claim
4. No action needed if the task is now in_progress with the correct owner

**Verdict:** Historical artifact. The noop reflects a past timeout; the subsequent claim resolved the situation.

---

## Escalation Guidance

### When to Investigate (Operator)

- Any discrepancy persisting across 3+ watchdog cycles (45+ seconds)
- Audit showing errors (`status: error`) for critical operations (submit_report, claim_next_task)
- Tasks stuck in `blocked` with no matching open blocker
- Agents showing `connected: true` but `active: false` repeatedly

### When to Escalate (to Manager/Codex)

- Tasks in `in_progress` with expired leases and no recovery events in the event bus
- State file corruption detected by watchdog (`state_corruption_detected` kind)
- Task count shrinkage blocked by state guard (check audit for `reject_task_count_shrink`)
- Multiple agents offline simultaneously with assigned tasks

### Resolution Priority Order

For any discrepancy, investigate sources in this order:

1. **orchestrator_status()** — current authoritative state (most recent)
2. **Audit log** — what actions were taken and their results (causal chain)
3. **Event bus** — fine-grained event timeline (correlation threading)
4. **Watchdog JSONL** — periodic diagnostic snapshots (age-based alerts)
5. **Worker/manager logs** — process-level output (error messages, stack traces)
