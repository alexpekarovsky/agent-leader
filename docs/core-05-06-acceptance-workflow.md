# CORE-05/06 Telemetry & No-Op Acceptance Workflow

Step-by-step signoff workflow for CORE-05 (dispatch telemetry) and CORE-06 (no-op diagnostics). Follow these phases in order once the implementation lands.

## Prerequisites

- CORE-01 (instance_id) and CORE-02 (instance-aware status) accepted
- Supervisor prototype operational with manager + at least one worker
- Event bus and audit log functional

## Phase 1: Operator Evidence Collection

The operator runs verification steps and fills in evidence templates.

### 1a. Run the verification checklist

Follow [core-05-06-telemetry-verification-checklist.md](core-05-06-telemetry-verification-checklist.md) steps 1–5:

| Step | Action | Artifact to fill |
|------|--------|-----------------|
| 1 | Trigger manager cycle, capture `dispatch.command` | Evidence template §1 |
| 2 | Observe worker ack, capture `dispatch.ack` | Evidence template §2 |
| 3 | Trigger timeout, capture `dispatch.noop` | Evidence template §3 |
| 4 | Check audit log chain | Evidence template §4 |
| 5 | Verify noop diagnostic fields | Evidence template §5 |

### 1b. Fill the evidence template

Paste captured JSON into [core-05-06-evidence-template.md](core-05-06-evidence-template.md):

- §1: `dispatch.command` event with correlation_id, task_id, target_agent
- §2: `dispatch.ack` event with matching correlation_id
- §3: `dispatch.noop` event with reason and elapsed_seconds
- §4: Audit log entries showing command→ack→result chain
- §5: Timeout diagnostic summary

### 1c. Run edge cases

Follow [core-06-noop-edge-cases.md](core-06-noop-edge-cases.md):

| Edge case | Scenario | Fill in |
|-----------|----------|---------|
| 1 | No active worker → noop | Edge case evidence §1 |
| 2 | Duplicate claim race → one ack wins | Edge case evidence §2 |
| 3 | Worker crash mid-task → timeout noop | Edge case evidence §3 |

### 1d. Capture correlation chains

Use [core-06-noop-correlation-capture.md](core-06-noop-correlation-capture.md) to record:

- At least 2 successful command→ack→result chains
- At least 1 noop chain with retry tracking
- Batch capture table filled for all observed dispatches

### 1e. Fill the witness log

Record live observations in [core-05-06-witness-log-template.md](core-05-06-witness-log-template.md):

- Timestamped event log entries
- Timing measurements (command→ack, command→noop latencies)
- Chain completeness table
- Any anomalies observed

**Operator signs off** on witness log and evidence template.

## Phase 2: Reviewer Validation

The reviewer cross-checks operator evidence against acceptance criteria.

### 2a. Use the acceptance packet checklist

Open [core-03-06-acceptance-packet.md](core-03-06-acceptance-packet.md) Part 2 and check items T1–T11:

| Check | What to verify | Evidence source |
|-------|---------------|-----------------|
| T1 | Manager cycle emits `dispatch.command` | Evidence §1 |
| T2 | Worker ack produces `dispatch.ack` | Evidence §2 |
| T3 | Timeout produces `dispatch.noop` with reason | Evidence §3 |
| T4 | Audit log shows command→ack→result chain | Evidence §4 |
| T5 | No-active-worker edge case correct | Edge cases §1 |
| T6 | Duplicate-claim race handled | Edge cases §2 |
| T7 | Worker crash produces timeout noop | Edge cases §3 |
| T8 | Witness log timings are reasonable | Witness log |
| T9 | Events match schema | [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) |
| T10 | Existing test suite unaffected | Test run output |
| T11 | Noop reason codes documented | Verification checklist §3 |

### 2b. Cross-check correlation consistency

Using the correlation capture and witness log:

- [ ] Every `dispatch.command` has either an `ack` or a `noop` (no orphans)
- [ ] All correlation IDs in evidence match across command/ack/noop/result
- [ ] Timestamps are monotonically increasing within each chain
- [ ] Retry chains use new correlation IDs

### 2c. Verify schema compliance

Compare observed events against [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md):

- [ ] `dispatch.command` has: correlation_id, task_id, target_agent, timestamp
- [ ] `dispatch.ack` has: correlation_id, source, status, task_id
- [ ] `dispatch.noop` has: correlation_id, reason, elapsed_seconds, target
- [ ] No extra required fields missing

## Phase 3: Signoff

### 3a. Fill the signoff summary

Complete [core-05-06-signoff-summary.md](core-05-06-signoff-summary.md):

- CORE-05 verdict (dispatch telemetry)
- CORE-06 verdict (no-op diagnostics)
- End-to-end correlation chain verdict
- Combined checkpoint verdict

### 3b. Sign the acceptance packet

In [core-03-06-acceptance-packet.md](core-03-06-acceptance-packet.md), fill the signoff table:

| Role | What to sign |
|------|-------------|
| Implementer | Confirms code matches spec |
| Reviewer | Confirms evidence is complete and consistent |
| Operator | Confirms operational verification passed |

### 3c. Record verdict

**Verdict options:** Accepted / Accepted with notes / Rejected (specify reason)

## Artifact Index

All artifacts used in this workflow:

| # | Artifact | Role | Phase |
|---|----------|------|-------|
| 1 | [core-05-06-telemetry-verification-checklist.md](core-05-06-telemetry-verification-checklist.md) | Operator guide | 1a |
| 2 | [core-05-06-evidence-template.md](core-05-06-evidence-template.md) | Evidence capture | 1b |
| 3 | [core-06-noop-edge-cases.md](core-06-noop-edge-cases.md) | Edge case verification | 1c |
| 4 | [core-06-noop-correlation-capture.md](core-06-noop-correlation-capture.md) | Correlation evidence | 1d |
| 5 | [core-05-06-witness-log-template.md](core-05-06-witness-log-template.md) | Live observation log | 1e |
| 6 | [core-03-06-acceptance-packet.md](core-03-06-acceptance-packet.md) | Reviewer checklist | 2a, 3b |
| 7 | [dispatch-telemetry-schema.md](dispatch-telemetry-schema.md) | Schema reference | 2c |
| 8 | [core-05-06-signoff-summary.md](core-05-06-signoff-summary.md) | Final signoff | 3a |
| 9 | [core-05-06-telemetry-verification.md](core-05-06-telemetry-verification.md) | Operator checklist (alt) | 1a |

## Quick Reference: Minimum Viable Signoff

For a fast-track signoff when time is limited:

1. Run verification checklist steps 1–5 → fill evidence template
2. Run edge case 1 (no active worker) → fill edge case evidence
3. Fill witness log with at least one complete chain
4. Reviewer checks T1–T4, T9 from acceptance packet
5. Sign the signoff summary

This covers the critical path. Full signoff requires all phases above.

## References

- [core-blocker-triage-template.md](core-blocker-triage-template.md) — If any check fails
- [restart-milestone-burnup.md](restart-milestone-burnup.md) — Milestone progress tracking
