# Idle Gate Benchmark Certification

**Date**: 2026-03-14
**Certifier**: claude_code (Claude Opus 4.6)
**Task**: TASK-811474e3

## Objective

Prove >= 90% reduction in headless control-plane LLM calls during idle operation
after implementing idle gate (TASK-3315cd37) and exponential backoff (TASK-d9f2d7f6).

## Before: Baseline (no idle gate)

Without idle gate, every loop cycle invokes the LLM CLI (`codex`, `claude`, `gemini`)
regardless of whether actionable work exists.

**Manager loop** (default interval=20s):
- 1 LLM invocation per cycle
- 3 cycles/minute = **180 LLM calls/hour** idle

**Worker loop** (default interval=25s):
- 1 LLM invocation per cycle
- ~2.4 cycles/minute = **144 LLM calls/hour** idle per worker

**Combined (1 manager + 2 workers)**: ~**468 LLM calls/hour** idle

## After: With idle gate + exponential backoff

With idle gate enabled, the preflight check reads `state/tasks.json` directly
(~1ms, no LLM, no MCP). When no work is found:

1. **LLM CLI is NOT invoked** (verified by 22 regression tests)
2. **Backoff progression**: 30s -> 60s -> 120s -> 300s -> 900s (15 min max)
3. **Max-idle auto-exit**: configurable cycle limit for clean shutdown

**Manager loop idle calls**: **0 LLM calls/hour**
**Worker loop idle calls**: **0 LLM calls/hour** (per worker)
**Combined**: **0 LLM calls/hour** idle

## Reduction Calculation

```
Before: 468 LLM calls/hour (idle)
After:    0 LLM calls/hour (idle)
Reduction: 100% (468/468)
```

Target was >= 90%. Achieved **100%** reduction in idle LLM invocations.

## Test Evidence

```
$ .venv/bin/python3 -m pytest tests/test_idle_gate_and_backoff.py -v
22 passed in 14.32s
```

Key test assertions:
- `test_no_tasks_file_skips_llm`: CLI stub marker file NOT created (worker + manager)
- `test_no_assigned_tasks_skips_llm`: CLI stub marker file NOT created
- `test_max_idle_cycles_exit`: clean exit with rc=0, no LLM invocation
- `test_assigned_task_invokes_llm`: CLI stub marker file IS created (confirms gate passes when work exists)
- `BackoffIntervalTests`: 8 tests verify progression 30->60->120->300->900

## Mechanism

### Preflight check (no LLM, no MCP)

Worker (`worker_loop.sh:worker_has_claimable_work`):
```python
# Reads state/tasks.json directly, filters by owner/status/team_id/lane
# Returns exit 0 if work found, exit 1 if idle
```

Manager (`manager_loop.sh:manager_has_actionable_work`):
```python
# Reads state/tasks.json directly
# Returns exit 0 if any task has status in {assigned, reported, bug_open, blocked}
```

### Gate logic

```bash
if [[ "$ONCE" != true ]]; then
  if ! worker_has_claimable_work; then    # <-- no LLM call
    idle_streak=$((idle_streak + 1))
    sleep_s="$(backoff_interval_for_streak ...)"
    log INFO "idle gate: no claimable work ..."
    sleep_with_jitter "$sleep_s"
    continue                               # <-- skip run_cli_prompt entirely
  fi
  idle_streak=0                            # <-- reset on work found
fi
run_cli_prompt ...                         # <-- only reached when work exists
```

## Residual Risk

- **File I/O**: preflight reads `tasks.json` on every cycle. On very large task
  lists (>10K tasks) this could add latency, but current scale is well under 1K.
- **Stale reads**: if tasks.json is updated between the preflight check and the
  LLM invocation, the cycle may run with slightly outdated information. This is
  acceptable because the LLM will re-check via MCP tools.
- **--once mode**: the idle gate is bypassed in `--once` mode (smoke tests). This
  is by design to allow runbook validation to always execute one full cycle.

## Commit

- Idle gate + backoff: `507ec03` (feat: add idle gate, exponential backoff, and daily budget)
- Budget status exposure: included in this certification commit

## Certification

The idle gate implementation achieves **100% reduction** in LLM calls during idle
headless operation, exceeding the >= 90% target. The reduction is deterministic,
regression-tested (22 tests), and observable via log markers.
