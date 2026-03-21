# State Schema Migration Runbook

## Overview

The orchestrator state files (tasks.json, agents.json, events.jsonl) now carry
a `schema_version` field on every record.  A directory-level
`state/schema_meta.json` tracks the overall version.

Migration runs automatically during `bootstrap()` — no manual steps are needed
for normal operation.  This runbook covers manual or troubleshooting scenarios.

## Schema versions

| Version | Description |
|---------|-------------|
| 0 (legacy) | No `schema_version` field; tasks.json is a bare list, agents.json is a bare dict |
| 1 (current) | Each record stamped with `schema_version: 1`; tasks get default `team_id`, `parent_task_id`, `tags`, `delivery_profile` |

## Automatic migration

`Orchestrator.bootstrap()` calls `migrate_state()` on every startup.  The
migration is idempotent — once `state/schema_meta.json` records
`schema_version >= 1`, subsequent calls are no-ops.

## Manual migration

### Check current version

```python
from orchestrator.migration import detect_schema_version
from pathlib import Path

version = detect_schema_version(Path("state"))
print(f"Current schema version: {version}")
```

### Run migration with dry-run

```python
from orchestrator.migration import migrate_state
from pathlib import Path

report = migrate_state(Path("state"), Path("bus"), dry_run=True)
print(report)
# {"migrated": ["tasks.json", ...], "skipped": [...], "errors": [...], "dry_run": true}
```

### Run migration

```python
from orchestrator.migration import migrate_state
from pathlib import Path

report = migrate_state(Path("state"), Path("bus"))
print(report)
```

## What changes on disk

### tasks.json

Before (v0):
```json
[
  {"id": "TASK-abc", "title": "my task", "status": "assigned"}
]
```

After (v1):
```json
[
  {
    "id": "TASK-abc",
    "title": "my task",
    "status": "assigned",
    "schema_version": 1,
    "team_id": null,
    "parent_task_id": null,
    "tags": [],
    "delivery_profile": {"risk": "low", "test_plan": "smoke", "doc_impact": "none"}
  }
]
```

### agents.json

Before (v0):
```json
{
  "claude_code": {"agent": "claude_code", "status": "active"}
}
```

After (v1):
```json
{
  "claude_code": {"agent": "claude_code", "status": "active", "schema_version": 1}
}
```

### events.jsonl

Each JSON line gains `"schema_version":1`.

### state/schema_meta.json (new file)

```json
{
  "schema_version": 1,
  "migrated_at": "2026-03-21T16:00:00+00:00",
  "files": ["tasks.json", "agents.json", "events.jsonl"]
}
```

## Rollback

Migration is additive — it only adds fields.  To roll back:

1. Remove the added `schema_version` fields from records (optional; existing
   code ignores unknown fields).
2. Delete `state/schema_meta.json` to allow migration to re-run on next
   bootstrap.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `WARNING: state migration failed` in stderr | Corrupt JSON in state file | Fix the JSON manually, then restart |
| `schema_meta.json` not created | Errors during migration | Check `report["errors"]` from `migrate_state()` |
| Migration runs every startup | `schema_meta.json` missing or version < current | Verify file exists and contains `"schema_version": 1` |

## Adding future migrations

To add a v2 migration:

1. Bump `CURRENT_SCHEMA_VERSION` to `2` in `orchestrator/migration.py`.
2. Add `_migrate_tasks_v1_to_v2()` (and similar) functions.
3. Chain migrations: v0 → v1 → v2 (existing v0→v1 runs first, then v1→v2).
4. Add tests in `tests/test_state_migration.py`.
5. Update this runbook.
