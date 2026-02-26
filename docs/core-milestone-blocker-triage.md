# CORE Milestone Blocker Triage Template

Template for triaging blockers against CORE-02..06 dependency gates
and assessing milestone percentage impact.

## Active blockers

Fill one row per open blocker:

| # | Blocker ID | Description | Blocking CORE task | Severity | % impact | Owner |
|---|-----------|-------------|-------------------|----------|----------|-------|
| 1 | | | CORE-__ | low/med/high | | |
| 2 | | | CORE-__ | low/med/high | | |
| 3 | | | CORE-__ | low/med/high | | |

## CORE dependency gate map

Each CORE task and what it blocks downstream:

```
CORE-01 (instance_id support)
  └── CORE-02 (instance-aware status)
       └── CORE-03 (lease issuance) ── requires instance_id for owner
            └── CORE-04 (lease expiry recovery) ── requires lease schema
       └── CORE-05 (dispatch telemetry) ── requires instance-aware routing
            └── CORE-06 (noop diagnostic) ── requires dispatch correlation
```

### Impact weights

| CORE task | Weight | Rationale |
|-----------|--------|-----------|
| CORE-01 | 20% | Foundation: everything depends on instance_id |
| CORE-02 | 15% | Operator visibility: multi-session tracking |
| CORE-03 | 20% | Task safety: lease prevents duplicate work |
| CORE-04 | 15% | Recovery: stale tasks auto-requeue |
| CORE-05 | 15% | Observability: dispatch traceability |
| CORE-06 | 15% | Diagnostics: timeout visibility |

## Blocker-to-gate mapping

For each blocker, identify which gates are affected:

| Blocker | Direct gate | Cascading gates | Total % at risk |
|---------|-------------|-----------------|-----------------|
| | CORE-__ | CORE-__, CORE-__ | |
| | CORE-__ | | |

## Percent impact calculation

```
% impact = sum of weights for all gates blocked (direct + cascading)
```

### Example

If CORE-01 is blocked:
- Direct: CORE-01 (20%)
- Cascading: CORE-02 (15%) + CORE-03 (20%) + CORE-04 (15%) + CORE-05 (15%) + CORE-06 (15%)
- Total: 100% at risk

If CORE-03 is blocked:
- Direct: CORE-03 (20%)
- Cascading: CORE-04 (15%)
- Total: 35% at risk

## Triage priority

Sort blockers by total % impact descending:

| Priority | Blocker | Total % at risk | Action |
|----------|---------|-----------------|--------|
| P1 | | | |
| P2 | | | |
| P3 | | | |

## Resolution tracking

| Blocker | Status | Assigned to | ETA | Resolution notes |
|---------|--------|-------------|-----|-----------------|
| | open/investigating/resolved | | | |
| | | | | |

## Milestone health summary

```
Total CORE tasks: 6
Gates clear: ___ / 6
Gates blocked: ___ / 6
Milestone % at risk: ___%
Milestone % confirmed: ___%
```

## Decision

- [ ] All P1 blockers have owners and ETAs
- [ ] No cascading blocker affects >50% of milestone
- [ ] Milestone % confirmed >= 70% (GO threshold)

**Status:** ON TRACK / AT RISK / BLOCKED

## References

- [roadmap.md](roadmap.md) -- Phase architecture and CORE task definitions
- [restart-milestone-checklist.md](restart-milestone-checklist.md) -- Milestone verification
- [milestone-communication-template.md](milestone-communication-template.md) -- Progress reporting
- [supervisor-known-limitations.md](supervisor-known-limitations.md) -- Known gaps
