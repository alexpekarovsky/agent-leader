# Multi-CC Collision Reporting Templates

Copy-paste templates for raising blockers and writing report notes during dual Claude Code operation.

## Blocker templates

### Duplicate claim detected

```
orchestrator_raise_blocker(
  task_id="{TASK_ID}",
  agent="claude_code",
  question="[{SESSION}] Duplicate claim detected. Both CC1 and CC2 appear to be working on {TASK_ID}. Which session should keep the task?",
  severity="high",
  options=["CC1 keeps task, CC2 drops it", "CC2 keeps task, CC1 drops it"]
)
```

### Git conflict between sessions

```
orchestrator_raise_blocker(
  task_id="{TASK_ID}",
  agent="claude_code",
  question="[{SESSION}] Git conflict in {FILE_PATH} between CC1 and CC2 commits. Need decision on which version to keep.",
  severity="medium",
  options=["Keep CC1 version", "Keep CC2 version", "Merge manually"]
)
```

### Task ownership unclear

```
orchestrator_raise_blocker(
  task_id="{TASK_ID}",
  agent="claude_code",
  question="[{SESSION}] {TASK_ID} has been in_progress for {MINUTES} min with no recent log activity. Is the other session still working on it, or should it be reassigned?",
  severity="medium",
  options=["Wait longer", "Reassign to me", "Cancel and re-create"]
)
```

### Missing dependency / prerequisite doc

```
orchestrator_raise_blocker(
  task_id="{TASK_ID}",
  agent="claude_code",
  question="[{SESSION}] {TASK_ID} requires {DEPENDENCY} which does not exist yet. Should I (A) create it first, or (B) skip this task?",
  severity="medium",
  options=["A: Create dependency first", "B: Skip and claim next task"]
)
```

### Worker stuck / CLI hung

```
orchestrator_raise_blocker(
  task_id="{TASK_ID}",
  agent="claude_code",
  question="[{SESSION}] Worker appears stuck on {TASK_ID}. CLI has not produced output for {MINUTES} min. Restart the worker loop?",
  severity="high"
)
```

## Report note templates

### Standard completion

```
[{SESSION}] Implemented {BRIEF_DESCRIPTION}. {TEST_COUNT} tests pass.
```

### Completion with caveat

```
[{SESSION}] Completed {TASK_ID}. Note: {CAVEAT}. Tests pass.
```

### Blocked → resolved → completed

```
[{SESSION}] Was blocked on {BLOCKER_REASON}. Resolved by {RESOLUTION}. Implementation complete. Tests pass.
```

### Doc-only task

```
[{SESSION}] Created {DOC_PATH} covering {TOPICS}. No executable tests (documentation task).
```

### Skipped / dropped task

```
[{SESSION}] Dropping {TASK_ID}: {REASON}. No changes committed.
```

## Placeholder reference

| Placeholder | Replace with |
|-------------|-------------|
| `{SESSION}` | `CC1` or `CC2` (or `CC-backend`, `CC-docs`, etc.) |
| `{TASK_ID}` | The task ID, e.g., `TASK-abc123` |
| `{FILE_PATH}` | Path to the conflicting file |
| `{MINUTES}` | Duration in minutes |
| `{DEPENDENCY}` | Missing file, doc, or feature |
| `{BRIEF_DESCRIPTION}` | One-line summary of what was done |
| `{TEST_COUNT}` | Number of passing tests |
| `{CAVEAT}` | Known limitation or follow-up needed |
| `{BLOCKER_REASON}` | What caused the block |
| `{RESOLUTION}` | How the blocker was resolved |
| `{DOC_PATH}` | Path to the created document |
| `{TOPICS}` | Brief list of topics covered |
| `{REASON}` | Why the task was skipped |

## References

- [dual-cc-conventions.md](dual-cc-conventions.md) — Session labeling and report note prefixes
- [multi-cc-escalation-ladder.md](multi-cc-escalation-ladder.md) — When to use blockers vs events
