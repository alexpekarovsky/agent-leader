#!/usr/bin/env bash
# Autopilot supervisor — manages loop processes without requiring tmux.
#
# Usage:
#   ./scripts/autopilot/supervisor.sh start   [options]
#   ./scripts/autopilot/supervisor.sh stop     [options]
#   ./scripts/autopilot/supervisor.sh status   [options]
#   ./scripts/autopilot/supervisor.sh restart  [options]
#   ./scripts/autopilot/supervisor.sh clean    [options]   # remove stale pids + supervisor logs
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
source "$ROOT_DIR/scripts/autopilot/common.sh"

ACTION="${1:-}"
shift 2>/dev/null || true

PROJECT_ROOT="$ROOT_DIR"
LOG_DIR=""
PID_DIR=""
MANAGER_CLI_TIMEOUT=300
WORKER_CLI_TIMEOUT=600
MANAGER_INTERVAL=20
WORKER_INTERVAL=25
LEADER_AGENT="codex"
LEADER_CLI=""
WINGMAN_AGENT="ccm"
WINGMAN_CLI="claude"
CLAUDE_PROJECT_ROOT=""
GEMINI_PROJECT_ROOT=""
CODEX_PROJECT_ROOT=""
WINGMAN_PROJECT_ROOT=""
CLAUDE_TEAM_ID=""
GEMINI_TEAM_ID=""
CODEX_TEAM_ID=""
WINGMAN_TEAM_ID=""
EXTRA_WORKER_SPECS=()
MAX_RESTARTS=5
BACKOFF_BASE=10
BACKOFF_MAX=120

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --pid-dir) PID_DIR="$2"; shift 2 ;;
    --manager-cli-timeout) MANAGER_CLI_TIMEOUT="$2"; shift 2 ;;
    --worker-cli-timeout) WORKER_CLI_TIMEOUT="$2"; shift 2 ;;
    --manager-interval) MANAGER_INTERVAL="$2"; shift 2 ;;
    --worker-interval) WORKER_INTERVAL="$2"; shift 2 ;;
    --leader-agent) LEADER_AGENT="$2"; shift 2 ;;
    --leader-cli) LEADER_CLI="$2"; shift 2 ;;
    --wingman-agent) WINGMAN_AGENT="$2"; shift 2 ;;
    --wingman-cli) WINGMAN_CLI="$2"; shift 2 ;;
    --claude-project-root) CLAUDE_PROJECT_ROOT="$2"; shift 2 ;;
    --gemini-project-root) GEMINI_PROJECT_ROOT="$2"; shift 2 ;;
    --codex-project-root) CODEX_PROJECT_ROOT="$2"; shift 2 ;;
    --wingman-project-root) WINGMAN_PROJECT_ROOT="$2"; shift 2 ;;
    --claude-team-id) CLAUDE_TEAM_ID="$2"; shift 2 ;;
    --gemini-team-id) GEMINI_TEAM_ID="$2"; shift 2 ;;
    --codex-team-id) CODEX_TEAM_ID="$2"; shift 2 ;;
    --wingman-team-id) WINGMAN_TEAM_ID="$2"; shift 2 ;;
    --extra-worker) EXTRA_WORKER_SPECS+=("$2"); shift 2 ;;
    --max-restarts) MAX_RESTARTS="$2"; shift 2 ;;
    --backoff-base) BACKOFF_BASE="$2"; shift 2 ;;
    --backoff-max) BACKOFF_MAX="$2"; shift 2 ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

[[ -z "$LOG_DIR" ]] && LOG_DIR="$PROJECT_ROOT/.autopilot-logs"
[[ -z "$PID_DIR" ]] && PID_DIR="$PROJECT_ROOT/.autopilot-pids"
[[ -z "$CLAUDE_PROJECT_ROOT" ]] && CLAUDE_PROJECT_ROOT="$PROJECT_ROOT"
[[ -z "$GEMINI_PROJECT_ROOT" ]] && GEMINI_PROJECT_ROOT="$PROJECT_ROOT"
[[ -z "$CODEX_PROJECT_ROOT" ]] && CODEX_PROJECT_ROOT="$PROJECT_ROOT"
[[ -z "$WINGMAN_PROJECT_ROOT" ]] && WINGMAN_PROJECT_ROOT="$PROJECT_ROOT"

if [[ -z "$LEADER_CLI" ]]; then
  case "$LEADER_AGENT" in
    codex) LEADER_CLI="codex" ;;
    claude_code) LEADER_CLI="claude" ;;
    gemini) LEADER_CLI="gemini" ;;
    *) LEADER_CLI="codex" ;;
  esac
fi

PROCS=(manager wingman claude gemini codex_worker watchdog)
EXTRA_PROC_NAMES=()
EXTRA_PROC_CMDS=()

proc_enabled() {
  local name="$1"
  case "$name" in
    claude) [[ "$LEADER_AGENT" != "claude_code" ]] ;;
    gemini) [[ "$LEADER_AGENT" != "gemini" ]] ;;
    codex_worker) [[ "$LEADER_AGENT" != "codex" ]] ;;
    *) return 0 ;;
  esac
}

proc_cmd() {
  local name="$1"
  local i
  for (( i=0; i<${#EXTRA_PROC_NAMES[@]}; i++ )); do
    if [[ "${EXTRA_PROC_NAMES[$i]}" == "$name" ]]; then
      echo "${EXTRA_PROC_CMDS[$i]}"
      return 0
    fi
  done
  local claude_team_arg=""
  local gemini_team_arg=""
  local codex_team_arg=""
  local wingman_team_arg=""
  [[ -n "$CLAUDE_TEAM_ID" ]] && claude_team_arg=" --team-id $CLAUDE_TEAM_ID"
  [[ -n "$GEMINI_TEAM_ID" ]] && gemini_team_arg=" --team-id $GEMINI_TEAM_ID"
  [[ -n "$CODEX_TEAM_ID" ]] && codex_team_arg=" --team-id $CODEX_TEAM_ID"
  [[ -n "$WINGMAN_TEAM_ID" ]] && wingman_team_arg=" --team-id $WINGMAN_TEAM_ID"
  case "$name" in
    manager)
      echo "$ROOT_DIR/scripts/autopilot/manager_loop.sh --cli $LEADER_CLI --leader-agent $LEADER_AGENT --project-root $PROJECT_ROOT --interval $MANAGER_INTERVAL --cli-timeout $MANAGER_CLI_TIMEOUT --log-dir $LOG_DIR"
      ;;
    wingman)
      echo "$ROOT_DIR/scripts/autopilot/worker_loop.sh --cli $WINGMAN_CLI --agent $WINGMAN_AGENT --lane wingman$wingman_team_arg --project-root $WINGMAN_PROJECT_ROOT --interval $WORKER_INTERVAL --cli-timeout $WORKER_CLI_TIMEOUT --log-dir $LOG_DIR"
      ;;
    claude)
      echo "$ROOT_DIR/scripts/autopilot/worker_loop.sh --cli claude --agent claude_code$claude_team_arg --project-root $CLAUDE_PROJECT_ROOT --interval $WORKER_INTERVAL --cli-timeout $WORKER_CLI_TIMEOUT --log-dir $LOG_DIR"
      ;;
    gemini)
      echo "$ROOT_DIR/scripts/autopilot/worker_loop.sh --cli gemini --agent gemini$gemini_team_arg --project-root $GEMINI_PROJECT_ROOT --interval $WORKER_INTERVAL --cli-timeout $WORKER_CLI_TIMEOUT --log-dir $LOG_DIR"
      ;;
    codex_worker)
      echo "$ROOT_DIR/scripts/autopilot/worker_loop.sh --cli codex --agent codex$codex_team_arg --project-root $CODEX_PROJECT_ROOT --interval $WORKER_INTERVAL --cli-timeout $WORKER_CLI_TIMEOUT --log-dir $LOG_DIR"
      ;;
    watchdog)
      echo "$ROOT_DIR/scripts/autopilot/watchdog_loop.sh --project-root $PROJECT_ROOT --interval 15 --log-dir $LOG_DIR"
      ;;
  esac
}

register_extra_workers() {
  if (( ${#EXTRA_WORKER_SPECS[@]} == 0 )); then
    return 0
  fi
  for spec in "${EXTRA_WORKER_SPECS[@]}"; do
    IFS=':' read -r name cli agent team_id project_root lane <<<"$spec"
    if [[ -z "$name" || -z "$cli" || -z "$agent" || -z "$team_id" || -z "$project_root" ]]; then
      log ERROR "Invalid --extra-worker spec '$spec' expected name:cli:agent:team_id:project_root[:lane]"
      exit 1
    fi
    [[ -z "$lane" ]] && lane="default"
    if [[ "$lane" != "default" && "$lane" != "wingman" ]]; then
      log ERROR "Invalid lane '$lane' in --extra-worker spec '$spec'"
      exit 1
    fi
    local i
    for (( i=0; i<${#EXTRA_PROC_NAMES[@]}; i++ )); do
      if [[ "${EXTRA_PROC_NAMES[$i]}" == "$name" ]]; then
        log ERROR "Duplicate extra worker process name '$name'"
        exit 1
      fi
    done
    EXTRA_PROC_NAMES+=("$name")
    EXTRA_PROC_CMDS+=("$ROOT_DIR/scripts/autopilot/worker_loop.sh --cli $cli --agent $agent --lane $lane --team-id $team_id --project-root $project_root --interval $WORKER_INTERVAL --cli-timeout $WORKER_CLI_TIMEOUT --log-dir $LOG_DIR")
    PROCS+=("$name")
  done
}

register_extra_workers

pid_file() {
  echo "$PID_DIR/$1.pid"
}

restart_count_file() {
  echo "$PID_DIR/$1.restarts"
}

proc_log_file() {
  echo "$LOG_DIR/supervisor-$1.log"
}

is_running() {
  local name="$1"
  local pf
  pf="$(pid_file "$name")"
  if [[ ! -f "$pf" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$pf" 2>/dev/null)" || return 1
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

start_proc() {
  local name="$1"
  if ! proc_enabled "$name"; then
    log INFO "skipping disabled process $name (leader_agent=$LEADER_AGENT)"
    return 0
  fi
  if is_running "$name"; then
    log INFO "$name already running (pid=$(cat "$(pid_file "$name")"))"
    return 0
  fi

  local cmd
  cmd="$(proc_cmd "$name")"
  local logf
  logf="$(proc_log_file "$name")"

  # Launch in background with nohup, redirect to supervisor log
  nohup bash -c "$cmd" >>"$logf" 2>&1 &
  local pid=$!
  echo "$pid" >"$(pid_file "$name")"
  echo "0" >"$(restart_count_file "$name")"
  log INFO "started $name pid=$pid log=$logf"
}

stop_proc() {
  local name="$1"
  local pf
  pf="$(pid_file "$name")"
  if [[ ! -f "$pf" ]]; then
    log INFO "$name not running (no pidfile)"
    return 0
  fi
  local pid
  pid="$(cat "$pf" 2>/dev/null)" || pid=""
  if [[ -z "$pid" ]]; then
    rm -f "$pf"
    return 0
  fi

  if kill -0 "$pid" 2>/dev/null; then
    log INFO "stopping $name pid=$pid"
    # Send SIGTERM, wait up to 10s, then SIGKILL
    kill "$pid" 2>/dev/null || true
    local waited=0
    while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 10 ]]; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      log WARN "$name pid=$pid did not exit after 10s, sending SIGKILL"
      kill -9 "$pid" 2>/dev/null || true
    fi
    log INFO "stopped $name pid=$pid"
  else
    log INFO "$name pid=$pid already exited"
  fi
  rm -f "$pf"
  rm -f "$(restart_count_file "$name")"
}

status_proc() {
  local name="$1"
  local pf
  pf="$(pid_file "$name")"
  local restarts_f
  restarts_f="$(restart_count_file "$name")"
  local restarts="0"
  [[ -f "$restarts_f" ]] && restarts="$(cat "$restarts_f" 2>/dev/null)" || true

  if ! proc_enabled "$name"; then
    printf '  %-10s  %-8s  pid=%-8s  restarts=%s\n' "$name" "disabled" "-" "$restarts"
    return
  fi

  if [[ ! -f "$pf" ]]; then
    printf '  %-10s  %-8s  pid=%-8s  restarts=%s\n' "$name" "stopped" "-" "$restarts"
    return
  fi
  local pid
  pid="$(cat "$pf" 2>/dev/null)" || pid=""
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    printf '  %-10s  %-8s  pid=%-8s  restarts=%s\n' "$name" "running" "$pid" "$restarts"
  else
    printf '  %-10s  %-8s  pid=%-8s  restarts=%s\n' "$name" "dead" "$pid" "$restarts"
  fi
}

do_start() {
  mkdir -p "$LOG_DIR" "$PID_DIR"
  log INFO "starting all processes (project=$PROJECT_ROOT)"
  for name in "${PROCS[@]}"; do
    if proc_enabled "$name"; then
      start_proc "$name"
    else
      # Ensure previously-running process is torn down when role topology changes.
      stop_proc "$name"
    fi
  done
  echo "Supervisor started. PID dir: $PID_DIR"
  echo "Check status: $0 status"
}

do_stop() {
  log INFO "stopping all processes"
  for name in "${PROCS[@]}"; do
    stop_proc "$name"
  done
  echo "All processes stopped."
}

do_status() {
  echo "Autopilot supervisor status"
  echo "Project: $PROJECT_ROOT"
  echo "PID dir: $PID_DIR"
  echo "Log dir: $LOG_DIR"
  echo
  for name in "${PROCS[@]}"; do
    status_proc "$name"
  done
}

do_restart() {
  do_stop
  sleep 1
  do_start
}

do_clean() {
  local cleaned=0

  # Remove stale pid files (process no longer running)
  if [[ -d "$PID_DIR" ]]; then
    for name in "${PROCS[@]}"; do
      local pf
      pf="$(pid_file "$name")"
      if [[ -f "$pf" ]]; then
        local pid
        pid="$(cat "$pf" 2>/dev/null)" || pid=""
        if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
          rm -f "$pf" "$(restart_count_file "$name")"
          log INFO "removed stale pidfile for $name (pid=$pid)"
          cleaned=$((cleaned + 1))
        else
          log WARN "$name is still running (pid=$pid) — stop it first"
        fi
      fi
    done
    # Remove pid dir if empty
    rmdir "$PID_DIR" 2>/dev/null || true
  fi

  # Remove supervisor log files
  if [[ -d "$LOG_DIR" ]]; then
    local sv_logs
    sv_logs=$(ls "$LOG_DIR"/supervisor-*.log 2>/dev/null || true)
    if [[ -n "$sv_logs" ]]; then
      local count
      count=$(echo "$sv_logs" | wc -l | tr -d ' ')
      rm -f "$LOG_DIR"/supervisor-*.log
      log INFO "removed $count supervisor log file(s)"
      cleaned=$((cleaned + $count))
    fi
  fi

  if [[ $cleaned -eq 0 ]]; then
    echo "Nothing to clean."
  else
    echo "Cleaned $cleaned file(s)."
  fi
}

case "$ACTION" in
  start)   do_start ;;
  stop)    do_stop ;;
  status)  do_status ;;
  restart) do_restart ;;
  clean)   do_clean ;;
  *)
    echo "Usage: $0 {start|stop|status|restart|clean} [options]"
    echo
    echo "Commands:"
    echo "  start    Start all autopilot processes"
    echo "  stop     Stop all running processes"
    echo "  status   Show process status"
    echo "  restart  Stop then start all processes"
    echo "  clean    Remove stale pid files and supervisor logs"
    echo
    echo "Visibility:"
    echo "  ./scripts/autopilot/headless_status.sh --once"
    echo "  ./scripts/autopilot/headless_status.sh --watch --interval 10"
    exit 1
    ;;
esac
