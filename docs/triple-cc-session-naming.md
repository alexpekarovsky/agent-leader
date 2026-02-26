# Triple-CC Session Naming Convention

Mapping between tmux panes/windows, session labels, and report-note
tags for interim multi-CC operation.

## Naming scheme

| Label | tmux window | tmux pane index | Agent identity | Report tag |
|-------|------------|-----------------|----------------|------------|
| CC1 | `worker-1` | Pane 0 in worker window | `claude_code` | `[CC1]` |
| CC2 | `worker-2` | Pane 1 in worker window | `claude_code` | `[CC2]` |
| CC3 | `worker-3` | Pane 2 in worker window (if present) | `claude_code` | `[CC3]` |

The manager window runs `codex` (leader) and is not part of the CC
numbering.

## tmux session layout

With `team_tmux.sh` default session name `agents-autopilot`:

```
agents-autopilot
  Window 0: manager     → codex (leader)
  Window 1: worker-1    → CC1 (claude, primary worker)
  Window 2: worker-2    → CC2 (gemini or second claude)
  Window 3: watchdog    → watchdog (read-only diagnostics)
  Window 4: monitor     → system monitor
```

For triple-CC operation, replace the gemini worker with a second
claude worker and add a third:

```
agents-autopilot
  Window 0: manager     → codex (leader)
  Window 1: worker-1    → CC1 (claude, qa workstream)
  Window 2: worker-2    → CC2 (claude, docs workstream)
  Window 3: worker-3    → CC3 (claude, devops workstream)
  Window 4: watchdog    → watchdog
  Window 5: monitor     → system monitor
```

## Report-note tags

Each session uses its label as a prefix in `submit_report` notes:

```
[CC1] Added smoke tests for supervisor lifecycle. 6 passed, 0 failed.
[CC2] Created operator guide for tmux pane mapping.
[CC3] Fixed supervisor clean to remove stale restart files.
```

## Commit message tags

Include the session label in git commit messages:

```
[CC1] test: add supervisor lifecycle smoke tests
[CC2] docs: add tmux pane cheat sheet
[CC3] fix: supervisor clean removes restart counter files
```

## Event compatibility

Session labels map to `manager.execution_plan` event payloads:

```json
{
  "partitions": [
    {"session": "CC1", "workstream": "qa", "tmux_window": "worker-1"},
    {"session": "CC2", "workstream": "default", "tmux_window": "worker-2"},
    {"session": "CC3", "workstream": "devops", "tmux_window": "worker-3"}
  ]
}
```

## Identifying sessions in tmux

```bash
# List all windows in the autopilot session
tmux list-windows -t agents-autopilot

# Attach to a specific worker
tmux select-window -t agents-autopilot:worker-1   # CC1
tmux select-window -t agents-autopilot:worker-2   # CC2
tmux select-window -t agents-autopilot:worker-3   # CC3
```

## Transition to instance-aware mode

When Phase B instance-aware presence ships, the naming convention
becomes automatic:

| Interim label | Instance ID (Phase B) |
|--------------|----------------------|
| CC1 | `claude_code#worker-01` |
| CC2 | `claude_code#worker-02` |
| CC3 | `claude_code#worker-03` |

Session labels in report notes and commit messages become optional
once `instance_id` is tracked by the orchestrator.

## References

- [multi-cc-partition-templates.md](multi-cc-partition-templates.md) — Partition strategy
- [triple-cc-assignment-board.md](triple-cc-assignment-board.md) — Assignment tracking template
- [tmux-pane-cheatsheet.md](tmux-pane-cheatsheet.md) — Pane index reference
- [instance-aware-status-fields.md](instance-aware-status-fields.md) — Future instance IDs
