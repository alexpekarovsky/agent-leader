# CORE Evidence Review Checklist

> Structured reviewer checklist for validating CORE milestone evidence.
> Use as a meeting agenda or async review workflow.

---

## 1. Pre-Review

Gather all materials before starting the per-CORE review.

| # | Item | Pass | Fail | Notes |
|---|------|------|------|-------|
| 1.1 | Evidence index available (`core-milestone-evidence-index.md` or equivalent) | [ ] | [ ] | |
| 1.2 | Test results collected for all in-scope COREs | [ ] | [ ] | |
| 1.3 | Commit list assembled (SHAs with descriptions) | [ ] | [ ] | |
| 1.4 | Task IDs mapped to CORE items | [ ] | [ ] | |
| 1.5 | Previous review notes addressed (if re-review) | [ ] | [ ] | |
| 1.6 | Blocker list current (`orchestrator_list_blockers`) | [ ] | [ ] | |

**Pre-review decision:** Proceed / Postpone (reason: _________)

---

## 2. Per-CORE Review

### 2.1 CORE-02: Instance-Aware Status

| # | Check | Pass | Fail | Evidence |
|---|-------|------|------|----------|
| 2.1.1 | Agent registration creates unique `instance_id` | [ ] | [ ] | |
| 2.1.2 | Identity verification via `connect_to_leader` works | [ ] | [ ] | |
| 2.1.3 | Heartbeat updates `last_seen` timestamp | [ ] | [ ] | |
| 2.1.4 | Stale detection triggers after `heartbeat_timeout_minutes` | [ ] | [ ] | |
| 2.1.5 | `list_agents` returns correct active/stale/offline status | [ ] | [ ] | |
| 2.1.6 | All CORE-02 tests pass (count: __ passed / __ failed) | [ ] | [ ] | |
| 2.1.7 | No regressions from previous acceptance | [ ] | [ ] | |

**CORE-02 decision:** Accept / Defer / Reject
**Notes:** ___________

---

### 2.2 CORE-03: Lease Schema

| # | Check | Pass | Fail | Evidence |
|---|-------|------|------|----------|
| 2.2.1 | Claiming a task creates a lease with correct fields | [ ] | [ ] | |
| 2.2.2 | `lease_id` is unique per issuance | [ ] | [ ] | |
| 2.2.3 | `expires_at` computed correctly from `issued_at + ttl_seconds` | [ ] | [ ] | |
| 2.2.4 | Lease renewal updates `renewed_at` and `expires_at` | [ ] | [ ] | |
| 2.2.5 | `attempt_index` increments on re-lease | [ ] | [ ] | |
| 2.2.6 | All CORE-03 tests pass (count: __ passed / __ failed) | [ ] | [ ] | |
| 2.2.7 | No regressions in CORE-02 after CORE-03 changes | [ ] | [ ] | |

**CORE-03 decision:** Accept / Defer / Reject
**Notes:** ___________

---

### 2.3 CORE-04: Lease Expiry Recovery

| # | Check | Pass | Fail | Evidence |
|---|-------|------|------|----------|
| 2.3.1 | Manager cycle detects expired leases | [ ] | [ ] | |
| 2.3.2 | Expired tasks requeued to `assigned` status | [ ] | [ ] | |
| 2.3.3 | `attempt_index` incremented on requeue | [ ] | [ ] | |
| 2.3.4 | Idempotent: double-run does not double-requeue | [ ] | [ ] | |
| 2.3.5 | Requeued tasks claimable by other agents | [ ] | [ ] | |
| 2.3.6 | All CORE-04 tests pass (count: __ passed / __ failed) | [ ] | [ ] | |
| 2.3.7 | No regressions in CORE-02 or CORE-03 | [ ] | [ ] | |

**CORE-04 decision:** Accept / Defer / Reject
**Notes:** ___________

---

### 2.4 CORE-05: Dispatch Telemetry

| # | Check | Pass | Fail | Evidence |
|---|-------|------|------|----------|
| 2.4.1 | `dispatch.command` events include `correlation_id` and `target` | [ ] | [ ] | |
| 2.4.2 | `dispatch.ack` echoes correct `correlation_id` | [ ] | [ ] | |
| 2.4.3 | Audience filtering delivers events only to targeted agents | [ ] | [ ] | |
| 2.4.4 | Timeout triggers noop when ack is missing | [ ] | [ ] | |
| 2.4.5 | Event bus cursor advances correctly after polling | [ ] | [ ] | |
| 2.4.6 | All CORE-05 tests pass (count: __ passed / __ failed) | [ ] | [ ] | |
| 2.4.7 | No regressions in CORE-02 | [ ] | [ ] | |

**CORE-05 decision:** Accept / Defer / Reject
**Notes:** ___________

---

### 2.5 CORE-06: Noop Diagnostics

| # | Check | Pass | Fail | Evidence |
|---|-------|------|------|----------|
| 2.5.1 | `dispatch.noop` generated on ack timeout | [ ] | [ ] | |
| 2.5.2 | Noop includes `correlation_id`, `reason`, `elapsed_seconds` | [ ] | [ ] | |
| 2.5.3 | Consecutive noop detection triggers stale-agent warning | [ ] | [ ] | |
| 2.5.4 | Noop events visible in `poll_events` for manager | [ ] | [ ] | |
| 2.5.5 | Diagnostic metadata sufficient for root-cause analysis | [ ] | [ ] | |
| 2.5.6 | All CORE-06 tests pass (count: __ passed / __ failed) | [ ] | [ ] | |
| 2.5.7 | No regressions in CORE-02 or CORE-05 | [ ] | [ ] | |

**CORE-06 decision:** Accept / Defer / Reject
**Notes:** ___________

---

## 3. Cross-CORE Review

| # | Check | Pass | Fail | Notes |
|---|-------|------|------|-------|
| 3.1 | Lease track dependency chain verified (02 -> 03 -> 04) | [ ] | [ ] | |
| 3.2 | Dispatch track dependency chain verified (02 -> 05 -> 06) | [ ] | [ ] | |
| 3.3 | Integration tests pass across all accepted COREs | [ ] | [ ] | |
| 3.4 | No shared-state conflicts between lease and dispatch tracks | [ ] | [ ] | |
| 3.5 | Full regression suite green (count: __ passed / __ failed) | [ ] | [ ] | |
| 3.6 | Manager cycle runs cleanly with all CORE features active | [ ] | [ ] | |

---

## 4. Sign-Off

| Field | Value |
|-------|-------|
| **Review date** | ___________ |
| **Reviewer** | ___________ |
| **COREs reviewed** | ___________ |
| **Decision** | Accept all / Accept partial / Defer / Reject |
| **COREs accepted** | ___________ |
| **COREs deferred** | ___________ (reason: ___________) |
| **COREs rejected** | ___________ (reason: ___________) |
| **Milestone % after review** | ___% (_/6 done) |
| **Regressions found** | ___________ |
| **Next actions** | ___________ |
| **Next review date** | ___________ |

---

## Quick Decision Guide

| Condition | Decision |
|-----------|----------|
| All checks pass, no regressions | **Accept** |
| Minor issue, fixable in <1 hour | **Defer** with fix instructions |
| Test failures in CORE scope | **Defer** until tests pass |
| Regression in upstream CORE | **Reject** -- fix regression first |
| Missing evidence | **Defer** -- gather evidence and re-review |
| Fundamental design issue | **Reject** with detailed feedback |
