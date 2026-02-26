# Restart Milestone Burnup Tracker

Tracks AUTO-M1 task completion for the "near-automatic restart" milestone. Update this doc as tasks complete to maintain an accurate progress view.

## Progress Formula

```
Milestone % = (done tasks / total tasks) x 100
```

Tasks counted: all tasks with `AUTO-M1` prefix in the title.

Current as of last update: **10 / 41 done = 24%**

> **Note**: The total may grow as supporting tasks are added. The formula always uses the current total.

## Summary by Category

| Category | Done | In Progress | Assigned | Total |
|----------|------|-------------|----------|-------|
| CORE (infrastructure) | 1 | 0 | 5 | 6 |
| CORE-SUPPORT (tests) | 0 | 0 | 17 | 17 |
| OPS (docs + checkers) | 9 | 2 | 7 | 18 |
| **Total** | **10** | **2** | **12** | **41** |

## Task List

### CORE — Infrastructure Changes

| Status | Task ID | Title |
|--------|---------|-------|
| Done | TASK-13a1fc1d | AUTO-M1-CORE-01 Instance ID support in registration/heartbeat/connect |
| Assigned | TASK-8549aa05 | AUTO-M1-CORE-02 Instance-aware status section for multi-session visibility |
| Assigned | TASK-6ba3bbac | AUTO-M1-CORE-03 Lease schema and issue lease on claim |
| Assigned | TASK-38077836 | AUTO-M1-CORE-04 Lease expiry recovery in manager/watchdog |
| Assigned | TASK-488d43c4 | AUTO-M1-CORE-05 Deterministic dispatch telemetry scaffolding |
| Assigned | TASK-da4ca8bb | AUTO-M1-CORE-06 No-op diagnostic on manager execute timeout |

### CORE-SUPPORT — Tests for Core Changes

| Status | Task ID | Title |
|--------|---------|-------|
| Assigned | TASK-9e25ee39 | CORE-SUPPORT-01 Instance ID fallback derivation precedence tests |
| Assigned | TASK-1a420e37 | CORE-SUPPORT-02 Active agent identities status payload tests |
| Assigned | TASK-e5d65eda | CORE-SUPPORT-03 Connect-to-leader instance ID round-trip tests |
| Assigned | TASK-0a24b9d4 | CORE-SUPPORT-04 Heartbeat metadata merge preserving instance ID |
| Assigned | TASK-b938dac9 | CORE-SUPPORT-05 List agents exposing instance ID tests |
| Assigned | TASK-8ddc5bf1 | CORE-SUPPORT-06 Discover agents instance-aware identity tests |
| Assigned | TASK-eae7058d | CORE-SUPPORT-07 Status handler backward compatibility tests |
| Assigned | TASK-57e3e2bc | CORE-SUPPORT-08 Instance ID fallback default format tests |
| Assigned | TASK-a2a07aad | CORE-SUPPORT-09 Register agent storing explicit instance ID tests |
| Assigned | TASK-3750c4ad | CORE-SUPPORT-10 Heartbeat explicit instance ID override tests |
| Assigned | TASK-4ade3c1c | CORE-SUPPORT-11 Lease schema test plan doc |
| Assigned | TASK-c47bd4ef | CORE-SUPPORT-13 Identity snapshot instance ID tests |
| Assigned | TASK-61d0d436 | CORE-SUPPORT-14 Status payload empty list behavior tests |
| Assigned | TASK-9eb5bdb9 | CORE-SUPPORT-15 Instance ID visibility through list agents filter |
| Assigned | TASK-618ff5a9 | CORE-SUPPORT-16 Identity snapshot project root/cwd coexistence |
| Assigned | TASK-6962fb47 | CORE-SUPPORT-17 Active agent identities field ordering stability |
| Assigned | TASK-07cf0bb3 | CORE-SUPPORT-12 Dispatch telemetry schema doc examples |

### OPS — Documentation and Checkers

| Status | Task ID | Title |
|--------|---------|-------|
| Done | TASK-439df85f | AUTO-M1-OPS-01 Supervisor prototype |
| Done | TASK-b67894d8 | AUTO-M1-OPS-02 Supervisor docs + CLI spec |
| Done | TASK-1926cd03 | AUTO-M1-OPS-03 Supervisor smoke test |
| Done | TASK-035a1655 | AUTO-M1-OPS-04 Dual-CC interim workflow doc |
| Done | TASK-936a3c5f | AUTO-M1-OPS-05 Docs consistency checker |
| Done | TASK-f80d5756 | AUTO-M1-OPS-06 Supervisor cleanup command |
| Done | TASK-1ea47cf6 | AUTO-M1-OPS-08 Restart milestone checklist |
| Done | TASK-7804d491 | AUTO-M1-OPS-12 Dual-CC quick reference card |
| Done | TASK-e3e2384f | AUTO-M1-OPS-13 Supervisor log naming conventions doc |
| In Progress | TASK-02cfdca2 | AUTO-M1-OPS-16 Milestone burnup tracker (this doc) |
| In Progress | TASK-b23083b9 | AUTO-M1-OPS-19 Supervisor startup profile examples |
| Done | TASK-9ca0ac62 | AUTO-M1-OPS-18 Post-restart verification flowchart |
| Assigned | TASK-8e60e9b0 | AUTO-M1-OPS-20 Checker for supervisor startup profiles |
| Assigned | TASK-571cb97b | AUTO-M1-OPS-21 Milestone acceptance evidence collection |
| Assigned | TASK-7cfc8143 | AUTO-M1-OPS-22 Checker for lease schema test plan |
| Assigned | TASK-50506abf | AUTO-M1-OPS-23 Checker for dispatch telemetry examples |
| Assigned | TASK-62b14a53 | AUTO-M1-OPS-24 Supervisor demo runbook quick mode |
| Assigned | TASK-743455a6 | AUTO-M1-OPS-25 Checker for demo runbook commands |
| Assigned | TASK-b97c6f0f | AUTO-M1-OPS-26 Milestone communication template |
| Assigned | TASK-2af05fbe | AUTO-M1-OPS-27 Checker for communication template |
| Assigned | TASK-d3b55f76 | AUTO-M1-OPS-28 Supervisor known limitations doc |
| Assigned | TASK-359db709 | AUTO-M1-OPS-29 Checker for known limitations references |

## How to Update

After completing a task, update the relevant row's status and recalculate the summary:

1. Change the task's status cell from `Assigned` or `In Progress` to `Done`
2. Update the category summary table counts
3. Recalculate: `Milestone % = done / total x 100`
4. Update the "Current as of last update" line

## Milestone Completion Criteria

The milestone is complete when:

- All CORE tasks are done (instance ID, leases, dispatch telemetry)
- All CORE-SUPPORT tests pass and are committed
- All OPS docs and checkers are committed
- Full smoke test suite passes: `./scripts/autopilot/smoke_test.sh`

## References

- [restart-milestone-checklist.md](restart-milestone-checklist.md) — Operator restart procedure
- [post-restart-verification.md](post-restart-verification.md) — Post-restart validation flowchart
- [roadmap.md](roadmap.md) — Architecture roadmap phases
