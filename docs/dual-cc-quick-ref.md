# Dual Claude Code — Quick Reference Card

Short operator reference for running two Claude Code sessions (CC1 + CC2) under shared `claude_code` identity. For full details see [dual-cc-operation.md](dual-cc-operation.md) and [dual-cc-conventions.md](dual-cc-conventions.md).

> **Interim workaround** — all collision issues resolve when `instance_id` ships in Phase B (AUTO-M1-CORE-01, done).

## Session Labels

| Session | Label | Example note prefix |
|---------|-------|-------------------|
| First (primary) | CC1 | `[CC1] Implemented feature X` |
| Second | CC2 | `[CC2] Added smoke test Y` |

## Claiming Tasks

| Do | Don't |
|----|-------|
| Use `set_claim_override` to direct tasks | Race both sessions on `claim_next_task` |
| Set one override, claim, then set the next | Set two overrides back-to-back (second replaces first) |
| Check `in_progress` before reassigning | Call `reassign_stale_tasks` with low thresholds |

## Report Notes

Always prefix with session label:

```
notes="[CC1] Added retry logic. 5/5 tests pass."
notes="[CC2] Created supervisor docs bundle."
```

## Conflict Avoidance

- **Same branch**: both sessions commit to the same branch
- **Different files**: assign tasks touching different parts of the codebase
- **Pull before commit**: `git pull --rebase` before committing
- **Heartbeat**: both sessions share one slot — cosmetic only, no action needed

## Stream Assignment

| Stream | Who takes it | Rationale |
|--------|-------------|-----------|
| Smoke tests / QA | CC1 | Tests need sequential runs; one owner avoids flaky conflicts |
| Docs | CC2 | Docs are independent files with minimal overlap |
| Backend / features | Either | Use claim overrides to partition |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Status shows stale `claude_code` | Other session's heartbeat overwrote yours | Both sessions call heartbeat — cosmetic only |
| Override claimed by wrong session | Both sessions raced `claim_next_task` | Clear override, re-set, have target session claim first |
| Git conflict on commit | Both sessions edited same file | `git pull --rebase`, resolve, re-commit |
| Task stuck `in_progress` | Other session may be working on it | Check logs before reassigning |

## References

- [dual-cc-operation.md](dual-cc-operation.md) — Full collision analysis
- [dual-cc-conventions.md](dual-cc-conventions.md) — Labels, prefixes, etiquette
- [swarm-mode.md](swarm-mode.md) — Phase B instance-aware resolution
