# Supervisor Prototype Readiness Summary Template

Quick-decision template for operators evaluating whether the supervisor
prototype is ready for the next restart test.

## Template

```markdown
## Supervisor Readiness Assessment — [DATE]

### Decision: [ ] GO  [ ] NO-GO

### Acceptance matrix rollup
| Category | Pass | Fail | Skip | Status |
|----------|------|------|------|--------|
| Core lifecycle (L1-L5) | _/5 | _/5 | _ | PASS / FAIL |
| Recovery (R1-R4) | _/4 | _/4 | _ | PASS / FAIL |
| Observability (O1-O4) | _/4 | _/4 | _ | PASS / FAIL |
| Error handling (E1-E3) | _/3 | _/3 | _ | PASS / FAIL |
| **Total** | _/16 | _/16 | _ | **PASS / FAIL** |

### Automated test results
| Suite | Passed | Failed | Command |
|-------|--------|--------|---------|
| Unit tests | _ | _ | `python3 -m unittest discover tests -v` |
| Smoke tests | _ | _ | `bash scripts/autopilot/smoke_test.sh` |

### Known gaps (accepted risks)
- [ ] No auto-restart on crash (manual restart required)
- [ ] No PID reuse detection (clean after reboot)
- [ ] No per-process restart (restart-all only)
- [ ] No instance-aware identity (shared agent name)
- [ ] Other: ___

### Blockers (must fix before GO)
- (none)

### Operator notes
[Any additional context for the GO/NO-GO decision]
```

## Filled example

```markdown
## Supervisor Readiness Assessment — 2026-02-26

### Decision: [x] GO  [ ] NO-GO

### Acceptance matrix rollup
| Category | Pass | Fail | Skip | Status |
|----------|------|------|------|--------|
| Core lifecycle (L1-L5) | 5/5 | 0/5 | 0 | PASS |
| Recovery (R1-R4) | 4/4 | 0/4 | 0 | PASS |
| Observability (O1-O4) | 4/4 | 0/4 | 0 | PASS |
| Error handling (E1-E3) | 2/3 | 0/3 | 1 | PASS |
| **Total** | 15/16 | 0/16 | 1 | **PASS** |

### Automated test results
| Suite | Passed | Failed | Command |
|-------|--------|--------|---------|
| Unit tests | 92 | 0 | `python3 -m unittest discover tests -v` |
| Smoke tests | 12 | 0 | `bash scripts/autopilot/smoke_test.sh` |

### Known gaps (accepted risks)
- [x] No auto-restart on crash (manual restart required)
- [x] No PID reuse detection (clean after reboot)
- [x] No per-process restart (restart-all only)
- [x] No instance-aware identity (shared agent name)

### Blockers (must fix before GO)
- (none)

### Operator notes
E3 (SIGKILL fallback) skipped — requires manual signal trap setup.
All other tests pass. Supervisor handles start/stop/status/clean
reliably. Ready for restart test with manual monitoring.
```

## GO criteria

All of these must be true for a GO decision:

1. **Zero failures** in acceptance matrix (skips are OK if documented)
2. **Zero failures** in automated test suites
3. **No open blockers** that affect restart safety
4. **Known gaps documented** and accepted as risks
5. **Operator available** for manual monitoring during test

## NO-GO criteria

Any of these triggers NO-GO:

- Any acceptance matrix failure
- Automated test failures
- Open blocker affecting supervisor lifecycle
- Unaccepted risk without workaround

## References

- [supervisor-acceptance-matrix.md](supervisor-acceptance-matrix.md) — Full test matrix
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — Known gaps
- [supervisor-test-plan.md](supervisor-test-plan.md) — Failure injection tests
- [milestone-evidence-collection.md](milestone-evidence-collection.md) — Evidence capture
