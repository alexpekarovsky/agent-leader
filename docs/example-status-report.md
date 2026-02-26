# Example One-Page Status Report

> Sample combining overall project %, AUTO-M1 milestone %, team status,
> and queue health for operator updates.

---

## Project Status — 2026-02-26T15:30:00Z

### Progress

| Metric | Value | Notes |
|---|---|---|
| **Overall project** | 72% | 213 of 297 tasks done |
| **AUTO-M1 milestone** | 100% | 198/198 — all core, docs, exec tasks complete |
| Phase 1 (Architecture + Vertical Slice) | 72% | Includes AUTO-M1 + RETRO tasks |
| Phase 2 (Content Pipeline) | 0% | Not started |
| Phase 3 (Full Production) | 0% | Not started |

### Vertical Slices

| Slice | Progress | Blocker |
|---|---|---|
| Backend (RETRO-BE) | 91% | Minor: placeholder asset refs |
| Frontend (RETRO-FE) | 0% | Gemini offline |
| QA/Validation | 72% | Tracking overall completion |

### Pipeline Health

| Indicator | Count | Status |
|---|---|---|
| Reported (pending review) | 0 | Clear |
| Open blockers | 10 | Needs triage |
| Open bugs | 5 | Under investigation |
| Stale in-progress (>30m) | 0 | Healthy |

### Team

| Agent | Role | Status | Current Work |
|---|---|---|---|
| codex | Manager | Active | RETRO-QA-01, RETRO-BE-01 |
| claude_code | Team member | Active | DOCS tasks (mirrored from gemini) |
| gemini | Team member | Offline | Last seen 2026-02-21 |

### Key Decisions

- AUTO-M1 milestone **complete** — all 198 tasks validated
- Gemini frontend tasks mirrored to claude_code while gemini is offline
- RETRO-series tasks (game hardening) in progress

### Next Actions

1. Resolve 10 open blockers (codex triage)
2. Complete RETRO-BE-01/02 (codex)
3. Continue DOCS mirror tasks (claude_code)
4. Reconnect gemini for frontend work

---

*Generated from `orchestrator_status()` + `live_status_report()`*
