#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

CLI="codex"
LEADER_AGENT="codex"
PROJECT_ROOT="$ROOT_DIR"
INTERVAL=20
ONCE=false
LOG_DIR="$ROOT_DIR/.autopilot-logs"
MAX_LOG_FILES=200
CLI_TIMEOUT=300
IDLE_BACKOFF="30,60,120,300,900"
MAX_IDLE_CYCLES=30
DAILY_CALL_BUDGET=100

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli) CLI="$2"; shift 2 ;;
    --leader-agent) LEADER_AGENT="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --max-logs) MAX_LOG_FILES="$2"; shift 2 ;;
    --cli-timeout) CLI_TIMEOUT="$2"; shift 2 ;;
    --idle-backoff) IDLE_BACKOFF="$2"; shift 2 ;;
    --max-idle-cycles) MAX_IDLE_CYCLES="$2"; shift 2 ;;
    --daily-call-budget) DAILY_CALL_BUDGET="$2"; shift 2 ;;
    --once) ONCE=true; shift ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

require_cmd "$CLI"
mkdir_logs "$LOG_DIR"

cycle=0
idle_streak=0

manager_has_actionable_work() {
  python3 - "$PROJECT_ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
tasks_path = root / "state" / "tasks.json"
if not tasks_path.exists():
    raise SystemExit(1)
try:
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if not isinstance(tasks, list):
    raise SystemExit(1)
actionable = {"assigned", "reported", "bug_open", "blocked"}
for task in tasks:
    if str(task.get("status", "")).strip().lower() in actionable:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

while true; do
  cycle=$((cycle + 1))
  cycle_rc=0

  if [[ "$ONCE" != true ]]; then
    if ! manager_has_actionable_work; then
      idle_streak=$((idle_streak + 1))
      sleep_s="$(backoff_interval_for_streak "$idle_streak" "$IDLE_BACKOFF" "$INTERVAL")"
      log INFO "idle gate: no actionable manager work (streak=$idle_streak sleep=${sleep_s}s)"
      if [[ "$MAX_IDLE_CYCLES" =~ ^[0-9]+$ ]] && (( MAX_IDLE_CYCLES > 0 )) && (( idle_streak >= MAX_IDLE_CYCLES )); then
        log INFO "max idle cycles reached ($MAX_IDLE_CYCLES); exiting manager loop to save tokens"
        exit 0
      fi
      sleep_with_jitter "$sleep_s"
      continue
    fi
    idle_streak=0
    if ! consume_daily_budget "$DAILY_CALL_BUDGET" "manager-${CLI}-${LEADER_AGENT}" "$LOG_DIR"; then
      log WARN "daily call budget exhausted (budget=$DAILY_CALL_BUDGET); exiting manager loop"
      exit 0
    fi
  fi

  ts="$(date '+%Y%m%d-%H%M%S')"
  prompt_file="$(mktemp)"
  out_file="$LOG_DIR/manager-${CLI}-${ts}.log"
  cat >"$prompt_file" <<EOF
Project: $(basename "$PROJECT_ROOT")
You are the manager/leader in an autonomous loop.

Execute exactly one manager cycle in this project and exit when done.
Required actions, in order:
1. Call orchestrator_set_role(agent=\"${LEADER_AGENT}\", role=\"leader\", source=\"${LEADER_AGENT}\").
2. Call orchestrator_heartbeat(agent=\"${LEADER_AGENT}\") with full identity metadata for this project and server version.
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

  log INFO "CANONICAL ACTION: MANAGER_SYNC cycle=$cycle cli=$CLI leader_agent=$LEADER_AGENT project=$PROJECT_ROOT"
  if run_cli_prompt "$CLI" "$PROJECT_ROOT" "$prompt_file" "$out_file" "$CLI_TIMEOUT" "$LEADER_AGENT" "leader" "${LEADER_AGENT}#headless-manager"; then
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
