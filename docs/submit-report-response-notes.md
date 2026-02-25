# Submit Report — Request and Response Reference

Reference for the `orchestrator_submit_report` MCP tool: required fields, response structure, auto-validation behavior, and error handling.

## Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | string | Yes | Task being reported (e.g., `TASK-abc123`) |
| `agent` | string | Yes | Reporter agent ID — must match task owner |
| `commit_sha` | string | Yes | Git commit containing the implementation |
| `status` | string | Yes | `done`, `blocked`, or `needs_review` |
| `test_summary` | object | Yes | Test execution results (see below) |
| `artifacts` | string[] | No | Changed files or evidence paths |
| `notes` | string | No | Implementation summary and residual risks |

### test_summary object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | Yes | Exact test command that was run |
| `passed` | integer | Yes | Count of passing tests |
| `failed` | integer | Yes | Count of failing tests |

## Response Structure

The response includes the report result plus optional auto-validation and auto-claim sections.

### Successful submission

```json
{
  "report": {
    "task_id": "TASK-abc123",
    "agent": "claude_code",
    "commit_sha": "abc1234",
    "status": "done",
    "test_summary": {
      "command": "./run_tests.sh",
      "passed": 10,
      "failed": 0
    },
    "artifacts": ["src/feature.py"],
    "notes": "Implemented feature X."
  },
  "auto_manager_cycle": {
    "enabled": true,
    "processed_reports": [
      {
        "task_id": "TASK-abc123",
        "passed": true,
        "result": {
          "task_id": "TASK-abc123",
          "owner": "claude_code",
          "notes": "Auto manager cycle accepted report abc1234"
        }
      }
    ],
    "pending_total": 5
  },
  "auto_claim_next": {
    "id": "TASK-def456",
    "title": "Next available task",
    "status": "in_progress",
    "owner": "claude_code"
  }
}
```

### Key response fields

| Field | Description |
|-------|-------------|
| `report` | Echo of the submitted report data |
| `auto_manager_cycle.enabled` | Whether auto-validation ran (controlled by policy `auto_validate_reports_on_submit`) |
| `auto_manager_cycle.processed_reports` | List of reports validated in this cycle |
| `auto_manager_cycle.processed_reports[].passed` | `true` if validation accepted, `false` if rejected |
| `auto_manager_cycle.pending_total` | Total pending tasks remaining |
| `auto_claim_next` | Next task auto-claimed for the reporting agent, or `null` if none available |

### Validation rejection

When the auto-manager-cycle rejects a report (e.g., `status=blocked` with `failed > 0`):

```json
{
  "auto_manager_cycle": {
    "processed_reports": [
      {
        "task_id": "TASK-abc123",
        "passed": false,
        "result": {
          "task_id": "TASK-abc123",
          "bug_id": "BUG-xyz789",
          "owner": "claude_code",
          "notes": "Auto manager cycle rejected report status=blocked, failed_tests=1"
        }
      }
    ]
  }
}
```

A rejection creates a bug (`BUG-*`) and the task re-enters the work loop.

### Retry queue (on submission error)

If the report fails to ingest (e.g., owner mismatch), it's queued for retry:

```json
{
  "queued_for_retry": true,
  "queue_entry": {
    "task_id": "TASK-abc123",
    "attempt": 1,
    "next_retry_at": "2026-02-25T12:00:15Z"
  },
  "submit_error": "Owner mismatch: expected codex, got claude_code"
}
```

### No task available after submission

When the queue is empty after successful submission:

```json
{
  "auto_claim_next": null
}
```

The agent should poll events or back off per the `retry_hint` convention.

## Common Patterns

### Submit and continue working

```
result = orchestrator_submit_report(...)
if result.auto_claim_next:
    # Work on the next task immediately
    next_task = result.auto_claim_next
else:
    # No more tasks — poll or idle
    orchestrator_poll_events(agent="claude_code", timeout_ms=120000)
```

### Check validation result

```
for report in result.auto_manager_cycle.processed_reports:
    if report.passed:
        # Task accepted — move on
    else:
        # Bug opened — check report.result.bug_id
```

## Task State Visibility Caveats (v0.1.0)

### Perceived state lag

Because `auto_manager_cycle` runs inline within the `submit_report`
call, the task you just reported as `"reported"` may already be
`"done"` by the time you read the response.  This is expected: the
manager validated it in the same request.  Do not be surprised if
`list_tasks` shows `"done"` immediately after submission.

### State is locked, not broadcast

Task mutations use a file-based lock (`fcntl` on `.state.lock`).
Changes are atomic within a single operation but are **not pushed** to
other agents.  Agents learn about state changes by:

- Polling events via `orchestrator_poll_events`
- Reading task contracts broadcast during manager cycles

Do **not** rely on `orchestrator_list_tasks` for real-time visibility
of another agent's work.

### Stale task reassignment during auto_manager_cycle

The manager cycle may reassign in-progress or blocked tasks from
silent agents to active workers.  This can happen during **any**
`auto_manager_cycle`, including ones triggered by another agent's
`submit_report`.  Check `pending_total` to understand how many tasks
shifted.

### Race between submit and reassign

If you submit a report while the manager is simultaneously reassigning
your tasks (due to a stale heartbeat), the report may fail with an
owner mismatch error and enter the retry queue.  Use
`orchestrator_heartbeat` regularly to prevent this.

### auto_claim_next and task ordering

The auto-claimed task is selected by the same policy routing as
`orchestrator_claim_next_task`.  If a `claim_override` was set for
your agent, that override takes priority.  The claimed task is
returned with `status: "in_progress"` — there is no separate claim
step needed.

## References

- [docs/task-queue-hygiene.md](task-queue-hygiene.md) — Task lifecycle and claim behavior
- [docs/dual-cc-conventions.md](dual-cc-conventions.md) — Report note prefix conventions
- [docs/operator-runbook.md](operator-runbook.md) — Stale task recovery procedures
