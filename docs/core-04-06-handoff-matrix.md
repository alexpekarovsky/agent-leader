# CORE-04/05/06 Reviewer Handoff Matrix

Matrix mapping each remaining core task to expected codex outputs, evidence
dependencies, and unblock checkpoints for parallel review preparation.

## Matrix Legend

- **Codex output**: Code, config, or runtime artifact codex must produce
- **Evidence**: What to capture from that output for the acceptance packet
- **Checkpoint**: Condition that unblocks the next step
- **CC action**: What claude_code does once the checkpoint is met

---

## CORE-04: Lease Expiry and Recovery

| # | Codex Output | Evidence Artifact | Checkpoint | CC Action | Status |
|---|-------------|-------------------|------------|-----------|--------|
| 1 | Watchdog detects expired lease and emits `lease_expired` event | C04-01: watchdog-expiry.jsonl | Watchdog JSONL contains at least one `lease_expired` entry | Capture JSONL, verify schema | BLOCKED |
| 2 | Expired task auto-requeued to `assigned` | C04-02: requeue.json | `list_tasks` shows task moved from `in_progress` → `assigned` after expiry | Capture task list snapshot | BLOCKED |
| 3 | Task blocked after exceeding `max_lease_retries` | C04-03: blocked-task.json | Task status is `blocked` with attempt_index > max_retries | Capture task record, verify attempt_index | BLOCKED |
| 4 | Auto-blocker raised on repeated expiry | C04-04: auto-blocker.json | `list_blockers` returns blocker referencing lease expiry | Capture blocker, verify reason field | BLOCKED |
| 5 | Lease cleared on successful report submission | C04-05: post-report.json | Task with prior lease shows no active lease after report | Capture task before/after report | BLOCKED |
| 6 | — | C04-06: reconciliation.md | All C04-01..05 collected and cross-checked | Fill reconciliation template | BLOCKED on #1-5 |

### CORE-04 Unblock Conditions

```
Codex lands:                          CC unblocked for:
─────────────                         ─────────────────
watchdog lease expiry code      ───>  C04-01, C04-02
max_lease_retries + auto-block  ───>  C04-03, C04-04
lease-clear-on-report wiring    ───>  C04-05
all above complete              ───>  C04-06 reconciliation
```

### CORE-04 Codex Deliverables Summary

| Deliverable | Engine method/config | Test coverage needed |
|------------|---------------------|---------------------|
| Lease TTL configuration | `lease_ttl_seconds` in policy or engine config | Config read + default test |
| Expiry detection loop | Watchdog or supervisor periodic check | Integration test: expired lease → requeue |
| `lease_expired` event emission | `bus.emit("task.lease_expired", ...)` | Event payload schema test |
| Max retries → auto-block | `max_lease_retries` config → `raise_blocker()` | Unit test: N expiries → blocked |
| Lease clear on report | `ingest_report()` clears lease fields | Unit test: post-report lease is null |

---

## CORE-05: Dispatch Telemetry

| # | Codex Output | Evidence Artifact | Checkpoint | CC Action | Status |
|---|-------------|-------------------|------------|-----------|--------|
| 1 | `dispatch.command` event emitted on task dispatch | C05-01: dispatch-command.json | `poll_events` returns event with `correlation_id`, `task_id`, `target_agent` | Capture event, verify schema | BLOCKED |
| 2 | `dispatch.ack` event emitted by worker on claim | C05-02: dispatch-ack.json | Event has matching `correlation_id` from command | Capture event, verify correlation | BLOCKED |
| 3 | `worker.result` event emitted on task completion | C05-03: worker-result.json | Event has matching `correlation_id`, outcome, timing | Capture event, verify chain | BLOCKED |
| 4 | Audit log records dispatch lifecycle | C05-04: audit-dispatch.json | `list_audit_logs` shows command→ack→result in order | Capture audit entries | BLOCKED on #1-3 |
| 5 | — | C05-05: schema-check.md | All C05-01..04 collected and schema verified | Fill schema validation table | BLOCKED on #1-4 |

### CORE-05 Unblock Conditions

```
Codex lands:                          CC unblocked for:
─────────────                         ─────────────────
dispatch.command emission       ───>  C05-01
dispatch.ack emission           ───>  C05-02
worker.result emission          ───>  C05-03
all three + audit logging       ───>  C05-04, C05-05
```

### CORE-05 Codex Deliverables Summary

| Deliverable | Engine method/config | Test coverage needed |
|------------|---------------------|---------------------|
| `dispatch.command` event | Manager emits on task dispatch with `correlation_id` | Event schema + correlation_id presence |
| `dispatch.ack` event | Worker emits on claim with matching `correlation_id` | Correlation chain: command → ack |
| `worker.result` event | Worker emits on completion with outcome + timing | Full chain: command → ack → result |
| `correlation_id` threading | UUID generated at dispatch, threaded through lifecycle | Unit test: all 3 events share same ID |
| Audit log integration | All dispatch events written to audit log | Audit entries present + ordered |

---

## CORE-06: No-Op Diagnostic

| # | Codex Output | Evidence Artifact | Checkpoint | CC Action | Status |
|---|-------------|-------------------|------------|-----------|--------|
| 1 | `dispatch.noop` event emitted on timeout/no-worker | C06-01: dispatch-noop.json | `poll_events` returns noop with `reason`, `correlation_id` | Capture event, verify schema | BLOCKED |
| 2 | — | C06-02: noop-chain.md | C06-01 collected, correlation chain documented | Fill correlation capture template | BLOCKED on #1 |
| 3 | Noop behavior under various timeout scenarios | C06-03: timeout-matrix.md | At least 3 timeout scenarios observed | Fill timeout behavior matrix | BLOCKED on #1 |
| 4 | — | C06-04: edge-cases.md | Edge cases exercised with real noop events | Fill edge case results | BLOCKED on #1 |
| 5 | — | C06-05: witness-log.md | All observations signed by observer | Fill witness log | BLOCKED on #1-4 |

### CORE-06 Unblock Conditions

```
Codex lands:                          CC unblocked for:
─────────────                         ─────────────────
dispatch.noop event emission    ───>  C06-01, C06-02, C06-03, C06-04
noop reason enum defined        ───>  C06-01 schema validation
all above + live session        ───>  C06-05 witness log
```

### CORE-06 Codex Deliverables Summary

| Deliverable | Engine method/config | Test coverage needed |
|------------|---------------------|---------------------|
| `dispatch.noop` event | Manager emits when dispatch times out or no worker | Event schema test |
| `reason` field enum | Defined values: `no_available_worker`, `timeout`, `empty_queue` | Reason field validation |
| `correlation_id` in noop | Links noop to the triggering dispatch command | Correlation chain test |
| Timeout configuration | `dispatch_timeout_seconds` in policy or config | Config read test |

---

## Cross-CORE Dependency Graph

```
CORE-04 (lease expiry)          CORE-05 (dispatch telemetry)
  depends on:                     depends on:
  - lease issuance (CORE-03)      - task dispatch (engine)
  - watchdog running              - correlation_id threading
  - max_retries config            - audit log integration
        \                              |
         \                             |
          +--- CORE-06 (noop) --------+
                depends on:
                - dispatch.noop event
                - reason enum
                - CORE-05 correlation_id pattern
```

## Parallel Execution Timeline

| Phase | Codex (code) | Claude_code (docs + tests) |
|-------|-------------|---------------------------|
| **Phase 1** | Implement dispatch events (command, ack, result) | Write dispatch chain integration test |
| **Phase 2** | Implement noop event + reason enum | Write noop schema validation test |
| **Phase 3** | Wire watchdog lease expiry detection | Write expiry detection integration test |
| **Phase 4** | Run live session with all events | Collect evidence into packet artifacts |
| **Phase 5** | — | Fill reconciliation + witness logs |
| **Phase 6** | — | Submit packet for reviewer signoff |

## Checkpoint Tracking

| Checkpoint | CORE | Condition | Met? | Date |
|-----------|------|-----------|------|------|
| CP-1 | 05 | `dispatch.command` event emitted in test | | |
| CP-2 | 05 | `dispatch.ack` event emitted in test | | |
| CP-3 | 05 | `worker.result` event emitted in test | | |
| CP-4 | 05 | Full correlation chain verified | | |
| CP-5 | 06 | `dispatch.noop` event emitted in test | | |
| CP-6 | 06 | Noop reason values defined | | |
| CP-7 | 04 | Watchdog detects expired lease | | |
| CP-8 | 04 | Auto-requeue on expiry works | | |
| CP-9 | 04 | Max retries → auto-block works | | |
| CP-10 | 04 | Lease cleared on report | | |
| CP-11 | ALL | Live session evidence collected | | |
| CP-12 | ALL | Reconciliation + witness logs filled | | |

## References

- [core-04-06-reviewer-packet-gaps.md](core-04-06-reviewer-packet-gaps.md) — Gap analysis
- [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md) — Artifact inventory
- [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md) — Reviewer criteria
- [core-03-04-signoff-workflow.md](core-03-04-signoff-workflow.md) — CORE-03/04 signoff steps
- [core-05-06-signoff-summary.md](core-05-06-signoff-summary.md) — CORE-05/06 signoff
