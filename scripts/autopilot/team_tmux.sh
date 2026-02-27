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
LEADER_AGENT="codex"
LEADER_CLI=""
WINGMAN_AGENT="ccm"
WINGMAN_CLI="claude"
CLAUDE_PROJECT_ROOT=""
GEMINI_PROJECT_ROOT=""
CODEX_PROJECT_ROOT=""
WINGMAN_PROJECT_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --session) SESSION_NAME="$2"; shift 2 ;;
    --manager-interval) MANAGER_INTERVAL="$2"; shift 2 ;;
    --worker-interval) WORKER_INTERVAL="$2"; shift 2 ;;
    --manager-cli-timeout) MANAGER_CLI_TIMEOUT="$2"; shift 2 ;;
    --worker-cli-timeout) WORKER_CLI_TIMEOUT="$2"; shift 2 ;;
    --leader-agent) LEADER_AGENT="$2"; shift 2 ;;
    --leader-cli) LEADER_CLI="$2"; shift 2 ;;
    --wingman-agent) WINGMAN_AGENT="$2"; shift 2 ;;
    --wingman-cli) WINGMAN_CLI="$2"; shift 2 ;;
    --claude-project-root) CLAUDE_PROJECT_ROOT="$2"; shift 2 ;;
    --gemini-project-root) GEMINI_PROJECT_ROOT="$2"; shift 2 ;;
    --codex-project-root) CODEX_PROJECT_ROOT="$2"; shift 2 ;;
    --wingman-project-root) WINGMAN_PROJECT_ROOT="$2"; shift 2 ;;
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
[[ -z "$CLAUDE_PROJECT_ROOT" ]] && CLAUDE_PROJECT_ROOT="$PROJECT_ROOT"
[[ -z "$GEMINI_PROJECT_ROOT" ]] && GEMINI_PROJECT_ROOT="$PROJECT_ROOT"
[[ -z "$CODEX_PROJECT_ROOT" ]] && CODEX_PROJECT_ROOT="$PROJECT_ROOT"
[[ -z "$WINGMAN_PROJECT_ROOT" ]] && WINGMAN_PROJECT_ROOT="$PROJECT_ROOT"
CLAUDE_PROJECT_Q="$(printf '%q' "$CLAUDE_PROJECT_ROOT")"
GEMINI_PROJECT_Q="$(printf '%q' "$GEMINI_PROJECT_ROOT")"
CODEX_PROJECT_Q="$(printf '%q' "$CODEX_PROJECT_ROOT")"
WINGMAN_PROJECT_Q="$(printf '%q' "$WINGMAN_PROJECT_ROOT")"

if [[ -z "$LEADER_CLI" ]]; then
  case "$LEADER_AGENT" in
    codex) LEADER_CLI="codex" ;;
    claude_code) LEADER_CLI="claude" ;;
    gemini) LEADER_CLI="gemini" ;;
    *) LEADER_CLI="codex" ;;
  esac
fi

MANAGER_CMD="cd $ROOT_Q && ./scripts/autopilot/manager_loop.sh --cli $LEADER_CLI --leader-agent $LEADER_AGENT --project-root $PROJECT_Q --interval '$MANAGER_INTERVAL' --cli-timeout '$MANAGER_CLI_TIMEOUT' --log-dir $LOG_Q"
CLAUDE_CMD="cd $ROOT_Q && ./scripts/autopilot/worker_loop.sh --cli claude --agent claude_code --project-root $CLAUDE_PROJECT_Q --interval '$WORKER_INTERVAL' --cli-timeout '$WORKER_CLI_TIMEOUT' --log-dir $LOG_Q"
GEMINI_CMD="cd $ROOT_Q && ./scripts/autopilot/worker_loop.sh --cli gemini --agent gemini --project-root $GEMINI_PROJECT_Q --interval '$WORKER_INTERVAL' --cli-timeout '$WORKER_CLI_TIMEOUT' --log-dir $LOG_Q"
CODEX_WORKER_CMD="cd $ROOT_Q && ./scripts/autopilot/worker_loop.sh --cli codex --agent codex --project-root $CODEX_PROJECT_Q --interval '$WORKER_INTERVAL' --cli-timeout '$WORKER_CLI_TIMEOUT' --log-dir $LOG_Q"
WINGMAN_CMD="cd $ROOT_Q && ./scripts/autopilot/worker_loop.sh --cli $WINGMAN_CLI --agent $WINGMAN_AGENT --lane wingman --project-root $WINGMAN_PROJECT_Q --interval '$WORKER_INTERVAL' --cli-timeout '$WORKER_CLI_TIMEOUT' --log-dir $LOG_Q"
WATCHDOG_CMD="cd $ROOT_Q && ./scripts/autopilot/watchdog_loop.sh --project-root $PROJECT_Q --interval 15 --log-dir $LOG_Q"
MONITOR_CMD="cd $ROOT_Q && ./scripts/autopilot/monitor_loop.sh $PROJECT_Q 10"

if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run: tmux session plan"
  echo "Session: $SESSION_NAME"
  echo "Project root: $PROJECT_ROOT"
  echo "Log dir: $LOG_DIR"
  echo
  echo "tmux new-session -d -s $SESSION_NAME -n manager \"$MANAGER_CMD\""
  workers_started=false
  if [[ "$LEADER_AGENT" != "claude_code" ]]; then
    echo "tmux new-window -t $SESSION_NAME -n workers \"$CLAUDE_CMD\""
    workers_started=true
  fi
  if [[ "$LEADER_AGENT" != "gemini" ]]; then
    if [[ "$workers_started" == true ]]; then
      echo "tmux split-window -h -t $SESSION_NAME:workers \"$GEMINI_CMD\""
    else
      echo "tmux new-window -t $SESSION_NAME -n workers \"$GEMINI_CMD\""
      workers_started=true
    fi
  fi
  if [[ "$LEADER_AGENT" != "codex" ]]; then
    if [[ "$workers_started" == true ]]; then
      echo "tmux split-window -h -t $SESSION_NAME:workers \"$CODEX_WORKER_CMD\""
    else
      echo "tmux new-window -t $SESSION_NAME -n workers \"$CODEX_WORKER_CMD\""
      workers_started=true
    fi
  fi
  if [[ "$workers_started" == true ]]; then
    echo "tmux split-window -v -t $SESSION_NAME:workers.0 \"$WINGMAN_CMD\""
    echo "tmux split-window -v -t $SESSION_NAME:workers.1 \"$WATCHDOG_CMD\""
  else
    echo "tmux new-window -t $SESSION_NAME -n workers \"$WINGMAN_CMD\""
    echo "tmux split-window -v -t $SESSION_NAME:workers \"$WATCHDOG_CMD\""
  fi
  echo "tmux new-window -t $SESSION_NAME -n monitor \"$MONITOR_CMD\""
  echo "tmux select-layout -t $SESSION_NAME:workers tiled"
  exit 0
fi

tmux new-session -d -s "$SESSION_NAME" -n manager "$MANAGER_CMD"
workers_started=false
if [[ "$LEADER_AGENT" != "claude_code" ]]; then
  tmux new-window -t "$SESSION_NAME" -n workers "$CLAUDE_CMD"
  workers_started=true
fi
if [[ "$LEADER_AGENT" != "gemini" ]]; then
  if [[ "$workers_started" == true ]]; then
    tmux split-window -h -t "$SESSION_NAME:workers" "$GEMINI_CMD"
  else
    tmux new-window -t "$SESSION_NAME" -n workers "$GEMINI_CMD"
    workers_started=true
  fi
fi
if [[ "$LEADER_AGENT" != "codex" ]]; then
  if [[ "$workers_started" == true ]]; then
    tmux split-window -h -t "$SESSION_NAME:workers" "$CODEX_WORKER_CMD"
  else
    tmux new-window -t "$SESSION_NAME" -n workers "$CODEX_WORKER_CMD"
    workers_started=true
  fi
fi
if [[ "$workers_started" == true ]]; then
  tmux split-window -v -t "$SESSION_NAME:workers.0" "$WINGMAN_CMD"
  tmux split-window -v -t "$SESSION_NAME:workers.1" "$WATCHDOG_CMD"
else
  tmux new-window -t "$SESSION_NAME" -n workers "$WINGMAN_CMD"
  tmux split-window -v -t "$SESSION_NAME:workers" "$WATCHDOG_CMD"
fi
tmux new-window -t "$SESSION_NAME" -n monitor "$MONITOR_CMD"

tmux select-layout -t "$SESSION_NAME:workers" tiled >/dev/null
echo "Started tmux session: $SESSION_NAME"
echo "Attach with: tmux attach -t $SESSION_NAME"
