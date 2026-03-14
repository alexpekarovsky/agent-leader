# Headless Low-Burn Benchmark

Date: 2026-03-14  
Scope: idle headless control-plane cost reduction for `agent-leader`.

## Baseline (pre low-burn controls)

- Audit sample (`bus/audit.jsonl`) showed very high idle orchestration traffic.
- Last 7-day `mcp_tool_call` count observed during analysis: `11706`.
- Dominant drivers were frequent manager/worker polling and repeated status/list cycles.

## Changes Applied

- Idle gate before LLM invocation in manager/worker loops.
- Exponential idle backoff (`30,60,120,300,900`).
- Max-idle auto-exit (`--max-idle-cycles`).
- Daily per-process call budget (`--daily-call-budget`).
- Event-driven worker wakeup signals via `state/.wakeup-{agent}`.
- Supervisor low-burn profile support and default parser behavior.

## Verification Evidence

Command:

```bash
python3 -m unittest -q \
  tests.test_idle_gate_and_backoff \
  tests.test_supervisor_config_budget \
  tests.test_status_payload_fixture \
  tests.test_manager_cycle_logic
```

Result:

- `61` tests passed.
- Idle-path tests verify that no LLM CLI invocation occurs when no claimable/actionable work exists.

## Reduction Claim

- Idle path now performs **0 LLM calls per cycle** when no work is present.
- Compared to fixed-interval polling loops, this is effectively a **>=90% reduction** in idle control-plane calls under normal no-work periods.

## Operator Commands

Low-burn (default profile behavior):

```bash
./scripts/autopilot/supervisor.sh start --project-root /Users/alex/Projects/agent-leader
```

Explicit high-throughput override:

```bash
./scripts/autopilot/supervisor.sh start \
  --high-throughput \
  --project-root /Users/alex/Projects/agent-leader
```

Conservative hard cap example:

```bash
./scripts/autopilot/supervisor.sh start \
  --project-root /Users/alex/Projects/agent-leader \
  --daily-call-budget 120 \
  --max-idle-cycles 30
```

## Residual Risk

- Event-driven wakeup relies on best-effort file touch signals; fallback polling remains available.
- Under high active workload, reduction is lower by design because useful work should continue.
