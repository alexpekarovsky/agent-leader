# CORE Milestone Blocker Triage Template

Tracks blockers across CORE gates with impact assessment and escalation rules.

## Metadata

```
Operator: _______________
Date:     _______________
Milestone: AUTO-M1
```

## Blocker table

| blocker_id | affected_task | gate    | severity | %_impact | status | resolution |
|------------|---------------|---------|----------|----------|--------|------------|
|            |               | CORE-02 | low      |          | open   |            |
|            |               | CORE-03 | medium   |          | open   |            |
|            |               | CORE-04 | high     |          | open   |            |
|            |               | CORE-05 | medium   |          | open   |            |
|            |               | CORE-06 | high     |          | open   |            |

## Impact formula

```
% impact = (tasks blocked by this gate / total milestone tasks) * 100
```

Use current totals from [restart-milestone-burnup.md](restart-milestone-burnup.md).

Example: if CORE-03 blocks 8 tasks and total is 41, impact = 8/41 * 100 = 19.5%.

## Dependency chain

```
CORE-01 --> CORE-02 --> CORE-03 --> CORE-04
CORE-01 --> CORE-05 --> CORE-06
```

A blocker on an upstream gate blocks all downstream gates. Count downstream
tasks in the impact calculation.

| Gate blocked | Downstream gates also blocked | Cascading tasks |
|-------------|-------------------------------|-----------------|
| CORE-01     | CORE-02, 03, 04, 05, 06      |                 |
| CORE-02     | CORE-03, 04                   |                 |
| CORE-03     | CORE-04                       |                 |
| CORE-05     | CORE-06                       |                 |

## Escalation rules

| Condition                            | Action                       |
|--------------------------------------|------------------------------|
| severity=high AND %_impact > 5%      | Immediate operator attention |
| severity=high AND %_impact <= 5%     | Next triage cycle            |
| severity=medium AND %_impact > 10%   | Escalate to high             |
| severity=low                         | Track, resolve in order      |
| Blocker open > 24h AND high severity | Notify project lead          |

## Resolution log

| blocker_id | resolved_date | resolution_summary | verified_by |
|------------|---------------|--------------------|-------------|
|            |               |                    |             |
|            |               |                    |             |

## Signoff

```
Operator: _______________
Date:     _______________
Open high-severity blockers: ___
```

## References

- [restart-milestone-burnup.md](restart-milestone-burnup.md)
- [restart-milestone-checklist.md](restart-milestone-checklist.md)
- [current-limitations-matrix.md](current-limitations-matrix.md)
