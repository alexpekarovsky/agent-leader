# Core Milestone Evidence Index

Evidence index for CORE-02 through CORE-06. Use this to track what evidence has been collected, where it lives, and what remains pending.

## How to Use

1. For each row, run the command or locate the artifact
2. Update the Status column: `collected` (evidence captured) or `pending` (not yet gathered)
3. Add commit SHAs, test counts, or file paths in the Notes column
4. A milestone is ready for signoff when all its rows show `collected`

---

## CORE-02: Instance Registration and Status

Instance registration, status response fields, and operator FAQ.

| Core ID | Evidence Type | Location / Command | Status | Notes |
|---------|--------------|-------------------|--------|-------|
| CORE-02 | Instance registration tests | `tests/test_list_agents_instance_id.py` | pending | Verify instance_id in agent list |
| CORE-02 | Instance field snapshot tests | `tests/test_agent_instances_field_snapshots.py` | pending | Field presence and type checks |
| CORE-02 | Instance persistence tests | `tests/test_agent_instances_persistence.py` | pending | Agent data survives restart |
| CORE-02 | Instance project_root tests | `tests/test_agent_instances_project_root.py` | pending | same_project field validation |
| CORE-02 | Instance sort tests | `tests/test_agent_instances_sort.py` | pending | Agent list ordering |
| CORE-02 | Status response tests | `tests/test_status_response_additive.py` | pending | Status payload backward compat |
| CORE-02 | Status regression tests | `tests/test_core02_status_regression.py` | pending | Regression suite for CORE-02 |
| CORE-02 | Status agent identities tests | `tests/test_status_agent_identities.py` | pending | Agent identity in status output |
| CORE-02 | Status payload fixture | `tests/test_status_payload_fixture.py` | pending | Fixture-based status checks |
| CORE-02 | Instance status advanced tests | `tests/test_status_instance_advanced.py` | pending | Multi-instance status edge cases |
| CORE-02 | FAQ doc exists | `tests/test_operator_docs_fixtures.py` | pending | Operator FAQ doc test |
| CORE-02 | Test count | `python -m pytest tests/test_core02_* tests/test_agent_instances_* tests/test_status_* -v` | pending | Record pass/fail counts |
| CORE-02 | Commit SHA | `git log --oneline` | pending | SHA of CORE-02 implementation |

---

## CORE-03: Lease Schema and Claim

Lease issuance on claim, schema validation, and lease field presence.

| Core ID | Evidence Type | Location / Command | Status | Notes |
|---------|--------------|-------------------|--------|-------|
| CORE-03 | Lease invariant tests | `tests/test_core03_lease_invariants.py` | pending | Schema invariants on claim |
| CORE-03 | Lease schema test plan tests | `tests/test_lease_schema_test_plan.py` | pending | Matches lease-schema-test-plan.md |
| CORE-03 | Lease issuance schema fixture | `tests/test_lease_issuance_schema_fixture.py` | pending | Fixture: lease fields on fresh claim |
| CORE-03 | Lease transitions tests | `tests/test_lease_transitions.py` | pending | State transitions: assigned -> in_progress |
| CORE-03 | Lease claim regression tests | `tests/test_lease_claim_regression.py` | pending | Claim edge cases |
| CORE-03 | Claim override lease tests | `tests/test_claim_override_lease.py` | pending | Claim override issues lease |
| CORE-03 | Multi-instance claim tests | `tests/test_multi_instance_claim.py` | pending | Concurrent claim behavior |
| CORE-03 | Lease advanced fixtures | `tests/test_lease_advanced_fixtures.py` | pending | Extended lease field checks |
| CORE-03 | Lease ownership mismatch tests | `tests/test_lease_ownership_mismatch.py` | pending | Owner != claimer rejection |
| CORE-03 | Lease renewal contract tests | `tests/test_lease_renewal_contract.py` | pending | Renewal extends expiry |
| CORE-03 | Lease renewal identity binding | `tests/test_lease_renewal_identity_binding.py` | pending | Only owner can renew |
| CORE-03 | Lease renewal edge cases | `tests/test_lease_renewal_edge_cases.py` | pending | Renewal after expiry, double renewal |
| CORE-03 | Test count | `python -m pytest tests/test_core03_* tests/test_lease_* tests/test_claim_* -v` | pending | Record pass/fail counts |
| CORE-03 | Commit SHA | `git log --oneline` | pending | SHA of CORE-03 implementation |

---

## CORE-04: Lease Expiry and Recovery

Expired lease detection, recovery in manager cycle, requeue events.

| Core ID | Evidence Type | Location / Command | Status | Notes |
|---------|--------------|-------------------|--------|-------|
| CORE-04 | Recovery scenario tests | `tests/test_core04_recovery_scenarios.py` | pending | Manager cycle recovers expired leases |
| CORE-04 | Lease expiry requeue tests | `tests/test_lease_expiry_requeue.py` | pending | Expired lease requeues task |
| CORE-04 | Lease expiry watchdog interaction | `tests/test_lease_expiry_watchdog_interaction.py` | pending | Watchdog vs lease expiry coordination |
| CORE-04 | Lease recovery and noop tests | `tests/test_lease_recovery_and_noop.py` | pending | Recovery with noop fallback |
| CORE-04 | Lease recovery scenarios matrix | `tests/test_lease_recovery_scenarios_matrix.py` | pending | Matrix of recovery edge cases |
| CORE-04 | Lease recovery event audit | `tests/test_lease_recovery_event_audit_correlation.py` | pending | Recovery events in audit log |
| CORE-04 | Recovery no eligible worker | `tests/test_recovery_no_eligible_worker.py` | pending | Recovery when no worker available |
| CORE-04 | Recovery replacement instance | `tests/test_recovery_replacement_instance.py` | pending | New instance picks up recovered task |
| CORE-04 | Dedupe and requeue tests | `tests/test_dedupe_and_requeue.py` | pending | Deduplication after requeue |
| CORE-04 | Reassign stale tasks tests | `tests/test_reassign_stale_tasks.py` | pending | Stale task reassignment |
| CORE-04 | Watchdog JSONL entries | `.autopilot-logs/watchdog-*.jsonl` | pending | Lease expiry entries in watchdog |
| CORE-04 | Event bus requeue entries | `orchestrator_poll_events` | pending | task.requeued events on bus |
| CORE-04 | Test count | `python -m pytest tests/test_core04_* tests/test_lease_expiry_* tests/test_recovery_* -v` | pending | Record pass/fail counts |
| CORE-04 | Commit SHA | `git log --oneline` | pending | SHA of CORE-04 implementation |

---

## CORE-05: Dispatch Events and Telemetry

Dispatch event emission, audience targeting, and correlation IDs.

| Core ID | Evidence Type | Location / Command | Status | Notes |
|---------|--------------|-------------------|--------|-------|
| CORE-05 | Telemetry stub tests | `tests/test_core0506_telemetry_stubs.py` | pending | Shared CORE-05/06 telemetry stubs |
| CORE-05 | Dispatch telemetry tests | `tests/test_dispatch_telemetry.py` | pending | Telemetry fields on dispatch events |
| CORE-05 | Dispatch targeting tests | `tests/test_dispatch_targeting.py` | pending | Audience filtering on events |
| CORE-05 | Dispatch event ordering tests | `tests/test_dispatch_event_ordering.py` | pending | Event sequence correctness |
| CORE-05 | Dispatch advanced stubs | `tests/test_dispatch_advanced_stubs.py` | pending | Extended dispatch scenarios |
| CORE-05 | Dispatch command payload fixtures | `tests/test_dispatch_command_payload_fixtures.py` | pending | Payload structure validation |
| CORE-05 | Telemetry fixture pack | `tests/test_telemetry_fixture_pack.py` | pending | Fixture-based telemetry checks |
| CORE-05 | Event bus lifecycle tests | `tests/test_event_bus_lifecycle.py` | pending | Publish/poll/ack cycle |
| CORE-05 | Bus poll and wait tests | `tests/test_bus_poll_and_wait.py` | pending | Long-poll and cursor behavior |
| CORE-05 | Poll events filtering tests | `tests/test_poll_events_filtering.py` | pending | Event type and audience filters |
| CORE-05 | Audit log entries | `orchestrator_list_audit_logs(tool="orchestrator_publish_event")` | pending | Dispatch events in audit trail |
| CORE-05 | Test count | `python -m pytest tests/test_core0506_* tests/test_dispatch_* tests/test_telemetry_* -v` | pending | Record pass/fail counts |
| CORE-05 | Commit SHA | `git log --oneline` | pending | SHA of CORE-05 implementation |

---

## CORE-06: Noop Diagnostics and Integration

Noop diagnostic payloads, recovery diagnostic events, and milestone integration tests.

| Core ID | Evidence Type | Location / Command | Status | Notes |
|---------|--------------|-------------------|--------|-------|
| CORE-06 | Noop diagnostic payload tests | `tests/test_noop_diagnostic_payload.py` | pending | Noop event payload structure |
| CORE-06 | Dispatch noop schema tests | `tests/test_dispatch_noop_schema.py` | pending | Noop schema validation |
| CORE-06 | Lease recovery and noop tests | `tests/test_lease_recovery_and_noop.py` | pending | Noop emitted on recovery |
| CORE-06 | Noop correlation capture | `docs/core-06-noop-correlation-capture.md` | pending | Correlation ID capture guide |
| CORE-06 | Noop edge case tests | `docs/core-06-noop-edge-cases.md` | pending | Edge case documentation |
| CORE-06 | Milestone integration tests | `tests/test_milestone_integration.py` | pending | Cross-milestone integration |
| CORE-06 | Task lifecycle integration | `tests/test_task_lifecycle_integration.py` | pending | Full lifecycle with diagnostics |
| CORE-06 | Manager cycle logic tests | `tests/test_manager_cycle_logic.py` | pending | Manager cycle emits diagnostics |
| CORE-06 | Telemetry stub tests (shared) | `tests/test_core0506_telemetry_stubs.py` | pending | Shared with CORE-05 |
| CORE-06 | Watchdog diagnostic entries | `.autopilot-logs/watchdog-*.jsonl` | pending | Noop and diagnostic entries |
| CORE-06 | Event bus diagnostic entries | `orchestrator_poll_events` | pending | diagnostic.noop events on bus |
| CORE-06 | Audit log diagnostic entries | `orchestrator_list_audit_logs` | pending | Noop calls in audit trail |
| CORE-06 | Test count | `python -m pytest tests/test_noop_* tests/test_dispatch_noop_* tests/test_milestone_integration* -v` | pending | Record pass/fail counts |
| CORE-06 | Commit SHA | `git log --oneline` | pending | SHA of CORE-06 implementation |

---

## Completion Checklist

| Milestone | Total Evidence Rows | Collected | Pending | Ready for Signoff |
|-----------|--------------------|-----------|---------|--------------------|
| CORE-02 | 13 | 0 | 13 | No |
| CORE-03 | 14 | 0 | 14 | No |
| CORE-04 | 14 | 0 | 14 | No |
| CORE-05 | 13 | 0 | 13 | No |
| CORE-06 | 14 | 0 | 14 | No |
| **Total** | **68** | **0** | **68** | -- |

Update the counts above as evidence is collected. A milestone is ready for signoff when its Pending column reaches 0.
