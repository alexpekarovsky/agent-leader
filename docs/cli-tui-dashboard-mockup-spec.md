# CLI/TUI Dashboard Mockup Spec

> Visual mockup and implementation spec for a single-screen terminal dashboard
> showing project %, team instances, queue health, and alerts. Targets 80x24
> minimum, 120x40 optimal terminal size.

---

## Single-Screen Layout (120x40)

```
┌─ claude-multi-ai ─────────────── Overall: 90% ── AUTO-M1: 96% ── 16:20 UTC ─┐
│                                                                               │
│  ┌─ PIPELINE ─────────────────┐  ┌─ TEAM INSTANCES ──────────────────────┐   │
│  │                            │  │                                        │   │
│  │  Done:     286 ██████████░ │  │  codex       mgr  ● active     0s    │   │
│  │  Assigned:  10 ░░░░░░░░░░░ │  │  claude_code  tm  ● active     2s    │   │
│  │  Blocked:   22 █░░░░░░░░░░ │  │  gemini       tm  ○ OFFLINE   47m    │   │
│  │  In-Prog:    0 ░░░░░░░░░░░ │  │                                        │   │
│  │  Reported:   0 ░░░░░░░░░░░ │  │  Instances:                            │   │
│  │                            │  │    codex-mgr-01       ● 10 tasks       │   │
│  │  Total: 318 tasks          │  │    cc-sess-alpha      ● idle           │   │
│  │  Bugs: 7  Blockers: 9     │  │    cc-sess-beta       ● idle           │   │
│  │                            │  │    gemini#default     ○ 0 tasks        │   │
│  └────────────────────────────┘  └────────────────────────────────────────┘   │
│                                                                               │
│  ┌─ ALERTS ──────────────────────────────────────────────────────────────┐   │
│  │  ▲ HIGH  gemini offline — 3 assigned tasks unworkable                 │   │
│  │  ▲ HIGH  9 open blockers (3 high severity)                            │   │
│  │  ▲ med   22 blocked tasks awaiting resolution                         │   │
│  │  · info  All in-progress leases valid                                 │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  ┌─ BLOCKER QUEUE (top 5) ───────────────────────────────────────────────┐   │
│  │  BLK-abc123  HIGH  TASK-xxx  claude_code  Lease expired, no worke...  │   │
│  │  BLK-def456  HIGH  TASK-yyy  gemini       No eligible worker for...   │   │
│  │  BLK-ghi789  HIGH  TASK-zzz  claude_code  Lease expired for in-p...  │   │
│  │  BLK-jkl012  med   TASK-aaa  codex        Architecture decision ...   │   │
│  │  BLK-mno345  med   TASK-bbb  gemini       Frontend dependency no...   │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  ┌─ ACTIVITY (last 5) ──────────────────────────────────────────────────┐   │
│  │  16:20  task.validated_accepted  TASK-9f4d27c9  claude_code  codex   │   │
│  │  16:15  task.validated_accepted  TASK-baf8add0  claude_code  codex   │   │
│  │  16:12  task.validated_accepted  TASK-cc3e078f  claude_code  codex   │   │
│  │  16:08  agent.heartbeat          claude_code                         │   │
│  │  16:05  agent.heartbeat          codex                               │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
├─ [s]tatus [t]asks [a]gents [b]lockers [m]anager [r]eassign [?]help ──────────┤
│  Source: orchestrator_status() │ Refresh: 10s │ Verified as of 16:20:12 UTC  │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Compact Layout (80x24)

For minimum terminal sizes, panels stack vertically with reduced detail:

```
── claude-multi-ai ── Overall: 90% ── M1: 96% ── 16:20 UTC ──

PIPELINE  Done: 286  Assigned: 10  Blocked: 22  InProg: 0
TEAM      codex ● active  cc ● active  gemini ○ OFFLINE

ALERTS
  ▲ gemini offline — 3 tasks unworkable
  ▲ 9 blockers (3 high)
  ▲ 22 blocked tasks

BLOCKERS (top 3)
  BLK-abc123 HIGH TASK-xxx claude_code  Lease expired...
  BLK-def456 HIGH TASK-yyy gemini       No eligible...
  BLK-ghi789 HIGH TASK-zzz claude_code  Lease expired...

ACTIVITY (last 3)
  16:20 task.validated_accepted TASK-9f4d27c9 cc
  16:15 task.validated_accepted TASK-baf8add0 cc
  16:12 task.validated_accepted TASK-cc3e078f cc

[s]tatus [b]lockers [m]anager [?]help  Refresh: 10s
```

---

## Panel Specifications

### Header Bar

| Field | Source | Position |
|---|---|---|
| Project name | Hardcoded or from policy | Left |
| Overall % | `orchestrator_status().live_status.overall_project_percent` | Center-left |
| AUTO-M1 % | `live_status.phase_1_percent` | Center-right |
| UTC time | System clock | Right |

Always shows **both** percentages to prevent confusion (see `percent-reporting-template.md`).

### Pipeline Panel

| Field | Source | Visual |
|---|---|---|
| Status counts | `task_status_counts` from `orchestrator_status()` | Bar chart (█/░) |
| Total tasks | `task_count` | Numeric |
| Bug count | `orchestrator_list_bugs(status=bug_open)` count | Numeric |
| Blocker count | `orchestrator_list_blockers(status=open)` count | Numeric |

Bar width scales to terminal width. Each bar shows `count / total` ratio.

### Team Instances Panel

| Field | Source | Visual |
|---|---|---|
| Agent name | `list_agents()` | Text |
| Role | `mgr` / `tm` | Abbreviated |
| Status | Agent `status` field | `●` active / `○` offline |
| Heartbeat age | `last_seen` delta | `Ns` / `Nm` / `Nh` |
| Per-instance rows | `list_agent_instances()` | Indented under agent |
| Instance task | `metadata.current_task_id` | Task ID or `idle` |

### Alerts Panel

Synthesized from multiple sources, sorted by severity:

| Alert Source | Trigger | Severity |
|---|---|---|
| Offline agent with assigned tasks | Agent offline + `assigned > 0` | HIGH |
| Open blockers | `blocker_count > 0` | HIGH (if any high-severity) |
| Blocked tasks | `blocked > 0` | med |
| Stale in-progress | `stale_in_progress_over_30m > 0` | HIGH |
| Stale reported | `stale_reported_over_10m > 0` | med |
| All leases valid | No stale/expired leases | info (positive) |

Severity indicators: `▲` HIGH, `▲` med, `·` info.

### Blocker Queue Panel

| Field | Source |
|---|---|
| Blocker ID | `list_blockers()` `.id` |
| Severity | `.severity` |
| Task ID | `.task_id` |
| Agent | `.agent` or task owner |
| Question | `.question` (truncated to fit) |

Sorted by severity (high first), then by creation time (oldest first).
Shows top 5 in full layout, top 3 in compact.

### Activity Panel

| Field | Source |
|---|---|
| Timestamp | `bus/events.jsonl` tail, formatted HH:MM |
| Event type | `.type` |
| Task ID | `.payload.task_id` |
| Agent | `.source` or `.payload.agent` |

Shows last 5 events in full layout, last 3 in compact.
Filters to significant events: `task.validated_accepted`, `task.claimed`,
`task.lease_renewed`, `agent.heartbeat`, `dispatch.noop`.

### Footer Bar

| Field | Content |
|---|---|
| Keybindings | Single-key shortcuts from command palette |
| Source | Primary data source for current view |
| Refresh interval | Current auto-refresh cadence |
| Freshness | Timestamp of last data fetch |

---

## Refresh and Data Flow

### Refresh Strategy

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Timer (10s)  │────▶│ Fetch all sources │────▶│ Render frame │
└─────────────┘     └──────────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    ▼             ▼
            orchestrator_    list_blockers()
            status()         list_bugs()
                             bus/events.jsonl
                             watchdog JSONL
```

| Parameter | Default | Override |
|---|---|---|
| Refresh interval | 10s | `--refresh N` flag |
| Event tail count | 5 | `--events N` flag |
| Blocker display count | 5 | `--blockers N` flag |

### Data Fetch Sequence (per refresh cycle)

1. `orchestrator_status()` — task counts, agent list, completion %, metrics
2. `list_blockers(status="open")` — open blockers sorted by severity
3. `list_bugs(status="bug_open")` — open bug count
4. `bus/events.jsonl` tail — last N significant events
5. Latest `watchdog-*.jsonl` — stale task diagnostics (if file changed)

All fetches are read-only. No state mutation during refresh.

### Freshness Tracking

Each panel shows data age in the footer:
- `Verified` — data fetched within current refresh cycle (<10s)
- `Recent` — data from previous cycle (10–30s)
- `Stale` — data older than 3 refresh cycles (>30s)

---

## Keybindings

| Key | Action | Mutates State? |
|---|---|---|
| `s` | Force refresh (status) | No |
| `t` | Toggle task list overlay | No |
| `a` | Toggle agent detail overlay | No |
| `b` | Toggle blocker detail overlay | No |
| `m` | Run manager cycle | Yes |
| `r` | Reassign stale tasks | Yes |
| `q` | Quit dashboard | No |
| `?` | Show help overlay | No |
| `1` | Switch to Ops layout | No |
| `2` | Switch to Dev layout | No |

State-mutating keys (`m`, `r`) show confirmation before executing.

---

## Terminal Compatibility

| Feature | Requirement | Fallback |
|---|---|---|
| Unicode box drawing | `┌─┐│└─┘` | ASCII `+-+|+-+` |
| Unicode indicators | `●○▲·█░` | `[*][ ][!][.][#][-]` |
| Colors (ANSI) | 16-color support | Monochrome with bold/dim |
| Minimum size | 80x24 | Compact layout auto-selected |
| Optimal size | 120x40 | Full layout with all panels |

Auto-detect terminal dimensions on startup and each refresh cycle.
Switch between compact and full layout dynamically on resize.

---

## Implementation Notes

### Phase 1 (MVP): `scripts/dashboard.py`

- Pure Python, no external TUI library
- Import `Orchestrator` and `Policy` directly
- Print-and-clear refresh loop (`os.system('clear')` or ANSI escape)
- `--json` flag outputs raw data instead of rendering
- `--watch` flag enables auto-refresh (default 10s)
- `--compact` flag forces compact layout

### Phase 2: Rich TUI

- Migrate to `rich` library for live display (`rich.live.Live`)
- Panel borders, color coding, progress bars
- Scrollable blocker/event lists
- Keyboard input via `rich.prompt` or `blessed`

### Phase 3: Full TUI Framework

- `textual` or `urwid` for interactive widgets
- Drill-down panels (click blocker → detail view)
- Task timeline view
- Multiple layout tabs (Ops / Dev / Custom)

---

## Current vs Future Data Distinction

| Panel | Data Available Today | Needs Future Work |
|---|---|---|
| Header (%, time) | Yes — `orchestrator_status()` | — |
| Pipeline counts | Yes — `task_status_counts` | — |
| Team instances | Yes — `list_agent_instances()` | — |
| Alerts | Mostly — derived from status + watchdog | Threshold config (Phase 2) |
| Blocker queue | Yes — `list_blockers()` | — |
| Activity log | Yes — `bus/events.jsonl` | Correlation threading (Phase D) |
| Throughput metrics | Yes — `_status_metrics()` | Time-windowed queries (Phase 2) |
| Historical trends | No | Snapshot infrastructure (Phase 3) |

All P0/P1 panels use existing data. No backend changes for MVP.

---

## Related Docs

- **Layout variants:** `docs/dashboard-layout-variants.md` — Ops vs Dev layouts
- **Content priority:** `docs/dashboard-content-priority.md` — panel ranking
- **Command palette:** `docs/dashboard-command-palette.md` — keybinding rationale
- **Gap analysis:** `docs/dashboard-gap-analysis-mvp-proposal.md` — MVP scope
- **Provenance:** `docs/dashboard-panel-provenance-examples.md` — confidence labels
- **Percent template:** `docs/percent-reporting-template.md` — % display rules
