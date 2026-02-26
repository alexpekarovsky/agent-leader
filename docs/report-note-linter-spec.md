# Multi-CC Report-Note Linter Checklist

Validation rules for report notes during interim multi-session mode.
Ensures traceability before instance-aware swarm mode ships.

## Required fields in report notes

Every `submit_report` note should include:

1. **Session label**: `[CC1]`, `[CC2]`, or `[CC3]`
2. **Project tag**: `[claude-multi-ai]` or the project short name

## Format

```
[CC1] [claude-multi-ai] Implemented supervisor lifecycle smoke tests.
```

Or the compact form with project implicit from context:

```
[CC1] Implemented supervisor lifecycle smoke tests.
```

## Validation rules

| Rule | Regex pattern | Required |
|------|--------------|----------|
| Session label present | `^\[CC[1-3]\]` | Yes |
| Project tag present | `\[claude-multi-ai\]` | Recommended |
| Non-empty description | `.{10,}` after labels | Yes |
| No task ID in note body | Should not repeat `TASK-xxx` | Advisory |

## Examples

### Valid notes

```
[CC1] Added supervisor lifecycle smoke tests. 6 passed, 0 failed.
[CC2] [claude-multi-ai] Created operator cheat sheet for tmux pane mapping.
[CC3] Fixed supervisor clean command to remove restart counter files.
[CC1] Doc already existed. All acceptance criteria met by existing content.
```

### Invalid notes

```
# Missing session label
Added supervisor lifecycle smoke tests.

# Empty description
[CC1]

# Wrong label format
[cc1] Added tests.
[Claude-1] Added tests.

# Too short
[CC1] Done.
```

## Checker pseudocode

```python
import re

def validate_report_note(note: str) -> list[str]:
    errors = []
    if not re.match(r'^\[CC[1-3]\]', note):
        errors.append("Missing session label [CC1]/[CC2]/[CC3] at start")
    body = re.sub(r'^\[CC[1-3]\]\s*(\[[\w-]+\]\s*)?', '', note)
    if len(body.strip()) < 10:
        errors.append("Description too short (min 10 chars)")
    return errors
```

## When to use

- During any multi-CC session operation (2+ Claude Code sessions)
- Not required for single-session operation
- Not required after instance-aware mode ships (labels become automatic)

## References

- [multi-cc-partition-templates.md](multi-cc-partition-templates.md) — Session label definitions
- [triple-cc-assignment-board.md](triple-cc-assignment-board.md) — Board template with note examples
- [dual-cc-operation.md](dual-cc-operation.md) — Dual-session conventions
