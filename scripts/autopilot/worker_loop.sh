#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

CLI=""
AGENT=""
LANE="default"
TEAM_ID=""
INSTANCE_ID_OVERRIDE=""
PROJECT_ROOT="$ROOT_DIR"
INTERVAL=25
ONCE=false
LOG_DIR="$ROOT_DIR/.autopilot-logs"
MAX_LOG_FILES=200
CLI_TIMEOUT=600
IDLE_BACKOFF="30,60,120,300,900"
MAX_IDLE_CYCLES=30
DAILY_CALL_BUDGET=100
DAILY_TOKEN_BUDGET=0
HOURLY_TOKEN_BUDGET=0
TOKENS_PER_CALL=10000
EVENT_DRIVEN=false
EVENT_POLL_INTERVAL=2
EVENT_MAX_WAIT=300

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli) CLI="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --lane) LANE="$2"; shift 2 ;;
    --team-id) TEAM_ID="$2"; shift 2 ;;
    --instance-id) INSTANCE_ID_OVERRIDE="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --max-logs) MAX_LOG_FILES="$2"; shift 2 ;;
    --cli-timeout) CLI_TIMEOUT="$2"; shift 2 ;;
    --idle-backoff) IDLE_BACKOFF="$2"; shift 2 ;;
    --max-idle-cycles) MAX_IDLE_CYCLES="$2"; shift 2 ;;
    --daily-call-budget) DAILY_CALL_BUDGET="$2"; shift 2 ;;
    --daily-token-budget) DAILY_TOKEN_BUDGET="$2"; shift 2 ;;
    --hourly-token-budget) HOURLY_TOKEN_BUDGET="$2"; shift 2 ;;
    --tokens-per-call) TOKENS_PER_CALL="$2"; shift 2 ;;
    --event-driven) EVENT_DRIVEN=true; shift ;;
    --event-poll-interval) EVENT_POLL_INTERVAL="$2"; shift 2 ;;
    --event-max-wait) EVENT_MAX_WAIT="$2"; shift 2 ;;
    --once) ONCE=true; shift ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

cycle=0
idle_streak=0
capacity_streak=0
if [[ -n "$INSTANCE_ID_OVERRIDE" ]]; then
  INSTANCE_ID="$INSTANCE_ID_OVERRIDE"
else
  INSTANCE_ID="${AGENT}#headless-${LANE}"
fi
CAPACITY_BACKOFF="60,120,300,600,900"

log INFO "worker cycle=$cycle agent=$AGENT cli=$CLI project=$PROJECT_ROOT"

if [[ -z "$CLI" || -z "$AGENT" ]]; then
  log ERROR "--cli and --agent are required"
  exit 1
fi

if [[ "$LANE" != "default" && "$LANE" != "wingman" ]]; then
  log ERROR "--lane must be one of: default, wingman"
  exit 1
fi

require_cmd "$CLI"
case "$CLI" in
  codex|claude|gemini)
    ;;
  *)
    log ERROR "Unsupported CLI: $CLI"
    log ERROR "worker cycle failed rc=2"
    cycle_rc=2
    break # Break from the while true loop
    ;;
esac

worker_has_claimable_work() {
  python3 - "$PROJECT_ROOT" "$AGENT" "$TEAM_ID" "$LANE" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
agent = sys.argv[2]
team_id = sys.argv[3].strip().lower()
lane = sys.argv[4].strip().lower()
tasks_path = root / "state" / "tasks.json"
if not tasks_path.exists():
    raise SystemExit(1)
try:
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if not isinstance(tasks, list):
    raise SystemExit(1)

def looks_qa(task):
    ws = str(task.get("workstream", "")).strip().lower()
    if ws == "qa":
        return True
    title = str(task.get("title", "")).strip().lower()
    desc = str(task.get("description", "")).strip().lower()
    txt = f"{title} {desc}"
    return any(k in txt for k in ("qa", "regression", "test"))

for task in tasks:
    if str(task.get("owner", "")).strip() != agent:
        continue
    if str(task.get("status", "")).strip().lower() not in {"assigned", "bug_open"}:
        continue
    if team_id:
        tid = str(task.get("team_id", "")).strip().lower()
        if tid and tid != team_id:
            continue
    if lane == "wingman" and not looks_qa(task):
        continue
    raise SystemExit(0)
raise SystemExit(1)
PY
}

while true; do
  cycle=$((cycle + 1))
  cycle_rc=0

  if [[ "$ONCE" != true ]]; then
    if ! worker_has_claimable_work; then
      idle_streak=$((idle_streak + 1))
      emit_agent_heartbeat "$PROJECT_ROOT" "$AGENT" "$CLI" "$LANE" "$INSTANCE_ID" "idle"
      log INFO "idle gate: no claimable work for $AGENT (streak=$idle_streak)"
      if [[ "$EVENT_DRIVEN" == true ]]; then
        log INFO "idle gate: waiting for wakeup signal for $AGENT (streak=$idle_streak max_wait=${EVENT_MAX_WAIT}s)"
        if wait_for_task_signal "$PROJECT_ROOT" "$AGENT" "$EVENT_MAX_WAIT" "$EVENT_POLL_INTERVAL" "60" "$CLI" "$LANE" "$INSTANCE_ID"; then
          log INFO "wakeup signal received for $AGENT; checking for work"
          continue  # Re-check immediately
        else
          log INFO "idle gate: no wakeup signal after ${EVENT_MAX_WAIT}s for $AGENT (streak=$idle_streak)"
          if [[ "$MAX_IDLE_CYCLES" =~ ^[0-9]+$ ]] && (( MAX_IDLE_CYCLES > 0 )) && (( idle_streak >= MAX_IDLE_CYCLES )); then
            # Auto-resume: check roadmap backlog before exiting
            if roadmap_has_backlog "$PROJECT_ROOT"; then
              log INFO "auto-resume: roadmap backlog detected; triggering plan_from_roadmap for $AGENT"
              _created="$(auto_resume_from_roadmap "$PROJECT_ROOT" "$AGENT" "$TEAM_ID")" || true
              if [[ "$_created" =~ ^[0-9]+$ ]] && (( _created > 0 )); then
                log INFO "auto-resume: created $_created tasks from roadmap; resetting idle streak"
                idle_streak=0
                continue
              fi
            fi
            log INFO "max idle cycles reached ($MAX_IDLE_CYCLES); no backlog remaining; exiting worker loop for $AGENT"
            exit 0
          fi
          continue  # Retry with incremented streak
        fi
      else
        sleep_s="$(backoff_interval_for_streak "$idle_streak" "$IDLE_BACKOFF" "$INTERVAL")"
        log INFO "idle gate: no claimable work for $AGENT (streak=$idle_streak sleep=${sleep_s}s)"
        if [[ "$MAX_IDLE_CYCLES" =~ ^[0-9]+$ ]] && (( MAX_IDLE_CYCLES > 0 )) && (( idle_streak >= MAX_IDLE_CYCLES )); then
          # Auto-resume: check roadmap backlog before exiting
          if roadmap_has_backlog "$PROJECT_ROOT"; then
            log INFO "auto-resume: roadmap backlog detected; triggering plan_from_roadmap for $AGENT"
            _created="$(auto_resume_from_roadmap "$PROJECT_ROOT" "$AGENT" "$TEAM_ID")" || true
            if [[ "$_created" =~ ^[0-9]+$ ]] && (( _created > 0 )); then
              log INFO "auto-resume: created $_created tasks from roadmap; resetting idle streak"
              idle_streak=0
              continue
            fi
          fi
          log INFO "max idle cycles reached ($MAX_IDLE_CYCLES); no backlog remaining; exiting worker loop for $AGENT"
          exit 0
        fi
        sleep_with_jitter "$sleep_s"
        continue
      fi
    fi
    idle_streak=0
    if ! consume_daily_budget "$DAILY_CALL_BUDGET" "worker-${CLI}-${AGENT}" "$LOG_DIR"; then
      log WARN "daily call budget exhausted (budget=$DAILY_CALL_BUDGET); exiting worker loop for $AGENT"
      exit 0
    fi
    if ! consume_token_budget "$DAILY_TOKEN_BUDGET" "$HOURLY_TOKEN_BUDGET" "$TOKENS_PER_CALL" "worker-${CLI}-${AGENT}" "$LOG_DIR"; then
      _exhaust_window="daily"
      if [[ "$HOURLY_TOKEN_BUDGET" =~ ^[0-9]+$ ]] && (( HOURLY_TOKEN_BUDGET > 0 )); then
        _exhaust_window="hourly"
      fi
      log WARN "token budget exhausted (daily=$DAILY_TOKEN_BUDGET hourly=$HOURLY_TOKEN_BUDGET); exiting worker loop for $AGENT"
      write_budget_exhaustion_marker "$PROJECT_ROOT/.autopilot-pids" "worker-${CLI}-${AGENT}" "$_exhaust_window"
      emit_token_budget_alert "$PROJECT_ROOT" "$AGENT" "$_exhaust_window" \
        "$(( DAILY_TOKEN_BUDGET > 0 ? DAILY_TOKEN_BUDGET : HOURLY_TOKEN_BUDGET ))" "0"
      emit_agent_heartbeat "$PROJECT_ROOT" "$AGENT" "$CLI" "$LANE" "$INSTANCE_ID" "budget_exhausted"
      exit 0
    fi
  fi

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
2. Check the connect response for an auto_claimed_task field.
   - If auto_claimed_task is present and contains a task, use it directly as your claimed task (skip to step 5).
   - If auto_claimed_task is absent or null, proceed to step 3.
3. Call orchestrator_poll_events(agent="${AGENT}", timeout_ms=1000).
4. Call orchestrator_claim_next_task(agent="${AGENT}"$(if [[ -n "$TEAM_ID" ]]; then printf ', team_id="%s"' "$TEAM_ID"; fi)).
5. If no task is claimable (and none was auto-claimed), print \"idle\" and exit.
6. If a task is claimed (either auto-claimed or via step 4):
${lane_rules}
${team_rules}
   - implement only that task in this project
   - run relevant tests/build checks
   - call orchestrator_submit_report with commit SHA and test results
   - if blocked, call orchestrator_raise_blocker instead of stalling
7. Exit after one task attempt.

Rules:
- Work only inside $PROJECT_ROOT
- Use MCP tools for orchestration state
- Never silently stop; submit report or raise blocker
EOF

  # Keep legacy marker for existing parsers/tests while adding canonical action event.
  log INFO "worker cycle=$cycle agent=$AGENT cli=$CLI project=$PROJECT_ROOT"
  log INFO "CANONICAL ACTION: WORKER_PULSE cycle=$cycle agent=$AGENT cli=$CLI project=$PROJECT_ROOT"
  cycle_sleep="$INTERVAL"
  if run_cli_prompt "$CLI" "$PROJECT_ROOT" "$prompt_file" "$out_file" "$CLI_TIMEOUT" "$AGENT" "$LANE" "${AGENT}#headless-${LANE}"; then
    log INFO "worker cycle complete agent=$AGENT; log=$out_file"
    # Check if auto_claim_next returned a new task
    skip_sleep=false
    if grep -q "auto_claim_next" "$out_file"; then
      # Extract auto_claim_next object and check for 'id' field
      if python3 -c 'import json, sys; data = json.load(sys.stdin); print(data.get("auto_claim_next", {}).get("id"))' < "$out_file" | grep -q "TASK-"; then
        log INFO "auto_claim_next returned a new task; skipping inter-cycle sleep."
        skip_sleep=true
      fi
    fi
    if (( capacity_streak > 0 )); then
      log INFO "capacity recovery: clearing capacity_streak=$capacity_streak after successful cycle"
      capacity_streak=0
      rm -f "$PROJECT_ROOT/.autopilot-pids/gemini.capacity_errors"
    fi
  else
    rc=$?
    cycle_rc=$rc
    if [[ $rc -eq 124 ]]; then
      log ERROR "worker cycle timed out agent=$AGENT after ${CLI_TIMEOUT}s; see $out_file"
    else
      log ERROR "worker cycle failed agent=$AGENT rc=$rc; see $out_file"
    fi
    # Gemini capacity error detection at the worker loop level
    if [[ "$CLI" == "gemini" ]] && detect_gemini_capacity_error "$out_file"; then
      capacity_streak=$((capacity_streak + 1))
      log WARN "GEMINI_CAPACITY_EXHAUSTED detected (streak=$capacity_streak); see $out_file"
      # Write marker file for supervisor status visibility
      mkdir -p "$PROJECT_ROOT/.autopilot-pids"
      echo "$capacity_streak" > "$PROJECT_ROOT/.autopilot-pids/gemini.capacity_errors"
      # Emit degraded heartbeat so orchestrator shows correct state
      emit_agent_heartbeat "$PROJECT_ROOT" "$AGENT" "$CLI" "$LANE" "$INSTANCE_ID" "capacity_degraded"
      # Use longer capacity-specific backoff for inter-cycle sleep
      cycle_sleep="$(backoff_interval_for_streak "$capacity_streak" "$CAPACITY_BACKOFF" "120")"
      log WARN "capacity backoff: next retry in ${cycle_sleep}s (streak=$capacity_streak)"
    fi
  fi
  rm -f "$prompt_file"
  prune_old_logs "$LOG_DIR" "worker-${AGENT}-" "$MAX_LOG_FILES"

  if [[ "$ONCE" == true ]]; then
    exit 0 # Loop completed its iteration, even if CLI timed out internally
  fi
  if [[ "$skip_sleep" == false ]]; then
    sleep_with_jitter "$cycle_sleep"
  fi
done
