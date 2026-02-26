# Dashboard Panel Provenance Examples and Confidence Wording

## Purpose

Every value displayed on the operator dashboard must indicate its **data source** (provenance) and **confidence level**. This prevents operators from treating stale, derived, or estimated values as authoritative facts.

---

## Confidence Levels

| Level | Wording | Meaning | Visual Indicator |
|---|---|---|---|
| **Verified** | "as of {timestamp}" | Direct read from authoritative state file within last 30s | Green / solid |
| **Recent** | "last updated {N}s ago" | Read from state file, but age 30s–5min | Yellow / normal |
| **Stale** | "last known {N}min ago — may be outdated" | Data older than 5 minutes | Orange / dimmed |
| **Derived** | "calculated from {source}" | Computed value, not directly stored | Blue / italic |
| **Unavailable** | "no data — {reason}" | Source missing or agent offline | Gray / dashed |

---

## Panel Provenance Examples

### Example 1: Task Completion Percentage

```
Progress: 72% complete (213/297 tasks done)
  Source: state/tasks.json via orchestrator_status()
  Confidence: Verified — as of 15:30:05 UTC
```

**Guideline:** Task counts come directly from `state/tasks.json`. The percentage is *derived* (division), but the underlying counts are *verified*. Label the percentage as verified when the source read is fresh.

---

### Example 2: Agent Status (Active)

```
claude_code: active (last heartbeat 3s ago)
  Source: state/agents.json via list_agents()
  Confidence: Verified — as of 15:30:02 UTC
```

**Guideline:** "Active" status is verified when the heartbeat is within the configured timeout (default 10 minutes). Show the exact seconds since last heartbeat so operators can judge freshness.

---

### Example 3: Agent Status (Offline)

```
gemini: OFFLINE (no heartbeat for 47min)
  Source: state/agents.json via list_agents()
  Confidence: Stale — last known 47min ago — may be outdated
```

**Guideline:** An offline agent's last-known state may not reflect reality (agent could have restarted without re-registering). Use "last known" wording rather than asserting current state.

---

### Example 4: Open Blockers Count

```
Blockers: 10 open (3 high severity)
  Source: state/blockers.json via list_blockers()
  Confidence: Verified — as of 15:30:05 UTC
```

**Guideline:** Blocker counts are direct reads from state. However, blocker *resolution* depends on human or manager action — the count may include blockers that are practically resolved but not yet marked as such. Add a note if blockers are older than 1 hour.

---

### Example 5: Average Time to Report (Throughput Metric)

```
Avg time to report: 120s
  Source: calculated from task timestamps (claimed_at → reported_at)
  Confidence: Derived — calculated from 213 completed tasks
```

**Guideline:** Throughput metrics are computed from task timestamp deltas. Always state the sample size. Small sample sizes (< 10) should be flagged: "Derived — low sample (N=5), may not be representative."

---

### Example 6: Stale Task Alert (Watchdog)

```
Alert: 2 stale in-progress tasks (>30min without update)
  Source: .autopilot-logs/watchdog-20260226-153000.jsonl
  Confidence: Recent — watchdog cycle ran 15s ago
```

**Guideline:** Watchdog diagnostics are periodic snapshots (default 15s cycle). The alert reflects the *last watchdog run*, not real-time state. A task flagged as stale may have been updated between watchdog cycles.

---

### Example 7: Code Output Metrics (LOC/Commits)

```
Code output: 45 commits, 12,500 LOC added
  Source: git log analysis via _status_metrics()
  Confidence: Derived — calculated from git history at query time
```

**Guideline:** LOC and commit counts are derived from git operations. These are accurate at query time but do not account for uncommitted work. State "at query time" to set expectations.

---

### Example 8: Instance-Level Current Task

```
claude_code [cc-sess-alpha]: working on TASK-3decb920
  Source: state/agent_instances.json metadata.current_task_id
  Confidence: Recent — last updated 45s ago
```

**Guideline:** The `current_task_id` field is updated by the agent's claim/report flow. Between claim and report, this value is accurate. After report submission, there may be a brief window before the next claim where the value is stale.

---

### Example 9: Dispatch Telemetry (Noop Count)

```
Dispatch noops: 3 claim override timeouts
  Source: bus/events.jsonl (type=dispatch.noop)
  Confidence: Derived — counted from event log since session start
```

**Guideline:** Noop counts are event log aggregations. The count grows monotonically within a session. Specify the time window ("since session start" or "last 24h") to avoid misinterpretation.

---

### Example 10: Phase Completion Estimate

```
Phase 1: 72% | Phase 2: 0% | Phase 3: 0%
  Source: task status counts mapped to phase tags
  Confidence: Derived — estimated from task completion ratios
```

**Guideline:** Phase percentages are *estimates* based on task counts per phase. They assume equal task weight. If tasks vary significantly in effort, add: "assumes equal task weight — actual progress may differ."

---

## Confidence Wording Guidelines

### Do

- **Always show the data source** — operators need to know where the number comes from
- **Always show freshness** — timestamp or "N seconds/minutes ago"
- **Use "calculated from" for derived values** — distinguishes computation from direct reads
- **Use "last known" for stale data** — avoids implying current accuracy
- **State sample sizes for averages** — "avg 120s (N=213)" not just "avg 120s"
- **Use "estimated" for composite metrics** — phase percentages, overall progress

### Don't

- **Don't display values without provenance** — bare numbers invite misinterpretation
- **Don't use "real-time" unless push-based** — polling is not real-time
- **Don't hide staleness** — if data is 10 minutes old, say so
- **Don't present derived values as authoritative** — "calculated from" ≠ "confirmed by"
- **Don't mix confidence levels without labels** — if one panel is verified and another is derived, both need labels

### Template for New Panels

When adding a new dashboard panel, use this template:

```
{Panel Title}: {value}
  Source: {file or function that provides the data}
  Confidence: {Verified|Recent|Stale|Derived|Unavailable} — {detail}
```

---

## Mapping: Panel → Source → Confidence

| Panel | Primary Source | Confidence Type |
|---|---|---|
| Task counts | state/tasks.json | Verified |
| Completion % | task counts (division) | Derived |
| Agent status | state/agents.json | Verified (active) / Stale (offline) |
| Blocker count | state/blockers.json | Verified |
| Bug count | state/bugs.json | Verified |
| Throughput metrics | task timestamp deltas | Derived |
| Code output | git log | Derived |
| Stale task alerts | watchdog-*.jsonl | Recent (within cycle interval) |
| Instance status | state/agent_instances.json | Verified / Recent |
| Dispatch noops | bus/events.jsonl | Derived |
| Phase completion | task counts per phase | Derived (estimated) |
| Activity log | bus/events.jsonl (tail) | Verified |
