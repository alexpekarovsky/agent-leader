# Submit Report Response Notes

This note defines the request and response shape for `orchestrator_submit_report`.

## Required Request Fields

The request must include:

- `task_id`
- `agent`
- `commit_sha`
- `status`
- `test_summary`

Example request:

```json
{
  "task_id": "TASK-1234abcd",
  "agent": "gemini",
  "commit_sha": "abc123def456",
  "status": "done",
  "notes": "Implemented feature and verified smoke tests.",
  "test_summary": {
    "command": "pytest -q",
    "passed": 42,
    "failed": 0
  }
}
```

## Response Structure

The response can include these lifecycle fields:

- `auto_manager_cycle`
- `auto_claim_next`
- `processed_reports`
- `passed`
- `pending_total`

Example response:

```json
{
  "ok": true,
  "result": {
    "submitted": true,
    "auto_manager_cycle": {
      "ok": true,
      "processed_reports": 1,
      "passed": 1,
      "pending_total": 0
    },
    "auto_claim_next": {
      "ok": true,
      "claimed": false
    }
  }
}
```

## Retry/Error Cases

When immediate processing is unavailable, the report can be `queued_for_retry`.
If submission itself fails, the response should include `submit_error` details.

Retry/error example:

```json
{
  "ok": false,
  "result": {
    "submitted": false,
    "queued_for_retry": true,
    "submit_error": "Transport closed while processing report."
  }
}
```
