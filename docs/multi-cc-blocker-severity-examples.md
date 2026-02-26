# Multi-CC Blocker Severity Examples

Concrete examples for each severity level with `orchestrator_raise_blocker`
calls and recommended next actions.

## Low severity

### Worker idle (no tasks)

```python
orchestrator_raise_blocker(
  task_id="TASK-current", agent="claude_code",
  question="[CC2] No claimable tasks in queue. Should I wait or create new tasks?",
  severity="low", options=["Wait for manager to create tasks", "Create tasks from backlog"])
```
**Next action:** Wait. Check `orchestrator_list_tasks(status="assigned")` periodically.

### Minor doc conflict

```python
orchestrator_raise_blocker(
  task_id="TASK-doc456", agent="claude_code",
  question="[CC1] Minor merge conflict in docs/session-handoff-template.md. Can resolve by accepting incoming.",
  severity="low", options=["Accept incoming changes", "Keep my version", "Merge manually"])
```
**Next action:** Accept incoming, recommit, continue.

### Cosmetic log noise

```python
orchestrator_raise_blocker(
  task_id="TASK-ops789", agent="claude_code",
  question="[CC1] Repeated '[WARN] heartbeat overwrite' in logs. Expected with shared identity?",
  severity="low", options=["Expected, ignore", "Investigate further"])
```
**Next action:** Note and ignore. Known limitation until instance_id support.

## Medium severity

Issues that may block progress if not resolved within 15 minutes.

### Unclear task ownership (>15 min)

```python
orchestrator_raise_blocker(
  task_id="TASK-abc123", agent="claude_code",
  question="[CC2] TASK-abc123 in_progress 20 min with no log activity. Is CC1 still working on it?",
  severity="medium", options=["CC1 is working, wait", "Reassign to CC2", "Cancel and re-create"])
```
**Next action:** Check worker logs for activity. If none, reassign.

### Claim override conflict

```python
orchestrator_raise_blocker(
  task_id="TASK-def456", agent="claude_code",
  question="[CC1] Set claim override for TASK-def456 but CC2 claimed it first. Override was overwritten.",
  severity="medium", options=["Let CC2 finish it", "Reset to assigned and re-override for CC1"])
```
**Next action:** If CC2 has not started real work, reset and re-override. Otherwise let CC2 finish.

### Git conflict in docs

```python
orchestrator_raise_blocker(
  task_id="TASK-ghi789", agent="claude_code",
  question="[CC1] Git conflict in docs/operator-runbook.md between CC1 and CC2 commits.",
  severity="medium", options=["Keep CC1 version", "Keep CC2 version", "Merge both sections"])
```
**Next action:** Merge manually; docs rarely have semantic conflicts.

## High severity

Issues that block progress and require immediate operator attention.

### Duplicate claim confirmed

```python
orchestrator_raise_blocker(
  task_id="TASK-dup001", agent="claude_code",
  question="[CC1] Duplicate claim confirmed: CC1 and CC2 both working on TASK-dup001. Which keeps it?",
  severity="high", options=["CC1 keeps, CC2 abandons", "CC2 keeps, CC1 abandons"])
```
**Next action:** Stop one session. Document with [duplicate-claim timeline](multi-cc-duplicate-claim-timeline.md).

### Worker stuck / hung

```python
orchestrator_raise_blocker(
  task_id="TASK-stuck01", agent="claude_code",
  question="[CC2] Worker PID alive but no output for 30+ min on TASK-stuck01. CLI appears hung.",
  severity="high", options=["Kill and restart worker", "Wait longer", "Reassign task"])
```
**Next action:** Kill worker, `supervisor.sh restart`, reassign task.

### Git conflict in source code

```python
orchestrator_raise_blocker(
  task_id="TASK-src001", agent="claude_code",
  question="[CC1] Git conflict in orchestrator/engine.py. Semantic conflict requires careful merge.",
  severity="high", options=["Keep CC1 version", "Keep CC2 version", "Operator merges manually"])
```
**Next action:** Stop both sessions from committing to the file. Operator resolves.

### State corruption detected

```python
orchestrator_raise_blocker(
  task_id="TASK-corrupt", agent="claude_code",
  question="[CC1] state_corruption_detected in state/bugs.json. Dict instead of list.",
  severity="high", options=["Back up and reset state file", "Stop all workers and investigate"])
```
**Next action:** Back up file, stop workers, fix state, restart.

## References

- [multi-cc-escalation-ladder.md](multi-cc-escalation-ladder.md) -- Escalation levels and decision flow
- [multi-cc-collision-templates.md](multi-cc-collision-templates.md) -- Blocker call templates
- [multi-cc-blocker-wording.md](multi-cc-blocker-wording.md) -- Reusable blocker message library
