# Dashboard Content Priority (MVP)

> One-screen priority ranking of dashboard panels for the MVP release.
> Each panel is justified by operator need and mapped to its data source.
> "Existing" means the data is available today via MCP tools with no
> backend changes. "Gap" means additional work is required.

## Priority Ranking

| Priority | Panel | Justification | Source | Status |
|----------|-------|---------------|--------|--------|
| **P0** | Task Pipeline | Primary operator need. Answers "where are we?" with status counts (assigned, in_progress, reported, done) and completion percentage. Most-checked view during any run. | `orchestrator_status` `.task_status_counts`, `.task_count`, `.metrics.throughput` | Existing |
| **P0** | Agent Activity | Immediate health check. Shows who is online, who is stale, and what each agent is working on. First thing operators look at after a restart or when progress stalls. | `orchestrator_list_agents` (presence, last_seen, task_counts); `orchestrator_status` `.agent_instances` (per-instance detail) | Existing |
| **P1** | Blocker Queue | Decision bottleneck. Open blockers directly stall agent progress. This panel surfaces unresolved questions ranked by severity so operators can unblock the pipeline. | `orchestrator_list_blockers(status=open)` | Existing |
| **P1** | Alert Panel | Intervention triggers. Aggregates stale-task, timeout, and corruption alerts from watchdog and status into a single severity-ranked list. Operators use this to decide when manual action is needed. | Watchdog JSONL (`stale_task`, `state_corruption_detected`); `orchestrator_status` `.metrics.reliability` (stale counts, open bugs); alert taxonomy | Existing (watchdog) + Synthetic (aggregation) |
| **P2** | Metrics Summary | Trend monitoring. Shows throughput rates (tasks/run), average claim-to-report time, open bugs/blockers count, and code output (commits, LOC). Not urgent per-minute, but critical for end-of-run reviews. | `orchestrator_status` `.metrics.timings_seconds`, `.metrics.reliability`, `.metrics.code_output` | Existing |
| **P2** | Audit Log Browser | Investigation tool. Operators drill into specific tool calls when diagnosing failures (e.g., why did `submit_report` return an error?). Filterable by tool name and status. | `orchestrator_list_audit_logs(tool=..., status=...)` | Existing |
| **P3** | Event Timeline | Future (requires Phase D). Full event sequence per task with correlation threading. Needed for incident reconstruction but not for daily operation. | `orchestrator_poll_events` + correlation_id linking | Gap -- requires Phase D dispatch contract |
| **P3** | Historical Trends | Future (requires snapshots). Time-series throughput, agent utilization percentiles, SLA compliance. Requires periodic status snapshots that do not exist yet. | Status snapshot JSONL (not yet implemented); synthetic aggregation | Gap -- requires snapshot infrastructure |

## Source Mapping Detail

### Existing Sources (no backend changes needed)

| Panel | MCP Tool | Key Fields Used |
|-------|----------|----------------|
| Task Pipeline | `orchestrator_status` | `task_count`, `task_status_counts`, `metrics.throughput.completion_rate_percent` |
| Task Pipeline | `orchestrator_list_tasks` | Per-task `id`, `title`, `status`, `owner`, timestamps |
| Agent Activity | `orchestrator_list_agents` | `agent`, `status`, `last_seen`, `task_counts`, `verified` |
| Agent Activity | `orchestrator_status` | `agent_instances` (instance_id, role, current_task_id) |
| Blocker Queue | `orchestrator_list_blockers` | `id`, `task_id`, `severity`, `question`, `status` |
| Alert Panel | Watchdog JSONL | `kind`, `task_id`, `age_seconds`, `timeout_seconds` |
| Alert Panel | `orchestrator_status` | `metrics.reliability.stale_in_progress_over_30m`, `open_bugs`, `open_blockers` |
| Metrics Summary | `orchestrator_status` | `metrics.timings_seconds`, `metrics.reliability`, `metrics.code_output` |
| Audit Log Browser | `orchestrator_list_audit_logs` | `timestamp`, `tool`, `status`, `args` |

### Missing Sources (gaps blocking P3 panels)

| Panel | What Is Missing | Roadmap Phase | Reference |
|-------|----------------|---------------|-----------|
| Event Timeline | Queryable event stream per task with correlation threading | Phase D (v0.3.0) | [dashboard-data-contract-gaps.md](dashboard-data-contract-gaps.md) Gap #11 |
| Event Timeline | Dispatch no-op rate tracking | Phase D (v0.3.0) | Gap #13 |
| Historical Trends | Periodic status snapshot capture to JSONL | Phase D+ (v0.3+) | Gap #1 (time-series throughput) |
| Historical Trends | P50/P95/P99 task duration percentiles | Phase D+ (v0.3+) | Gap #7 |
| Historical Trends | Agent utilization rates (idle% vs active%) | Phase D+ (v0.3+) | Gap #6 |
| Historical Trends | SLA compliance metrics | Phase E+ (v0.4+) | Gap #15 |

## Operator Decision Guide

| Question | Panel to Check | Priority |
|----------|---------------|----------|
| "Where are we overall?" | Task Pipeline | P0 |
| "Is everyone online?" | Agent Activity | P0 |
| "What's blocking progress?" | Blocker Queue | P1 |
| "Is anything broken?" | Alert Panel | P1 |
| "How fast are we going?" | Metrics Summary | P2 |
| "What happened with task X?" | Audit Log Browser | P2 |
| "What was the event sequence?" | Event Timeline | P3 (future) |
| "How does this run compare to last?" | Historical Trends | P3 (future) |

## References

- [dashboard-provenance-labels.md](dashboard-provenance-labels.md) -- source
  labels shown on each panel
- [data-source-trust-matrix.md](data-source-trust-matrix.md) -- authority and
  conflict resolution per source
- [dashboard-data-contract-gaps.md](dashboard-data-contract-gaps.md) -- full
  gap tracker with roadmap phases
- [operator-alert-taxonomy.md](operator-alert-taxonomy.md) -- alert
  classification feeding the Alert Panel
