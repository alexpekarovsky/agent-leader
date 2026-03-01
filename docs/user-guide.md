# User Guide

This guide is for operators using `agent-leader` in daily work.

It supports two flows:

1. Interactive flow (`connect to leader`) for supervised operation.
2. Headless flow (`autopilot` loops) for autonomous cycle execution.

## Which Flow To Use

- Use interactive flow when you want tighter manual control, frequent steering, or debugging.
- Use headless flow when tasks are well-defined and you want continuous execution cycles.

## Flow A: Interactive (Connect To Leader)

### 1. Install MCP server

```bash
cd /Users/alex/claude-multi-ai
./scripts/install_agent_leader_mcp.sh --all
```

### 2. Open three terminals in the same project

- Terminal 1: `codex` (leader/manager)
- Terminal 2: `claude` (worker)
- Terminal 3: `gemini` (worker)

### 3. Connect workers

In each worker terminal, ask to connect to leader with identity metadata.

### 4. Leader handshake + tasking

From leader:
- `orchestrator_connect_team_members`
- `orchestrator_create_task`
- workers claim via `orchestrator_claim_next_task`
- workers report via `orchestrator_submit_report`
- leader validates via `orchestrator_validate_task`

### 5. Monitor status

Use:
- `orchestrator_status`
- `orchestrator_live_status_report`
- `orchestrator_list_tasks`
- `orchestrator_list_blockers`

## Flow B: Headless (Autopilot Swarm)

### What this means in plain language

Headless mode is a background team runner.

- One leader loop keeps orchestration moving.
- Worker loops keep claiming tasks, coding, and reporting.
- Wingman loop handles QA lane behavior.
- You can route different workers to different projects and teams under one leader.

### 1. Dry run first (always)

```bash
cd /Users/alex/claude-multi-ai
./scripts/autopilot/team_tmux.sh --dry-run
```

### 2. Start headless loops

Option A (`tmux`):

```bash
./scripts/autopilot/team_tmux.sh
tmux attach -t agents-autopilot
```

Option B (`supervisor`):

```bash
./scripts/autopilot/supervisor.sh start --project-root /Users/alex/claude-multi-ai
./scripts/autopilot/supervisor.sh status --project-root /Users/alex/claude-multi-ai
```

### 3. Single leader + multiple teams (new)

Use one leader and assign each worker lane a `team_id`.
Tasks with that `team_id` are claimed by that lane.

Example: one leader with two product teams under it.

```bash
./scripts/autopilot/supervisor.sh start \
  --project-root /Users/alex/claude-multi-ai \
  --leader-agent claude_code \
  --gemini-team-id team-web \
  --codex-team-id team-api \
  --wingman-team-id team-api \
  --gemini-project-root /Users/alex/my-web \
  --codex-project-root /Users/alex/my-api \
  --wingman-project-root /Users/alex/my-api
```

If you need extra workers beyond the default lanes, add `--extra-worker`:

```bash
./scripts/autopilot/supervisor.sh start \
  --project-root /Users/alex/claude-multi-ai \
  --extra-worker teamapi2:claude:claude_code:team-api:/Users/alex/my-api:default \
  --extra-worker teamweb2:gemini:gemini:team-web:/Users/alex/my-web:default
```

`--extra-worker` format:

`name:cli:agent:team_id:project_root[:lane]`

- `lane` can be `default` or `wingman`
- `name` must be unique
- `team_id` must match tasks you create

### 4. Seed work (required)

Create tasks with `project_root`, `project_name`, and `team_id`.

Example task creation fields:

- `title`: `"Add /health endpoint"`
- `workstream`: `"backend"`
- `owner`: `"codex"` (or routed owner)
- `project_root`: `"/Users/alex/my-api"`
- `project_name`: `"my-api"`
- `team_id`: `"team-api"`
- `tags`: `["api","p1"]`

Workers claim by owner plus team lane.
The system also auto-tags tasks with:

- `project:<project_name>`
- `workstream:<workstream>`
- `team:<team_id>` (when team is set)

### 5. Observe and recover

```bash
./scripts/autopilot/log_check.sh
tail -n 100 .autopilot-logs/supervisor-manager.log
./scripts/autopilot/headless_status.sh --watch --project-root /Users/alex/claude-multi-ai
```

If needed:

```bash
./scripts/autopilot/supervisor.sh restart --project-root /Users/alex/claude-multi-ai
```

### 6. Filtering and checks

Use MCP filters to see exactly one team/project:

- `orchestrator_list_tasks(project_name="my-api", team_id="team-api")`
- `orchestrator_list_tasks(tags=["team:team-api","project:my-api"])`

## Should This Be Two Separate Apps?

Short answer: not yet.

Recommended now:
- Keep one core orchestrator.
- Expose two productized entrypoints:
  1. `agent-leader interactive`
  2. `agent-leader swarm`

Split into two apps only when these diverge in:
- release cadence,
- state model,
- permissions/safety model,
- or support ownership.

Today both flows share the same task/state/event core, so splitting now would increase maintenance cost without major user benefit.

## Quick Commands

```bash
# Current status
codex mcp get agent-leader-orchestrator

# Show orchestrator status
# (run from any connected agent session)
orchestrator_status

# List active work
orchestrator_list_tasks(status="in_progress")
```
