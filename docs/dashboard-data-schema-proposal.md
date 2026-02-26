# Dashboard Data Schema Proposal

> JSON/TUI schema for a future operator dashboard, mapping each field to its
> authoritative source tool or log file.

## Schema: Dashboard Payload

```jsonc
{
  // ── Team & Instance Panel ─────────────────────────────────
  "team": {
    "source": "orchestrator_status + list_agent_instances",
    "fields": {
      "agents": [
        {
          "agent_name": "string   — list_agent_instances().agent_name",
          "instance_id": "string   — list_agent_instances().instance_id",
          "role": "string   — list_agent_instances().role  (leader|team_member)",
          "status": "string   — list_agent_instances().status (active|idle|stale|disconnected)",
          "project_root": "string   — list_agent_instances().project_root",
          "current_task_id": "string|null — list_agent_instances().current_task_id",
          "last_seen": "ISO 8601  — list_agent_instances().last_seen",
          "verified": "bool     — list_agents().verified"
        }
      ],
      "active_count": "int — orchestrator_status().active_agents.length",
      "manager": "string — orchestrator_status().manager"
    }
  },

  // ── Task Summary Panel ────────────────────────────────────
  "tasks": {
    "source": "orchestrator_status + list_tasks",
    "fields": {
      "total": "int — orchestrator_status().task_count",
      "by_status": {
        "assigned": "int — orchestrator_status().task_status_counts.assigned",
        "in_progress": "int — orchestrator_status().task_status_counts.in_progress",
        "reported": "int — orchestrator_status().task_status_counts.reported",
        "done": "int — orchestrator_status().task_status_counts.done",
        "blocked": "int — orchestrator_status().task_status_counts.blocked",
        "bug_open": "int — orchestrator_status().task_status_counts.bug_open"
      },
      "completion_percent": "int — live_status.overall_project_percent"
    }
  },

  // ── Blocker & Bug Panel ───────────────────────────────────
  "blockers": {
    "source": "list_blockers + list_bugs",
    "fields": {
      "open_blockers": "int — live_status.pipeline_health.open_blockers",
      "open_bugs": "int — live_status.pipeline_health.open_bugs",
      "blocker_details": [
        {
          "id": "string — list_blockers().id",
          "task_id": "string — list_blockers().task_id",
          "severity": "string — list_blockers().severity",
          "status": "string — list_blockers().status",
          "question": "string — list_blockers().question",
          "resolution": "string|null — list_blockers().resolution"
        }
      ]
    }
  },

  // ── Alert Panel (Watchdog) ────────────────────────────────
  "alerts": {
    "source": ".autopilot-logs/watchdog-*.jsonl",
    "fields": {
      "stale_tasks": [
        {
          "task_id": "string — watchdog.task_id",
          "owner": "string — watchdog.owner",
          "status": "string — watchdog.status",
          "age_seconds": "int — watchdog.age_seconds",
          "timeout_seconds": "int — watchdog.timeout_seconds",
          "title": "string — watchdog.title"
        }
      ],
      "corruption_events": [
        {
          "path": "string — watchdog.path",
          "previous_type": "string — watchdog.previous_type",
          "expected_type": "string — watchdog.expected_type"
        }
      ]
    }
  },

  // ── Progress Panel ────────────────────────────────────────
  "progress": {
    "source": "orchestrator_status().live_status",
    "fields": {
      "overall_project_percent": "int",
      "phase_1_percent": "int — Phase 1 (Architecture + Vertical Slice)",
      "phase_2_percent": "int — Phase 2 (Content Pipeline)",
      "phase_3_percent": "int — Phase 3 (Full Production)",
      "backend_percent": "int",
      "frontend_percent": "int",
      "qa_validation_percent": "int"
    }
  },

  // ── Metrics Panel ─────────────────────────────────────────
  "metrics": {
    "source": "orchestrator_status().metrics",
    "fields": {
      "throughput": {
        "tasks_done": "int — metrics.throughput.tasks_done",
        "completion_rate_percent": "int — metrics.throughput.completion_rate_percent"
      },
      "timings_seconds": {
        "avg_time_to_claim": "int|null — metrics.timings_seconds.avg_time_to_claim",
        "avg_time_to_report": "int|null — metrics.timings_seconds.avg_time_to_report",
        "avg_time_to_validate": "int|null — metrics.timings_seconds.avg_time_to_validate"
      },
      "reliability": {
        "open_bugs": "int",
        "open_blockers": "int",
        "stale_in_progress_over_30m": "int",
        "stale_reported_over_10m": "int"
      },
      "code_output": {
        "unique_commits": "int — metrics.code_output.unique_commits",
        "files_changed_total": "int",
        "lines_added_total": "int",
        "lines_deleted_total": "int",
        "by_agent": "object — per-agent commit/LOC breakdown"
      }
    }
  },

  // ── Audit Trail Panel ─────────────────────────────────────
  "audit": {
    "source": "bus/audit.jsonl + list_audit_logs",
    "fields": {
      "recent_actions": [
        {
          "timestamp": "ISO 8601 — audit.timestamp",
          "tool": "string — audit.tool",
          "status": "string — audit.status (ok|error)",
          "args": "object — audit.args (filterable)"
        }
      ]
    }
  }
}
```

## Source-to-Field Map

| Dashboard Panel | Primary Source | Backup/Detail Source |
|---|---|---|
| Team instances | `list_agent_instances()` | `list_agents()` for verified flag |
| Task summary | `orchestrator_status()` | `list_tasks()` for per-task detail |
| Blockers/bugs | `list_blockers()`, `list_bugs()` | `live_status.pipeline_health` |
| Alerts | `.autopilot-logs/watchdog-*.jsonl` | — (no MCP tool yet) |
| Progress % | `orchestrator_status().live_status` | `live_status_text` for formatted |
| Metrics | `orchestrator_status().metrics` | — |
| Audit trail | `list_audit_logs()` | `bus/audit.jsonl` for raw access |

## Gaps Requiring New Backend Fields

| Gap | Panel Affected | What's Needed | Status |
|---|---|---|---|
| No MCP tool for watchdog alerts | Alerts | `list_watchdog_alerts()` tool or event bus integration | Not yet implemented |
| No time-series throughput | Metrics | Time-windowed task counts (tasks/hour) | Planned for v0.3+ |
| No task lifecycle timeline | Task detail | Aggregated timestamp chain per task | Planned for v0.3 |
| No percentile durations | Metrics | P50/P95/P99 instead of only averages | Planned for v0.3+ |
| No push/streaming updates | All panels | WebSocket or SSE endpoint | Planned for Phase 2 |
| No agent utilization rate | Team | idle% vs active% per instance | Not yet instrumented |

See also: [dashboard-data-contract-gaps.md](dashboard-data-contract-gaps.md) for full gap tracker.
