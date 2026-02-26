# Three-Worker FAQ

FAQ addendum for operating with 3 workers: three Claude Code sessions (CC1/CC2/CC3) or two Claude Code sessions plus Gemini (CC1/CC2/Gemini). Extends [dual-cc-conventions.md](dual-cc-conventions.md) and multi-cc-conventions.md.

---

**Q1: Can 3 Claude Code sessions share the `claude_code` identity?**

Yes. All three sessions register as `claude_code` with the orchestrator. The orchestrator treats them as one logical agent for task ownership and routing purposes. To distinguish them operationally, use the CC1/CC2/CC3 labels defined in multi-cc-conventions.md. Tag all report notes with `[CC1]`, `[CC2]`, or `[CC3]` so the manager and reviewers can trace which session did the work.

This is an interim workaround. When `instance_id` ships in Phase B (see Q7), each session will have a unique identifier.

---

**Q2: How do I distinguish CC1/CC2/CC3 in reports?**

Use the report note tag convention:

```
notes="[CC1] Implemented lease schema. 8/8 tests pass."
notes="[CC2] Created supervisor troubleshooting doc."
notes="[CC3] Ran full smoke test suite. 99/99 pass."
```

In dashboards and operator logs, refer to sessions by label (CC1, CC2, CC3) or by workstream role (CC-backend, CC-docs, CC-qa). The orchestrator itself does not distinguish them -- the labels are a human convention applied in notes and commit messages.

See [dual-cc-conventions.md](dual-cc-conventions.md) for the full labeling scheme.

---

**Q3: What happens to claim overrides with 3 sessions?**

`orchestrator_set_claim_override` targets the `claude_code` agent identity, not a specific session. When you set a claim override for `claude_code`, whichever CC session calls `claim_next_task` first will pick up that task. You cannot target CC2 specifically with a claim override.

**Workaround:** Coordinate claim order verbally or via operator notes. For example, instruct CC1 to claim next while CC2 and CC3 wait. Alternatively, partition workstreams so each session only claims from its assigned lane.

---

**Q4: Can a 3-worker setup handle the full task queue?**

Yes, but with caveats:

| Setup | Throughput | Best for |
|-------|-----------|----------|
| CC1 + CC2 + CC3 | High parallel throughput, but all share one agent identity | Sprint bursts where traceability can use note tags |
| CC1 + CC2 + Gemini | Better identity separation (2 agents), mixed model strengths | Sustained operation where gemini handles frontend |

Three workers can process the full queue faster than two. The bottleneck shifts from worker count to: manager validation speed, blocker resolution time, and claim coordination (avoiding duplicate claims when sessions race).

---

**Q5: What if one of three workers goes stale?**

The orchestrator detects staleness at the agent level, not the session level. If one CC session goes stale but another CC session is still heartbeating, the `claude_code` agent will appear active. The stale session's in-progress task will have an expiring lease.

**Detection:** Look for tasks with expired leases whose owner (`claude_code`) is still active. This signals one session died while others are healthy.

**Recovery:**
1. `orchestrator_manager_cycle` will recover the expired lease
2. The task returns to `assigned` status
3. One of the remaining healthy CC sessions will claim it on next cycle
4. Restart the failed session and reconnect

See instance-aware-status-fields.md for how instance-level staleness will work after Phase B.

---

**Q6: How does heartbeat work with 3 instances of the same agent?**

All three sessions call `orchestrator_heartbeat(agent="claude_code")`. Each call updates the same agent record's `last_seen` timestamp. This means:

- If CC1 heartbeats at T+0, CC2 at T+5, CC3 at T+10, the agent shows last_seen = T+10
- If CC3 dies at T+10, CC1 and CC2 continue heartbeating -- the agent never appears stale
- If all three die, the agent goes stale after `stale_after_seconds` from the last heartbeat

**Implication:** A single session failure is invisible at the agent level. You must rely on lease expiry to detect per-session failures. This is a known limitation addressed by instance_id in Phase B.

---

**Q7: What changes when instance_id ships in Phase B?**

With `instance_id`, each session gets a unique identifier (e.g., `claude_code#worker-01`, `claude_code#worker-02`, `claude_code#worker-03`). This changes:

| Capability | Before (current) | After (Phase B) |
|-----------|------------------|-----------------|
| Heartbeat | Shared per agent | Per instance |
| Staleness detection | Agent-level only | Per instance |
| Claim override | Targets agent | Can target specific instance |
| Task ownership | `claude_code` (ambiguous) | `claude_code#worker-02` (precise) |
| Dashboard display | One row per agent | One row per instance |

The CC1/CC2/CC3 label convention becomes unnecessary -- instance_id replaces it with a system-level distinction. See instance-aware-status-fields.md for the planned field schema.

---

## Related Docs

- [dual-cc-conventions.md](dual-cc-conventions.md) -- Session labeling and report note prefixes for 2 CC sessions
- multi-cc-conventions.md -- Extended conventions for 2-3 CC sessions, queue hygiene
- instance-aware-status-fields.md -- Planned instance-level status fields for Phase B
