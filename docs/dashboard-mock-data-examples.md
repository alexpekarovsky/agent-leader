# Dashboard Mock Data Examples

> Realistic mock data snippets for a future operator dashboard, generated from
> current orchestrator output schemas. Synthetic values marked with `[mock]`.

## Team Panel

```json
{
  "agents": [
    {
      "agent_name": "codex",
      "instance_id": "codex#leader",
      "role": "leader",
      "status": "active",
      "project_root": "/Users/alex/claude-multi-ai",
      "current_task_id": "TASK-111dbf76",
      "last_seen": "2026-02-26T15:30:00+00:00"
    },
    {
      "agent_name": "claude_code",
      "instance_id": "claude_code#worker-01",
      "role": "team_member",
      "status": "active",
      "project_root": "/Users/alex/claude-multi-ai",
      "current_task_id": "TASK-8f2649d2",
      "last_seen": "2026-02-26T15:32:46+00:00"
    },
    {
      "agent_name": "claude_code",
      "instance_id": "claude_code#worker-02",
      "role": "team_member",
      "status": "active",
      "project_root": "/Users/alex/claude-multi-ai",
      "current_task_id": "TASK-a6e952ef",
      "last_seen": "2026-02-26T15:31:00+00:00"
    },
    {
      "agent_name": "gemini",
      "instance_id": "gemini#w1",
      "role": "team_member",
      "status": "stale",
      "project_root": "/Users/alex/claude-multi-ai",
      "current_task_id": null,
      "last_seen": "2026-02-21T22:20:20+00:00"
    }
  ],
  "active_count": 3,
  "manager": "codex"
}
```

**Note:** `[mock]` — claude_code#worker-02 is synthetic; current deployment uses single instance.

## Task Queue Panel

```json
{
  "total": 297,
  "by_status": {
    "done": 215,
    "assigned": 50,
    "in_progress": 10,
    "blocked": 22,
    "reported": 0,
    "bug_open": 0
  },
  "completion_percent": 72
}
```

**Source:** `orchestrator_status().task_count` + `task_status_counts`

## Alerts Panel

```json
{
  "stale_tasks": [
    {
      "task_id": "TASK-ba1b2ee1",
      "owner": "gemini",
      "status": "assigned",
      "age_seconds": 432000,
      "timeout_seconds": 180,
      "title": "RETRO-FE-01 Bootstrap frontend toolchain"
    }
  ],
  "corruption_events": []
}
```

**Source:** `.autopilot-logs/watchdog-*.jsonl`

## Progress Panel

```json
{
  "overall_project_percent": 72,
  "phase_1_percent": 72,
  "phase_2_percent": 0,
  "phase_3_percent": 0,
  "backend_percent": 91,
  "frontend_percent": 0,
  "qa_validation_percent": 72
}
```

**Source:** `orchestrator_status().live_status`

## Metrics Panel

```json
{
  "throughput": {
    "tasks_done": 215,
    "completion_rate_percent": 72
  },
  "timings_seconds": {
    "avg_time_to_claim": 5,
    "avg_time_to_report": 120,
    "avg_time_to_validate": 3
  },
  "reliability": {
    "open_bugs": 5,
    "open_blockers": 10,
    "stale_in_progress_over_30m": 0,
    "stale_reported_over_10m": 0
  },
  "code_output": {
    "unique_commits": 12,
    "files_changed_total": 85,
    "lines_added_total": 4200,
    "lines_deleted_total": 310
  }
}
```

**Source:** `orchestrator_status().metrics`

## Synthetic vs Real Values

| Field | Source | Real/Synthetic |
|---|---|---|
| task counts | `orchestrator_status()` | Real (from current run) |
| agent instances | `list_agent_instances()` | Real (worker-02 is synthetic) |
| watchdog alerts | `.autopilot-logs/watchdog-*.jsonl` | Real stale task, synthetic format |
| progress % | `live_status` | Real |
| timing metrics | `_status_metrics()` | Approximate from current run |
| code_output | Report commit metrics | Approximate |
