# Multi-CC Task Partition Templates

Reusable templates for splitting work across multiple Claude Code
sessions (CC1, CC2, CC3) before instance-aware swarm mode lands.

## Session labels

Use consistent labels in report notes and commit messages so the
manager can trace which session produced each artifact.

| Label | Session | Typical workstream |
|-------|---------|-------------------|
| `CC1` | Claude Code session 1 | smoke tests, script validation |
| `CC2` | Claude Code session 2 | docs, operator guides |
| `CC3` | Claude Code session 3 | supervisor, infra tasks |

## Report note format

Include the session label at the start of every `submit_report` note:

```
[CC1] Implemented smoke tests for supervisor lifecycle.
      Tests: 6 passed, 0 failed.
```

```
[CC2] Created operator cheat sheet for tmux pane mapping.
      No tests required (doc-only task).
```

```
[CC3] Added failure injection checklist to supervisor test plan.
      Tests: 4 passed, 0 failed.
```

## Split-plan messaging template

When the manager creates an execution plan that spans multiple
sessions, use this event format:

```
orchestrator_publish_event(
  type="manager.execution_plan",
  source="codex",
  payload={
    "plan_id": "PLAN-001",
    "description": "AUTO-M1 milestone sprint",
    "partitions": [
      {
        "session": "CC1",
        "workstream": "qa",
        "tasks": ["TASK-aaa", "TASK-bbb"],
        "focus": "smoke tests and script checkers"
      },
      {
        "session": "CC2",
        "workstream": "default",
        "tasks": ["TASK-ccc", "TASK-ddd"],
        "focus": "operator docs and guides"
      },
      {
        "session": "CC3",
        "workstream": "devops",
        "tasks": ["TASK-eee", "TASK-fff"],
        "focus": "supervisor and infra tasks"
      }
    ]
  }
)
```

## Claim override setup

To assign specific tasks to specific sessions, use `set_claim_override`
before each session calls `claim_next_task`:

```
# Route TASK-aaa to whichever CC session claims next
orchestrator_set_claim_override(
  agent="claude_code",
  task_id="TASK-aaa",
  source="codex"
)
```

After the target session claims, clear the override:

```
orchestrator_set_claim_override(
  agent="claude_code",
  task_id="",
  source="codex"
)
```

## Workstream-based partitioning

Alternatively, create tasks in separate workstreams and instruct each
session to focus on its assigned workstream.  This relies on session
discipline — the engine does not enforce workstream filters on claims.

| Session | Workstream | Task types |
|---------|-----------|------------|
| CC1 | `qa` | Test files, checkers, validators |
| CC2 | `default` | Documentation, guides, schemas |
| CC3 | `devops` | Scripts, infra, supervisor tasks |

## Commit message convention

Include the session label in commit messages for traceability:

```
[CC1] test: add supervisor lifecycle smoke tests
[CC2] docs: add tmux pane cheat sheet
[CC3] fix: supervisor clean removes stale restart files
```

## Coordination checklist

Before starting multi-CC operation:

- [ ] All sessions target the same project root
- [ ] Session labels agreed (CC1/CC2/CC3)
- [ ] Task partition published via `manager.execution_plan` event
- [ ] Claim overrides set for first task per session
- [ ] All sessions on the same git branch

During operation:

- [ ] Reports include session label in notes
- [ ] Commits include session label prefix
- [ ] Monitor `orchestrator_list_tasks(status="in_progress")` for overlap
- [ ] Clear claim overrides after each successful claim

## References

- [dual-cc-operation.md](dual-cc-operation.md) — Dual-CC collision avoidance
- [task-queue-hygiene.md](task-queue-hygiene.md) — Claim override management
- [roadmap.md](roadmap.md) — Phase B instance-aware presence
