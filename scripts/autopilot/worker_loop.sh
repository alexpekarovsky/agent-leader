#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

CLI=""
AGENT=""
LANE="default"
TEAM_ID=""
PROJECT_ROOT="$ROOT_DIR"
INTERVAL=25
ONCE=false
LOG_DIR="$ROOT_DIR/.autopilot-logs"
MAX_LOG_FILES=200
CLI_TIMEOUT=600

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli) CLI="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --lane) LANE="$2"; shift 2 ;;
    --team-id) TEAM_ID="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --max-logs) MAX_LOG_FILES="$2"; shift 2 ;;
    --cli-timeout) CLI_TIMEOUT="$2"; shift 2 ;;
    --once) ONCE=true; shift ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$CLI" || -z "$AGENT" ]]; then
  log ERROR "--cli and --agent are required"
  exit 1
fi

if [[ "$LANE" != "default" && "$LANE" != "wingman" ]]; then
  log ERROR "--lane must be one of: default, wingman"
  exit 1
fi

require_cmd "$CLI"
mkdir_logs "$LOG_DIR"

cycle=0
while true; do
  cycle=$((cycle + 1))
  cycle_rc=0
  ts="$(date '+%Y%m%d-%H%M%S')"
  prompt_file="$(mktemp)"
  out_file="$LOG_DIR/worker-${AGENT}-${CLI}-${ts}.log"
  lane_rules=""
  team_rules=""
  if [[ "$LANE" == "wingman" ]]; then
    lane_rules="$(cat <<'RULES'
   - QA lane guard: if task is not QA-scoped, do not execute it.
     Consider task non-QA when workstream != "qa" and title/description do not clearly mention qa/regression/test.
   - For non-QA task in this lane:
     * call orchestrator_update_task_status(task_id=..., status="assigned", note="Wingman QA lane: task is not QA-scoped; returned to queue for reassignment")
     * call orchestrator_publish_event(source="__AGENT__", type="manager.sync", payload={"task_id":"...","reason":"wingman_non_qa_task_requeued"})
     * print "rerouted_non_qa" and exit
RULES
)"
    lane_rules="${lane_rules/__AGENT__/$AGENT}"
  fi
  if [[ -n "$TEAM_ID" ]]; then
    team_rules="$(cat <<'TEAM_RULES'
   - Team lane guard: if task.team_id exists and does not match "__TEAM_ID__", do not execute it.
   - For non-matching team task:
     * call orchestrator_update_task_status(task_id=..., status="assigned", note="Headless team lane: task team_id mismatch; returned to queue")
     * call orchestrator_publish_event(source="__AGENT__", type="manager.sync", payload={"task_id":"...","reason":"team_id_mismatch_requeued","expected_team_id":"__TEAM_ID__"})
     * print "rerouted_team_mismatch" and exit
TEAM_RULES
)"
    team_rules="${team_rules//__TEAM_ID__/$TEAM_ID}"
    team_rules="${team_rules//__AGENT__/$AGENT}"
  fi
  cat >"$prompt_file" <<EOF
Project: $(basename "$PROJECT_ROOT")
You are worker agent ${AGENT} running an autonomous work loop.
Lane: ${LANE}
Team: ${TEAM_ID:-none}

Execute exactly one worker cycle and exit when done:
1. Call orchestrator_connect_to_leader for agent="${AGENT}" with full identity metadata if needed.
2. Call orchestrator_poll_events(agent="${AGENT}", timeout_ms=1000).
3. Call orchestrator_claim_next_task(agent="${AGENT}"$(if [[ -n "$TEAM_ID" ]]; then printf ', team_id="%s"' "$TEAM_ID"; fi)).
4. If no task is claimable, print \"idle\" and exit.
5. If a task is claimed:
${lane_rules}
${team_rules}
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
  if run_cli_prompt "$CLI" "$PROJECT_ROOT" "$prompt_file" "$out_file" "$CLI_TIMEOUT"; then
    log INFO "worker cycle complete agent=$AGENT; log=$out_file"
  else
    rc=$?
    cycle_rc=$rc
    if [[ $rc -eq 124 ]]; then
      log ERROR "worker cycle timed out agent=$AGENT after ${CLI_TIMEOUT}s; see $out_file"
    else
      log ERROR "worker cycle failed agent=$AGENT rc=$rc; see $out_file"
    fi
  fi
  rm -f "$prompt_file"
  prune_old_logs "$LOG_DIR" "worker-${AGENT}-" "$MAX_LOG_FILES"

  if [[ "$ONCE" == true ]]; then
    exit "$cycle_rc"
  fi
  sleep_with_jitter "$INTERVAL"
done
