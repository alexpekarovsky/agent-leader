# Dashboard Gap Analysis and MVP Dashboard Proposal

## 1. Gap Analysis: Existing Visibility vs Missing Pieces

### Existing Visibility (What We Have)

| Capability | Source | Format | Access Method |
|---|---|---|---|
| Task counts by status | `orchestrator_status()` | JSON | MCP tool call |
| Overall/phase completion % | `orchestrator_live_status_report()` | JSON + text | MCP tool call |
| Agent presence & heartbeat | `list_agents()`, `list_agent_instances()` | JSON | MCP tool call |
| Throughput metrics (avg claim/report/validate time) | `_status_metrics()` | JSON | Internal function |
| Event trail (heartbeats, claims, dispatches) | `bus/events.jsonl` | JSONL (85K+ lines) | File read + jq |
| Audit trail (MCP tool calls) | `bus/audit.jsonl` | JSONL (1.6K lines) | File read + jq |
| Stale task diagnostics | `.autopilot-logs/watchdog-*.jsonl` | JSONL | File read + jq |
| Process output logs | `.autopilot-logs/manager-*.log`, `worker-*.log` | Plain text | tail/less |
| File listing refresh | `monitor_loop.sh` | Terminal output | tmux pane |
| Code output metrics (commits, LOC) | `_status_metrics()` | JSON | Internal function |
| Instance-aware fields (instance_id, project_root) | `list_agent_instances()` | JSON | MCP tool call |

### Missing Pieces (What We Need)

| Gap | Impact | Priority |
|---|---|---|
| **No unified dashboard view** — status scattered across 5+ sources | Operator must mentally correlate JSON, JSONL, and log files | HIGH |
| **No real-time updates** — polling only at 600s cadence | Status can be 10 minutes stale; no push notifications | MEDIUM |
| **No structured log aggregation** — watchdog JSONL requires manual jq | Stale tasks and corruption alerts buried in files | HIGH |
| **No blocker/bug visibility panel** — blockers only via `list_blockers()` | Open blockers (10+) not surfaced in operator view | HIGH |
| **No task timeline/history** — events.jsonl has data but no viewer | Can't trace task lifecycle without custom scripting | MEDIUM |
| **No per-agent workload view** — instance-level task assignment hidden | Can't see which Claude instance owns which tasks | MEDIUM |
| **No alerting on threshold breaches** — stale tasks detected but not escalated | Watchdog flags issues but operator may not notice | LOW (Phase 2) |
| **No run analytics export** — metrics computed but not persisted as scorecard | Can't compare across runs or generate reports | LOW (Phase 2) |

### Key Insight

The *data* for a comprehensive dashboard already exists — `orchestrator_status()`, `_status_metrics()`, `list_agent_instances()`, and JSONL logs contain all the raw information. The gap is **presentation and aggregation**, not data collection.

---

## 2. MVP Dashboard Proposal

### Scope: CLI-Based Status Aggregator

The MVP dashboard is a **single CLI command** that aggregates all existing data sources into one structured output. No web server, no TUI framework, no external dependencies.

**Why CLI first:**
- Zero infrastructure — runs in any terminal, no server needed
- Composable — output can be piped to `jq`, redirected to file, or parsed by scripts
- Matches current workflow — operators already work in terminal/tmux
- Fast iteration — pure Python, no frontend build step

### Data Sources (all existing)

```
orchestrator_status()          → task counts, agent list, completion %
_status_metrics()              → throughput, reliability, code output
list_agent_instances()         → per-instance status, current_task_id
list_blockers()                → open blockers with severity
list_bugs()                    → open bugs
watchdog-*.jsonl (latest)      → recent stale task diagnostics
```

### MVP Output Schema

```json
{
  "timestamp": "2026-02-26T15:30:00+00:00",
  "project": "claude-multi-ai",
  "completion": {
    "overall_percent": 72,
    "phase_1_percent": 72,
    "tasks_done": 213,
    "tasks_total": 297,
    "tasks_in_progress": 10,
    "tasks_blocked": 22,
    "tasks_assigned": 52
  },
  "team_instances": [
    {
      "agent_name": "codex",
      "instance_id": "codex-mgr-01",
      "role": "leader",
      "status": "active",
      "current_tasks": 10,
      "last_seen_seconds_ago": 5
    },
    {
      "agent_name": "claude_code",
      "instance_id": "session-20260226-153300",
      "role": "team_member",
      "status": "active",
      "current_tasks": 0,
      "last_seen_seconds_ago": 2
    },
    {
      "agent_name": "gemini",
      "instance_id": "gemini#default",
      "role": "team_member",
      "status": "offline",
      "current_tasks": 0,
      "last_seen_seconds_ago": null
    }
  ],
  "blockers": {
    "open_count": 10,
    "high_severity": 3,
    "items": [
      {
        "id": "BLK-abc12345",
        "task_id": "TASK-xxx",
        "severity": "high",
        "agent": "claude_code",
        "question": "Lease expired..."
      }
    ]
  },
  "alerts": {
    "stale_in_progress": 2,
    "stale_reported": 0,
    "watchdog_warnings": 3,
    "offline_agents_with_tasks": 1
  },
  "throughput": {
    "avg_claim_seconds": 5.2,
    "avg_report_seconds": 120.0,
    "avg_validate_seconds": 2.1,
    "commits_total": 45,
    "loc_total": 12500
  },
  "activity_log": [
    {
      "timestamp": "2026-02-26T15:28:00+00:00",
      "type": "task.validated_accepted",
      "task_id": "TASK-3decb920",
      "agent": "claude_code"
    }
  ]
}
```

### MVP Implementation Plan

#### Phase 1: CLI Dashboard Script (Restart Milestone)

**File:** `scripts/dashboard.py`

**Capabilities:**
1. **Summary view** — One-liner: completion %, active agents, open blockers
2. **Team view** — Per-instance table: agent, instance_id, status, current tasks
3. **Blockers view** — Open blockers sorted by severity
4. **Alerts view** — Stale tasks, offline agents with assigned work, watchdog warnings
5. **JSON mode** — `--json` flag outputs full schema above for programmatic consumption

**Implementation approach:**
- Import `Orchestrator` and `Policy` directly (no MCP server needed)
- Read latest watchdog JSONL for diagnostics
- Aggregate into the schema above
- Pretty-print as table (default) or JSON (`--json`)

**Example CLI output:**
```
claude-multi-ai Dashboard — 2026-02-26 15:30 UTC
═══════════════════════════════════════════════════

Progress: 72% (213/297 done, 10 in-progress, 22 blocked, 52 assigned)

Team:
  codex        leader       active   10 tasks in-progress   5s ago
  claude_code  team_member  active    0 tasks in-progress   2s ago
  gemini       team_member  OFFLINE   0 tasks in-progress   —

Alerts:
  ⚠ 10 open blockers (3 high severity)
  ⚠ gemini offline with 52 assigned tasks
  ⚠ 2 stale in-progress tasks (>30min)

Recent Activity (last 5):
  15:28 task.validated_accepted  TASK-3decb920  claude_code
  15:27 task.lease_renewed       TASK-46a47c21  codex
  ...
```

#### Phase 2: Enhanced Visibility (Post-Restart)

- **Watch mode** — `--watch` flag auto-refreshes every N seconds (replaces monitor_loop.sh)
- **Task timeline** — `--task TASK-xxx` shows full lifecycle from events.jsonl
- **Agent drill-down** — `--agent claude_code` shows all instances, tasks, recent events
- **Scorecard export** — `--scorecard run-001.json` exports run metrics for comparison

#### Phase 3: Web Dashboard (Future)

- Static HTML + JSON API (no runtime server needed if using file-based state)
- Or lightweight Flask/FastAPI serving the same schema
- Deferred until after restart milestone completes

---

## 3. Alignment with Restart Milestone and Roadmap

| Roadmap Phase | Dashboard Relevance |
|---|---|
| **Phase A** (Harden MVP) | Dashboard reads existing watchdog/log data — no new instrumentation |
| **Phase B** (Instance-aware) | Dashboard uses `list_agent_instances()` — already implemented |
| **Phase C** (Task leases) | Dashboard surfaces lease expiry alerts from recovery events |
| **Phase D** (Dispatch telemetry) | Dashboard will display command→ack→result/noop chains when available |
| **Phase E** (Completion engine) | Dashboard becomes the operator's primary progress monitor |

The MVP CLI dashboard is **immediately useful** at the restart milestone because:
- All data sources already exist and are populated
- No new backend work required — purely presentation layer
- Replaces the manual correlation workflow operators currently use
- Provides the foundation for Phase 2/3 enhancements
