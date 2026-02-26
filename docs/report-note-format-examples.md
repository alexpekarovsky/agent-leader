# Project-Tagged Report Note Format Examples

> Examples of report note formats with project tags and session labels
> for Claude Code and Gemini agents. Covers valid/invalid patterns and
> alignment with current execution-plan conventions.

## Note Format Structure

```
[SESSION_LABEL] [PROJECT_TAG] <description (10+ chars)>
```

| Component | Format | Required | Example |
|-----------|--------|----------|---------|
| Session label | `[CC1]`..`[CC3]` | Yes (multi-CC) | `[CC1]` |
| Project tag | `[claude-multi-ai]` | Recommended | `[claude-multi-ai]` |
| Description | Free text, 10+ chars | Yes | `Added lease renewal tests.` |

Session labels are only required when running multiple Claude Code sessions
sharing the `claude_code` agent identity. Single-session and Gemini reports
do not need session labels.

---

## Claude Code Examples

### Single-Session CC (No Session Label Required)

```python
orchestrator_submit_report(
    task_id="TASK-abc12345",
    agent="claude_code",
    commit_sha="a1b2c3d",
    status="done",
    test_summary={"command": ".venv/bin/python -m pytest tests/ -v", "passed": 48, "failed": 0},
    artifacts=["tests/test_lease_transitions.py"],
    notes="[claude-multi-ai] Added 18 lease transition tests covering claim-renew-expire lifecycle."
)
```

**Notes field:** `[claude-multi-ai] Added 18 lease transition tests covering claim-renew-expire lifecycle.`

When running a single Claude Code session, the project tag is the only
label needed. The session label is omitted.

### Multi-CC Session (Session Label + Project Tag)

```python
# CC1 submitting a backend feature:
notes="[CC1] [claude-multi-ai] Implemented lease renewal contract. 21/21 tests pass."

# CC2 submitting a documentation task:
notes="[CC2] [claude-multi-ai] Created operator FAQ for instance-aware status fields."

# CC3 submitting a QA run:
notes="[CC3] [claude-multi-ai] Ran full smoke test suite. 1374/1374 pass."
```

### Compact Form (Project Tag Implicit)

When the project context is obvious from the orchestrator's `run_context.root_name`
field (auto-injected by the MCP server), the project tag can be omitted:

```python
# Compact — project tag implicit:
notes="[CC1] Implemented lease renewal contract. 21/21 tests pass."

# Full — project tag explicit:
notes="[CC1] [claude-multi-ai] Implemented lease renewal contract. 21/21 tests pass."
```

Both are valid. The `run_context` block auto-added to every report includes
`root_name: "claude-multi-ai"`, providing project attribution even without
the inline tag.

### Status Variants

```python
# done — task completed successfully:
notes="[CC1] Added dispatch telemetry tests. 22 tests, all pass."

# blocked — cannot proceed, needs operator decision:
notes="[CC2] Blocked: docs/supervisor-troubleshooting.md does not exist. Need doc created first."

# needs_review — completed but needs human review:
notes="[CC1] Refactored engine._write_json to per-file methods. Needs review for edge cases."

# blocked — wrong session claimed task:
notes="[CC2] Wrong session claimed this. Reassign to CC1 stream."

# blocked — mistaken task:
notes="[CC1] Created by mistake. Blocking to remove from active queue."
```

---

## Gemini Examples

Gemini registers as `gemini` agent and does not use CC session labels.
Project tags follow the same `[project-name]` convention.

### Standard Gemini Report

```python
orchestrator_submit_report(
    task_id="TASK-def67890",
    agent="gemini",
    commit_sha="d4e5f6a",
    status="done",
    test_summary={"command": "npm test -- --runInBand", "passed": 42, "failed": 0},
    artifacts=["frontend/src/components/Dashboard.tsx", "frontend/src/hooks/useStatus.ts"],
    notes="[claude-multi-ai] Implemented dashboard pipeline card with live status polling."
)
```

### Gemini Variants

```python
# Feature implementation:
notes="[claude-multi-ai] Added agent activity table with presence indicators and task counts."

# Bug fix:
notes="[claude-multi-ai] Fixed blocker queue sort order — severity then age, descending."

# Blocked:
notes="Blocked: API endpoint for list_blockers returns wrong schema. Need backend fix first."

# Compact (project tag implicit):
notes="Implemented checkout UI with validation and loading/error states."
```

Gemini notes do not require session labels since there is typically one
Gemini session. If multiple Gemini instances run concurrently (future),
a similar `[G1]`/`[G2]` convention would apply.

---

## Valid vs Invalid Examples

### Valid Notes

| Note | Why Valid |
|------|----------|
| `[CC1] Added supervisor lifecycle smoke tests. 6 passed, 0 failed.` | Session label + description 10+ chars |
| `[CC2] [claude-multi-ai] Created operator cheat sheet for tmux pane mapping.` | Session label + project tag + description |
| `[CC3] Fixed supervisor clean command to remove restart counter files.` | Session label + description |
| `[CC1] Doc already existed. All acceptance criteria met by existing content.` | Session label + descriptive summary |
| `[claude-multi-ai] Added 18 lease transition tests covering claim-renew-expire lifecycle.` | Project tag + description (single-session, no CC label needed) |
| `Implemented checkout UI with validation and loading/error states.` | Gemini single-session, description sufficient |

### Invalid Notes

| Note | Error | Fix |
|------|-------|-----|
| `Added supervisor lifecycle smoke tests.` | Missing session label (multi-CC) | Prefix with `[CC1]` |
| `[CC1]` | Empty description | Add 10+ char summary |
| `[CC1] Done.` | Description too short (< 10 chars) | Expand: `[CC1] Done. All 12 tests pass, no regressions.` |
| `[cc1] Added tests.` | Wrong case — must be uppercase `CC` | Use `[CC1]` |
| `[Claude-1] Added tests.` | Wrong format — not `[CC1]`..`[CC3]` | Use `[CC1]` |
| `CC1 Added tests for feature X.` | Missing square brackets | Use `[CC1]` |
| `[CC4] Added more tests.` | Label out of range (max CC3) | Use `[CC1]`..`[CC3]` |

---

## Validation Rules

From the [report-note-linter-spec](report-note-linter-spec.md):

| Rule | Regex | Required |
|------|-------|----------|
| Session label present | `^\[CC[1-3]\]` | Yes (multi-CC only) |
| Project tag present | `\[claude-multi-ai\]` | Recommended |
| Non-empty description | `.{10,}` after labels | Yes |
| No task ID in note body | Should not repeat `TASK-xxx` | Advisory |

### Linter Pseudocode

```python
import re

def validate_report_note(note: str, multi_cc: bool = True) -> list[str]:
    errors = []
    if multi_cc and not re.match(r'^\[CC[1-3]\]', note):
        errors.append("Missing session label [CC1]/[CC2]/[CC3] at start")
    # Strip session label and optional project tag to get body
    body = re.sub(r'^\[CC[1-3]\]\s*(\[[\w-]+\]\s*)?', '', note)
    if len(body.strip()) < 10:
        errors.append("Description too short (min 10 chars)")
    return errors
```

---

## Auto-Injected Context

The MCP server automatically enriches every report with project context.
These fields provide attribution even when inline tags are omitted:

```json
{
  "run_context": {
    "run_id": "run-2026-02-26-001",
    "orchestrator_version": "0.1.0",
    "policy_name": "standard",
    "prompt_profile_version": "v2",
    "root_name": "claude-multi-ai"
  },
  "commit_metrics": {
    "collected": true,
    "commit_sha": "a1b2c3d",
    "files_changed": 3,
    "lines_added": 145,
    "lines_deleted": 12,
    "net_lines": 133,
    "provenance": "git"
  }
}
```

The `root_name` field serves as the authoritative project tag. Inline
`[claude-multi-ai]` tags in notes are a convenience for human readability
in audit log review, not the source of truth.

---

## Cross-Agent Consistency

All agents share the same report schema (`config/report.schema.json`):

| Field | CC | Gemini | Codex |
|-------|-----|--------|-------|
| `task_id` | Required | Required | Required |
| `agent` | `"claude_code"` | `"gemini"` | `"codex"` |
| `commit_sha` | Required | Required | Required |
| `status` | `done`/`blocked`/`needs_review` | Same | Same |
| `test_summary` | Required | Required | Required |
| `artifacts` | Optional | Optional | Optional |
| `notes` | Session label + description | Description | Description |

The only formatting difference is that Claude Code uses `[CC1]`..`[CC3]`
session labels in multi-session mode. All other fields are identical
across agents.

---

## References

- [report-note-linter-spec.md](report-note-linter-spec.md) — Linter validation rules
- [dual-cc-conventions.md](dual-cc-conventions.md) — Dual-session CC conventions
- [multi-cc-conventions.md](multi-cc-conventions.md) — Triple-CC labeling and queue hygiene
- [config/report.schema.json](../config/report.schema.json) — Report JSON schema
