# Triple-CC Task Assignment Board Template

Reusable markdown template for tracking CC1/CC2/CC3 task streams
during multi-session operation.  Paste into manager notes or publish
as a `manager.execution_plan` event payload.

## Assignment board

```markdown
## CC Task Assignment Board — [DATE]

### CC1 (smoke tests / qa)
| Field | Value |
|-------|-------|
| Current task | TASK-________ |
| Status | idle / in_progress / reporting |
| Last report | TASK-________ @ [commit_sha] |
| Handoff notes | — |

### CC2 (docs / default)
| Field | Value |
|-------|-------|
| Current task | TASK-________ |
| Status | idle / in_progress / reporting |
| Last report | TASK-________ @ [commit_sha] |
| Handoff notes | — |

### CC3 (supervisor / devops)
| Field | Value |
|-------|-------|
| Current task | TASK-________ |
| Status | idle / in_progress / reporting |
| Last report | TASK-________ @ [commit_sha] |
| Handoff notes | — |

### Queue summary
| Metric | Count |
|--------|-------|
| Assigned (claimable) | __ |
| In progress | __ |
| Reported (awaiting validation) | __ |
| Blocked | __ |
| Done | __ |
```

## Filled example

```markdown
## CC Task Assignment Board — 2026-02-26

### CC1 (smoke tests / qa)
| Field | Value |
|-------|-------|
| Current task | TASK-abc123 |
| Status | in_progress |
| Last report | TASK-xyz789 @ d7ab431 |
| Handoff notes | Blocked TASK-def456, prerequisite doc missing |

### CC2 (docs / default)
| Field | Value |
|-------|-------|
| Current task | TASK-ghi012 |
| Status | reporting |
| Last report | TASK-jkl345 @ a56a95a |
| Handoff notes | — |

### CC3 (supervisor / devops)
| Field | Value |
|-------|-------|
| Current task | none |
| Status | idle |
| Last report | TASK-mno678 @ b12c34d |
| Handoff notes | All devops tasks done, picking up qa overflow |

### Queue summary
| Metric | Count |
|--------|-------|
| Assigned (claimable) | 15 |
| In progress | 2 |
| Reported (awaiting validation) | 3 |
| Blocked | 7 |
| Done | 42 |
```

## Publishing as an event

To share the board with all agents:

```
orchestrator_publish_event(
  type="manager.execution_plan",
  source="codex",
  payload={
    "board_date": "2026-02-26",
    "sessions": {
      "CC1": {"task": "TASK-abc123", "status": "in_progress", "workstream": "qa"},
      "CC2": {"task": "TASK-ghi012", "status": "reporting", "workstream": "default"},
      "CC3": {"task": null, "status": "idle", "workstream": "devops"}
    },
    "queue": {"assigned": 15, "in_progress": 2, "reported": 3, "blocked": 7, "done": 42}
  }
)
```

## Report-note labels

Each session prefixes report notes with its label:

```
[CC1] Added supervisor lifecycle smoke tests. 6 passed, 0 failed.
[CC2] Created operator cheat sheet. Doc-only task.
[CC3] Fixed supervisor clean to remove restart files.
```

## References

- [multi-cc-partition-templates.md](multi-cc-partition-templates.md) — Partition strategy and claim setup
- [dual-cc-operation.md](dual-cc-operation.md) — Collision avoidance for shared identity
- [task-queue-hygiene.md](task-queue-hygiene.md) — Queue management procedures
