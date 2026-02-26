# CORE-02 Acceptance Evidence Template

Maps to [core-02-verification-checklist.md](core-02-verification-checklist.md) steps 1-4.

## Metadata

```
Operator: _______________
Date:     _______________
Test ID:  _______________
```

## Step 1: Agent list with instance IDs

```
orchestrator_list_agents(active_only=false)
```

```json
PASTE_OUTPUT_HERE
```

| Check                          | P/F | Notes |
|--------------------------------|-----|-------|
| All agents have `instance_id`  |     |       |
| Each `instance_id` non-empty   |     |       |
| `status` and `last_seen` present |   |       |

## Step 2: Instance ID format check

| Agent | instance_id | Format `{agent}#{suffix}`? |
|-------|-------------|---------------------------|
|       |             | PASS / FAIL                |
|       |             | PASS / FAIL                |
|       |             | PASS / FAIL                |

| Check                           | P/F |
|---------------------------------|-----|
| All match `{agent}#{suffix}`    |     |
| No duplicate instance_id values |     |

## Step 3: Two workers distinguishable

```
orchestrator_list_agents(active_only=true)
```

```json
PASTE_OUTPUT_HERE
```

| Check                               | P/F | Notes |
|--------------------------------------|-----|-------|
| Two separate `claude_code` entries   |     |       |
| Distinct `instance_id` per entry     |     |       |
| Each has own `last_seen`             |     |       |
| Each has own `current_task_id`       |     |       |

## Step 4: Disconnected worker status

Setup: stopped worker `_______________`, waited `___`s

```
orchestrator_list_agents(active_only=false)
```

```json
PASTE_OUTPUT_HERE
```

| Check                                 | P/F | Notes |
|---------------------------------------|-----|-------|
| Stopped worker shows `stale`/`disconnected` |  |       |
| Running worker shows `active`         |     |       |
| No cross-contamination                |     |       |

## Summary

| Step | Result | | Step | Result |
|------|--------|-|------|--------|
| 1 Agent list | PASS / FAIL | | 3 Two workers | PASS / FAIL |
| 2 Format check | PASS / FAIL | | 4 Disconnected | PASS / FAIL |

**CORE-02 Overall:** PASS / FAIL | Operator: _______________ | Date: _______________

## References

- [core-02-verification-checklist.md](core-02-verification-checklist.md)
- [instance-aware-status-fields.md](instance-aware-status-fields.md)
