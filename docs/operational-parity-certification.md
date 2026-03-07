# Operational Parity Certification

Date: 2026-03-07  
Project: `/Users/alex/Projects/agent-leader`

## Scope

Certification covers operational parity between interactive MCP control paths and headless runtime control for day-to-day swarm operations.

## Completed Parity Items

- MCP lifecycle controls now include:
  - `orchestrator_headless_start`
  - `orchestrator_headless_stop`
  - `orchestrator_headless_status`
  - `orchestrator_headless_restart`
  - `orchestrator_headless_clean`
- Runtime-control responses are machine-readable and audit-friendly.
- Status parity matrix and gap analysis documented in `docs/parity-plan.md`.
- Role/project-scope regression protections locked with targeted tests.

## Validation Evidence

### Targeted parity/regression suites

```bash
./.venv/bin/python -m pytest -q \
  tests/test_headless_mcp_tools.py \
  tests/test_manager_and_project_scope_regression.py \
  tests/test_status_payload_fixture.py \
  tests/test_team_lane_counters.py
```

Result: `25 passed in 0.12s`

### Full suite

```bash
./.venv/bin/python -m pytest -q
```

Result: `1634 passed, 83 subtests passed in 123.45s (0:02:03)`

## Residual Risks

- MCP tool transport can intermittently drop (`Transport closed`) in this environment, requiring process/session rebinding.  
  Core implementation parity is complete, but runtime session stability should continue to be monitored in live usage.

## Certification Verdict

Operational parity for core interactive/headless control is complete for current scope, with the above transport stability caveat.
