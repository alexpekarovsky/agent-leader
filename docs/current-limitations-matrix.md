# Current Limitations Matrix

Summary of MVP limitations, their impact on operations, available workarounds, and planned fixes from the roadmap.

## Identity and Presence

| Limitation | Impact | Workaround | Planned Fix |
|-----------|--------|------------|-------------|
| Agent identity is name-based (`claude_code`), not instance-based | Cannot safely run 2 workers of the same CLI type | Run one worker per CLI type; use manual partitioning for dual-CC (see [dual-cc-operation.md](dual-cc-operation.md)) | Phase B: `instance_id` per running loop (e.g., `claude_code#worker-01`) |
| Single heartbeat slot per agent name | Second session overwrites first session's metadata | Both sessions call heartbeat periodically; cosmetic only | Phase B: per-instance heartbeat slots |
| No presence timeout auto-disconnect | Stale agent entries persist until overwritten | Manual check via `orchestrator_status()` | Phase B: instance-aware stale detection |

## Task Lifecycle

| Limitation | Impact | Workaround | Planned Fix |
|-----------|--------|------------|-------------|
| No task leases or expiry | Crashed worker leaves task stuck in `in_progress` | Watchdog detects; operator manually reassigns or uses `reassign_stale_tasks` | Phase C: lease with `expires_at`, auto-requeue on expiry |
| No automatic task retry on failure | Failed task stays failed until manually re-assigned | Bug loop via manager validation; manual `update_task_status` back to `assigned` | Phase C: retry policy with configurable max attempts |
| No task priority or ordering | Tasks are claimed in insertion order | Create high-priority tasks first; use `set_claim_override` for urgent tasks | Future: priority field with weighted claim |
| No workstream-filtered claiming | `claim_next_task` returns any available task | Manual partitioning via overrides or agent prompts | Future: workstream-aware claim API |

## Communication

| Limitation | Impact | Workaround | Planned Fix |
|-----------|--------|------------|-------------|
| No dispatch acknowledgment | Manager can't confirm worker received an event | Check worker logs directly; use `poll_events` in worker loop | Phase D: correlation ID and ack window |
| Events are best-effort delivery | Silent failures invisible to manager | Watchdog detects stale tasks as indirect signal | Phase D: `dispatch.noop` diagnostic on timeout |
| No cross-project routing | Each project needs its own MCP server | Run separate MCP instances per project | Future: multi-project orchestrator |

## Process Management

| Limitation | Impact | Workaround | Planned Fix |
|-----------|--------|------------|-------------|
| No auto-restart on crash | Crashed loop stays down until operator intervenes | Monitor via `supervisor.sh status` or tmux panes; manual restart | Phase C: supervisor auto-restart with backoff |
| No per-process restart in supervisor | `restart` stops and starts all 4 processes | Use tmux for per-pane restart; or stop/start individually | Phase B: per-instance supervisor control |
| No health check beyond PID | `status` only checks if PID is alive, not if process is responsive | Check logs for recent output; watchdog for task progress | Future: signal-based health check |
| PID reuse after reboot | Stale PID file may match a different process | `supervisor.sh clean` removes stale PIDs; check manually | Future: store process start time alongside PID |

## State and Storage

| Limitation | Impact | Workaround | Planned Fix |
|-----------|--------|------------|-------------|
| No task deletion API | Unwanted tasks cannot be removed from `tasks.json` | Block with cancellation note (see [task-queue-hygiene.md](task-queue-hygiene.md)) | By design — preserves audit trail |
| State files are local JSON | No concurrent access safety across machines | Run one MCP server per project on one machine | Future: database-backed state |
| Watchdog is read-only | Cannot auto-fix state corruption, only report | Engine self-heals on next MCP read; manual fix as fallback | Future: watchdog write capability with safety guards |
| Log pruning is per-loop | No global retention policy across all log types | Each loop manages its own prefix; `log_check.sh` for overview | Future: global retention configuration |

## Roadmap Phase Summary

| Phase | Focus | Key capabilities added |
|-------|-------|----------------------|
| **A (MVP)** | Current state | Single-team autopilot, watchdog, supervisor, smoke tests |
| **B** | Instance-aware presence | `instance_id`, multi-instance workers, per-instance status |
| **C** | Task leases and recovery | Lease expiry, auto-requeue, auto-restart with backoff |
| **D** | Deterministic dispatch | Correlation IDs, ack windows, observable delivery |

See [docs/roadmap.md](roadmap.md) for full phase details.

## References

- [docs/swarm-mode.md](swarm-mode.md) — Detailed phase prerequisites
- [docs/roadmap.md](roadmap.md) — Architecture roadmap
- [docs/headless-mvp-architecture.md](headless-mvp-architecture.md) — Component overview with limitations table
- [docs/dual-cc-operation.md](dual-cc-operation.md) — Workarounds for identity limitation
