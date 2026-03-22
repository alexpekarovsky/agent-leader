# Lumen → Agent-Leader Integration Design

## System Flow

```
User: "I want feature X" (Telegram/CLI)
         |
         v
    LUMEN (meta-orchestrator)
    |-- 1. Clarify -- asks user questions via Telegram
    |-- 2. Consult -- multi-LLM design input (orchestrator_create_consult or internal)
    |-- 3. Plan -- synthesize into milestones
    |-- 4. Present -- Telegram inline buttons [Approve] [Edit] [Cancel]
    |-- 5. Write -- approved milestones to target project.yaml
    |-- 6. Deploy -- orchestrator_headless_start with team config
    |                |
    |                v
    |          AGENT-LEADER
    |          |-- Leader (headless) -- breaks milestones into tasks via plan_from_roadmap
    |          |-- Wingman (ccm) -- pure code reviewer, approves/rejects via review gate
    |          |-- Worker 1 (claude) -- implements tasks
    |          |-- Worker 2 (gemini) -- implements tasks
    |          |-- Worker 3 (codex) -- implements tasks (when tokens available)
    |          |-- Auto-stop when all_tasks_complete
    |                |
    |                v
    |-- 7. Monitor -- sprint_monitor proactive task (2-3min poll)
    |-- 8. Escalate -- blocker_monitor proactive task (60s poll -> Telegram buttons)
    |-- 9. Complete -- sprint summary -> Mem0 + Telegram notification
```

## Component Responsibilities

### Lumen (meta-orchestrator)
- Receives feature requests from user
- Drives clarification conversation
- Orchestrates multi-LLM consultation for plan quality
- Presents and manages approval flow
- Kicks off agent-leader teams via MCP tools
- Monitors progress and surfaces blockers
- Generates completion summaries
- Does NOT: break milestones into tasks, validate reports, review code

### Agent-Leader (execution engine)
- Receives milestones via project.yaml
- Leader breaks milestones into implementable tasks
- Workers claim and execute tasks
- Wingman reviews code quality (mandatory review gate)
- Manager auto-validates test results
- Reports progress via status tools and event bus
- Does NOT: interact with user directly, make product decisions

## Key Design Decisions

1. **Lumen creates milestones, Leader creates tasks** -- Lumen provides high-level features, leader has codebase context to break them into implementable units
2. **Plan stored in project.yaml** -- existing pipeline reads it, version controlled, visible in dashboard
3. **Consult via existing MCP tools** -- orchestrator_create_consult already handles multi-agent async
4. **Telegram inline buttons** for approval and blocker escalation
5. **Polling, not event-driven** -- clean MCP boundary, orchestrator_headless_status every 2-3 min
6. **Leader does task breakdown** -- plan_from_roadmap reads milestones, creates tasks with dedup

## Data Flow

```
LUMEN STATE                         AGENT-LEADER STATE
~/.lumen/state/sprint_state.json    state/tasks.json
~/.lumen/state/proactive_state.json state/blockers.json
Mem0 (sprint memories)              state/agents.json
                                    bus/events.jsonl
                                    project.yaml (milestones)

Lumen --[MCP: orchestrator_create_consult]--> Agent-Leader
Lumen --[file: project.yaml milestones]-----> Agent-Leader
Lumen --[MCP: orchestrator_headless_start]--> Agent-Leader
Lumen <--[MCP: orchestrator_headless_status]- Agent-Leader
Lumen <--[MCP: orchestrator_list_blockers]--- Agent-Leader
Lumen --[MCP: orchestrator_resolve_blocker]-> Agent-Leader
Lumen --[MCP: orchestrator_headless_stop]---> Agent-Leader
```

## Approval & Escalation Points

| Point | Trigger | User Action | Auto-Resolution |
|-------|---------|-------------|-----------------|
| Plan approval | Plan ready after consultation | Approve/Edit/Cancel buttons | None -- always requires user |
| Blocker escalation | Open blocker detected by polling | Resolve/Skip/Reassign buttons | Auto-skip after 30min if non-critical |
| Budget alert | Worker budget exhausted | Continue/Stop buttons | Auto-stop after 1h |
| Sprint stall | No progress for 30min | Investigate/Restart/Stop buttons | Always notifies user |
| Sprint completion | All tasks done | View summary | Auto-stop team, store to Mem0 |

## Default Team Template

```
Leader (any model, headless) -- manages, validates, plans
Wingman (claude/ccm) -- pure code reviewer, never implements
Worker 1 (gemini) -- fast for small/medium tasks
Worker 2 (claude lanes x3) -- better for complex architecture
Worker 3 (codex) -- when tokens available
```

## Implementation Sequence

Sprint 1 (P0): MCP wiring + /sprint command + sprint state tracker
Sprint 2 (P1): Sprint monitor + blocker escalation proactive tasks
Sprint 3 (P2): Multi-LLM consultation + plan approval flow
Sprint 4 (P3): Multi-project sprint support + dashboard card

## What Already Exists (80%)

All orchestrator MCP tools, headless supervisor, consult workflow, quality gates,
wingman review with set_review_gate, plan_from_roadmap, auto-stop on completion,
Lumen Telegram bot with inline buttons, ProactiveEngine, ProjectTracker.

## What Needs Building (20%)

P0: agent-leader MCP wiring in Lumen's .mcp.json + sandbox profile
P0: /sprint Telegram command (start/stop/status)
P0: sprint_state.json tracker
P1: sprint_monitor proactive task (poll headless_status)
P1: blocker_monitor proactive task (poll list_blockers -> Telegram buttons)
P2: Multi-LLM consultation flow using orchestrator_create_consult
P2: Sprint completion summary (new MCP tool or computed in Lumen)
P3: Multi-project sprint support (meta-orchestrator pattern)
