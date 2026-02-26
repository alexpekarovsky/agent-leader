# Dashboard: Normal vs Degraded Mode Summaries

One-screen ASCII dashboard mockups for four operational scenarios. Use these as reference when interpreting `orchestrator_live_status_report` output and deciding on operator next actions.

## Scenario 1: Normal -- All Agents Active, Tasks Flowing

```
+---------------------------------------------------------------+
|  ORCHESTRATOR DASHBOARD              2026-02-26 14:05 UTC      |
+---------------------------------------------------------------+
|  AGENTS            STATUS     TASK           HEARTBEAT         |
|  codex (leader)    active     --             5s ago            |
|  claude_code       active     TASK-a1b2c3    8s ago            |
|  gemini            active     TASK-d4e5f6    12s ago           |
+---------------------------------------------------------------+
|  TASK PIPELINE                                                 |
|  assigned:  2    in_progress:  2    reported:  1    done:  5   |
|  blocked:   0    bug_open:     0                               |
+---------------------------------------------------------------+
|  BLOCKERS: 0 open                                              |
+---------------------------------------------------------------+
|  PROGRESS          Phase 1: 100%  Phase 2: 60%  Phase 3: 0%   |
|  Overall: 45%      Backend: 55%   Frontend: 35%  QA: 40%      |
+---------------------------------------------------------------+
|  ALERTS: none                                                  |
+---------------------------------------------------------------+
```

**Interpretation:** Healthy state. Both workers are claiming and progressing tasks. No blockers. Pipeline is moving.

**Operator next actions:**
- No intervention needed
- Run `orchestrator_manager_cycle` on normal cadence
- Monitor for reported tasks awaiting validation

## Scenario 2: Worker Offline -- Gemini Down, Frontend Stalled

```
+---------------------------------------------------------------+
|  ORCHESTRATOR DASHBOARD              2026-02-26 14:05 UTC      |
+---------------------------------------------------------------+
|  AGENTS            STATUS     TASK           HEARTBEAT         |
|  codex (leader)    active     --             5s ago            |
|  claude_code       active     TASK-a1b2c3    8s ago            |
|  gemini            OFFLINE    TASK-d4e5f6    1820s ago         |
+---------------------------------------------------------------+
|  TASK PIPELINE                                                 |
|  assigned:  3    in_progress:  1    reported:  0    done:  4   |
|  blocked:   0    bug_open:     0                               |
+---------------------------------------------------------------+
|  BLOCKERS: 0 open                                              |
+---------------------------------------------------------------+
|  PROGRESS          Phase 1: 100%  Phase 2: 40%  Phase 3: 0%   |
|  Overall: 35%      Backend: 50%   Frontend: 10%  QA: 30%      |
+---------------------------------------------------------------+
|  ALERTS:                                                       |
|  [WARN] gemini offline -- last seen 30m ago                    |
|  [WARN] TASK-d4e5f6 lease expired (owned by gemini)            |
|  [WARN] 2 frontend tasks assigned, none in_progress            |
+---------------------------------------------------------------+
```

**Interpretation:** Gemini is offline. Its in-progress task has an expired lease. Frontend workstream is stalled because gemini was the frontend worker.

**Operator next actions:**
1. Run `orchestrator_reassign_stale_tasks` to move gemini's tasks to claude_code
2. Attempt to restart gemini session and reconnect
3. If gemini cannot restart, re-route frontend tasks to claude_code via `orchestrator_set_claim_override`
4. Run `orchestrator_manager_cycle` to recover the expired lease

## Scenario 3: Blocker Spike -- 10+ Open Blockers, Agents Idle

```
+---------------------------------------------------------------+
|  ORCHESTRATOR DASHBOARD              2026-02-26 14:05 UTC      |
+---------------------------------------------------------------+
|  AGENTS            STATUS     TASK           HEARTBEAT         |
|  codex (leader)    active     --             5s ago            |
|  claude_code       idle       --             10s ago           |
|  gemini            idle       --             15s ago           |
+---------------------------------------------------------------+
|  TASK PIPELINE                                                 |
|  assigned:  0    in_progress:  0    reported:  0    done:  3   |
|  blocked:  12    bug_open:     0                               |
+---------------------------------------------------------------+
|  BLOCKERS: 12 open                                             |
|  BLK-001  high    claude_code  "Need DB schema decision"       |
|  BLK-002  high    gemini       "API auth method unclear"       |
|  BLK-003  medium  claude_code  "Which test framework?"         |
|  ... (+9 more)                                                 |
+---------------------------------------------------------------+
|  PROGRESS          Phase 1: 100%  Phase 2: 15%  Phase 3: 0%   |
|  Overall: 20%      Backend: 20%   Frontend: 10%  QA: 0%       |
+---------------------------------------------------------------+
|  ALERTS:                                                       |
|  [CRIT] 12 open blockers -- all work halted                    |
|  [WARN] Both workers idle with no claimable tasks              |
+---------------------------------------------------------------+
```

**Interpretation:** All remaining tasks are blocked. Workers are idle because there is nothing to claim. This is a decision bottleneck, not a technical failure.

**Operator next actions:**
1. Run `orchestrator_list_blockers(status="open")` to see all blocker questions
2. Triage blockers by severity: resolve `high` blockers first
3. Provide decisions via `orchestrator_resolve_blocker` for each
4. After resolving blockers, tasks will automatically return to assigned status
5. Workers will pick up work on their next `claim_next_task` call

## Scenario 4: Queue Jam -- All Tasks Assigned, None Claimed

```
+---------------------------------------------------------------+
|  ORCHESTRATOR DASHBOARD              2026-02-26 14:05 UTC      |
+---------------------------------------------------------------+
|  AGENTS            STATUS     TASK           HEARTBEAT         |
|  codex (leader)    active     --             5s ago            |
|  claude_code       active     --             8s ago            |
|  gemini            active     --             12s ago           |
+---------------------------------------------------------------+
|  TASK PIPELINE                                                 |
|  assigned:  8    in_progress:  0    reported:  0    done:  2   |
|  blocked:   0    bug_open:     0                               |
+---------------------------------------------------------------+
|  BLOCKERS: 0 open                                              |
+---------------------------------------------------------------+
|  PROGRESS          Phase 1: 100%  Phase 2: 10%  Phase 3: 0%   |
|  Overall: 18%      Backend: 15%   Frontend: 10%  QA: 0%       |
+---------------------------------------------------------------+
|  ALERTS:                                                       |
|  [WARN] 8 tasks assigned, 0 in_progress                       |
|  [WARN] claude_code active but not claiming tasks              |
|  [WARN] gemini active but not claiming tasks                   |
+---------------------------------------------------------------+
```

**Interpretation:** Workers are alive (heartbeats healthy) but not claiming tasks. This typically indicates a routing or policy issue: tasks may be assigned to the wrong agent, or workers are not calling `claim_next_task`.

**Operator next actions:**
1. Check task ownership: `orchestrator_list_tasks(status="assigned")` -- verify tasks are assigned to active agents
2. Check for owner mismatch: if all 8 tasks are assigned to `gemini` but gemini is not claiming, use `orchestrator_set_claim_override` to redirect
3. Verify workers are in their claim loop (check worker logs or send a test event)
4. If routing policy is wrong, reassign tasks manually or adjust workstream assignments
5. As a last resort, run `orchestrator_reassign_stale_tasks` to redistribute the queue

## Summary: Scenario-to-Action Map

| Scenario | Key signal | First action |
|----------|-----------|--------------|
| Normal | All green, tasks flowing | No action -- routine manager cycle |
| Worker offline | Agent heartbeat > threshold | `reassign_stale_tasks`, restart agent |
| Blocker spike | Many open blockers, idle workers | Triage and resolve blockers |
| Queue jam | Tasks assigned but none claimed | Check routing, verify claim loops |
