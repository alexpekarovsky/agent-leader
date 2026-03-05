#!/usr/bin/env bash
# Autopilot supervisor — thin wrapper delegating to orchestrator.supervisor.
#
# Usage:
#   ./scripts/autopilot/supervisor.sh start   [options]
#   ./scripts/autopilot/supervisor.sh stop     [options]
#   ./scripts/autopilot/supervisor.sh status   [options]
#   ./scripts/autopilot/supervisor.sh restart  [options]
#   ./scripts/autopilot/supervisor.sh clean    [options]   # remove stale pids + supervisor logs
#   ./scripts/autopilot/supervisor.sh monitor  [options]   # watch for dead processes and restart
#   ./scripts/autopilot/headless_status.sh --watch [--interval N] [--project-root DIR]
#
# Options:
#   --project-root DIR        Project root (default: repo root)
#   --log-dir DIR             Log directory (default: .autopilot-logs)
#   --pid-dir DIR             PID file directory (default: .autopilot-pids)
#   --manager-cli-timeout N   Manager CLI timeout in seconds (default: 300)
#   --worker-cli-timeout N    Worker CLI timeout in seconds (default: 600)
#   --manager-interval N      Manager loop interval (default: 20)
#   --worker-interval N       Worker loop interval (default: 25)
#   --leader-agent AGENT      Leader agent id (default: codex)
#   --leader-cli CLI          Leader CLI (default: derived from leader agent)
#   --wingman-agent AGENT     Wingman agent id (default: ccm)
#   --wingman-cli CLI         Wingman CLI (default: claude)
#   --claude-project-root DIR Worker project root for claude_code (default: --project-root)
#   --gemini-project-root DIR Worker project root for gemini (default: --project-root)
#   --codex-project-root DIR  Worker project root for codex worker (default: --project-root)
#   --wingman-project-root DIR Worker project root for wingman (default: --project-root)
#   --claude-team-id ID       Team id for claude_code worker lane
#   --gemini-team-id ID       Team id for gemini worker lane
#   --codex-team-id ID        Team id for codex worker lane
#   --wingman-team-id ID      Team id for wingman worker lane
#   --extra-worker SPEC       Extra worker: name:cli:agent:team_id:project_root[:lane]
#   --max-restarts N          Max restarts before giving up on a process (default: 5)
#   --backoff-base N          Base backoff seconds on restart (default: 10)
#   --backoff-max N           Max backoff seconds (default: 120)
#   --monitor-interval N      Monitor loop interval in seconds (default: 30)
#
# Processes managed:
#   manager   — manager_loop.sh (leader agent)
#   wingman   — worker_loop.sh (claude / ccm, qa lane)
#   claude    — worker_loop.sh (claude / claude_code)
#   gemini    — worker_loop.sh (gemini / gemini)
#   codex_worker — worker_loop.sh (codex / codex, only when codex is not leader)
#   watchdog  — watchdog_loop.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 is required to run the supervisor." >&2
  exit 1
fi

# Delegate to the Python runtime module, passing all arguments through.
cd "$ROOT_DIR"
exec python3 -c "from orchestrator.supervisor import main; raise SystemExit(main())" "$@"
