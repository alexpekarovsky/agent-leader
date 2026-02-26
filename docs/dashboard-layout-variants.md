# One-Screen Dashboard Layout Variants

Two layout variants for an eventual dashboard, both using only current and near-term data sources. Each fits a single terminal screen (80x24 minimum, 120x40 optimal).

---

## Variant A: Operations-Focused ("Ops Dashboard")

Prioritizes system health, agent availability, and blocker resolution. Designed for an operator monitoring a running autopilot session.

### Layout (120-column terminal)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  claude-multi-ai Ops Dashboard          76% complete    16:05 UTC      │
├──────────────────────────┬──────────────────────────────────────────────┤
│  PIPELINE HEALTH         │  TEAM STATUS                                │
│                          │                                             │
│  Done:     239 ████████░ │  codex        leader    active     0s ago   │
│  Assigned:  52 ██░░░░░░░ │  claude_code  worker    active     2s ago   │
│  Blocked:   22 █░░░░░░░░ │  gemini       worker    OFFLINE    47m ago  │
│  In-Prog:    0 ░░░░░░░░░ │                                             │
│                          │  Alerts:                                     │
│  Blockers: 10 open       │  ▲ gemini offline — 52 tasks waiting        │
│  Bugs:      5 tracked    │  ▲ 10 open blockers (3 high severity)       │
│  Reported:  0 pending    │  ▲ 22 blocked tasks need resolution         │
├──────────────────────────┴──────────────────────────────────────────────┤
│  OPEN BLOCKERS (top 5 by severity)                                     │
│                                                                         │
│  BLK-abc123  HIGH  TASK-xxx  claude_code  Lease expired, no worker...  │
│  BLK-def456  HIGH  TASK-yyy  gemini       No eligible worker for...    │
│  BLK-ghi789  HIGH  TASK-zzz  claude_code  Lease expired for in-pr...   │
│  BLK-jkl012  med   TASK-aaa  codex        Architecture decision p...   │
│  BLK-mno345  med   TASK-bbb  gemini       Frontend dependency not...   │
├─────────────────────────────────────────────────────────────────────────┤
│  RECENT EVENTS (last 5)                                                │
│                                                                         │
│  16:04  task.validated_accepted  TASK-ca9d3fa2  claude_code   codex    │
│  16:04  agent.heartbeat          claude_code                           │
│  16:03  task.validated_accepted  TASK-12dfbab4  claude_code   codex    │
│  16:02  agent.heartbeat          codex                                 │
│  16:01  task.claimed             TASK-8759477d  claude_code            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Panel Breakdown

| Panel | Size | Data Source | Confidence |
|---|---|---|---|
| Header (project, %, time) | 1 row | `orchestrator_status()` | Verified |
| Pipeline Health | 8 rows | `orchestrator_status()` task counts | Verified |
| Team Status | 5 rows | `list_agents()` / `list_agent_instances()` | Verified/Stale |
| Alerts | 3 rows | Derived from team + blockers + watchdog | Derived |
| Open Blockers | 5 rows | `list_blockers()` sorted by severity | Verified |
| Recent Events | 5 rows | `bus/events.jsonl` tail | Verified |

### Tradeoffs

| Pro | Con |
|---|---|
| Immediate blocker/alert visibility | No per-task detail or code output metrics |
| Agent health at a glance | Doesn't show throughput or velocity trends |
| Escalation-ready (blockers front and center) | Less useful when everything is healthy (mostly empty) |
| Good for overnight/unattended monitoring | No drill-down — operator must use CLI for details |

### Missing Backend Fields Needed

- None — all data sources exist today
- **Nice to have:** `blocker.age_seconds` for staleness sorting (derivable from `created_at`)

---

## Variant B: Engineering-Focused ("Dev Dashboard")

Prioritizes task throughput, code output, and per-agent workload. Designed for a developer tracking progress and identifying bottlenecks.

### Layout (120-column terminal)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  claude-multi-ai Dev Dashboard          76% complete    16:05 UTC      │
├────────────────────────────────┬────────────────────────────────────────┤
│  PHASE PROGRESS                │  THROUGHPUT                            │
│                                │                                        │
│  Phase 1: 76% ██████░░░░      │  Avg claim→report:  120s              │
│  Phase 2:  0% ░░░░░░░░░░      │  Avg report→done:     2s              │
│  Phase 3:  0% ░░░░░░░░░░      │  Tasks done today:   26               │
│                                │  Commits today:      13               │
│  Backend:  96% █████████░      │  LOC added:        3,200              │
│  Frontend: 23% ██░░░░░░░░      │                                        │
│  QA:       76% ███████░░░      │                                        │
├────────────────────────────────┼────────────────────────────────────────┤
│  AGENT WORKLOAD                │  CODE OUTPUT BY AGENT                  │
│                                │                                        │
│  codex                         │  claude_code:  42 commits  11,800 LOC │
│    done: 48  assigned: 0       │  codex:         3 commits     700 LOC │
│    blocked: 2  in_progress: 0  │  gemini:        0 commits       0 LOC │
│                                │                                        │
│  claude_code                   │                                        │
│    done: 191  assigned: 0      │                                        │
│    blocked: 8  in_progress: 0  │                                        │
│                                │                                        │
│  gemini                        │                                        │
│    done: 0  assigned: 52       │                                        │
│    blocked: 12  in_progress: 0 │                                        │
├────────────────────────────────┴────────────────────────────────────────┤
│  RECENT COMPLETIONS (last 5)                                           │
│                                                                         │
│  16:04  TASK-ca9d3fa2  Status discrepancy scenarios       claude_code  │
│  16:03  TASK-12dfbab4  Panel provenance examples          claude_code  │
│  16:02  TASK-8759477d  Dashboard gap analysis             claude_code  │
│  15:29  TASK-3decb920  Lease renewal identity binding     claude_code  │
│  15:28  TASK-8f31f055  Post-restart visibility fixture    claude_code  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Panel Breakdown

| Panel | Size | Data Source | Confidence |
|---|---|---|---|
| Header (project, %, time) | 1 row | `orchestrator_status()` | Verified |
| Phase Progress | 6 rows | `orchestrator_live_status_report()` | Derived |
| Throughput | 5 rows | `_status_metrics()` | Derived |
| Agent Workload | 10 rows | `list_tasks()` grouped by owner + status | Derived |
| Code Output by Agent | 4 rows | `_status_metrics()` LOC/commits | Derived |
| Recent Completions | 5 rows | `bus/events.jsonl` (task.validated_accepted) | Verified |

### Tradeoffs

| Pro | Con |
|---|---|
| Clear velocity and throughput visibility | Doesn't surface blockers or alerts prominently |
| Per-agent workload shows bottlenecks | Less useful for incident response |
| Phase breakdown shows strategic progress | Assumes equal task weight for percentages |
| Code output validates productivity | LOC is a noisy metric (tests vs features) |
| Good for sprint reviews and planning | Operator may miss critical health issues |

### Missing Backend Fields Needed

- **`tasks_done_today`**: Derivable from `task.validated_accepted` events with today's date filter
- **`commits_today`** / **`loc_today`**: Needs time-windowed git log (not currently exposed via API, but computable from git)
- All other fields exist today

---

## Comparison Matrix

| Dimension | Variant A (Ops) | Variant B (Dev) |
|---|---|---|
| **Primary audience** | Operator/SRE | Developer/PM |
| **Key question answered** | "Is anything broken?" | "Are we making progress?" |
| **Top panel priority** | Alerts + blockers | Phase progress + throughput |
| **Agent detail** | Status + heartbeat age | Task counts per status |
| **Code metrics** | Not shown | Commits + LOC per agent |
| **Blocker visibility** | Full table (top 5) | Count only (in workload) |
| **Event stream** | All event types | Completions only |
| **Best for** | Monitoring overnight runs | Sprint standups, retrospectives |
| **All data available today?** | Yes | Mostly (time-windowed metrics need derivation) |

---

## Recommendation

**Start with Variant A (Ops)** for the restart milestone because:
1. All data sources exist — zero backend work
2. Blocker/alert visibility is the highest-value gap right now (10 open blockers, offline agent)
3. Ops layout naturally supports the `--watch` mode for unattended monitoring

**Add Variant B panels incrementally** as throughput metrics and time-windowed queries are refined. The two variants can eventually merge into a tabbed or switchable view (`--layout ops` / `--layout dev`).
