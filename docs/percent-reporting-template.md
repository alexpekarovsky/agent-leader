# Percent Reporting Template: Overall vs AUTO-M1

> Reusable template for status updates that always shows both overall project %
> and AUTO-M1 milestone %. Prevents metric confusion by requiring explicit labels,
> definitions, and context on every percentage.

---

## The Two Percentages (Always Report Both)

| Metric | Definition | Formula | Source |
|---|---|---|---|
| **Overall project %** | All tasks across all phases and workstreams | `done / total_tasks × 100` | `orchestrator_status().live_status.overall_project_percent` |
| **AUTO-M1 milestone %** | Only CORE-02 through CORE-06 restart tasks | `done_milestone / total_milestone × 100` | `phase_1_percent` in `orchestrator_live_status_report()` |

**Why they diverge:** AUTO-M1 is a subset of the full project. When the milestone
completes, overall % may still be <100% because frontend, DOCS, QA, and later
phases have remaining tasks.

---

## Templates (Three Formats)

### Short Form (heartbeat/quick updates)

```
Status: Overall {overall}% | AUTO-M1 {milestone}% | {done}/{total} tasks done
        Backend {backend}% | Frontend {frontend}% | Blockers: {blocker_count}
```

**Example:**
```
Status: Overall 76% | AUTO-M1 96% | 239/313 tasks done
        Backend 96% | Frontend 23% | Blockers: 10
```

Use for: heartbeats, inline log messages, quick checks (every 1–5 minutes).

### Standard Form (10-minute cadence reports)

```
Status Update — {date} {time} UTC

Project: claude-multi-ai
Run: {run_id or session tag}

── Progress ──────────────────────────────────
Overall project:     {overall}%  ({done}/{total} tasks)
AUTO-M1 milestone:   {milestone}%  ({milestone_done}/{milestone_total} tasks)

  Phase 1 (Arch + Slice):  {phase_1}%
  Phase 2 (Content):       {phase_2}%
  Phase 3 (Production):    {phase_3}%

  Backend slice:   {backend}%   Current: {backend_task_id}
  Frontend slice:  {frontend}%  Current: {frontend_task_id}
  QA validation:   {qa}%

── Pipeline Health ───────────────────────────
In-progress: {in_progress}  Blocked: {blocked}  Reported: {reported}
Blockers: {blocker_count} open ({high_severity} high)  Bugs: {bug_count}

── Team ──────────────────────────────────────
{agent} ({role}): {status} ({heartbeat}s ago); {current_task or idle}
...

── Notes ─────────────────────────────────────
{free-form context, blockers, next actions}
```

Use for: regular operator cadence reports (recommended every 600s).

### Full Form (sprint reviews or escalation)

```
═══ Full Status Report — {date} {time} UTC ═══

PROGRESS
  Overall project:       {overall}%  ({done}/{total} tasks)
  AUTO-M1 milestone:     {milestone}%  ({milestone_done}/{milestone_total} tasks)
  Phase 1 (Arch+Slice):  {phase_1}%
  Phase 2 (Pipeline):    {phase_2}%
  Phase 3 (Production):  {phase_3}%

WORKSTREAM DETAIL
  Backend:   {backend}%  done: {be_done}  assigned: {be_assigned}  blocked: {be_blocked}
  Frontend:  {frontend}% done: {fe_done}  assigned: {fe_assigned}  blocked: {fe_blocked}
  QA:        {qa}%

THROUGHPUT
  Avg claim-to-report:   {avg_report}s  (N={sample_size})
  Avg report-to-done:    {avg_validate}s
  Commits total:         {commits}
  LOC added (net):       {loc}

PIPELINE HEALTH
  In-progress: {in_progress}  Blocked: {blocked}  Reported: {reported}
  Blockers: {blocker_count} open ({high_severity} high severity)
  Bugs: {bug_count} open
  Stale in-progress (>30min): {stale_ip}
  Stale reported (>10min):    {stale_rep}

TEAM
  {agent}  {role}  {status}  last seen {heartbeat}s ago
  ...

ALERTS
  {alert_1}
  {alert_2}
```

Use for: sprint reviews, escalation, incident response (on-demand).

---

## Definitions

| Metric | Formula | What It Measures |
|---|---|---|
| **Overall project %** | `tasks_done / tasks_total × 100` | All tasks across all phases |
| **AUTO-M1 milestone %** | `milestone_done / milestone_total × 100` | Only restart milestone tasks (CORE-02..06, DOCS, EXEC) |
| **Phase N %** | `phase_done / phase_total × 100` | Tasks scoped to that phase |
| **Backend/Frontend %** | `workstream_done / workstream_total × 100` | Vertical slice progress |
| **QA validation %** | `validated / (reported + done) × 100` | Review throughput vs. completion |

---

## Field Reference

### Progress Fields

| Field | Source | Notes |
|---|---|---|
| `overall` | `orchestrator_status().live_status.overall_project_percent` | Auto-computed `done / total × 100` |
| `milestone` | `live_status.phase_1_percent` | Phase 1 tracks AUTO-M1 scope |
| `done` / `total` | `orchestrator_status().task_summary` | Total includes all statuses |
| `milestone_done` / `milestone_total` | Phase 1 task subset | Filter by CORE-02–06 tags |

### Workstream Fields

| Field | Source | Notes |
|---|---|---|
| `backend` | `live_status.backend_percent` | Auto or manual override |
| `frontend` | `live_status.frontend_percent` | Auto or manual override |
| `qa` | `live_status.qa_validation_percent` | Defaults to overall if not overridden |

### Pipeline Fields

| Field | Source | Notes |
|---|---|---|
| `in_progress` | `task_summary.in_progress` | Tasks with active leases |
| `blocked` | `task_summary.blocked` | Cannot proceed without resolution |
| `reported` | `task_summary.reported` | Awaiting manager validation |
| `blocker_count` | `list_blockers(status="open")` | Direct state read |
| `bug_count` | `list_bugs(status="open")` | Direct state read |

### Throughput Fields

| Field | Source | Notes |
|---|---|---|
| `avg_report` | `_status_metrics().throughput.avg_report_seconds` | Claim-to-report latency |
| `avg_validate` | `_status_metrics().throughput.avg_validate_seconds` | Report-to-done latency |
| `commits` | `_status_metrics().code_output.commits_total` | From git log |
| `loc` | `_status_metrics().code_output.loc_total` | Net lines added |

---

## Example (Filled — Standard Form)

```
Status Update — 2026-02-26 16:05 UTC

Project: claude-multi-ai
Run: session-20260226-restart

── Progress ──────────────────────────────────
Overall project:     76%  (239/313 tasks)
AUTO-M1 milestone:   96%  (168/175 tasks)

  Phase 1 (Arch + Slice):  96%
  Phase 2 (Content):        0%
  Phase 3 (Production):     0%

  Backend slice:   96%   Current: TASK-e75fb59d
  Frontend slice:  23%   Current: TASK-ba1b2ee1
  QA validation:   76%

── Pipeline Health ───────────────────────────
In-progress: 0  Blocked: 22  Reported: 0
Blockers: 10 open (3 high)  Bugs: 5

── Team ──────────────────────────────────────
codex (manager): active (0s ago); in_progress on RETRO-QA-01
claude_code (team_member): active (2s ago); idle
gemini (team_member): OFFLINE (47min ago)

── Notes ─────────────────────────────────────
AUTO-M1 core milestone at 96%. Gemini offline — 52 frontend tasks
assigned but unworkable. 10 open blockers (3 high severity).
claude_code queue empty; waiting for mirrored tasks from codex.
```

---

## Common Mistakes to Avoid

| Mistake | Why It's Wrong | Correct Approach |
|---|---|---|
| Reporting only overall % | Hides milestone progress; operator can't tell if AUTO-M1 is done | Always show both overall and milestone |
| Saying "96% complete" without label | Ambiguous — overall or milestone? | Always label: "Overall 76%" or "AUTO-M1 96%" |
| Using Phase 1 % as overall | Phase 1 is a subset; overall includes all phases | Use `overall_project_percent` for overall |
| Reporting 100% when blocked tasks exist | Blocked tasks drag max achievable below 100% | Note: "76% (max achievable: 93% with 22 blocked)" |
| Omitting sample size on throughput | "Avg 120s" from 3 tasks is unreliable | Always include: "Avg 120s (N=213)" |
| Treating stale data as current | Status could be minutes old | Add timestamp: "as of 16:05 UTC" |
| Mixing auto vs manual override | Manual overrides persist until next call | Note when values are auto-computed vs overridden |

---

## Relationship to Other Docs

- **Percent interpretation:** `docs/status-percent-interpretation.md` — why percentages diverge
- **Panel provenance:** `docs/dashboard-panel-provenance-examples.md` — confidence levels on each field
- **Dashboard layouts:** `docs/dashboard-layout-variants.md` — visual terminal mockups
- **Discrepancy scenarios:** `docs/status-discrepancy-scenarios.md` — when sources disagree
