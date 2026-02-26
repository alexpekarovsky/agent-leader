# Restart Verification Run Log

Template for recording a CORE-02 post-restart verification run. Copy this template, fill in each row, and attach as evidence for restart signoff.

## Run Metadata

| Field | Value |
|-------|-------|
| **Date** | YYYY-MM-DD HH:MM UTC |
| **Operator** | [name or session label] |
| **Restart reason** | [config change / crash recovery / system reboot / MCP restart] |
| **Restart method** | [`supervisor.sh start` / manual / tmux relaunch] |
| **Pre-restart commit** | [git SHA before restart] |

## Verification Steps

| # | Step | Command | Expected | Actual | Pass/Fail | Evidence |
|---|------|---------|----------|--------|-----------|----------|
| 1 | Status check | `orchestrator_status()` | All agents in `active_agents` | | | [paste active_agents list or screenshot ref] |
| 2 | Supervisor check | `supervisor.sh status` | All processes `running` | | | [paste status output or log ref] |
| 3 | Task recovery | `list_tasks(status="in_progress")` | No stuck pre-restart tasks | | | [task IDs if any, or "none"] |
| 4 | Log flow | `ls -lt .autopilot-logs/ \| head -5` | New files after restart time | | | [newest file timestamp] |
| 5 | Task flow | `list_tasks(status="assigned")` x2 (2 min gap) | Assigned count decreasing | | [count_1] -> [count_2] |

## Rollup

| Metric | Value |
|--------|-------|
| **Steps passed** | _/5 |
| **Steps failed** | _/5 |
| **Overall** | PASS / FAIL |
| **Remediation needed** | [none / describe] |

## Failure Detail

_Fill in only for failed steps. Delete this section if all steps pass._

| Failed Step | Root Cause | Action Taken | Resolved? |
|-------------|-----------|--------------|-----------|
| Step _ | | | YES / NO |

## Remediation Actions

_Actions taken to fix failures before re-running verification._

- [ ] [action 1]
- [ ] [action 2]

## Re-verification

_If any step failed and was remediated, record the re-run here._

| # | Step | Re-run Result | Evidence |
|---|------|---------------|----------|
| _ | | PASS / FAIL | |

## Signoff

| Role | Name | Date | Approved |
|------|------|------|----------|
| Operator | | | YES / NO |

## Notes

_Any additional context, warnings, or observations from this restart._

## References

- [post-restart-verification.md](post-restart-verification.md) — Verification flowchart and step details
- [restart-milestone-checklist.md](restart-milestone-checklist.md) — Broader restart context
- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) — Fix guidance for failed steps
