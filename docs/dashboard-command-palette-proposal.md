# Dashboard MVP Command Palette Proposal

> CLI shortcut set for an eventual operator dashboard using existing
> MCP tools. Ranked by frequency of operator need.

## Top Actions (Tier 1 — Every Session)

| Shortcut | Tool | Description | Backend Support |
|---|---|---|---|
| `s` | `orchestrator_status` | Full status snapshot with %, agents, tasks | Exists |
| `t` | `orchestrator_list_tasks` | Task list (filterable by status/owner) | Exists |
| `b` | `orchestrator_list_blockers` | Open blockers queue | Exists |
| `g` | `orchestrator_list_bugs` | Bug list | Exists |
| `a` | `orchestrator_list_agents` | Agent presence and instance details | Exists |

**Rationale:** These five views cover the operator's primary questions: "What's the state?", "What's stuck?", "Who's online?"

## Common Actions (Tier 2 — Multiple Times Per Session)

| Shortcut | Tool | Description | Backend Support |
|---|---|---|---|
| `tf` | `orchestrator_list_tasks --status=in_progress` | In-flight tasks only | Exists (filter param) |
| `tb` | `orchestrator_list_tasks --status=blocked` | Blocked tasks | Exists (filter param) |
| `tr` | `orchestrator_list_tasks --status=reported` | Pending review | Exists (filter param) |
| `al` | `orchestrator_list_audit_logs --limit=20` | Recent audit trail | Exists |
| `e` | `orchestrator_poll_events` | Latest events | Exists |

## Task Management (Tier 3 — As Needed)

| Shortcut | Tool | Description | Backend Support |
|---|---|---|---|
| `ct` | `orchestrator_create_task` | Create new task | Exists |
| `cn` | `orchestrator_claim_next_task` | Claim next for agent | Exists |
| `sr` | `orchestrator_submit_report` | Submit task report | Exists |
| `vt` | `orchestrator_validate_task` | Manager validates task | Exists |
| `rb` | `orchestrator_raise_blocker` | Raise a blocker | Exists |

## Manager Operations (Tier 4 — Leader Only)

| Shortcut | Tool | Description | Backend Support |
|---|---|---|---|
| `mc` | `orchestrator_manager_cycle` | Run manager cycle | Exists |
| `rs` | `orchestrator_reassign_stale_tasks` | Reassign stale work | Exists |
| `lr` | `orchestrator_live_status_report` | Update live percentages | Exists |
| `co` | `orchestrator_set_claim_override` | Force next claim target | Exists |

## Needs New Backend Support

| Proposed Shortcut | What It Would Do | Missing Backend |
|---|---|---|
| `w` | Show watchdog alerts | No `list_watchdog_alerts` MCP tool |
| `tl` | Task lifecycle timeline | No aggregated timestamp chain |
| `p50` | Percentile task durations | Only averages available |
| `util` | Agent utilization rates | Not instrumented |
| `hist` | Task status history | No state transition query |

## Implementation Notes

- All Tier 1-4 shortcuts map to existing MCP tools — no new backend needed
- Shortcut keys chosen for single-hand reach on QWERTY layout
- Dashboard can be implemented as a TUI wrapper calling these tools
- Refresh cadence: Tier 1 auto-refreshes every 10s, others on-demand
