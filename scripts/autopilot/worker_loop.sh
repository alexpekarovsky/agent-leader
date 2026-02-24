#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

CLI=""
AGENT=""
PROJECT_ROOT="$ROOT_DIR"
INTERVAL=25
ONCE=false
LOG_DIR="$ROOT_DIR/.autopilot-logs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli) CLI="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --once) ONCE=true; shift ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$CLI" || -z "$AGENT" ]]; then
  log ERROR "--cli and --agent are required"
  exit 1
fi

require_cmd "$CLI"
mkdir_logs "$LOG_DIR"

cycle=0
while true; do
  cycle=$((cycle + 1))
  ts="$(date '+%Y%m%d-%H%M%S')"
  prompt_file="$(mktemp)"
  out_file="$LOG_DIR/worker-${AGENT}-${CLI}-${ts}.log"
  cat >"$prompt_file" <<EOF
Project: $(basename "$PROJECT_ROOT")
You are worker agent ${AGENT} running an autonomous work loop.

Execute exactly one worker cycle and exit when done:
1. Call orchestrator_connect_to_leader for agent="${AGENT}" with full identity metadata if needed.
2. Call orchestrator_poll_events(agent="${AGENT}", timeout_ms=1000).
3. Call orchestrator_claim_next_task(agent="${AGENT}").
4. If no task is claimable, print \"idle\" and exit.
5. If a task is claimed:
   - implement only that task in this project
   - run relevant tests/build checks
   - call orchestrator_submit_report with commit SHA and test results
   - if blocked, call orchestrator_raise_blocker instead of stalling
6. Exit after one task attempt.

Rules:
- Work only inside $PROJECT_ROOT
- Use MCP tools for orchestration state
- Never silently stop; submit report or raise blocker
EOF

  log INFO "worker cycle=$cycle agent=$AGENT cli=$CLI project=$PROJECT_ROOT"
  if ! run_cli_prompt "$CLI" "$PROJECT_ROOT" "$prompt_file" "$out_file"; then
    log ERROR "worker cycle failed agent=$AGENT; see $out_file"
  else
    log INFO "worker cycle complete agent=$AGENT; log=$out_file"
  fi
  rm -f "$prompt_file"

  if [[ "$ONCE" == true ]]; then
    break
  fi
  sleep_with_jitter "$INTERVAL"
done
