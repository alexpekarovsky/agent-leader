# Watchdog JSONL Schema

Reference for the JSONL diagnostic events emitted by
`scripts/autopilot/watchdog_loop.sh`.

## Output file

Each cycle writes to:

```
.autopilot-logs/watchdog-YYYYMMDD-HHMMSS.jsonl
```

One JSON object per line. Empty files are valid (no anomalies detected).

## Common fields

Every JSONL line contains:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string (ISO 8601) | UTC time the event was emitted |
| `kind` | string | Event type — see sections below |

Additional fields depend on `kind`.

## Event kinds

### `stale_task`

Emitted when a task has been in a time-sensitive status longer than the
configured timeout.

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Task identifier (e.g. `TASK-abcdef12`) |
| `owner` | string | Assigned agent (`claude_code`, `gemini`, `codex`) |
| `status` | string | Current status that triggered the timeout |
| `age_seconds` | integer | Seconds since the task was last updated |
| `timeout_seconds` | integer | Configured threshold that was exceeded |
| `title` | string | Task title for quick identification |

**Timeout thresholds** (configurable via CLI flags):

| Status | Default timeout | Flag |
|--------|-----------------|------|
| `assigned` | 180 s (3 min) | `--assigned-timeout` |
| `in_progress` | 900 s (15 min) | `--inprogress-timeout` |
| `reported` | 180 s (3 min) | `--reported-timeout` |

**Example:**

```json
{
  "timestamp": "2026-02-25T23:30:00.123456+00:00",
  "kind": "stale_task",
  "task_id": "TASK-abcdef12",
  "owner": "claude_code",
  "status": "in_progress",
  "age_seconds": 1024,
  "timeout_seconds": 900,
  "title": "Implement retry logic for event bus"
}
```

### `state_corruption_detected`

Emitted when a state file (`bugs.json` or `blockers.json`) exists but
contains an unexpected data type (e.g. a `dict` instead of a `list`).

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Absolute path to the corrupted file |
| `previous_type` | string | Python type name of the actual value |
| `expected_type` | string | Always `"list"` |

**Example:**

```json
{
  "timestamp": "2026-02-25T23:30:00.456789+00:00",
  "kind": "state_corruption_detected",
  "path": "/Users/alex/claude-multi-ai/state/bugs.json",
  "previous_type": "dict",
  "expected_type": "list"
}
```

## Parsing guidance

Read lines with standard JSONL parsing — one `json.loads()` per line:

```python
import json
from pathlib import Path

for line in Path("watchdog-20260225-233000.jsonl").read_text().splitlines():
    event = json.loads(line)
    if event["kind"] == "stale_task":
        print(f"Stale: {event['task_id']} ({event['age_seconds']}s)")
```

The existing `scripts/autopilot/log_check.sh --strict` validates that
every line in watchdog JSONL files is parseable JSON.

## Operator response

- **`stale_task`**: Check if the owning agent is alive and making
  progress. The manager loop reads these entries and may publish
  `manager.sync` events or raise blockers for stuck tasks.
- **`state_corruption_detected`**: Inspect the file at `path`. A
  common cause is a partial write during a crash. Fix the file content
  or delete it so the orchestrator recreates it on next bootstrap.
