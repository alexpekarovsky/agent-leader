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

### CORE-04 Example Rows (filled)

These show what completed evidence looks like for reviewer reference:

| # | Codex Output | Evidence Artifact | Checkpoint | CC Action | Status |
|---|-------------|-------------------|------------|-----------|--------|
| 1 | Watchdog emits: `{"type":"task.lease_expired","payload":{"task_id":"TASK-abc123","lease_id":"lease-7f3a","elapsed_seconds":605}}` | `evidence/core-04/watchdog-expiry.jsonl` — JSONL with `lease_expired` entry | `grep lease_expired watchdog-expiry.jsonl` returns 1+ rows | Verified: schema has task_id, lease_id, elapsed_seconds | DONE |
| 2 | `list_tasks` shows: `{"id":"TASK-abc123","status":"assigned","attempt_index":2}` | `evidence/core-04/requeue.json` — before/after snapshots | Before: `in_progress`, After: `assigned`, attempt_index incremented | Captured diff, verified transition | DONE |
| 3 | `list_tasks` shows: `{"id":"TASK-abc123","status":"blocked","attempt_index":4}` | `evidence/core-04/blocked-task.json` — task record after max retries | `attempt_index` (4) > `max_lease_retries` (3) and status is `blocked` | Captured, verified attempt_index exceeds threshold | DONE |
| 4 | `list_blockers` returns: `{"id":"BLK-abc123","task_id":"TASK-abc123","reason":"lease_expiry_max_retries","severity":"high"}` | `evidence/core-04/auto-blocker.json` — blocker record | Blocker references lease expiry with matching task_id | Captured, verified reason field and task_id | DONE |
| 5 | `list_tasks` after report: `{"id":"TASK-abc123","status":"reported","lease":null}` | `evidence/core-04/post-report.json` — task record after submit_report | Lease fields absent or null in task record | Captured, verified lease cleared | DONE |

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

### CORE-05 Example Rows (filled)

| # | Codex Output | Evidence Artifact | Checkpoint | CC Action | Status |
|---|-------------|-------------------|------------|-----------|--------|
| 1 | Manager emits: `{"type":"dispatch.command","payload":{"correlation_id":"corr-9a2b","task_id":"TASK-def456","target_agent":"claude_code","timeout_seconds":30}}` | `evidence/core-05/dispatch-command.json` | Event has correlation_id, task_id, target_agent | Verified: all fields present, schema matches [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) | DONE |
| 2 | Worker emits: `{"type":"dispatch.ack","payload":{"correlation_id":"corr-9a2b","source":"claude_code","status":"accepted","task_id":"TASK-def456"}}` | `evidence/core-05/dispatch-ack.json` | correlation_id matches command | Verified: correlation chain command→ack intact | DONE |
| 3 | Worker emits: `{"type":"worker.result","payload":{"correlation_id":"corr-9a2b","source":"claude_code","task_id":"TASK-def456","outcome":"success","duration_seconds":12}}` | `evidence/core-05/worker-result.json` | correlation_id matches command and ack | Verified: full chain command→ack→result with matching correlation_id | DONE |
| 4 | Audit log: `[{"tool":"dispatch","status":"ok","correlation_id":"corr-9a2b","events":["command","ack","result"]}]` | `evidence/core-05/audit-dispatch.json` | All 3 events in chronological order | Verified: timestamps monotonic, no gaps | DONE |
| 5 | Schema validation: all 4 events checked against dispatch-telemetry-schema.md | `evidence/core-05/schema-check.md` — field-by-field validation table | Every required field present with correct type in each event | Filled table: 4 events × 5 fields, all PASS | DONE |

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

### CORE-06 Example Rows (filled)

| # | Codex Output | Evidence Artifact | Checkpoint | CC Action | Status |
|---|-------------|-------------------|------------|-----------|--------|
| 1 | Manager emits: `{"type":"dispatch.noop","payload":{"correlation_id":"corr-f1d2","reason":"ack_timeout","target":"claude_code","elapsed_seconds":31}}` | `evidence/core-06/dispatch-noop.json` | Event has reason, correlation_id, elapsed_seconds | Verified: reason is `ack_timeout`, correlation matches command | DONE |
| 2 | Correlation capture: command `corr-f1d2` → noop `corr-f1d2` (same ID, timeout after 31s) | `evidence/core-06/noop-chain.md` — correlation chain doc | command and noop share `correlation_id`, timestamps show noop after timeout | Verified: chain intact, elapsed_seconds matches timeout config | DONE |
| 3 | Timeout matrix filled with 3 scenarios: (a) ack_timeout — worker not running, (b) no_available_worker — no agents registered, (c) result_timeout — worker acked but crashed | `evidence/core-06/timeout-matrix.md` | At least 3 distinct timeout scenarios observed | Filled matrix rows, each with correlation chain | DONE |
| 4 | Edge cases: (a) noop emitted twice for same command — dedup check, (b) noop after partial ack — ack received but worker crashed, (c) noop with zero-length timeout — config edge | `evidence/core-06/edge-cases.md` | At least 3 edge cases exercised or documented as "validated by design" | Filled results, each with expected vs actual behavior | DONE |

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
| `reason` field enum | Defined values: `ack_timeout`, `no_available_worker`, `result_timeout` | Reason field validation |
| `correlation_id` in noop | Links noop to the triggering dispatch command | Correlation chain test |
| Timeout configuration | `dispatch_timeout_seconds` in policy or config | Config read test |

---

## Unblock Recommendations

Practical steps when codex outputs are delayed or missing. Each recommendation allows parallel progress without waiting for the full codex deliverable.

### CORE-04 Unblock Recommendations

| Blocker | Likely Cause | Unblock Action | Owner |
|---------|-------------|----------------|-------|
| No `lease_expired` watchdog event | Watchdog not wired to lease TTL check | Write integration test with mocked expiry time; stub lease TTL to 1s in test config | claude_code |
| Requeue not happening on expiry | `requeue_stale_in_progress_tasks` not lease-aware | Add lease-aware requeue path in engine; test with `stale_after_seconds=1` | codex |
| Max retries config missing | `max_lease_retries` not yet in policy schema | Use hardcoded default (3) in engine; add policy key later | codex |
| Auto-blocker not raised | `raise_blocker` not called from expiry path | Test blocker lifecycle independently (already covered in `test_blocker_lifecycle.py`) | claude_code |
| Lease not cleared on report | `ingest_report` doesn't touch lease fields | Write test asserting lease fields absent after report; flag to codex | claude_code |

### CORE-05 Unblock Recommendations

| Blocker | Likely Cause | Unblock Action | Owner |
|---------|-------------|----------------|-------|
| No `dispatch.command` event | Manager dispatch loop not wired to emit | Define event schema in test; emit manually in integration test to validate pipeline | claude_code |
| No `dispatch.ack` event | Worker claim path doesn't emit ack | Write test asserting `correlation_id` threading from command to ack | claude_code |
| No `worker.result` event | Report path doesn't emit result event | Write test asserting full chain; stub with `publish_event` in interim | claude_code |
| Correlation ID not threaded | No UUID generation at dispatch point | Define `correlation_id` field in event schema doc; flag to codex as prerequisite | claude_code |
| Audit log gaps | `_audit_tool_call` not called for dispatch events | Verify audit entries exist in `test_audit_log_read.py`; extend if needed | claude_code |

### CORE-06 Unblock Recommendations

| Blocker | Likely Cause | Unblock Action | Owner |
|---------|-------------|----------------|-------|
| No `dispatch.noop` event | Noop path not implemented | Write event schema test assuming noop event structure; flag to codex | claude_code |
| Reason enum not defined | No standard values for noop reasons | Propose enum: `ack_timeout`, `no_available_worker`, `result_timeout`; document in schema doc | claude_code |
| Timeout config missing | `dispatch_timeout_seconds` not in policy | Use default (30s) in test; add to policy schema doc | claude_code |
| Edge cases not observable | Need live noop events to fill matrix | Pre-fill edge case template with expected scenarios; validate when events land | claude_code |

### Proactive Pre-Work (do now, validate later)

These tasks can be completed before codex delivers the code, then validated against real outputs:

| # | Task | File | Depends on codex? |
|---|------|------|--------------------|
| 1 | Write dispatch event schema test (command + ack + result) | `tests/test_dispatch_events.py` | No — test structure only |
| 2 | Write noop event schema test | `tests/test_noop_diagnostic.py` | No — test structure only |
| 3 | Pre-fill CORE-05 schema validation table (C05-05) | `evidence/core-05/schema-check.md` | No — template only |
| 4 | Pre-fill CORE-06 timeout matrix (C06-03) | `evidence/core-06/timeout-matrix.md` | No — template only |
| 5 | Pre-fill CORE-06 edge case results (C06-04) | `evidence/core-06/edge-cases.md` | No — template only |

---

## Unblock Path Examples: Happy Path + Fallback

For each CORE task row, the reviewer should expect one of two outcomes. Use these to decide whether evidence is valid or the fallback path was correctly taken.

### CORE-04 Path Examples

| Row | Happy Path | Fallback Condition | Fallback Action |
|-----|-----------|-------------------|-----------------|
| C04-01: Watchdog expiry | Watchdog emits `lease_expired` with valid `task_id` and `elapsed_seconds` > TTL | Watchdog runs but no `lease_expired` event after 2x TTL | Check watchdog logs for errors; verify lease TTL config is loaded; raise blocker BLK-04-01 |
| C04-02: Auto-requeue | Task moves from `in_progress` → `assigned` with `attempt_index` incremented | Task stays `in_progress` after watchdog expiry event | Verify `reassign_stale_tasks` is lease-aware; manually call `reassign_stale_tasks(stale_after_seconds=1)` and re-check |
| C04-03: Max retries block | Task status becomes `blocked` when `attempt_index` > `max_lease_retries` | Task keeps re-assigning past max retries without blocking | Verify `max_lease_retries` config (default: 3); check engine logic for attempt_index threshold |
| C04-04: Auto-blocker | `list_blockers` returns blocker with `source_task` matching expired task | No blocker raised after max retries exceeded | Manually verify `raise_blocker` is called from expiry path; check `test_blocker_lifecycle.py` passes |
| C04-05: Lease clear on report | After `submit_report`, task record has `lease: null` | Lease fields persist after report | Verify `ingest_report` clears lease; file bug against engine if not |
| C04-06: Reconciliation | All C04-01..05 artifacts collected, cross-checked across status API, audit log, and event bus | One or more C04-0x artifacts still missing or status API disagrees with bus | Complete whichever artifacts are ready; mark incomplete ones with "`PENDING: [reason]`" in reconciliation table; do not sign off until all 5 are present and three-source check passes |

### CORE-05 Path Examples

| Row | Happy Path | Fallback Condition | Fallback Action |
|-----|-----------|-------------------|-----------------|
| C05-01: dispatch.command | `poll_events` returns event with `correlation_id`, `task_id`, `target_agent` | Manager cycle completes but no `dispatch.command` event in bus | Verify manager emit call; check bus.emit is wired in dispatch path; use `publish_event` manually to validate bus pipeline |
| C05-02: dispatch.ack | Worker emits ack with `correlation_id` matching command | Worker claims task but no ack event emitted | Verify worker claim path calls `bus.emit("dispatch.ack", ...)`; check correlation_id is passed through |
| C05-03: worker.result | Completion emits result with `correlation_id` and outcome | Report submitted but no `worker.result` event | Verify `ingest_report` or worker loop emits result event; stub with manual `publish_event` if needed |
| C05-04: Audit chain | Audit log contains command, ack, and result with matching correlation_id | Audit entries missing or out of order | Run `test_audit_log.py` to verify audit read/write; check `append_audit` is called for dispatch events |
| C05-05: Schema validation | All C05-01..04 collected, each event matches [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) | One or more events fail schema check (missing field, wrong type) | File bug with field name and expected type; patch schema doc if the event is correct but schema is outdated |

### CORE-06 Path Examples

| Row | Happy Path | Fallback Condition | Fallback Action |
|-----|-----------|-------------------|-----------------|
| C06-01: dispatch.noop | Noop emitted with `reason` (`ack_timeout`/`no_available_worker`), `correlation_id`, `elapsed_seconds` | Dispatch times out but no noop event | Verify timeout detection loop exists; check noop emit path; use manual `publish_event("dispatch.noop", ...)` to validate pipeline |
| C06-02: Noop chain | Correlation capture shows command → noop link with matching IDs | Noop event has different or missing correlation_id | Verify correlation_id is threaded from command to noop in timeout handler |
| C06-03: Timeout matrix | At least 3 timeout scenarios observed (ack_timeout, no_available_worker, result_timeout) | Only 1-2 scenarios reproducible | Document which scenarios were observed; mark missing scenarios as "not yet observable" with justification |
| C06-04: Edge cases | All 3 edge cases from [core-06-noop-edge-cases.md](core-06-noop-edge-cases.md) exercised | Edge case scenario not reproducible in test environment | Pre-fill expected outcomes in template; mark as "validated by design" with code review reference |
| C06-05: Witness log | All observations from C06-01..04 signed by observer with timestamp and session ID | Observer unable to reproduce noop in live session | Use evidence from automated tests (with commit hash) as substitute; note "witness: automated test" in the log and require human co-sign on next live session |

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

## Appendix: Reviewer Pitfalls and Fixes

Common mistakes during CORE-04/05/06 review prep, with recommended fixes.

| # | Pitfall | Affected Row(s) | Fix |
|---|---------|-----------------|-----|
| 1 | **Stale evidence**: Reviewer uses evidence captured against an older commit while code has changed | All CORE-04/05/06 | Always verify the `commit under test` in the bundle metadata matches the current HEAD. Re-collect evidence if the commit has advanced. |
| 2 | **Correlation ID mismatch accepted**: Reviewer overlooks that `dispatch.ack` has a different `correlation_id` than the `dispatch.command` | C05-01, C05-02 | Cross-check correlation IDs character-by-character. Use `grep -c <correlation_id>` across all evidence files — count must equal the number of events in the chain. |
| 3 | **Noop without command**: `dispatch.noop` evidence exists but no corresponding `dispatch.command` captured | C06-01, C06-02 | Every noop must link back to a command via `correlation_id`. If the command is missing from evidence, the noop chain is incomplete — reject and re-collect. |
| 4 | **Lease TTL not verified numerically**: Reviewer accepts `expires_at` without computing `claimed_at + TTL` | C04-01, C04-05 | Parse both timestamps and subtract. The difference must equal the configured `lease_ttl_seconds` (default: 600). Off-by-one second is acceptable; larger drift is a bug. |
| 5 | **Attempt index starts at 0**: Evidence shows `attempt_index: 0` on first claim instead of 1 | C04-02, C04-03 | Per the lease schema, `attempt_index` starts at 1. If evidence shows 0, this is a code bug — reject and file against engine. |
| 6 | **Fallback path not documented**: Review evidence only shows the happy path without noting that the fallback condition was checked | All rows | Each row in the happy-path/fallback table should have a note: either "happy path observed" or "fallback taken — see details." Absence of either means incomplete review. |
| 7 | **Reconciliation done against single source**: Cross-source reconciliation table filled using only the event bus, ignoring audit log and status API | C04-06, C05-05 | All three sources (status API, audit log, event bus) must be independently checked. Single-source reconciliation masks inconsistencies. |
| 8 | **Timeout matrix has duplicate scenarios**: Three timeout rows all describe `ack_timeout` with slightly different wording | C06-03 | The three scenarios must be distinct: `ack_timeout` (worker not running), `no_available_worker` (no agents registered), `result_timeout` (worker acked but crashed). If duplicates exist, re-test with different setups. |

---

## References

- [core-04-06-reviewer-packet-gaps.md](core-04-06-reviewer-packet-gaps.md) — Gap analysis
- [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md) — Artifact inventory
- [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md) — Reviewer criteria
- [core-03-04-signoff-workflow.md](core-03-04-signoff-workflow.md) — CORE-03/04 signoff steps
- [core-05-06-signoff-summary.md](core-05-06-signoff-summary.md) — CORE-05/06 signoff
