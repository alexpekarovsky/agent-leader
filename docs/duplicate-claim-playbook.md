# Duplicate-Claim Incident Response Playbook

How to detect and resolve duplicate task claims when multiple Claude
Code sessions share one `claude_code` identity (pre-instance-aware
mode).

## Background

In the current MVP, all Claude Code sessions register as `claude_code`.
The orchestrator's atomic `claim_next_task` prevents two sessions from
claiming the exact same task simultaneously.  However, race conditions
can occur with `set_claim_override` or when sessions retry claims in
quick succession.

## Detection

### Symptoms

| Symptom | Likely cause |
|---------|-------------|
| Two sessions report working on the same task | Override was not cleared after first claim |
| `submit_report` returns validation error | Another session already submitted for this task |
| Task shows unexpected `commit_sha` in report | Different session completed the task |
| Manager validation finds conflicting artifacts | Two sessions edited the same files |

### Verification

```
# Check who owns what
orchestrator_list_tasks(status="in_progress")

# Look for duplicate task IDs across session logs
# If the same TASK-xxx appears in two session transcripts, it's a duplicate claim
```

## Response steps

### Step 1: Identify the duplicate

Determine which task is affected and which sessions are involved:

```
orchestrator_list_tasks(status="in_progress")
```

Look for tasks where two sessions believe they are the owner.

### Step 2: Decide which session keeps the task

Pick the session that has made more progress.  The other session
should abandon its work on this task.

### Step 3: Notify the abandoning session

Publish a correction event:

```
orchestrator_publish_event(
  type="manager.correction",
  source="codex",
  payload={
    "action": "duplicate_claim_resolved",
    "task_id": "TASK-xxx",
    "kept_by": "CC1",
    "abandoned_by": "CC2",
    "reason": "Duplicate claim due to override race. CC1 has more progress.",
    "instruction": "CC2: stop work on TASK-xxx and claim next available task."
  }
)
```

### Step 4: Raise a blocker if work conflicts

If both sessions committed changes to the same files:

```
orchestrator_raise_blocker(
  task_id="TASK-xxx",
  source="operator",
  description="Duplicate claim produced conflicting commits. Manual merge needed.",
  severity="high"
)
```

Resolve the git conflict manually, then clear the blocker:

```
orchestrator_resolve_blocker(
  blocker_id="BLOCKER-xxx",
  source="operator",
  resolution="Merged conflicting changes. CC1 commit retained."
)
```

### Step 5: Clear the claim override

Prevent the same race from recurring:

```
orchestrator_set_claim_override(
  agent="claude_code",
  task_id="",
  source="operator"
)
```

### Step 6: Redirect the abandoned session

Set a new override for the session that needs a fresh task:

```
orchestrator_set_claim_override(
  agent="claude_code",
  task_id="TASK-next",
  source="operator"
)
```

Or let the session call `claim_next_task` normally.

### Step 7: Verify resolution

```
# Task should have exactly one in-progress owner
orchestrator_list_tasks(status="in_progress")

# No duplicate reports pending
orchestrator_list_tasks(status="reported")

# Override cleared
# (No direct way to check; rely on next claim behavior)
```

## Prevention

### Before starting multi-CC operation

- [ ] Clear all existing claim overrides
- [ ] Assign tasks to sessions via overrides one at a time
- [ ] Clear each override immediately after the target session claims

### During operation

- [ ] Never set two overrides for `claude_code` in quick succession
- [ ] Monitor `in_progress` task list for unexpected entries
- [ ] Use session labels ([CC1]/[CC2]/[CC3]) in report notes for traceability

### Claim override protocol

```
# 1. Set override for CC1's task
set_claim_override(agent="claude_code", task_id="TASK-aaa", source="codex")

# 2. Wait for CC1 to claim
# 3. Clear override
set_claim_override(agent="claude_code", task_id="", source="codex")

# 4. Now set override for CC2's task
set_claim_override(agent="claude_code", task_id="TASK-bbb", source="codex")

# 5. Wait for CC2 to claim
# 6. Clear override
set_claim_override(agent="claude_code", task_id="", source="codex")
```

## Blocker wording examples

For different severity levels:

**High (conflicting changes):**
```
Duplicate claim on TASK-xxx produced conflicting git commits.
CC1 commit: abc123 (supervisor lifecycle tests)
CC2 commit: def456 (supervisor lifecycle tests — different approach)
Manual merge required before validation can proceed.
```

**Medium (wasted work):**
```
Duplicate claim on TASK-xxx. CC2 completed work that CC1 already
submitted. CC2's work is redundant. No conflict but wasted effort.
Recommend tighter override protocol.
```

**Low (caught early):**
```
Duplicate claim detected on TASK-xxx before either session made
significant progress. CC2 redirected to TASK-yyy. No work lost.
```

## References

- [dual-cc-operation.md](dual-cc-operation.md) — Multi-session collision avoidance
- [multi-cc-partition-templates.md](multi-cc-partition-templates.md) — Session labeling conventions
- [task-queue-hygiene.md](task-queue-hygiene.md) — Override management and cleanup
- [queue-hygiene-checker.md](queue-hygiene-checker.md) — Bulk rollback procedure
