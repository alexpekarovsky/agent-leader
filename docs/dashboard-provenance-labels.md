# Data Provenance Labels for Dashboard Panels

> Standardized labels indicating the data source for each dashboard panel
> value. Helps operators understand data freshness, reliability, and how
> values are computed.

## Label Definitions

| Label | Source | Meaning | Freshness |
|-------|--------|---------|-----------|
| `STATUS` | `orchestrator_status` | Live point-in-time snapshot from the engine | Real-time on each call |
| `TASKS` | `orchestrator_list_tasks` | Direct read from tasks.json state | Real-time on each call |
| `AGENTS` | `orchestrator_list_agents` | Direct read from agents.json state | Real-time on each call |
| `AUDIT` | `orchestrator_list_audit_logs` | Append-only audit JSONL log | Retroactive, up to ~400 entries |
| `WATCHDOG` | Watchdog JSONL files | Periodic scan of state for staleness/corruption | Interval-based (default 15s) |
| `BUS` | Event bus JSONL | Raw event stream from all agents/tools | Append-only, real-time |
| `SYNTHETIC` | Computed client-side | Derived by dashboard from multiple sources | Depends on input freshness |
| `SNAPSHOT` | Status snapshots JSONL | Historical status records over time | Periodic (per status call) |

## Panel-to-Label Mapping

### Task Pipeline Card
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Status counts (assigned, in_progress, etc.) | `STATUS` | `orchestrator_status.task_status_counts` | Point-in-time totals |
| Total task count | `STATUS` | `orchestrator_status.task_count` | |
| Completion rate % | `STATUS` | `orchestrator_status.metrics.throughput.completion_rate_percent` | Computed by engine |
| Recent task list | `TASKS` | `orchestrator_list_tasks` | Full task objects |

### Agent Activity Table
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Agent name, status, last_seen | `AGENTS` | `orchestrator_list_agents` | Includes staleness calc |
| Instance ID, role | `STATUS` | `orchestrator_status.agent_instances` | Per-instance detail |
| Task counts per agent | `AGENTS` | `orchestrator_list_agents.task_counts` | Aggregated by engine |
| Verified flag | `AGENTS` | `orchestrator_list_agents.verified` | Identity verification |
| Presence indicator (green/orange/red) | `SYNTHETIC` | Derived from `last_seen` + threshold | Client-side computation |

### Metrics Summary
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Avg time to claim/report/validate | `STATUS` | `orchestrator_status.metrics.timings_seconds` | Engine-computed averages |
| Open bugs count | `STATUS` | `orchestrator_status.metrics.reliability.open_bugs` | Point-in-time |
| Open blockers count | `STATUS` | `orchestrator_status.metrics.reliability.open_blockers` | Point-in-time |
| Stale in_progress count | `STATUS` | `orchestrator_status.metrics.reliability.stale_in_progress_over_30m` | Threshold-based |
| Commits/LOC by agent | `STATUS` | `orchestrator_status.metrics.code_output` | Aggregated from reports |

### Blocker Queue
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Blocker list (id, task, severity) | `STATUS` | `orchestrator_list_blockers(status=open)` | Direct state read |
| Avg blocker age | `SYNTHETIC` | Computed from `created_at` timestamps | Client-side aggregation |
| Resolution rate | `SYNTHETIC` | Computed from open vs resolved counts | Client-side over time window |

### Audit Log Browser
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Log entries | `AUDIT` | `orchestrator_list_audit_logs` | Filterable by tool/status |
| Tool call success rate | `SYNTHETIC` | Computed from ok vs error counts | Client-side aggregation |

### Watchdog Diagnostics
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Stale task alerts | `WATCHDOG` | Watchdog JSONL `kind=stale_task` | Periodic scan results |
| State corruption alerts | `WATCHDOG` | Watchdog JSONL `kind=state_corruption_detected` | Integrity check |
| Timeout markers | `WATCHDOG` | CLI log `[AUTOPILOT] CLI timeout` lines | Log scan by log_check.sh |

### Event Timeline (Future - Phase D)
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Event stream | `BUS` | `orchestrator_poll_events` | Filtered by audience/cursor |
| Dispatch correlation chain | `BUS` | Events linked by correlation_id | Requires Phase D dispatch |
| Event counts over time | `SYNTHETIC` | Computed from bus events | Time-bucketed aggregation |

### Historical Trends (Future - Phase D+)
| Panel Value | Label | Source Tool | Notes |
|-------------|-------|-------------|-------|
| Task throughput over time | `SNAPSHOT` | Status snapshots JSONL | Requires periodic capture |
| Agent utilization % | `SYNTHETIC` | Computed from snapshots | Multi-snapshot derivation |
| SLA compliance | `SYNTHETIC` | Computed from task timing data | Requires defined SLO thresholds |

## Display Guidelines

1. **Always show the provenance label** next to dashboard values, either as
   a subtle badge or tooltip. Example: `Tasks Done: 42 [STATUS]`

2. **Color-code by freshness**:
   - Green: `STATUS`, `TASKS`, `AGENTS` (real-time on call)
   - Blue: `AUDIT`, `BUS` (append-only, retroactive)
   - Yellow: `WATCHDOG`, `SNAPSHOT` (interval-based, may be stale)
   - Gray: `SYNTHETIC` (derived, depends on input freshness)

3. **Include last-updated timestamp** for each panel showing when the
   source data was last fetched.

4. **Mark synthetic values clearly** with a computation icon or "(computed)"
   suffix so operators know the value is derived, not directly from state.

## Examples

```
Task Pipeline          [STATUS - 2s ago]
  Assigned:    12
  In Progress:  5
  Done:        42
  Completion:  77% (computed)

Agent Activity         [AGENTS - 2s ago]
  codex        active  last_seen: 3s ago  tasks: 12 done
  claude_code  active  last_seen: 8s ago  tasks: 5 in_progress
  gemini       offline last_seen: 2d ago  tasks: 0 done

Blockers               [STATUS - 2s ago]
  3 open (avg age: 45m [SYNTHETIC])
  BLK-abc123  high  "Task stuck..."  created 2h ago
```
