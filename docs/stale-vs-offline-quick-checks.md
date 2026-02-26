# Quick Checks: Stale vs Offline Instance Interpretation

> How to distinguish stale, offline, and active agents using status fields
> and timestamps in the current orchestrator version.

## Status Definitions

| Status | Condition | What Happened |
|---|---|---|
| **active** | `last_seen` within `heartbeat_timeout_minutes` (default: 10) | Agent is running and sending heartbeats |
| **stale** | `last_seen` exceeded timeout but agent entry still exists | Agent stopped heartbeating (crash, network, closed) |
| **offline** | Not in `active_agents` list; may still appear in `agent_instances` | Agent hasn't been seen for extended period |
| **disconnected** | No agent entry at all | Agent never connected or was removed |

## Quick Decision Tree

```
Is the agent in orchestrator_status().active_agents?
  ├─ YES → status = active
  │        └─ Check current_task_id: null = idle, set = working
  └─ NO  → Check agent_instances for the agent
           ├─ Found, last_seen < 10 min ago → Likely reconnecting
           ├─ Found, last_seen > 10 min ago → Stale (needs attention)
           └─ Not found → Never connected or entry cleaned up
```

## Example Rows

### Active Agent
```json
{
  "agent_name": "claude_code",
  "instance_id": "claude_code#worker-01",
  "status": "active",
  "last_seen": "2026-02-26T15:32:46+00:00",
  "current_task_id": "TASK-8f2649d2"
}
```
**Interpretation:** Healthy. Working on a task. Heartbeat fresh.

### Stale Agent (Recent)
```json
{
  "agent_name": "gemini",
  "instance_id": "gemini#w1",
  "status": "stale",
  "last_seen": "2026-02-26T15:20:00+00:00",
  "current_task_id": "TASK-ba1b2ee1"
}
```
**Interpretation:** Went stale ~12 minutes ago. Still has a claimed task. May need task reassignment if it doesn't recover.

### Stale Agent (Long Offline)
```json
{
  "agent_name": "gemini",
  "instance_id": "gemini#w1",
  "status": "stale",
  "last_seen": "2026-02-21T22:20:20+00:00",
  "current_task_id": null
}
```
**Interpretation:** Offline for days. Tasks were already reassigned or never claimed. Safe to ignore until reconnection.

## Follow-Up Actions

| Scenario | What to Do |
|---|---|
| Agent stale < 15 min | Wait — may be temporary (network blip, restart) |
| Agent stale > 30 min with claimed task | Run `orchestrator_reassign_stale_tasks` to free the task |
| Agent stale > 1 hour | Consider mirroring their tasks to active agents |
| Multiple instances, one stale | Check if the other instance is still active |
| All instances of an agent stale | Agent is fully offline — mirror or wait |

## Verification Tools

| Check | Tool |
|---|---|
| Who's active right now? | `orchestrator_status` → `active_agents` |
| Full instance details | `orchestrator_list_agent_instances(active_only=false)` |
| When did agent last heartbeat? | Check `last_seen` field in instance row |
| Are their tasks stuck? | `orchestrator_list_tasks(owner=<agent>, status=in_progress)` |
| Reassign stale work | `orchestrator_reassign_stale_tasks(stale_after_seconds=600)` |
