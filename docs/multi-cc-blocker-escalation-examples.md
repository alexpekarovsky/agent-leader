# Multi-CC Blocker Escalation Examples by Severity

Reusable blocker examples mapped to low/medium/high severity with
recommended next actions for interim multi-CC operation.

## Low severity

Issues that do not block work but should be tracked.

### Example 1: Session label mismatch in report

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="{session_label}",
  description="Report on {task_id} submitted without session label in notes. Traceability degraded but task is complete. Add label retroactively.",
  severity="low"
)
```

**Next action:** Add session label to report notes. No work blocked.

### Example 2: Override set but not yet consumed

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="{session_label}",
  description="Claim override for {agent} set to {task_id} but worker has not yet claimed. Override may be stale if session restarted.",
  severity="low"
)
```

**Next action:** Verify worker is alive; clear override if session restarted.

### Example 3: Workstream imbalance detected

```
orchestrator_raise_blocker(
  task_id="",
  source="{session_label}",
  description="Workstream {workstream} has {count} assigned tasks with no active session. Consider rotating {idle_session} from {current_stream}.",
  severity="low"
)
```

**Next action:** Rotate an idle session to the starved workstream.

## Medium severity

Issues that may block one session but other sessions can continue.

### Example 4: Duplicate claim detected

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="{session_label}",
  description="Duplicate claim on {task_id}. Sessions {session_a} and {session_b} both working. {session_keep} retains ownership; {session_drop} should abandon and reclaim.",
  severity="medium"
)
```

**Next action:** Notify the dropping session immediately. Review partitioning strategy.

### Example 5: Git merge conflict between sessions

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="{session_label}",
  description="Sessions {session_a} and {session_b} committed conflicting changes to {file_path}. Manual merge required before dependent tasks proceed.",
  severity="medium"
)
```

**Next action:** Operator resolves conflict in git. Both sessions pause dependent work on that file.

### Example 6: Prerequisite doc missing

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="{session_label}",
  description="{task_id} requires {doc_path} which does not exist yet. Blocking until prerequisite is created.",
  severity="medium"
)
```

**Next action:** Check if another task creates the prerequisite. If not, create a new task for it.

### Example 7: Worker disconnected mid-task

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="operator",
  description="{session_label} disconnected while working on {task_id}. Task in_progress with possible partial commits. Check git log before resuming.",
  severity="medium"
)
```

**Next action:** Check `git log` for partial work. Reassign task if session will not reconnect.

## High severity

Issues that block multiple sessions or risk data loss.

### Example 8: State file corruption

```
orchestrator_raise_blocker(
  task_id="",
  source="operator",
  description="State file corruption detected by watchdog. All sessions should pause claims until state is verified. Back up .orchestrator/ immediately.",
  severity="high"
)
```

**Next action:** Stop all workers. Back up state files. Investigate watchdog JSONL for details. Restart after fix.

### Example 9: Override race condition

```
orchestrator_raise_blocker(
  task_id="{task_id}",
  source="operator",
  description="Two overrides set in quick succession for {agent}. Tasks {task_a} and {task_b} may both be claimed by same session. Clear all overrides and re-route one at a time.",
  severity="high"
)
```

**Next action:** Clear all overrides. Set one override, wait for claim, then set next.

### Example 10: Supervisor crash loop affecting all workers

```
orchestrator_raise_blocker(
  task_id="",
  source="operator",
  description="Supervisor crash loop detected: {process} restarted {count} times in {window}. All dependent workers affected. Investigate root cause before restarting.",
  severity="high"
)
```

**Next action:** Check supervisor logs. Fix root cause (CLI path, API key, state corruption). Only restart after fix confirmed.

## Severity decision guide

| Condition | Severity | Rationale |
|-----------|----------|-----------|
| One session's traceability degraded | low | Work continues, fix later |
| One session blocked, others continue | medium | Partial impact, needs attention |
| Two sessions conflicting on same resource | medium | Manual resolution needed |
| Prerequisite missing for one task | medium | Other tasks unaffected |
| All sessions must pause | high | Full stop required |
| Data loss or corruption risk | high | Immediate intervention |

## References

- [multi-cc-blocker-wording.md](multi-cc-blocker-wording.md) -- Full blocker message library
- [duplicate-claim-playbook.md](duplicate-claim-playbook.md) -- Collision incident response
- [triple-cc-rotation-policy.md](triple-cc-rotation-policy.md) -- Starvation prevention
- [supervisor-crash-loop-runbook.md](supervisor-crash-loop-runbook.md) -- Crash loop diagnosis
