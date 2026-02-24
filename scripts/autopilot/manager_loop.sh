#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

CLI="codex"
PROJECT_ROOT="$ROOT_DIR"
INTERVAL=20
ONCE=false
LOG_DIR="$ROOT_DIR/.autopilot-logs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli) CLI="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --once) ONCE=true; shift ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

require_cmd "$CLI"
mkdir_logs "$LOG_DIR"

cycle=0
while true; do
  cycle=$((cycle + 1))
  ts="$(date '+%Y%m%d-%H%M%S')"
  prompt_file="$(mktemp)"
  out_file="$LOG_DIR/manager-${CLI}-${ts}.log"
  cat >"$prompt_file" <<EOF
Project: $(basename "$PROJECT_ROOT")
You are the manager/leader in an autonomous loop.

Execute exactly one manager cycle in this project and exit when done.
Required actions, in order:
1. Call orchestrator_connect_to_leader as codex manager with full identity metadata if needed.
2. Call orchestrator_bootstrap if state is not initialized.
3. Call orchestrator_manager_cycle(strict=true).
4. Call orchestrator_list_blockers(status=\"open\") and summarize blockers.
5. If there are reported tasks, validate them.
6. Inspect .autopilot-logs/watchdog-*.jsonl recent entries for stale_task/state_repair diagnostics.
7. For stale tasks, publish manager.sync or manager.execution_plan reminders and raise blockers when a task appears stuck beyond timeout.
8. If there are idle/assigned tasks, publish manager execution_plan events to the correct owners.
9. End with a compact status summary (tasks by status, blockers, bugs).

Rules:
- Use MCP tools only for orchestration.
- Do not wait for user input.
- Keep this to one cycle and stop.
EOF

  log INFO "manager cycle=$cycle cli=$CLI project=$PROJECT_ROOT"
  if ! run_cli_prompt "$CLI" "$PROJECT_ROOT" "$prompt_file" "$out_file"; then
    log ERROR "manager cycle failed; see $out_file"
  else
    log INFO "manager cycle complete; log=$out_file"
  fi
  rm -f "$prompt_file"

  if [[ "$ONCE" == true ]]; then
    break
  fi
  sleep_with_jitter "$INTERVAL"
done
