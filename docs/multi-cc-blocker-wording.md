# Multi-CC Blocker Wording Library

Reusable blocker messages for common interim multi-CC issues.
Copy and fill in the placeholders (`{...}`).

## 1. Duplicate claim detected

```
Duplicate claim on {task_id}. Sessions {session_a} and {session_b} both
working on the same task. {session_keep} retains ownership; {session_drop}
should abandon and claim next task.
```

## 2. Stale claim override

```
Claim override for claude_code still points to {task_id} from a previous
session. Clear with: set_claim_override(agent="claude_code", task_id="",
source="codex") before setting the next override.
```

## 3. Unclear task ownership

```
{task_id} is in_progress but no active session claims to be working on it.
Last known session: {session_label}. Verify session status or reassign:
update_task_status(task_id="{task_id}", status="assigned", source="operator")
```

## 4. Git merge conflict between sessions

```
{session_a} and {session_b} committed conflicting changes to {file_path}.
Manual merge required before either session can continue on dependent tasks.
Resolve in git, then update task status.
```

## 5. Prerequisite doc missing

```
{task_id} requires {doc_path} which does not exist yet. Blocking until
the prerequisite doc is created by another task. Do not implement stub.
```

## 6. Queue starvation on workstream

```
Workstream {workstream} has {count} assigned tasks but no session is
working on it. Recommend rotating {session_label} from {current_stream}
to {workstream} to prevent starvation.
```

## 7. Session disconnected mid-task

```
{session_label} disconnected while working on {task_id}. Task remains
in_progress with partial work. Next session should check git log for
partial commits before resuming or reassigning.
```

## 8. Report submitted by wrong session

```
{task_id} report submitted by {session_wrong} but was assigned to
{session_expected}. Report accepted (same claude_code identity) but
traceability is degraded. Review commit SHA {sha} for correctness.
```

## 9. Override race condition

```
Two overrides set in quick succession for claude_code. {task_a} and
{task_b} may both be claimed by the same session. Clear all overrides
and re-route one task at a time.
```

## 10. Task completed but tests not run

```
{task_id} reported as done by {session_label} but test_summary shows
0 passed / 0 failed. Verify tests were actually executed. If doc-only
task, add note explaining no tests required.
```

## Usage

Raise a blocker with the appropriate wording:

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="{session_label}",
  description="[paste wording here with placeholders filled]",
  severity="medium"
)
```

## References

- [duplicate-claim-playbook.md](duplicate-claim-playbook.md) — Full incident response
- [triple-cc-rotation-policy.md](triple-cc-rotation-policy.md) — Starvation prevention
- [task-queue-hygiene.md](task-queue-hygiene.md) — Queue management
