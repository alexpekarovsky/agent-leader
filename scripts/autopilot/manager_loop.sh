#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

CLI="codex"
PROJECT_ROOT="$ROOT_DIR"
INTERVAL=20
ONCE=false
LOG_DIR="$ROOT_DIR/.autopilot-logs"
MAX_LOG_FILES=200
CLI_TIMEOUT=300

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli) CLI="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --max-logs) MAX_LOG_FILES="$2"; shift 2 ;;
    --cli-timeout) CLI_TIMEOUT="$2"; shift 2 ;;
    --once) ONCE=true; shift ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

require_cmd "$CLI"
mkdir_logs "$LOG_DIR"

cycle=0
while true; do
  cycle=$((cycle + 1))
  cycle_rc=0
  ts="$(date '+%Y%m%d-%H%M%S')"
  prompt_file="$(mktemp)"
  out_file="$LOG_DIR/manager-${CLI}-${ts}.log"
  cat >"$prompt_file" <<EOF
Project: $(basename "$PROJECT_ROOT")
You are the manager/leader in an autonomous loop.

Execute exactly one manager cycle in this project and exit when done.
Required actions, in order:
1. Call orchestrator_set_role(agent=\"codex\", role=\"leader\", source=\"codex\").
2. Call orchestrator_heartbeat(agent=\"codex\") with full identity metadata for this project and server version.
3. Call orchestrator_bootstrap if state is not initialized.
4. Call orchestrator_manager_cycle(strict=true).
5. Call orchestrator_list_blockers(status=\"open\") and summarize blockers.
6. If there are reported tasks, validate them.
7. Inspect .autopilot-logs/watchdog-*.jsonl recent entries for stale_task/state_corruption_detected diagnostics.
8. For stale tasks, publish manager.sync or manager.execution_plan reminders and raise blockers when a task appears stuck beyond timeout.
9. If there are idle/assigned tasks, publish manager execution_plan events to the correct owners.
10. End with a compact status summary (tasks by status, blockers, bugs).

Rules:
- Use MCP tools only for orchestration.
- Do not wait for user input.
- Keep this to one cycle and stop.
EOF

  log INFO "manager cycle=$cycle cli=$CLI project=$PROJECT_ROOT"
  if run_cli_prompt "$CLI" "$PROJECT_ROOT" "$prompt_file" "$out_file" "$CLI_TIMEOUT"; then
    log INFO "manager cycle complete; log=$out_file"
  else
    rc=$?
    cycle_rc=$rc
    if [[ $rc -eq 124 ]]; then
      log ERROR "manager cycle timed out after ${CLI_TIMEOUT}s; see $out_file"
    else
      log ERROR "manager cycle failed rc=$rc; see $out_file"
    fi
  fi
  rm -f "$prompt_file"
  prune_old_logs "$LOG_DIR" "manager-" "$MAX_LOG_FILES"

  if [[ "$ONCE" == true ]]; then
    exit "$cycle_rc"
  fi
  sleep_with_jitter "$INTERVAL"
done
