# Mixed project_root Examples

Status examples showing mixed `project_root` values when multiple agent instances run on one machine. These scenarios arise when an agent connects to the orchestrator with a cwd that does not match the manager's project.

## Example 1: Two claude_code instances, different projects

CC1 is working on the orchestrator project. CC2 was started in a different repo by mistake.

```
orchestrator_list_agents(active_only=false)
```

```json
{
  "agents": [
    {
      "agent": "codex",
      "status": "active",
      "last_seen": "2026-02-26T14:00:05Z",
      "verified": true,
      "same_project": true,
      "project_root": "/Users/alex/claude-multi-ai"
    },
    {
      "agent": "claude_code",
      "status": "active",
      "last_seen": "2026-02-26T14:00:03Z",
      "verified": true,
      "same_project": true,
      "project_root": "/Users/alex/claude-multi-ai",
      "note": "CC1 -- backend worker"
    },
    {
      "agent": "claude_code",
      "status": "active",
      "last_seen": "2026-02-26T14:00:02Z",
      "verified": true,
      "same_project": false,
      "project_root": "/Users/alex/Projects/retro-mystery",
      "note": "CC2 -- WRONG PROJECT"
    }
  ]
}
```

**What to notice:**
- CC2 shows `same_project: false` because its `project_root` is `/Users/alex/Projects/retro-mystery`
- The manager (codex) has `project_root: /Users/alex/claude-multi-ai`
- CC2 will not receive task assignments through normal routing because the orchestrator treats non-same-project agents as external

**Operator action:** Restart CC2 in the correct directory (`/Users/alex/claude-multi-ai`) and reconnect.

## Example 2: Three agents, all same project (normal state)

All agents correctly connected to the same codebase.

```json
{
  "agents": [
    {
      "agent": "codex",
      "status": "active",
      "verified": true,
      "same_project": true,
      "project_root": "/Users/alex/claude-multi-ai"
    },
    {
      "agent": "claude_code",
      "status": "active",
      "verified": true,
      "same_project": true,
      "project_root": "/Users/alex/claude-multi-ai"
    },
    {
      "agent": "gemini",
      "status": "active",
      "verified": true,
      "same_project": true,
      "project_root": "/Users/alex/claude-multi-ai"
    }
  ]
}
```

**What to notice:**
- Every agent has `same_project: true` and `verified: true`
- All `project_root` values match
- This is the expected healthy state -- no action required

## Example 3: Gemini with stale project_root after restart

Gemini was restarted but its reconnection metadata still carries the old project_root from a previous session.

```json
{
  "agents": [
    {
      "agent": "codex",
      "status": "active",
      "verified": true,
      "same_project": true,
      "project_root": "/Users/alex/claude-multi-ai"
    },
    {
      "agent": "claude_code",
      "status": "active",
      "verified": true,
      "same_project": true,
      "project_root": "/Users/alex/claude-multi-ai"
    },
    {
      "agent": "gemini",
      "status": "stale",
      "verified": false,
      "same_project": false,
      "project_root": "/Users/alex/old-experiment",
      "last_seen": "2026-02-26T13:45:00Z"
    }
  ]
}
```

**What to notice:**
- Gemini shows `verified: false` -- the reconnection did not complete with valid metadata
- `same_project: false` because the stale metadata still points to `/Users/alex/old-experiment`
- `status: stale` confirms the heartbeat has not been refreshed since the restart

**Operator action:**
1. Verify gemini's actual working directory in its terminal
2. Have gemini call `orchestrator_connect_to_leader` with correct metadata including `cwd: /Users/alex/claude-multi-ai`
3. Confirm `same_project` flips to `true` after reconnection

## Interpretation Guidance

When you see mixed `project_root` values in agent listings:

| Check | How | Expected |
|-------|-----|----------|
| `same_project` field | `orchestrator_list_agents` or `orchestrator_discover_agents` | `true` for all workers |
| Agent cwd | Ask agent or check terminal session | Matches manager project_root |
| Reconnection | `orchestrator_connect_to_leader` with correct metadata | `verified: true`, `same_project: true` |

**Common causes of project_root mismatch:**
- Agent terminal opened in wrong directory
- Agent restarted without `cd` to project root first
- Stale metadata from a previous session persisting after crash
- Copy-paste error in launch script pointing to old path

**Resolution steps:**
1. Identify which agent has the wrong project_root (look for `same_project: false`)
2. Verify the agent's actual working directory
3. Reconnect the agent with the correct `cwd` in its metadata payload
4. Confirm the fix: re-run `orchestrator_list_agents` and check all agents show `same_project: true`
