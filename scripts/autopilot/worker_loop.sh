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
PERSISTENT=false
MAX_TASKS_PER_SESSION=5

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
    --persistent) PERSISTENT=true; shift ;;
    --max-tasks-per-session) MAX_TASKS_PER_SESSION="$2"; shift 2 ;;
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

# ---------------------------------------------------------------------------
# Persistent mode: delegate to Python persistent worker.
# Falls back to legacy spawn-per-cycle if the persistent worker exits non-zero.
# ---------------------------------------------------------------------------
if [[ "$PERSISTENT" == true ]]; then
  log INFO "persistent mode enabled; delegating to orchestrator.persistent_worker"
  persistent_args=(
    --cli "$CLI" --agent "$AGENT" --lane "$LANE"
    --project-root "$PROJECT_ROOT" --repo-root "$ROOT_DIR"
    --log-dir "$LOG_DIR" --cli-timeout "$CLI_TIMEOUT"
    --idle-backoff "$IDLE_BACKOFF" --max-idle-cycles "$MAX_IDLE_CYCLES"
    --daily-call-budget "$DAILY_CALL_BUDGET"
    --signal-max-wait "$EVENT_MAX_WAIT"
    --signal-poll-interval "$EVENT_POLL_INTERVAL"
  )
  if [[ -n "$TEAM_ID" ]]; then
    persistent_args+=(--team-id "$TEAM_ID")
  fi
  if [[ -n "$INSTANCE_ID_OVERRIDE" ]]; then
    persistent_args+=(--instance-id "$INSTANCE_ID_OVERRIDE")
  fi
  if [[ "$DAILY_TOKEN_BUDGET" -gt 0 ]]; then
    persistent_args+=(--daily-token-budget "$DAILY_TOKEN_BUDGET")
  fi
  if [[ "$HOURLY_TOKEN_BUDGET" -gt 0 ]]; then
    persistent_args+=(--hourly-token-budget "$HOURLY_TOKEN_BUDGET")
  fi
  if [[ "$TOKENS_PER_CALL" -ne 10000 ]]; then
    persistent_args+=(--tokens-per-call "$TOKENS_PER_CALL")
  fi
  if python3 -m orchestrator.persistent_worker "${persistent_args[@]}"; then
    log INFO "persistent worker exited cleanly"
    exit 0
  else
    pw_rc=$?
    log WARN "persistent worker exited rc=$pw_rc; falling back to legacy spawn-per-cycle"
    # Fall through to legacy loop below.
  fi
fi

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
   - YOU ARE A PURE CODE REVIEWER. You do NOT implement tasks. You ONLY review.
   - DO NOT call orchestrator_claim_next_task. You never claim or implement work.
   - Your cycle:
     1. Call orchestrator_list_tasks(status="reported") to find tasks awaiting your review.
     2. For each reported task where review_gate.status="pending":
        a) Read the task report file (commit SHA, test results, acceptance criteria)
        b) Use git diff to read the actual code changes for that commit
        c) Check for: bugs, logic errors, missing edge cases, security issues, test gaps, code quality
        d) If the code is good:
           Call orchestrator_set_review_gate(task_id=..., status="approved", reviewer_agent="__AGENT__", notes="Approved: <brief reason>")
        e) If the code has issues:
           Call orchestrator_set_review_gate(task_id=..., status="rejected", reviewer_agent="__AGENT__", notes="Rejected: <specific issues found>")
           Call orchestrator_raise_blocker(task_id=..., question="Code review failed: <issues>", agent="__AGENT__")
     3. If no tasks need review, print "idle" and exit.
   - Be thorough. Check actual code, not just test results. Find real bugs.
   - You are the quality gate. Nothing ships without your approval.
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
  claim_args="agent=\"${AGENT}\""
  if [[ -n "$TEAM_ID" ]]; then
    claim_args="${claim_args}, team_id=\"${TEAM_ID}\""
  fi

  if [[ "$PERSISTENT" == true ]]; then
    # Persistent mode: multi-task loop prompt. The CLI stays alive across
    # consecutive tasks, eliminating cold-start (MCP init, schema negotiation)
    # for all but the first task in the session.
    cat >"$prompt_file" <<EOF
Project: $(basename "$PROJECT_ROOT")
You are worker agent ${AGENT} running a PERSISTENT session (multi-task).
Lane: ${LANE}
Team: ${TEAM_ID:-none}
Max tasks this session: ${MAX_TASKS_PER_SESSION}

Execute worker cycles continuously until no claimable work remains or you
have completed ${MAX_TASKS_PER_SESSION} tasks, whichever comes first.

SETUP (once, at session start):
1. Call orchestrator_connect_to_leader for agent="${AGENT}" with full identity metadata.
2. Check the connect response for an auto_claimed_task field.
   - If auto_claimed_task is present and contains a task, use it directly as your first claimed task (skip to TASK LOOP step 6).
   - If auto_claimed_task is absent or null, proceed to step 3.
3. Call orchestrator_poll_events(agent="${AGENT}", timeout_ms=1000).
4. Call orchestrator_claim_next_task(${claim_args}).
5. If no task is claimable (and none was auto-claimed), print "idle" and exit.

TASK LOOP (repeat for each claimed task):
6. If a task is claimed:
${lane_rules}
${team_rules}
   - implement only that task in this project
   - run relevant tests/build checks
   - call orchestrator_submit_report with commit SHA and test results
   - if blocked, call orchestrator_raise_blocker instead of stalling
7. After submitting the report, call orchestrator_claim_next_task(${claim_args}).
8. If another task is claimed, go to step 6.
9. If no more tasks are claimable, print "session_complete" and exit.

Rules:
- Work only inside $PROJECT_ROOT
- Use MCP tools for orchestration state
- Never silently stop; submit report or raise blocker
- Process up to ${MAX_TASKS_PER_SESSION} tasks per session, then exit for refresh
- Keep the session alive between tasks to avoid cold-start overhead
EOF
  else
    # Legacy one-shot mode: single task per CLI invocation.
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
4. Call orchestrator_claim_next_task(${claim_args}).
5. If no task is claimable (and none was auto-claimed), print "idle" and exit.
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
  fi

  # Persistent sessions get a proportionally longer timeout.
  effective_timeout="$CLI_TIMEOUT"
  if [[ "$PERSISTENT" == true ]]; then
    effective_timeout=$(( CLI_TIMEOUT * MAX_TASKS_PER_SESSION ))
  fi

  # Keep legacy marker for existing parsers/tests while adding canonical action event.
  log INFO "worker cycle=$cycle agent=$AGENT cli=$CLI project=$PROJECT_ROOT persistent=$PERSISTENT"
  log INFO "CANONICAL ACTION: WORKER_PULSE cycle=$cycle agent=$AGENT cli=$CLI project=$PROJECT_ROOT persistent=$PERSISTENT"
  cycle_sleep="$INTERVAL"
  if run_cli_prompt "$CLI" "$PROJECT_ROOT" "$prompt_file" "$out_file" "$effective_timeout" "$AGENT" "$LANE" "${AGENT}#headless-${LANE}"; then
    log INFO "worker cycle complete agent=$AGENT; log=$out_file"
    # In persistent mode, the session already processed consecutive tasks
    # internally, so there is no next task to pick up; check session_complete.
    skip_sleep=false
    if [[ "$PERSISTENT" == true ]] && grep -q "session_complete" "$out_file"; then
      log INFO "persistent session completed multiple tasks; skipping inter-cycle sleep."
      skip_sleep=true
    fi
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
      log ERROR "worker cycle timed out agent=$AGENT after ${effective_timeout}s; see $out_file"
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
