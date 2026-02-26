# Dashboard Data Contract Gap Tracker

> Tracked list of backend fields/events needed for dashboard MVP that current
> status/audit outputs do not yet provide. Prioritized by operator impact.

## Current Data Available (v0.1.x)

| Tool | Key Fields | Coverage |
|------|-----------|----------|
| `orchestrator_status` | task_count, task_status_counts, active_agents, active_agent_identities, agent_instances, metrics (throughput, timings, reliability, code_output) | Good for point-in-time |
| `orchestrator_list_tasks` | id, title, status, owner, timestamps (created/claimed/reported/validated), lease fields | Per-task detail |
| `orchestrator_list_agents` | agent, instance_id, status, task_counts, last_seen, verified | Agent presence |
| `orchestrator_list_blockers` | id, task_id, severity, status, question, resolution | Blocker queue |
| `orchestrator_list_bugs` | id, task_id, severity, status, description | Bug tracking |
| `orchestrator_list_audit_logs` | timestamp, tool, status, args (filterable by tool/status) | Audit trail |

## Priority 1: Missing for MVP Dashboard (High Operator Impact)

| # | Gap | What's Missing | Impact | Roadmap Phase |
|---|-----|---------------|--------|---------------|
| 1 | **Time-series task throughput** | No time-window view (tasks/hour, tasks/day) | Cannot track velocity trends or SLA compliance | Phase D+ (v0.3+) |
| 2 | **Task lifecycle timeline** | No aggregated assigned->claimed->reported->validated timeline per task | Cannot diagnose where delays occur | Phase D (v0.3.0) |
| 3 | **Lease expiry diagnostics surface** | Events on bus but not queryable via dashboard tool | Cannot tune lease policy or detect patterns | Phase C (v0.2.x) |
| 4 | **Blocker resolution funnel** | No aggregation: count raised vs resolved, avg resolution time by severity | Cannot measure decision bottleneck | Phase D (v0.3.0) |
| 5 | **Single task detail join** | No single-call task+events+blockers+reports view | Must call 4+ tools to investigate one task | Phase D (v0.3.0) |

## Priority 2: Needed for Operational Excellence (Medium Impact)

| # | Gap | What's Missing | Impact | Roadmap Phase |
|---|-----|---------------|--------|---------------|
| 6 | **Agent utilization rates** | No idle% vs active% per agent/instance | Cannot identify bottleneck agents | Phase D+ (v0.3+) |
| 7 | **P50/P95/P99 task duration** | Only averages; no percentiles | Cannot detect outliers | Phase D+ (v0.3+) |
| 8 | **Dispatch attempt tracking** | No log of claim attempts per agent | Cannot diagnose no-op patterns | Phase D (v0.3.0) |
| 9 | **Agent state transition history** | Only current status; no online->idle->working->stale log | Cannot debug connection issues | Phase B+ (v0.2.0+) |
| 10 | **Stale task age distribution** | Only hardcoded 30m/10m thresholds; no percentile view | Cannot tune timeout thresholds | Phase C (v0.2.x) |

## Priority 3: Future Analytics (Lower Immediate Impact)

| # | Gap | What's Missing | Impact | Roadmap Phase |
|---|-----|---------------|--------|---------------|
| 11 | **Event replay / full stream** | No dashboard query for event sequence per task | Cannot reconstruct incidents | Phase D (v0.3.0) |
| 12 | **Per-run scorecard** | No aggregated run manifest (start/end, all metrics, versions) | Cannot compare overnight runs | Post Phase E (v0.4+) |
| 13 | **Dispatch no-op rate** | No command-sent-but-no-ACK tracking | Cannot measure dispatch reliability | Phase D (v0.3.0) |
| 14 | **Workstream-level drill-down** | Only overall % + focus tasks; no per-stream pipeline | Cannot manage multi-stream projects | Phase B/C (v0.2.0+) |
| 15 | **SLA metrics** | No % tasks validated within X hours | Cannot set operational SLOs | Phase E+ (v0.4+) |
| 16 | **Cost attribution** | No per-agent token/API cost tracking | Cannot manage budget | Future (not planned) |
| 17 | **Energy efficiency** | LOC/Wh, tasks/Wh not instrumented | Sustainability reporting | Future (not planned) |

## MVP Dashboard Scope (Buildable Now)

These views use only current tool data with no backend changes needed:

1. **Task Pipeline Card** - Status counts from `orchestrator_status.task_status_counts`
2. **Agent Activity Table** - From `orchestrator_list_agents` with presence indicators
3. **Blocker Queue** - From `orchestrator_list_blockers(status=open)` with severity
4. **Metrics Summary** - From `orchestrator_status.metrics` (throughput, timings, reliability)
5. **Task Detail** - From `orchestrator_list_tasks` + separate blocker/bug queries
6. **Audit Log Browser** - From `orchestrator_list_audit_logs` with tool/status filters

## Gap-to-CORE-Task Mapping

| Gap | CORE Task(s) | Status |
|-----|-------------|--------|
| Time-series throughput | CORE-05 (Benchmarking/Analytics) | Planned |
| Task lifecycle timeline | CORE-02 (Improved Observability) | Planned |
| Lease expiry diagnostics | CORE-03/04 (Task Leases) | In progress |
| Blocker aggregation | CORE-02 (Improved Status) | Planned |
| Task detail join | CORE-02 (Per-task timeline) | Planned |
| Agent utilization | CORE-05 (Analytics metrics) | Planned |
| Dispatch tracking | CORE-02 (Deterministic Dispatch) | Planned |
| Event replay | CORE-02 (Dispatch Contract) | Planned |
| Per-run scorecard | CORE-05 (Benchmarking) | Future |
| SLA metrics | CORE-05 (Acceptance criteria) | Future |
