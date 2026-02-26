# CORE Milestone Blocker Impact Scoring Template

Scoring template to rank blockers by impact on AUTO-M1 milestone
progress and critical-path delay.

## Scoring dimensions

Each blocker is scored on two dimensions:

### Dimension 1: Milestone % impact

How much of the milestone is at risk if this blocker is not resolved.

| Score | % at risk | Label |
|-------|-----------|-------|
| 1 | 0-15% | Low |
| 2 | 16-35% | Medium |
| 3 | 36-50% | High |
| 4 | 51-100% | Critical |

### Dimension 2: Critical-path delay

How many CORE tasks are sequentially blocked (depth of dependency chain).

| Score | Chain depth | Label |
|-------|------------|-------|
| 1 | 1 task only | Isolated |
| 2 | 2 tasks | Short chain |
| 3 | 3-4 tasks | Long chain |
| 4 | 5+ tasks | Full chain |

### Combined score

```
Impact score = % impact score + critical-path score
```

| Combined | Priority | Action |
|----------|----------|--------|
| 2-3 | P3 | Track, resolve in normal flow |
| 4-5 | P2 | Assign owner, resolve this sprint |
| 6-7 | P1 | Escalate immediately, resolve today |
| 8 | P0 | Stop all other work, fix first |

## Scoring worksheet

| # | Blocker | CORE task | % impact | % score | Chain depth | Path score | Combined | Priority |
|---|---------|-----------|----------|---------|-------------|------------|----------|----------|
| 1 | | CORE-__ | | | | | | P_ |
| 2 | | CORE-__ | | | | | | P_ |
| 3 | | CORE-__ | | | | | | P_ |

## CORE task % weights (reference)

| CORE task | Weight | Cumulative downstream |
|-----------|--------|----------------------|
| CORE-01 | 20% | 100% (blocks all) |
| CORE-02 | 15% | 80% (blocks 03-06) |
| CORE-03 | 20% | 35% (blocks 04) |
| CORE-04 | 15% | 15% (leaf) |
| CORE-05 | 15% | 30% (blocks 06) |
| CORE-06 | 15% | 15% (leaf) |

## Current milestone thresholds

| Threshold | Meaning |
|-----------|---------|
| 17% | Current baseline (docs + tests only) |
| 35% | CORE-01 + CORE-02 implemented |
| 55% | + CORE-03 implemented |
| 70% | + CORE-04 + CORE-05 implemented |
| 85% | + CORE-06 implemented |
| 100% | All CORE tasks verified + evidence collected |

## Priority ranking

Sort blockers by combined score (highest first):

| Rank | Blocker | Combined score | Priority | Owner | ETA |
|------|---------|---------------|----------|-------|-----|
| 1 | | | P_ | | |
| 2 | | | P_ | | |
| 3 | | | P_ | | |

## Decision

- [ ] All P0/P1 blockers have owners
- [ ] No P0 blockers exist (or are being actively fixed)
- [ ] Next milestone threshold is achievable given current blockers

**Milestone risk level:** LOW / MEDIUM / HIGH / CRITICAL

## References

- [core-milestone-blocker-triage.md](core-milestone-blocker-triage.md) -- Dependency gate map
- [roadmap.md](roadmap.md) -- Phase architecture
- [milestone-communication-template.md](milestone-communication-template.md) -- Progress reporting
