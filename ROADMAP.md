# Roadmap

This document tracks planned direction for `agent-leader`.

## v0.2 - Stability
- Finalize one-shot connection workflow:
  - `orchestrator_connect_to_leader`
  - `orchestrator_connect_workers`
- Add server-side anti-spam guard for `claim_next_task` (cooldown/retry hint).
- Add `orchestrator_doctor` for root/policy/auth/connectivity checks.
- Harden docs for manual MCP-first workflow.

## v0.3 - UX
- Add slash-command bundles for common actions:
  - `/connect-to-leader`
  - `/manager-start`
  - `/worker-loop`
- Add clearer status summaries:
  - active workers
  - pending tasks
  - blockers
  - next actions
- Improve prompts/templates for manager and worker startup.

## v0.4 - Reliability
- Add stale-task reassignment policies (configurable thresholds).
- Add idempotent report handling (dedupe by task + commit).
- Add event retention/compaction with cursor safety.
- Improve reconnect behavior for interrupted sessions.

## v0.5 - Governance
- Add policy bundles:
  - strict QA
  - prototype/fast iteration
  - balanced default
- Add explicit risk gates for high-impact actions.
- Expand architecture-decision workflow templates and tie-break rules.

## v0.6 - Multi-Project Operations
- Add global config + per-repo override model.
- Add project registry for quick context switching.
- Add cross-project status/reporting view.

## v0.7 - Integrations
- GitHub integration:
  - open issues from orchestrator bugs
  - PR-ready summaries from reports
- CI integration:
  - consume CI test outcomes in validation cycle
  - attach logs/artifacts to reports

## v1.0 - Production Readiness
- Freeze MCP tool contract for compatibility.
- Add migration tooling for state schema evolution.
- Publish security hardening and least-privilege deployment guide.
- Finalize operational runbooks (incident/recovery/resume).

## Notes
- Prioritization may shift based on real-world usage.
- Near-term focus: reliability and lower operator overhead before new integrations.

## Progress Reporting Format
All project progress reports should include explicit percentages in this format:

- Overall project: `<n>%`
- Phase 1 (Architecture + Vertical Slice): `<n>%`
- Phase 2 (Content Pipeline): `<n>%`
- Phase 3 (Full Production): `<n>%`
- Backend vertical slice (`claude_code`): `<n>%`
- Frontend vertical slice (`gemini`): `<n>%`
- QA/validation completed: `<n>%`

Example:
- Overall project: `12%`
- Phase 1 (Architecture + Vertical Slice): `30%`
- Phase 2 (Content Pipeline): `0%`
- Phase 3 (Full Production): `0%`
- Backend vertical slice (`claude_code`): `25%`
- Frontend vertical slice (`gemini`): `20%`
- QA/validation completed: `5%`
