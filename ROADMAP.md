# Roadmap

This document tracks planned direction for `agent-leader`.

## v0.2 - Stability
- Finalize one-shot connection workflow:
  - `orchestrator_connect_to_leader`
  - `orchestrator_connect_team_members`
- Add server-side anti-spam guard for `claim_next_task` (cooldown/retry hint).
- Add `orchestrator_doctor` for root/policy/auth/connectivity checks.
- Add project-aware and team-aware routing primitives:
  - task `project_root`/`project_name` tags and filters
  - `team_id` lanes and team-scoped claim routing
- Add MCP-native headless runtime lifecycle controls:
  - `orchestrator_headless_start`
  - `orchestrator_headless_stop`
  - `orchestrator_headless_status`
- Harden docs for manual MCP-first workflow.

## v0.3 - UX
- Add slash-command bundles for common actions:
  - `/connect-to-leader`
  - `/manager-start`
  - `/team-member-loop`
- Add clearer status summaries:
  - active team members
  - pending tasks
  - blockers
  - next actions
- Improve prompts/templates for manager and team member startup.
- **dashboard_tui.py efficiency overhaul**:
  - Replace busy-poll loop with kqueue/inotify file watching on bus/ directory
  - Only re-render when source data actually changes (hash comparison of snapshot)
  - Increase default `--refresh-seconds` from 2.0 to 5.0 (data doesn't change faster)
  - Add `--watch` mode using `select.kqueue()` (macOS) / `inotify` (Linux) for near-zero idle CPU
  - Current problem: 80-90% CPU per instance with `--refresh-seconds 1`, `build_snapshot()` does full I/O every tick

## v0.4 - Reliability
- Add stale-task reassignment policies (configurable thresholds).
- Add idempotent report handling (dedupe by task + commit).
- Add event retention/compaction with cursor safety.
- Improve reconnect behavior for interrupted sessions.

## v0.5 - Governance & Quality Gates
- Add policy bundles:
  - strict QA
  - prototype/fast iteration
  - balanced default
- Add explicit risk gates for high-impact actions.
- Expand architecture-decision workflow templates and tie-break rules.
- **Quality gate system** (ralph-inspired): automated "plankton" checker that runs between task completion and PR creation — catches architecture violations, missing tests, bad patterns, style/consistency issues.
- **Iterative self-review**: workers critique their own output 2-3 rounds before submitting to wingman/manager. Reduces review noise, catches obvious issues earlier.

## v0.6 - Multi-Project Operations
- Add global config + per-repo override model.
- Add project registry for quick context switching.
- Add cross-project status/reporting view.
- **Codebase comprehension phase** (ralph-inspired): `comprehend_project` task type where parallel workers map an unfamiliar codebase (file structure, key modules, patterns, dependencies) before planning begins. Output feeds into all subsequent task planning.

## v0.7 - Integrations
- GitHub integration:
  - open issues from orchestrator bugs
  - PR-ready summaries from reports
  - **Stacked/dependent PR chains** (ralph-inspired): when features span multiple PRs, auto-create base→child branch relationships with proper ordering
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
