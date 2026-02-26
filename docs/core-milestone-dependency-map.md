# CORE Milestone Dependency Map

Critical path and dependency relationships across CORE-02 through
CORE-06. Use this map to plan execution order, identify blockers,
and understand which milestones can proceed in parallel.

---

## Dependency Overview

```
                      CORE-02
                 Instance-Aware Status
                    (foundation)
                    /          \
                   /            \
                  v              v
             CORE-03          CORE-05
          Lease Schema     Dispatch Telemetry
               |                 |
               v                 v
             CORE-04          CORE-06
        Lease Expiry       Noop Diagnostics
          Recovery
```

CORE-02 is the foundation with no external dependencies. It feeds
two independent tracks that can execute in parallel once CORE-02
is accepted.

---

## Dependency Table

| CORE ID | Title | Depends on | Reason |
|---------|-------|------------|--------|
| CORE-02 | Instance-Aware Status | (none) | Foundation milestone. Introduces `instance_id`, agent status, and identity verification. |
| CORE-03 | Lease Schema | CORE-02 | Lease records require `owner_instance_id`, which is the `instance_id` from CORE-02. Without instance-aware identity, leases cannot be tied to specific agent instances. |
| CORE-04 | Lease Expiry Recovery | CORE-03 | Recovery scans for expired lease records. Those records must exist (from CORE-03) before expiry detection and requeue logic can operate. |
| CORE-05 | Dispatch Telemetry | CORE-02 | Dispatch commands target agents by `instance_id`. Audience filtering relies on instance-aware identity to route events to the correct agent. |
| CORE-06 | Noop Diagnostics | CORE-05 | Noop events are generated when dispatch commands time out. The dispatch event flow (command/ack) must exist before noop detection can be built on top. |

---

## Critical Paths

There are two critical paths through the CORE milestones:

### Lease Track

```
CORE-02  ───►  CORE-03  ───►  CORE-04
  (02)           (03)           (04)
```

- **CORE-02 -> CORE-03**: Lease schema needs `instance_id` for
  `owner_instance_id`. Cannot define lease records without
  instance-aware identity.
- **CORE-03 -> CORE-04**: Expiry recovery needs lease records to
  exist in the task store. Cannot scan for expired leases if leases
  are not issued.

### Dispatch Track

```
CORE-02  ───►  CORE-05  ───►  CORE-06
  (02)           (05)           (06)
```

- **CORE-02 -> CORE-05**: Dispatch commands use `instance_id` as the
  `target` field. Audience filtering requires knowing which agent
  identities are valid.
- **CORE-05 -> CORE-06**: Noop diagnostics fire when `dispatch.command`
  events go unacknowledged. The command/ack flow must exist before
  noop detection can be layered on.

---

## Full ASCII Diagram

```
Timeline ──────────────────────────────────────────────────►

Phase 1              Phase 2                    Phase 3
(Foundation)         (Schema + Telemetry)       (Recovery + Diagnostics)

┌──────────┐
│ CORE-02  │
│ Instance │
│  Status  │
└────┬─────┘
     │
     ├─────────────┐
     │             │
     v             v
┌──────────┐  ┌──────────┐
│ CORE-03  │  │ CORE-05  │     ◄── these two run in parallel
│  Lease   │  │ Dispatch │
│  Schema  │  │ Telemetry│
└────┬─────┘  └────┬─────┘
     │             │
     v             v
┌──────────┐  ┌──────────┐
│ CORE-04  │  │ CORE-06  │     ◄── these two run in parallel
│  Lease   │  │   Noop   │
│ Recovery │  │  Diag.   │
└──────────┘  └──────────┘
```

---

## Parallel Execution Windows

| Phase | Milestones | Can run in parallel? | Notes |
|-------|------------|---------------------|-------|
| Phase 1 | CORE-02 | N/A (single item) | Must complete before anything else starts. |
| Phase 2 | CORE-03, CORE-05 | Yes | No dependency between lease schema and dispatch telemetry. Assign to separate agents if available. |
| Phase 3 | CORE-04, CORE-06 | Yes | No dependency between lease recovery and noop diagnostics. Assign to separate agents if available. |

**Minimum sequential phases:** 3 (one per row in the diagram above).

**Maximum parallelism:** 2 milestones per phase in Phases 2 and 3.

---

## Blocker Implications

If a milestone is blocked, the following downstream work is affected:

| Blocked milestone | Downstream impact |
|-------------------|-------------------|
| CORE-02 | Everything. All other CORE milestones are blocked. |
| CORE-03 | CORE-04 is blocked. Dispatch track (CORE-05, CORE-06) is unaffected. |
| CORE-04 | No downstream CORE dependencies. Lease track is fully blocked at its terminal node. |
| CORE-05 | CORE-06 is blocked. Lease track (CORE-03, CORE-04) is unaffected. |
| CORE-06 | No downstream CORE dependencies. Dispatch track is fully blocked at its terminal node. |

---

## Operator Checklist

Use this to verify readiness before starting each milestone:

- [ ] **Before CORE-03**: Confirm CORE-02 is accepted. Verify `instance_id` is
      available in `orchestrator_list_agents` output.
- [ ] **Before CORE-04**: Confirm CORE-03 is accepted. Verify lease records are
      created on `orchestrator_claim_next_task`.
- [ ] **Before CORE-05**: Confirm CORE-02 is accepted. Verify `instance_id` is
      available for dispatch `target` field.
- [ ] **Before CORE-06**: Confirm CORE-05 is accepted. Verify `dispatch.command`
      and `dispatch.ack` events flow correctly on the event bus.
