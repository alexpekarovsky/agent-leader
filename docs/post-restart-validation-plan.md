# Post-Restart Validation Script Plan

Spec for a validation script that verifies system health after a
restart — covering instance-aware status, lease recovery, and no-op
diagnostics.  This script is designed to run once the AUTO-M1 core
features (instance-aware presence and task leases) land.

## Purpose

After restarting the supervisor or tmux session, operators need
confidence that:

1. All agents re-registered with correct identity
2. In-progress tasks resumed or were safely requeued
3. No orphaned leases block future claims
4. The orchestrator state is consistent

This script automates those checks.

## Prerequisites (AUTO-M1 core tasks)

This validation script depends on features not yet shipped:

| Feature | Status | Task |
|---------|--------|------|
| Instance-aware agent presence | Planned (Phase B) | AUTO-M1-CORE-01 |
| Task lease expiry | Planned (Phase B) | AUTO-M1-CORE-02 |
| Deterministic dispatch contract | Planned (Phase B) | Roadmap Phase B |

Until these land, the script should degrade gracefully — running
available checks and skipping instance/lease checks with clear
warnings.

## Planned checks

### 1. Agent registration status

```
CHECK: All expected agents are registered and verified
  - codex: verified=true, role=leader
  - claude_code: verified=true, role=team_member
  - gemini: verified=true, role=team_member
```

**Instance-aware extension:** When instance IDs land, also verify:
- Each instance has a unique `instance_id`
- No stale instances from the previous session remain
- Heartbeat ages are within expected bounds

### 2. Task state consistency

```
CHECK: No tasks in invalid states
  - No tasks with status=in_progress and owner not registered
  - No tasks with status=assigned older than assigned_timeout
  - No tasks with status=reported older than reported_timeout
```

**Lease-aware extension:** When task leases land, also verify:
- No expired leases on in-progress tasks
- Lease holder matches current instance registration
- Expired leases triggered automatic requeue

### 3. No-op manager cycle

```
CHECK: Manager cycle completes without side effects
  - Run orchestrator_manager_cycle(strict=true)
  - Verify no tasks were reassigned (stable state)
  - Verify no stale agents flagged
  - Verify pending_total matches expected count
```

This confirms the manager can run a full cycle without unexpected
mutations — proving the state is clean.

### 4. Event bus continuity

```
CHECK: Event bus is readable and cursors are valid
  - Poll events for each agent with timeout_ms=1000
  - Verify no decode errors
  - Verify cursor positions are within log bounds
```

### 5. Log directory health

```
CHECK: Log directory is writable and recent
  - .autopilot-logs/ exists and is writable
  - log_check.sh --strict passes
  - Most recent log file is within expected age
```

## Expected outputs

### All checks pass

```
Post-restart validation: 5/5 checks passed
  PASS  Agent registration (3 agents verified)
  PASS  Task state consistency (0 issues)
  PASS  No-op manager cycle (stable, 12 pending)
  PASS  Event bus continuity (3 cursors valid)
  PASS  Log directory health (writable, 4 recent files)
```

### Partial failure

```
Post-restart validation: 3/5 checks passed
  PASS  Agent registration (3 agents verified)
  FAIL  Task state consistency: 2 tasks in_progress with unregistered owner
  PASS  No-op manager cycle (stable, 12 pending)
  SKIP  Instance-aware presence (not yet implemented)
  PASS  Log directory health (writable, 4 recent files)
```

### Graceful degradation (pre-Phase B)

```
Post-restart validation: 3/5 checks passed (2 skipped)
  PASS  Agent registration (3 agents, instance_id not available)
  PASS  Task state consistency (0 issues, lease checks skipped)
  PASS  No-op manager cycle (stable)
  SKIP  Instance-aware presence (requires AUTO-M1-CORE-01)
  SKIP  Lease recovery (requires AUTO-M1-CORE-02)
```

## Implementation notes

- Script location: `scripts/autopilot/post_restart_check.sh`
- Calls orchestrator MCP tools via the codex CLI (or directly via
  Python if MCP client is available)
- Bounded runtime: each check has a 30s timeout
- Exit code: 0 if all non-skipped checks pass, 1 otherwise
- JSONL output option for machine-readable results

## References

- [roadmap.md](roadmap.md) — Phase B instance-aware presence
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Supervisor commands
- [supervisor-test-plan.md](supervisor-test-plan.md) — Failure scenarios
- [troubleshooting-autopilot.md](troubleshooting-autopilot.md) — Manual checks
