#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PROJECT_ROOT="$ROOT_DIR"
SESSION_NAME="agents-autopilot"
MANAGER_INTERVAL=20
WORKER_INTERVAL=25
LOG_DIR="$PROJECT_ROOT/.autopilot-logs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --session) SESSION_NAME="$2"; shift 2 ;;
    --manager-interval) MANAGER_INTERVAL="$2"; shift 2 ;;
    --worker-interval) WORKER_INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

command -v tmux >/dev/null 2>&1 || { echo "tmux is required" >&2; exit 1; }
mkdir -p "$LOG_DIR"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "Session already exists: $SESSION_NAME" >&2
  exit 1
fi

tmux new-session -d -s "$SESSION_NAME" -n manager \
  "cd '$ROOT_DIR' && ./scripts/autopilot/manager_loop.sh --cli codex --project-root '$PROJECT_ROOT' --interval '$MANAGER_INTERVAL' --log-dir '$LOG_DIR'"
tmux split-window -h -t "$SESSION_NAME:manager" \
  "cd '$ROOT_DIR' && ./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code --project-root '$PROJECT_ROOT' --interval '$WORKER_INTERVAL' --log-dir '$LOG_DIR'"
tmux split-window -v -t "$SESSION_NAME:manager.1" \
  "cd '$ROOT_DIR' && ./scripts/autopilot/worker_loop.sh --cli gemini --agent gemini --project-root '$PROJECT_ROOT' --interval '$WORKER_INTERVAL' --log-dir '$LOG_DIR'"
tmux split-window -v -t "$SESSION_NAME:manager.0" \
  "cd '$ROOT_DIR' && ./scripts/autopilot/watchdog_loop.sh --project-root '$PROJECT_ROOT' --interval 15 --log-dir '$LOG_DIR'"
tmux new-window -t "$SESSION_NAME" -n monitor \
  \"cd '$PROJECT_ROOT' && watch -n 10 'echo project=$PROJECT_ROOT; ls -1 .autopilot-logs 2>/dev/null | tail -n 10; echo; codex mcp list | sed -n \\\"1,5p\\\"'\"

tmux select-layout -t "$SESSION_NAME:manager" tiled >/dev/null
echo "Started tmux session: $SESSION_NAME"
echo "Attach with: tmux attach -t $SESSION_NAME"
