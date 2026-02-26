# Dashboard MVP Command Palette

Single-key shortcuts for the most common operator actions during a live orchestration session. All commands map directly to existing orchestrator MCP tools -- no new backend work required for MVP.

## Shortcut Map

| Key | Action            | MCP Tool                                      | Description                        |
|-----|-------------------|-----------------------------------------------|------------------------------------|
| `s` | Quick status      | `orchestrator_status`                         | Overall progress, percent, phase   |
| `t` | Task list         | `orchestrator_list_tasks`                     | All tasks with status and owner    |
| `a` | Agent list        | `orchestrator_list_agents`                    | Registered agents, active/offline  |
| `b` | Open blockers     | `orchestrator_list_blockers(status=open)`     | Unresolved blockers needing input  |
| `g` | Open bugs         | `orchestrator_list_bugs(status=bug_open)`     | Validation-generated bugs          |
| `l` | Audit log         | `orchestrator_list_audit_logs`                | Recent tool calls and results      |
| `m` | Run manager cycle | `orchestrator_manager_cycle`                  | Validate, reconnect, summarize     |
| `r` | Reassign stale    | `orchestrator_reassign_stale_tasks`           | Move stuck tasks to active workers |
| `w` | Watchdog one-shot | _(diagnostics via noop dispatch + telemetry)_ | Health check across agents         |
| `?` | Help              | _(print this table)_                          | Show available shortcuts           |

## Rationale for Top Actions

**`s` (status)** is the most frequent operator action. It answers "where are we?" in one keypress. Returns percentage completion, phase breakdown, and any alerts.

**`t` (tasks)** is the second-most-used view. Operators need to see the queue to spot stuck, unowned, or blocked work items quickly.

**`b` (blockers)** surfaces the highest-priority operator input needed. Open blockers directly stall agent progress; resolving them unblocks the pipeline.

**`m` (manager cycle)** is the primary "nudge" when the system looks stuck. It validates reported tasks, reconnects stale agents, and produces a summary of remaining work. Safe to run repeatedly.

**`r` (reassign)** is the recovery action when an agent goes offline or stale. Redistributes orphaned tasks to healthy workers so execution continues.

## Backend Requirements

All shortcuts map to existing MCP tools. No new backend endpoints or schema changes are needed for the MVP palette. The `w` (watchdog) shortcut composes existing dispatch telemetry and noop diagnostics; it does not require a dedicated backend route.

## Usage Notes

- Shortcuts are case-insensitive in the CLI.
- Commands that mutate state (`m`, `r`) print a confirmation summary after execution.
- Read-only commands (`s`, `t`, `a`, `b`, `g`, `l`) can be called at any frequency without side effects.
- The palette is designed for a tmux operator pane or supervisor CLI. It does not replace the full MCP tool interface for advanced queries.
