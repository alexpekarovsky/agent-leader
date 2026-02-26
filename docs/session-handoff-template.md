# Session Handoff Note Template

Standard template for transferring task context between CC1/CC2/CC3 sessions to avoid duplicate work.

## Template

```
## Handoff: [CC1→CC2] TASK-xxxxxxxx

**Task**: [title]
**Status**: [in_progress | blocked | needs_review]
**Files touched**:
- path/to/file1.py (added function X)
- path/to/file2.sh (modified lines 50-75)

**What's done**:
- [Completed step 1]
- [Completed step 2]

**Next step**:
- [What the receiving session should do next]

**Risks**:
- [Uncommitted changes in file X]
- [Test Y is failing — needs investigation]
- (none)

**Git state**: [committed sha / uncommitted / stashed]
```

## Example

```
## Handoff: [CC1→CC2] TASK-4ade3c1c

**Task**: Add lease schema test plan doc
**Status**: in_progress
**Files touched**:
- docs/lease-schema-test-plan.md (created, 8 test cases written)

**What's done**:
- Lease fields table complete
- State transition diagrams complete
- Test cases T1-T6 written

**Next step**:
- Write test cases T7 (concurrent claim) and T8 (idempotent expiry)
- Commit and submit report

**Risks**:
- None — all content is in one new file

**Git state**: uncommitted
```

## Usage

1. Paste the template into the orchestrator event bus or report notes
2. Fill in all fields — don't skip "Risks" even if empty (write "none")
3. The receiving session reads the handoff before starting work

### Via event bus

```
orchestrator_publish_event(
  event_type="session.handoff",
  source="claude_code",
  payload={
    "from": "CC1",
    "to": "CC2",
    "task_id": "TASK-xxx",
    "note": "[CC1→CC2] See handoff note in report."
  }
)
```

### Via report notes

```
orchestrator_submit_report(
  task_id="TASK-xxx",
  agent="claude_code",
  status="blocked",
  notes="[CC1] Handing off to CC2. Files: docs/x.md (created). Next: add test cases T7-T8. Git: uncommitted.",
  ...
)
```

## References

- [multi-cc-conventions.md](multi-cc-conventions.md) — Session labels and etiquette
- [claim-preflight-checklist.md](claim-preflight-checklist.md) — Pre-claim checks
