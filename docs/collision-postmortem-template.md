# Collision Postmortem Template

Lightweight template for documenting duplicate-claim or collision incidents when running multiple Claude Code sessions under shared identity.

## Template

```
## Collision Postmortem — [DATE]

### Incident Summary
- **Type**: [duplicate-claim | git-conflict | override-race | report-collision]
- **Sessions involved**: [CC1, CC2] or [CC1, CC2, CC3]
- **Task(s) affected**: TASK-xxxxxxxx, TASK-yyyyyyyy
- **Duration**: [time from detection to resolution]

### Timeline
| Time | Session | Action |
|------|---------|--------|
| HH:MM | CC1 | [what happened first] |
| HH:MM | CC2 | [what happened next] |
| HH:MM | operator | [intervention taken] |

### Root Cause
[One sentence: why the collision occurred]

Examples:
- "Both sessions called claim_next_task simultaneously without override coordination"
- "Override was set for CC1 but CC2 claimed before CC1 could"
- "Both sessions committed to the same file without pulling first"

### Impact
- **Tasks affected**: [count and IDs]
- **Work lost**: [none | partial | full — describe what was wasted]
- **State corruption**: [none | task stuck in wrong status | duplicate reports]

### Resolution
1. [Step taken to fix]
2. [Step taken to fix]
3. [Verification done]

### Remediation
- [ ] [Action to prevent recurrence]
- [ ] [Process change or checklist update]

### Lessons
- [What we learned]
```

## Example

```
## Collision Postmortem — 2026-02-26

### Incident Summary
- **Type**: duplicate-claim
- **Sessions involved**: CC1, CC2
- **Task(s) affected**: TASK-4ade3c1c
- **Duration**: 5 minutes

### Timeline
| Time | Session | Action |
|------|---------|--------|
| 00:10 | CC1 | Called claim_next_task, got TASK-4ade3c1c |
| 00:10 | CC2 | Called claim_next_task simultaneously, got TASK-50506abf |
| 00:12 | CC2 | Realized TASK-50506abf depends on TASK-4ade3c1c (not yet done) |
| 00:13 | CC2 | Submitted TASK-50506abf as blocked |
| 00:15 | operator | Cleared claim state, CC2 waited for CC1 to finish |

### Root Cause
Both sessions claimed without checking in_progress tasks first.

### Impact
- **Tasks affected**: 1 (TASK-50506abf blocked temporarily)
- **Work lost**: None — CC2 detected dependency before starting
- **State corruption**: None

### Resolution
1. CC2 submitted blocked report
2. CC1 finished TASK-4ade3c1c
3. CC2 re-claimed and completed TASK-50506abf

### Remediation
- [x] Added claim preflight checklist to docs
- [x] Both sessions now check in_progress before claiming

### Lessons
- Always run claim preflight checks with 2+ sessions
```

## When to Write a Postmortem

| Incident severity | Write postmortem? |
|-------------------|-------------------|
| Task blocked for <5 min, no work lost | Optional — quick note is enough |
| Task blocked for >15 min or work was duplicated | Yes |
| Git conflict requiring manual merge | Yes |
| State corruption from collision | Yes — include recovery steps |
| Override race with no impact | No |

## References

- [claim-preflight-checklist.md](claim-preflight-checklist.md) — Prevention checks
- [multi-cc-conventions.md](multi-cc-conventions.md) — Session labels and etiquette
- [session-handoff-template.md](session-handoff-template.md) — Context transfer between sessions
