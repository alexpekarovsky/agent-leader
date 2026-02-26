# CORE-04/05/06 Reviewer Packet Workflow Gaps and Handoff Notes

Concise handoff artifact listing remaining gaps in the reviewer packet
workflows for CORE-04, CORE-05, and CORE-06, and what evidence or code
is still needed from codex (manager) to close them.

## Status overview

| CORE | Templates ready | Evidence collected | Code landed | Signoff ready |
|------|----------------|-------------------|-------------|--------------|
| CORE-04 | YES | PARTIAL | PARTIAL | NO |
| CORE-05 | YES | NO | PARTIAL | NO |
| CORE-06 | YES | NO | PARTIAL | NO |

## CORE-04: Lease expiry and recovery

### Templates available

- [x] Evidence template (`core-03-04-evidence-template.md`)
- [x] Cross-source reconciliation (`core-03-04-cross-source-reconciliation.md`)
- [x] Witness log (`lease-witness-log-template.md`)
- [x] Reviewer checklist (`core-03-06-reviewer-checklist.md`, CORE-04 section)
- [x] Signoff workflow (`core-03-04-signoff-workflow.md`)
- [x] Signoff summary (`core-02-04-signoff-summary.md`)

### Remaining gaps

| # | Gap | Owner | Dependency | Priority |
|---|-----|-------|-----------|----------|
| 1 | Watchdog lease expiry detection not yet exercised in live run | codex | Watchdog must be running with lease TTL configured | HIGH |
| 2 | No live evidence for C04-01 (watchdog lease_expired event) | codex | Requires supervisor + watchdog running with short TTL | HIGH |
| 3 | No live evidence for C04-03 (blocked task after max retries) | codex | Requires repeated expiry scenario (agent stopped, lease expires N times) | HIGH |
| 4 | No live evidence for C04-04 (auto-blocker raised) | codex | Same as #3 — blocker raised after max retries exceeded | HIGH |
| 5 | C04-06 reconciliation template unfilled | both | Needs live evidence from #1-#4 first | MEDIUM |
| 6 | No `renew_lease()` engine method yet | codex | Engine code needed for lease renewal; tests reference it but it may not exist | MEDIUM |

### What codex needs to provide

- Supervisor session with watchdog running and `lease_ttl_seconds` set short (e.g. 30s)
- A stopped-agent scenario to trigger lease expiry naturally
- Watchdog JSONL output capturing `lease_expired` events
- Confirmation that `max_lease_retries` config is wired to blocker auto-raise

## CORE-05: Dispatch telemetry

### Templates available

- [x] Evidence template (`core-05-06-evidence-template.md`)
- [x] Witness log (`core-05-06-witness-log-template.md`)
- [x] Verification checklist (`core-05-06-telemetry-verification-checklist.md`)
- [x] Reviewer checklist (`core-03-06-reviewer-checklist.md`, CORE-05 section)
- [x] Signoff summary (`core-05-06-signoff-summary.md`)

### Remaining gaps

| # | Gap | Owner | Dependency | Priority |
|---|-----|-------|-----------|----------|
| 1 | No `dispatch.command` event implementation in engine | codex | Engine must emit `dispatch.command` when manager dispatches work | HIGH |
| 2 | No `dispatch.ack` event implementation in engine | codex | Workers must emit `dispatch.ack` on claim/start | HIGH |
| 3 | No `worker.result` event implementation in engine | codex | Workers must emit result event after task completion | HIGH |
| 4 | No `correlation_id` threading in dispatch events | codex | All three events must share a correlation_id for chain verification | HIGH |
| 5 | No live evidence for C05-01 through C05-05 | both | Blocked by #1-#4 | HIGH |
| 6 | Dispatch telemetry schema doc may be missing | claude_code | `dispatch-telemetry-schema.md` referenced but may not exist | LOW |

### What codex needs to provide

- Engine code emitting `dispatch.command`, `dispatch.ack`, `worker.result` events
- `correlation_id` field threaded through the dispatch lifecycle
- A live session producing at least one complete command→ack→result chain
- Audit log entries for dispatch events

## CORE-06: No-op diagnostic

### Templates available

- [x] Evidence template (`core-05-06-evidence-template.md`, noop section)
- [x] Correlation capture (`core-06-noop-correlation-capture.md`)
- [x] Edge cases (`core-06-noop-edge-cases.md`)
- [x] Reviewer checklist (`core-03-06-reviewer-checklist.md`, CORE-06 section)
- [x] Signoff summary (`core-05-06-signoff-summary.md`)

### Remaining gaps

| # | Gap | Owner | Dependency | Priority |
|---|-----|-------|-----------|----------|
| 1 | No `dispatch.noop` event implementation in engine | codex | Engine must emit noop when dispatch times out or no worker available | HIGH |
| 2 | Noop `reason` field schema not finalized | codex | Need defined enum/string values for noop reasons | MEDIUM |
| 3 | No live evidence for C06-01 through C06-05 | both | Blocked by #1-#2 | HIGH |
| 4 | Timeout behavior matrix unfilled | both | Needs live observation of timeout scenarios | MEDIUM |
| 5 | Edge case doc is template-only | claude_code | Can be filled once noop events are emitted | LOW |

### What codex needs to provide

- Engine code emitting `dispatch.noop` with reason and correlation_id
- Defined noop reason values (e.g. `no_available_worker`, `timeout`, `empty_queue`)
- A live session that triggers at least one noop scenario
- Confirmation of timeout thresholds for noop emission

## Cross-cutting gaps

| # | Gap | Affects | Owner | Priority |
|---|-----|---------|-------|----------|
| 1 | `evidence/` folder structure not created | all | either | LOW |
| 2 | No automated evidence collection script | all | claude_code | LOW |
| 3 | Signoff summaries are template-only | all | both | MEDIUM |
| 4 | No end-to-end integration test for dispatch chain | CORE-05/06 | claude_code | MEDIUM |

## Parallel execution plan

```
codex (code)                    claude_code (docs + tests)
─────────────                   ──────────────────────────
Implement dispatch events  ──>  Write dispatch chain integration test
Implement noop events      ──>  Fill edge case doc with real examples
Wire watchdog lease expiry ──>  Fill reconciliation with live evidence
Run live session           ──>  Collect evidence into packet
                           ──>  Fill signoff summaries
                           ──>  Submit packet for review
```

## Readiness checklist

- [ ] All dispatch events implemented (command, ack, result, noop)
- [ ] Correlation_id threaded through dispatch lifecycle
- [ ] Watchdog lease expiry detection working
- [ ] Max retries → auto-blocker wired
- [ ] Live session evidence collected for all 16 artifacts (C04-01..C06-05)
- [ ] Cross-source reconciliation filled
- [ ] Signoff summaries completed
- [ ] Packet submitted for reviewer signoff

## References

- [core-03-04-signoff-workflow.md](core-03-04-signoff-workflow.md) -- CORE-03/04 workflow
- [core-03-06-acceptance-packet-index.md](core-03-06-acceptance-packet-index.md) -- Artifact inventory
- [core-03-06-reviewer-checklist.md](core-03-06-reviewer-checklist.md) -- Reviewer criteria
- [core-02-04-signoff-summary.md](core-02-04-signoff-summary.md) -- CORE-02..04 signoff
- [core-05-06-signoff-summary.md](core-05-06-signoff-summary.md) -- CORE-05/06 signoff
- [core-milestone-blocker-triage.md](core-milestone-blocker-triage.md) -- Blocker impact analysis
