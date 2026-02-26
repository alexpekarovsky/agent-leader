# CORE-02 Acceptance Evidence Execution Template

Structured template for collecting evidence while running the CORE-02
verification checklist. Fill each section during the restart test.

## Metadata

```
Operator: _______________
Date: _______________
CORE-02 checklist: docs/core-02-verification-checklist.md
Restart test ID: _______________
```

## Step 1: Agent list with instance IDs

### Command run

```
orchestrator_list_agents(active_only=false)
```

### Evidence capture

Paste the raw output:

```json
[paste orchestrator_list_agents output here]
```

### Verification

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| All agents have `instance_id` | | |
| Each `instance_id` is non-empty | | |
| Format matches `{agent}#{suffix}` | | |
| No duplicate `instance_id` values | | |
| `status` field present | | |
| `last_seen` field present and recent | | |

## Step 2: Instance ID format validation

### Evidence

List each observed instance_id:

| Agent | instance_id | Format valid? |
|-------|-------------|---------------|
| | | |
| | | |
| | | |

### Verification

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| All follow `{agent}#{suffix}` | | |
| Prefix matches `agent_name` | | |
| Suffix is non-empty | | |

## Step 3: Two workers distinguishable

### Setup

```
# Worker 1 connected via: [describe]
# Worker 2 connected via: [describe]
```

### Command run

```
orchestrator_list_agents(active_only=true)
```

### Evidence capture

```json
[paste output showing two claude_code entries]
```

### Verification

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Two separate entries for `claude_code` | | |
| Distinct `instance_id` values | | |
| Each has own `last_seen` | | |
| Each shows own `current_task_id` | | |

## Step 4: Stale detection per-instance

### Setup

```
# Stopped worker: [instance_id]
# Kept running: [instance_id]
# Wait time: ___s
```

### Command run

```
orchestrator_list_agents(active_only=false)
```

### Evidence capture

```json
[paste output showing stale vs active]
```

### Verification

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Stopped worker shows `stale`/`disconnected` | | |
| Running worker shows `active` | | |
| Stopped worker `last_seen` is old | | |
| Running worker `last_seen` is recent | | |
| No cross-contamination | | |

## Backward compatibility

### Command run

```
orchestrator_list_agents(active_only=false)
```

### Verification

| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Agents without explicit ID get `{agent}#default` | | |
| No errors from old-style connections | | |

## Overall result

| Criterion | Result |
|-----------|--------|
| Step 1: Agent list | PASS / FAIL |
| Step 2: Format validation | PASS / FAIL |
| Step 3: Two workers | PASS / FAIL |
| Step 4: Stale detection | PASS / FAIL |
| Backward compat | PASS / FAIL |
| **CORE-02 Overall** | **PASS / FAIL** |

## Signoff

```
Operator: _______________
Date: _______________
Result: PASS / FAIL
Notes: _______________
```

## References

- [core-02-verification-checklist.md](core-02-verification-checklist.md) -- Step-by-step checklist
- [instance-aware-status-fields.md](instance-aware-status-fields.md) -- Field definitions
- [evidence-folder-layout.md](evidence-folder-layout.md) -- Where to store evidence files
