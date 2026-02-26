# Instance-Aware Status Examples: Multi-CC Sessions

Realistic `orchestrator_status` output examples for 1, 2, and 3 active
Claude Code (CC) sessions. Shows what operators see today (interim session
labels) and what changes with future swarm mode (automatic instance tracking).

---

## What is Interim vs Future

| Aspect | Interim (now) | Future (swarm mode) |
|--------|---------------|---------------------|
| Identity | Manual session labels (`cc-alpha`, `cc-beta`) | Auto-assigned instance IDs (`claude_code#worker-01`) |
| Registration | Single `claude_code` entry, shared | One entry per instance, unique |
| Heartbeat | Single slot, last-writer-wins | Per-instance heartbeat slots |
| Task ownership | By agent name (`claude_code`) | By instance ID (`claude_code#worker-01`) |
| Stale detection | Per agent name | Per instance |
| Collision risk | Possible (two sessions claim same task) | Eliminated (unique instance leases) |

---

## Example 1: Single CC Session

One Claude Code session running alongside codex (manager) and gemini.

### orchestrator_status output

```
{
  "active_agents": ["codex", "claude_code", "gemini"],
  "agent_instances": {
    "codex": {
      "status": "active",
      "last_seen": "2026-02-26T14:30:05Z",
      "age_seconds": 3,
      "current_task": "TASK-82466844",
      "session_id": null,
      "role": "leader"
    },
    "claude_code": {
      "status": "active",
      "last_seen": "2026-02-26T14:30:02Z",
      "age_seconds": 6,
      "current_task": "TASK-3cb6bab0",
      "session_id": "sess-abc-001",
      "role": "team_member"
    },
    "gemini": {
      "status": "active",
      "last_seen": "2026-02-26T14:29:58Z",
      "age_seconds": 10,
      "current_task": "TASK-dc0af9ac",
      "session_id": null,
      "role": "team_member"
    }
  },
  "active_agent_identities": {
    "claude_code": {
      "client": "claude_code",
      "model": "claude-sonnet-4-20250514",
      "session_id": "sess-abc-001",
      "verified": true,
      "cwd": "/Users/alex/claude-multi-ai"
    }
  },
  "queue_summary": {
    "assigned": 24,
    "in_progress": 3,
    "reported": 0,
    "done": 268,
    "blocked": 2,
    "total": 297
  }
}
```

### Operator notes

- Single CC entry in `agent_instances`. No collision risk.
- `session_id` is populated for CC, null for codex and gemini (they
  do not use session-based identity).
- One identity entry in `active_agent_identities`.
- This is the simplest and most common configuration.

---

## Example 2: Two CC Sessions (Both Active)

Two Claude Code sessions running concurrently. In the interim model, both
share the `claude_code` agent name. The operator distinguishes them by
session label convention (e.g., `cc-alpha`, `cc-beta` in tmux panes).

### orchestrator_status output

```
{
  "active_agents": ["codex", "claude_code", "gemini"],
  "agent_instances": {
    "codex": {
      "status": "active",
      "last_seen": "2026-02-26T14:30:05Z",
      "age_seconds": 3,
      "current_task": "TASK-82466844",
      "session_id": null,
      "role": "leader"
    },
    "claude_code": {
      "status": "active",
      "last_seen": "2026-02-26T14:30:01Z",
      "age_seconds": 7,
      "current_task": "TASK-3cb6bab0",
      "session_id": "sess-abc-002",
      "role": "team_member",
      "_interim_note": "Two sessions share this identity. Last heartbeat wins."
    },
    "gemini": {
      "status": "offline",
      "last_seen": "2026-02-24T11:15:00Z",
      "age_seconds": 185400,
      "current_task": null,
      "session_id": null,
      "role": "team_member"
    }
  },
  "active_agent_identities": {
    "claude_code": {
      "client": "claude_code",
      "model": "claude-sonnet-4-20250514",
      "session_id": "sess-abc-002",
      "verified": true,
      "cwd": "/Users/alex/claude-multi-ai",
      "_interim_note": "Only the most recent session identity is visible"
    }
  },
  "queue_summary": {
    "assigned": 38,
    "in_progress": 2,
    "reported": 1,
    "done": 254,
    "blocked": 3,
    "total": 298
  },
  "_operator_context": {
    "known_sessions": [
      {
        "label": "cc-alpha",
        "session_id": "sess-abc-001",
        "tmux_pane": "agents-autopilot:claude-1",
        "assigned_workstream": "backend",
        "status": "active (heartbeat via claim loop)"
      },
      {
        "label": "cc-beta",
        "session_id": "sess-abc-002",
        "tmux_pane": "agents-autopilot:claude-2",
        "assigned_workstream": "qa",
        "status": "active (heartbeat via claim loop)"
      }
    ],
    "collision_risk": "Possible. Use claim_override to partition tasks."
  }
}
```

### Operator notes

- `agent_instances` still shows a single `claude_code` entry because the
  interim model does not distinguish instances. The `last_seen` and
  `session_id` reflect whichever session heartbeated most recently.
- `active_agent_identities` shows only the latest session identity.
- The `_operator_context` section is not part of the actual API output --
  it represents information the operator tracks manually (tmux pane labels,
  workstream partitions).
- **Collision risk**: Two sessions may attempt to claim the same task. Use
  `set_claim_override` to partition work by session.
- See [dual-cc-operation.md](dual-cc-operation.md) for the full interim workflow.

### Future swarm mode equivalent

With automatic instance tracking, the same setup would produce:

```
"agent_instances": {
  "codex#leader": { "status": "active", ... },
  "claude_code#worker-01": {
    "status": "active",
    "session_id": "sess-abc-001",
    "current_task": "TASK-a1b2c3d4",
    ...
  },
  "claude_code#worker-02": {
    "status": "active",
    "session_id": "sess-abc-002",
    "current_task": "TASK-3cb6bab0",
    ...
  },
  "gemini#worker-01": { "status": "offline", ... }
}
```

Each instance gets its own heartbeat slot, task assignment, and lease.
No collision risk. No manual session labeling needed.

---

## Example 3: Three CC Sessions (Mixed Active/Stale)

Three Claude Code sessions: two active, one stale (crashed or disconnected).

### orchestrator_status output

```
{
  "active_agents": ["codex", "claude_code"],
  "agent_instances": {
    "codex": {
      "status": "active",
      "last_seen": "2026-02-26T14:30:05Z",
      "age_seconds": 3,
      "current_task": "TASK-82466844",
      "session_id": null,
      "role": "leader"
    },
    "claude_code": {
      "status": "active",
      "last_seen": "2026-02-26T14:30:03Z",
      "age_seconds": 5,
      "current_task": "TASK-e75fb59d",
      "session_id": "sess-abc-003",
      "role": "team_member",
      "_interim_note": "Three sessions attempted. Only latest heartbeat visible."
    },
    "gemini": {
      "status": "active",
      "last_seen": "2026-02-26T14:29:55Z",
      "age_seconds": 13,
      "current_task": "TASK-dc0af9ac",
      "session_id": null,
      "role": "team_member"
    }
  },
  "active_agent_identities": {
    "claude_code": {
      "client": "claude_code",
      "model": "claude-sonnet-4-20250514",
      "session_id": "sess-abc-003",
      "verified": true,
      "cwd": "/Users/alex/claude-multi-ai"
    }
  },
  "queue_summary": {
    "assigned": 18,
    "in_progress": 3,
    "reported": 0,
    "done": 274,
    "blocked": 1,
    "total": 296
  },
  "_operator_context": {
    "known_sessions": [
      {
        "label": "cc-alpha",
        "session_id": "sess-abc-001",
        "tmux_pane": "agents-autopilot:claude-1",
        "assigned_workstream": "backend",
        "status": "stale (no heartbeat for 12m, tmux pane shows shell prompt)"
      },
      {
        "label": "cc-beta",
        "session_id": "sess-abc-002",
        "tmux_pane": "agents-autopilot:claude-2",
        "assigned_workstream": "qa",
        "status": "active (heartbeat via claim loop)"
      },
      {
        "label": "cc-gamma",
        "session_id": "sess-abc-003",
        "tmux_pane": "agents-autopilot:claude-3",
        "assigned_workstream": "core-support",
        "status": "active (heartbeat via claim loop)"
      }
    ],
    "collision_risk": "Elevated. Stale session may hold in_progress tasks with valid leases.",
    "recommended_action": "Check if cc-alpha's in_progress tasks need reassignment."
  }
}
```

### Operator notes

- The stale session (`cc-alpha`, `sess-abc-001`) does not appear in the
  status output at all. The orchestrator only tracks the most recent
  `claude_code` heartbeat, which belongs to `cc-gamma`.
- **Stale session tasks**: If `cc-alpha` was working on a task when it
  crashed, that task remains `in_progress` with owner `claude_code`.
  The lease will eventually expire and the task will requeue. The operator
  can accelerate this by running:
  ```
  reassign_stale_tasks(source="operator", stale_after_seconds=300)
  ```
- **Manual tracking required**: The operator must maintain the
  `_operator_context` information (session labels, pane mappings) outside
  the orchestrator. This is the primary limitation of the interim model.

### Future swarm mode equivalent

```
"agent_instances": {
  "codex#leader": { "status": "active", ... },
  "claude_code#worker-01": {
    "status": "stale",
    "last_seen": "2026-02-26T14:18:00Z",
    "age_seconds": 725,
    "current_task": "TASK-a1b2c3d4",
    "lease_status": "expiring_soon"
  },
  "claude_code#worker-02": {
    "status": "active",
    "session_id": "sess-abc-002",
    "current_task": "TASK-3cb6bab0",
    ...
  },
  "claude_code#worker-03": {
    "status": "active",
    "session_id": "sess-abc-003",
    "current_task": "TASK-e75fb59d",
    ...
  },
  "gemini#worker-01": { "status": "active", ... }
}
```

Key differences in swarm mode:
- The stale instance (`worker-01`) appears explicitly with `status: stale`
- Its lease status is visible (`expiring_soon`)
- No manual session tracking needed
- Automatic reassignment when lease expires

---

## Comparison Summary

| Scenario | Interim (now) | Swarm mode (future) |
|----------|---------------|---------------------|
| 1 CC | Works correctly. Single entry, no ambiguity. | Same behavior, with instance ID suffix. |
| 2 CC | Single `claude_code` entry. Last heartbeat wins. Manual session labels needed. Collision risk. | Two distinct entries. Independent heartbeats. No collision. |
| 3 CC (mixed) | Stale session invisible. Tasks may be stuck. Manual tracking required. | Stale instance visible with status. Automatic lease-based recovery. |

## Operator Checklist for Multi-CC (Interim)

- [ ] Label each tmux pane with session identifier (cc-alpha, cc-beta, etc.)
- [ ] Use `set_claim_override` to partition tasks between sessions
- [ ] Monitor tmux panes for crashed sessions (shell prompt visible)
- [ ] Run `reassign_stale_tasks` if a session dies with in_progress tasks
- [ ] Track session-to-workstream mapping in operator notes
- [ ] Verify no two sessions are working on the same task

## References

- [instance-aware-status-fields.md](instance-aware-status-fields.md) -- Field definitions
- [dual-cc-operation.md](dual-cc-operation.md) -- Two-session workflow
- [triple-cc-lane-cheatsheet.md](triple-cc-lane-cheatsheet.md) -- Three-session lane assignments
- [duplicate-claim-playbook.md](duplicate-claim-playbook.md) -- Collision response
- [swarm-mode.md](swarm-mode.md) -- Future automatic instance tracking
- [multi-cc-conventions.md](multi-cc-conventions.md) -- Naming and partition conventions
