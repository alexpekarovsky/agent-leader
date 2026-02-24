#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PROJECT_ROOT="$ROOT_DIR"
SESSION_NAME="agents-autopilot"
MANAGER_INTERVAL=20
WORKER_INTERVAL=25
LOG_DIR="$PROJECT_ROOT/.autopilot-logs"
DRY_RUN=false
MANAGER_CLI_TIMEOUT=300
WORKER_CLI_TIMEOUT=600

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --session) SESSION_NAME="$2"; shift 2 ;;
    --manager-interval) MANAGER_INTERVAL="$2"; shift 2 ;;
    --worker-interval) WORKER_INTERVAL="$2"; shift 2 ;;
    --manager-cli-timeout) MANAGER_CLI_TIMEOUT="$2"; shift 2 ;;
    --worker-cli-timeout) WORKER_CLI_TIMEOUT="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ "$DRY_RUN" != true ]]; then
  command -v tmux >/dev/null 2>&1 || { echo "tmux is required" >&2; exit 1; }
fi
mkdir -p "$LOG_DIR"
chmod +x "$ROOT_DIR"/scripts/autopilot/*.sh >/dev/null 2>&1 || true

if [[ "$DRY_RUN" != true ]] && tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "Session already exists: $SESSION_NAME" >&2
  exit 1
fi

ROOT_Q="$(printf '%q' "$ROOT_DIR")"
PROJECT_Q="$(printf '%q' "$PROJECT_ROOT")"
LOG_Q="$(printf '%q' "$LOG_DIR")"

MANAGER_CMD="cd $ROOT_Q && ./scripts/autopilot/manager_loop.sh --cli codex --project-root $PROJECT_Q --interval '$MANAGER_INTERVAL' --cli-timeout '$MANAGER_CLI_TIMEOUT' --log-dir $LOG_Q"
CLAUDE_CMD="cd $ROOT_Q && ./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code --project-root $PROJECT_Q --interval '$WORKER_INTERVAL' --cli-timeout '$WORKER_CLI_TIMEOUT' --log-dir $LOG_Q"
GEMINI_CMD="cd $ROOT_Q && ./scripts/autopilot/worker_loop.sh --cli gemini --agent gemini --project-root $PROJECT_Q --interval '$WORKER_INTERVAL' --cli-timeout '$WORKER_CLI_TIMEOUT' --log-dir $LOG_Q"
WATCHDOG_CMD="cd $ROOT_Q && ./scripts/autopilot/watchdog_loop.sh --project-root $PROJECT_Q --interval 15 --log-dir $LOG_Q"
MONITOR_CMD="cd $ROOT_Q && ./scripts/autopilot/monitor_loop.sh $PROJECT_Q 10"

if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run: tmux session plan"
  echo "Session: $SESSION_NAME"
  echo "Project root: $PROJECT_ROOT"
  echo "Log dir: $LOG_DIR"
  echo
  echo "tmux new-session -d -s $SESSION_NAME -n manager \"$MANAGER_CMD\""
  echo "tmux split-window -h -t $SESSION_NAME:manager \"$CLAUDE_CMD\""
  echo "tmux split-window -v -t $SESSION_NAME:manager.1 \"$GEMINI_CMD\""
  echo "tmux split-window -v -t $SESSION_NAME:manager.0 \"$WATCHDOG_CMD\""
  echo "tmux new-window -t $SESSION_NAME -n monitor \"$MONITOR_CMD\""
  echo "tmux select-layout -t $SESSION_NAME:manager tiled"
  exit 0
fi

tmux new-session -d -s "$SESSION_NAME" -n manager "$MANAGER_CMD"
tmux split-window -h -t "$SESSION_NAME:manager" "$CLAUDE_CMD"
tmux split-window -v -t "$SESSION_NAME:manager.1" "$GEMINI_CMD"
tmux split-window -v -t "$SESSION_NAME:manager.0" "$WATCHDOG_CMD"
tmux new-window -t "$SESSION_NAME" -n monitor "$MONITOR_CMD"

tmux select-layout -t "$SESSION_NAME:manager" tiled >/dev/null
echo "Started tmux session: $SESSION_NAME"
echo "Attach with: tmux attach -t $SESSION_NAME"
