# Dashboard MVP Rollout Checklist

> Operator-facing checklist for introducing the dashboard MVP after
> instance-aware status (CORE-02) lands. This is a docs-only rollout
> gate -- no code ships until every prerequisite is checked.

## Prerequisites

All items must be complete before dashboard MVP work begins.

- [ ] **CORE-02 accepted** -- instance-aware status verified via
      `orchestrator_status` returning per-instance `agent_instances`
      and `active_agent_identities` (see [core-02-acceptance-packet.md](core-02-acceptance-packet.md))
- [ ] **Status field glossary reviewed** -- operators confirm
      [operator-status-field-glossary.md](operator-status-field-glossary.md)
      covers all fields surfaced in the dashboard (active, idle, stale,
      disconnected, verified, instance_id)
- [ ] **Data provenance labels finalized** -- label set in
      [dashboard-provenance-labels.md](dashboard-provenance-labels.md) approved
      (STATUS, TASKS, AGENTS, AUDIT, WATCHDOG, BUS, SYNTHETIC, SNAPSHOT)
- [ ] **Alert taxonomy agreed upon** -- severity scale, response times, and
      source-to-alert mapping in
      [operator-alert-taxonomy.md](operator-alert-taxonomy.md) signed off
- [ ] **Command palette shortcuts mapped** -- every shortcut in
      [dashboard-command-palette.md](dashboard-command-palette.md) confirmed to
      map to a working MCP tool (`s`=status, `t`=tasks, `a`=agents, `b`=blockers,
      `g`=bugs, `l`=audit, `m`=manager cycle, `r`=reassign, `w`=watchdog)

## Validation

Perform these checks against mock data before exposing the dashboard to operators.

- [ ] **Mock data renders correctly for all panels** -- use examples from
      [dashboard-mock-data-examples.md](dashboard-mock-data-examples.md) to
      verify Task Pipeline, Agent Activity, Blocker Queue, Alert Panel,
      Metrics Summary, and Audit Log Browser all render without errors
- [ ] **Degraded-mode alerts display properly** -- inject watchdog
      `stale_task` and `state_corruption_detected` events; confirm alert panel
      shows correct severity, source label, and suggested action (reference
      [dashboard-degraded-mode-alerts.md](dashboard-degraded-mode-alerts.md))
- [ ] **Normal vs degraded summaries distinguishable** -- side-by-side
      comparison of a healthy run (0 stale, 0 corruption, all agents active)
      versus a degraded run (2+ stale tasks, 1 agent offline); verify visual
      differentiation matches
      [dashboard-normal-vs-degraded.md](dashboard-normal-vs-degraded.md)
- [ ] **Provenance labels visible on each panel** -- every panel shows its
      `[SOURCE - Ns ago]` badge per the display guidelines in
      [dashboard-provenance-labels.md](dashboard-provenance-labels.md)
- [ ] **Audit log browser filters work** -- filter by tool name
      (`orchestrator_submit_report`) and by status (`error`) using
      `orchestrator_list_audit_logs`; confirm results match raw JSONL

## Post-Launch (First 24 Hours)

- [ ] **Operator feedback collected after 24h** -- structured feedback on:
      panel usefulness (1-5 per panel), missing information, confusing labels,
      false-positive alerts
- [ ] **Alert thresholds tuned based on real data** -- compare default
      timeouts (assigned: 180s, in_progress: 900s, reported: 180s) against
      observed task durations; adjust if false-positive rate exceeds 10%
- [ ] **Dashboard data contract gaps prioritized** -- review
      [dashboard-data-contract-gaps.md](dashboard-data-contract-gaps.md) in
      light of operator feedback; re-rank Priority 1-3 gaps and assign to
      roadmap phases

## References

- [data-source-trust-matrix.md](data-source-trust-matrix.md) -- source
  authority, freshness, and conflict resolution
- [restart-milestone-checklist.md](restart-milestone-checklist.md) --
  completion gates for the restart milestone (prerequisite infrastructure)
- [dashboard-content-priority.md](dashboard-content-priority.md) -- panel
  priority ranking and justifications
- [dashboard-data-contract-gaps.md](dashboard-data-contract-gaps.md) -- known
  backend gaps blocking advanced panels
