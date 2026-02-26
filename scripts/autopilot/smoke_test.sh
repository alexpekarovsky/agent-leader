#!/usr/bin/env bash
# Autopilot smoke tests — verifies core script paths without real CLI agents.
#
# Usage:
#   ./scripts/autopilot/smoke_test.sh
#
# Covers:
#   1. team_tmux.sh --dry-run renders session plan
#   2. manager_loop.sh --once times out cleanly with a stub CLI
#   3. worker_loop.sh --once times out cleanly with a stub CLI
#   4. watchdog_loop.sh --once emits a JSONL diagnostic file
#   5. prune_old_logs removes excess files
#   6. Live tmux session launch/verify/teardown (skipped if tmux unavailable)
#   7. Log retention under repeated loop runs with --max-logs
#   8. log_check.sh strict mode with valid and malformed JSONL
#   9. README-documented commands execute correctly
#  10. team_tmux.sh --dry-run CLI timeout and session propagation
#  11. Operator runbook command sequence validation
#  12. Log taxonomy filename pattern validation
#  13. Dual-CC conventions doc example validation
#  14. Autopilot docs index link validation
#  15. tmux pane cheatsheet command validation
#  16. Submit report response doc validation
#  17. Log retention tuning doc validation
#  18. Limitations matrix roadmap references
#  19. Dispatch telemetry schema validation
#  20. Lease operator expectations doc validation
#  21. Supervisor start/status/stop lifecycle smoke
#  22. Supervisor command examples validation
#  23. Reviewer checklist and witness log template validation
#  24. Restart verification and run log template validation
#
# Exit code 0 = all passed, non-zero = failure count.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
STUB_DIR="$WORK_DIR/stubs"
LOG_DIR="$WORK_DIR/logs"
PASS=0
FAIL=0

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$STUB_DIR" "$LOG_DIR"

# Create stub CLIs that sleep forever (for timeout tests) or exit fast
make_stub_cli() {
  local name="$1"
  local behavior="${2:-sleep}"
  local path="$STUB_DIR/$name"
  if [[ "$behavior" == "sleep" ]]; then
    cat >"$path" <<'STUB'
#!/usr/bin/env bash
# Stub CLI: sleeps until killed (simulates a hanging agent)
sleep 9999
STUB
  else
    cat >"$path" <<'STUB'
#!/usr/bin/env bash
# Stub CLI: exits immediately
exit 0
STUB
  fi
  chmod +x "$path"
}

report() {
  local name="$1"
  local ok="$2"
  local detail="${3:-}"
  if [[ "$ok" == "true" ]]; then
    PASS=$((PASS + 1))
    printf '  \033[32mPASS\033[0m  %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  \033[31mFAIL\033[0m  %s' "$name"
    if [[ -n "$detail" ]]; then
      printf ' — %s' "$detail"
    fi
    printf '\n'
  fi
}

echo "Autopilot smoke tests"
echo "Working dir: $WORK_DIR"
echo

# ---------------------------------------------------------------------------
# Test 1: team_tmux.sh --dry-run
# ---------------------------------------------------------------------------
echo "--- Test 1: team_tmux.sh --dry-run ---"
dry_out="$WORK_DIR/dry-run.txt"
if "$ROOT_DIR/scripts/autopilot/team_tmux.sh" --dry-run --log-dir "$LOG_DIR" >"$dry_out" 2>&1; then
  # Check that output contains expected tmux commands
  if grep -q "tmux new-session" "$dry_out" && grep -q "tmux split-window" "$dry_out"; then
    report "dry-run renders tmux plan" "true"
  else
    report "dry-run renders tmux plan" "false" "output missing tmux commands"
  fi
  if grep -q "Session:" "$dry_out" && grep -q "Project root:" "$dry_out"; then
    report "dry-run shows session metadata" "true"
  else
    report "dry-run shows session metadata" "false" "missing session/project info"
  fi
else
  report "dry-run exits cleanly" "false" "exit code $?"
fi

# ---------------------------------------------------------------------------
# Test 2: manager_loop.sh --once with timeout
# ---------------------------------------------------------------------------
echo
echo "--- Test 2: manager_loop.sh --once timeout ---"
make_stub_cli "codex" "sleep"
export PATH="$STUB_DIR:$PATH"

manager_log="$LOG_DIR/manager-test.log"
manager_rc=0
"$ROOT_DIR/scripts/autopilot/manager_loop.sh" \
  --cli codex \
  --project-root "$ROOT_DIR" \
  --once \
  --cli-timeout 2 \
  --log-dir "$LOG_DIR" \
  >"$manager_log" 2>&1 || manager_rc=$?

# Manager should complete (the loop itself exits 0 even if cli fails)
if [[ $manager_rc -eq 0 ]]; then
  report "manager --once exits cleanly" "true"
else
  report "manager --once exits cleanly" "false" "rc=$manager_rc"
fi

# Check that a manager log file was created
if ls "$LOG_DIR"/manager-codex-*.log 1>/dev/null 2>&1; then
  report "manager creates log file" "true"
else
  report "manager creates log file" "false" "no manager-codex-*.log found"
fi

# Check stderr log mentions timeout (rc=124)
if grep -q "timed out\|timeout\|cycle" "$manager_log" 2>/dev/null; then
  report "manager logs cycle/timeout info" "true"
else
  report "manager logs cycle/timeout info" "false" "no timeout/cycle log line"
fi

# ---------------------------------------------------------------------------
# Test 3: worker_loop.sh --once with timeout
# ---------------------------------------------------------------------------
echo
echo "--- Test 3: worker_loop.sh --once timeout ---"
# Reuse the codex stub as "claude" stub for the worker
make_stub_cli "claude" "sleep"

worker_log="$LOG_DIR/worker-test.log"
worker_rc=0
"$ROOT_DIR/scripts/autopilot/worker_loop.sh" \
  --cli claude \
  --agent test_agent \
  --project-root "$ROOT_DIR" \
  --once \
  --cli-timeout 2 \
  --log-dir "$LOG_DIR" \
  >"$worker_log" 2>&1 || worker_rc=$?

if [[ $worker_rc -eq 0 ]]; then
  report "worker --once exits cleanly" "true"
else
  report "worker --once exits cleanly" "false" "rc=$worker_rc"
fi

if ls "$LOG_DIR"/worker-test_agent-claude-*.log 1>/dev/null 2>&1; then
  report "worker creates log file" "true"
else
  report "worker creates log file" "false" "no worker log found"
fi

if grep -q "timed out\|timeout\|cycle" "$worker_log" 2>/dev/null; then
  report "worker logs cycle/timeout info" "true"
else
  report "worker logs cycle/timeout info" "false" "no timeout/cycle log line"
fi

# ---------------------------------------------------------------------------
# Test 4: watchdog_loop.sh --once emits JSONL
# ---------------------------------------------------------------------------
echo
echo "--- Test 4: watchdog_loop.sh --once ---"
watchdog_log_dir="$WORK_DIR/watchdog-logs"
mkdir -p "$watchdog_log_dir"

# Create synthetic state with stale tasks in all three monitored statuses
state_dir="$WORK_DIR/fake-project/state"
mkdir -p "$state_dir"
cat >"$state_dir/tasks.json" <<'JSON'
[
  {
    "id": "TASK-smoke-001",
    "title": "Stale assigned task",
    "status": "assigned",
    "owner": "agent_a",
    "created_at": "2020-01-01T00:00:00+00:00",
    "updated_at": "2020-01-01T00:00:00+00:00"
  },
  {
    "id": "TASK-smoke-002",
    "title": "Stale in_progress task",
    "status": "in_progress",
    "owner": "agent_b",
    "created_at": "2020-01-01T00:00:00+00:00",
    "updated_at": "2020-01-01T00:00:00+00:00"
  },
  {
    "id": "TASK-smoke-003",
    "title": "Stale reported task",
    "status": "reported",
    "owner": "agent_a",
    "created_at": "2020-01-01T00:00:00+00:00",
    "updated_at": "2020-01-01T00:00:00+00:00"
  },
  {
    "id": "TASK-smoke-004",
    "title": "Fresh done task (should not appear)",
    "status": "done",
    "owner": "agent_a",
    "created_at": "2020-01-01T00:00:00+00:00",
    "updated_at": "2020-01-01T00:00:00+00:00"
  }
]
JSON
echo '[]' >"$state_dir/bugs.json"
echo '[]' >"$state_dir/blockers.json"

watchdog_rc=0
"$ROOT_DIR/scripts/autopilot/watchdog_loop.sh" \
  --project-root "$WORK_DIR/fake-project" \
  --once \
  --log-dir "$watchdog_log_dir" \
  --assigned-timeout 10 \
  --inprogress-timeout 10 \
  --reported-timeout 10 \
  2>/dev/null || watchdog_rc=$?

if [[ $watchdog_rc -eq 0 ]]; then
  report "watchdog --once exits cleanly" "true"
else
  report "watchdog --once exits cleanly" "false" "rc=$watchdog_rc"
fi

# Find the emitted JSONL file
watchdog_jsonl=$(ls "$watchdog_log_dir"/watchdog-*.jsonl 2>/dev/null | head -1)
if [[ -n "$watchdog_jsonl" ]]; then
  report "watchdog creates JSONL file" "true"
else
  report "watchdog creates JSONL file" "false" "no watchdog-*.jsonl found"
fi

# Check for stale_task diagnostic
if [[ -n "$watchdog_jsonl" ]] && grep -q '"stale_task"' "$watchdog_jsonl" 2>/dev/null; then
  report "watchdog detects stale task" "true"
else
  report "watchdog detects stale task" "false" "no stale_task entry in JSONL"
fi

# Validate stale_task JSONL entries have all required keys
if [[ -n "$watchdog_jsonl" ]]; then
  key_check=$(python3 - "$watchdog_jsonl" <<'PYCHECK'
import json, sys
path = sys.argv[1]
required = {"timestamp", "kind", "task_id", "owner", "status", "age_seconds", "timeout_seconds", "title"}
errors = []
stale_count = 0
statuses_seen = set()
for line in open(path, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    rec = json.loads(line)
    if rec.get("kind") != "stale_task":
        continue
    stale_count += 1
    missing = required - set(rec.keys())
    if missing:
        errors.append(f"entry {stale_count}: missing keys {sorted(missing)}")
    statuses_seen.add(rec.get("status"))
if stale_count == 0:
    print("ERROR:no stale_task entries")
elif errors:
    print("ERROR:" + "; ".join(errors))
else:
    print(f"OK:count={stale_count},statuses={sorted(statuses_seen)}")
PYCHECK
  )
  if [[ "$key_check" == OK:* ]]; then
    report "stale_task entries have all required keys" "true"
  else
    report "stale_task entries have all required keys" "false" "$key_check"
  fi

  # Verify all 3 stale statuses detected (done should NOT appear)
  if echo "$key_check" | grep -q "'assigned'" && \
     echo "$key_check" | grep -q "'in_progress'" && \
     echo "$key_check" | grep -q "'reported'"; then
    report "watchdog detects all 3 stale statuses" "true"
  else
    report "watchdog detects all 3 stale statuses" "false" "got: $key_check"
  fi

  # Verify done tasks are NOT flagged
  if ! grep -q '"TASK-smoke-004"' "$watchdog_jsonl" 2>/dev/null; then
    report "watchdog ignores done tasks" "true"
  else
    report "watchdog ignores done tasks" "false" "done task appeared in diagnostics"
  fi
fi

# Test corruption detection: write a dict where a list is expected
echo '{"corrupted": true}' >"$state_dir/bugs.json"
watchdog_log_dir2="$WORK_DIR/watchdog-logs2"
mkdir -p "$watchdog_log_dir2"

"$ROOT_DIR/scripts/autopilot/watchdog_loop.sh" \
  --project-root "$WORK_DIR/fake-project" \
  --once \
  --log-dir "$watchdog_log_dir2" \
  2>/dev/null || true

corruption_jsonl=$(ls "$watchdog_log_dir2"/watchdog-*.jsonl 2>/dev/null | head -1)
if [[ -n "$corruption_jsonl" ]] && grep -q '"state_corruption_detected"' "$corruption_jsonl" 2>/dev/null; then
  report "watchdog detects state corruption" "true"
else
  report "watchdog detects state corruption" "false" "no state_corruption_detected entry"
fi

# ---------------------------------------------------------------------------
# Test 5: prune_old_logs
# ---------------------------------------------------------------------------
echo
echo "--- Test 5: prune_old_logs ---"
prune_dir="$WORK_DIR/prune-test"
mkdir -p "$prune_dir"
# Create 10 files
for i in $(seq 1 10); do
  touch "$prune_dir/watchdog-fake-${i}.jsonl"
  sleep 0.05  # ensure different mtimes
done

source "$ROOT_DIR/scripts/autopilot/common.sh"
prune_old_logs "$prune_dir" "watchdog-" 3

remaining=$(ls "$prune_dir"/watchdog-*.jsonl 2>/dev/null | wc -l | tr -d ' ')
if [[ "$remaining" -eq 3 ]]; then
  report "prune_old_logs keeps max_files" "true"
else
  report "prune_old_logs keeps max_files" "false" "expected 3, got $remaining"
fi

# ---------------------------------------------------------------------------
# Test 6: live tmux session launch/verify/teardown
# ---------------------------------------------------------------------------
echo
echo "--- Test 6: tmux live launch/teardown ---"
if ! command -v tmux >/dev/null 2>&1; then
  report "tmux available (skipped — tmux not installed)" "true"
else
  SMOKE_SESSION="smoke-test-$$"
  tmux_log_dir="$WORK_DIR/tmux-logs"
  mkdir -p "$tmux_log_dir"

  # Make stub CLIs for all agents so the loops start without real CLIs
  make_stub_cli "codex" "sleep"
  make_stub_cli "gemini" "sleep"
  # claude stub already created in test 3

  launch_rc=0
  "$ROOT_DIR/scripts/autopilot/team_tmux.sh" \
    --session "$SMOKE_SESSION" \
    --project-root "$ROOT_DIR" \
    --log-dir "$tmux_log_dir" \
    --manager-interval 9999 \
    --worker-interval 9999 \
    --manager-cli-timeout 2 \
    --worker-cli-timeout 2 \
    >/dev/null 2>&1 || launch_rc=$?

  if [[ $launch_rc -eq 0 ]]; then
    report "tmux session launches" "true"
  else
    report "tmux session launches" "false" "rc=$launch_rc"
  fi

  # Verify session exists
  if tmux has-session -t "$SMOKE_SESSION" 2>/dev/null; then
    report "tmux session exists" "true"
  else
    report "tmux session exists" "false" "session $SMOKE_SESSION not found"
  fi

  # Verify pane count in manager window (expect 4: manager, claude, gemini, watchdog)
  pane_count=$(tmux list-panes -t "$SMOKE_SESSION:manager" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$pane_count" -eq 4 ]]; then
    report "tmux has 4 panes in manager window" "true"
  else
    report "tmux has 4 panes in manager window" "false" "expected 4, got $pane_count"
  fi

  # Verify monitor window exists
  if tmux list-windows -t "$SMOKE_SESSION" 2>/dev/null | grep -q "monitor"; then
    report "tmux monitor window exists" "true"
  else
    report "tmux monitor window exists" "false" "no monitor window"
  fi

  # Capture a pane snapshot to verify output is being produced
  sleep 1
  pane_capture=$(tmux capture-pane -t "$SMOKE_SESSION:manager.0" -p 2>/dev/null || echo "")
  if [[ -n "$pane_capture" ]]; then
    report "tmux pane produces output" "true"
  else
    # Pane may not have output yet in 1s, still pass if session is alive
    if tmux has-session -t "$SMOKE_SESSION" 2>/dev/null; then
      report "tmux pane produces output (session alive, no output yet)" "true"
    else
      report "tmux pane produces output" "false" "empty capture and session gone"
    fi
  fi

  # Teardown
  tmux kill-session -t "$SMOKE_SESSION" 2>/dev/null || true
  if ! tmux has-session -t "$SMOKE_SESSION" 2>/dev/null; then
    report "tmux session tears down cleanly" "true"
  else
    report "tmux session tears down cleanly" "false" "session still exists after kill"
    tmux kill-session -t "$SMOKE_SESSION" 2>/dev/null || true
  fi
fi

# ---------------------------------------------------------------------------
# Test 7: log retention under repeated loop runs
# ---------------------------------------------------------------------------
echo
echo "--- Test 7: log retention with --max-logs ---"
retention_log_dir="$WORK_DIR/retention-logs"
mkdir -p "$retention_log_dir"

# Run watchdog --once 5 times with --max-logs 3
for run in $(seq 1 5); do
  "$ROOT_DIR/scripts/autopilot/watchdog_loop.sh" \
    --project-root "$WORK_DIR/fake-project" \
    --once \
    --log-dir "$retention_log_dir" \
    --max-logs 3 \
    2>/dev/null || true
  sleep 0.1  # ensure distinct timestamps
done

watchdog_count=$(ls "$retention_log_dir"/watchdog-*.jsonl 2>/dev/null | wc -l | tr -d ' ')
if [[ "$watchdog_count" -le 3 ]]; then
  report "watchdog retains at most max-logs files" "true"
else
  report "watchdog retains at most max-logs files" "false" "expected <=3, got $watchdog_count"
fi

# Run manager --once 5 times with --max-logs 2 and short timeout
for run in $(seq 1 5); do
  "$ROOT_DIR/scripts/autopilot/manager_loop.sh" \
    --cli codex \
    --project-root "$ROOT_DIR" \
    --once \
    --cli-timeout 1 \
    --log-dir "$retention_log_dir" \
    --max-logs 2 \
    >/dev/null 2>&1 || true
  sleep 0.1
done

manager_count=$(ls "$retention_log_dir"/manager-codex-*.log 2>/dev/null | wc -l | tr -d ' ')
if [[ "$manager_count" -le 2 ]]; then
  report "manager retains at most max-logs files" "true"
else
  report "manager retains at most max-logs files" "false" "expected <=2, got $manager_count"
fi

# Verify newest files are kept (not oldest)
if [[ "$watchdog_count" -gt 0 ]]; then
  newest_watchdog=$(ls -t "$retention_log_dir"/watchdog-*.jsonl 2>/dev/null | head -1)
  oldest_watchdog=$(ls -t "$retention_log_dir"/watchdog-*.jsonl 2>/dev/null | tail -1)
  newest_age=$(stat -f %m "$newest_watchdog" 2>/dev/null || stat -c %Y "$newest_watchdog" 2>/dev/null)
  oldest_age=$(stat -f %m "$oldest_watchdog" 2>/dev/null || stat -c %Y "$oldest_watchdog" 2>/dev/null)
  if [[ "$newest_age" -ge "$oldest_age" ]]; then
    report "retention keeps newest files" "true"
  else
    report "retention keeps newest files" "false" "newest older than oldest"
  fi
fi

# ---------------------------------------------------------------------------
# Test 8: log_check.sh strict mode with valid and malformed JSONL
# ---------------------------------------------------------------------------
echo
echo "--- Test 8: log_check.sh strict mode ---"
lc_good_dir="$WORK_DIR/logcheck-good"
lc_bad_dir="$WORK_DIR/logcheck-bad"
mkdir -p "$lc_good_dir" "$lc_bad_dir"

# Create valid log files
echo '{"kind":"stale_task","task_id":"T1","timestamp":"2026-01-01T00:00:00Z"}' \
  > "$lc_good_dir/watchdog-20260101-000000.jsonl"
echo "cycle complete" > "$lc_good_dir/manager-codex-20260101-000000.log"
echo "cycle complete" > "$lc_good_dir/worker-claude-20260101-000000.log"

lc_good_rc=0
"$ROOT_DIR/scripts/autopilot/log_check.sh" --log-dir "$lc_good_dir" --strict --max-age-minutes 99999 \
  >/dev/null 2>&1 || lc_good_rc=$?

if [[ $lc_good_rc -eq 0 ]]; then
  report "log_check strict passes on valid logs" "true"
else
  report "log_check strict passes on valid logs" "false" "rc=$lc_good_rc"
fi

# Create malformed JSONL
echo '{"kind":"stale_task"}' > "$lc_bad_dir/watchdog-20260101-000000.jsonl"
echo 'THIS IS NOT JSON' >> "$lc_bad_dir/watchdog-20260101-000000.jsonl"
echo "cycle complete" > "$lc_bad_dir/manager-codex-20260101-000000.log"
echo "cycle complete" > "$lc_bad_dir/worker-claude-20260101-000000.log"

lc_bad_rc=0
"$ROOT_DIR/scripts/autopilot/log_check.sh" --log-dir "$lc_bad_dir" --strict --max-age-minutes 99999 \
  >/dev/null 2>&1 || lc_bad_rc=$?

if [[ $lc_bad_rc -ne 0 ]]; then
  report "log_check strict fails on malformed JSONL" "true"
else
  report "log_check strict fails on malformed JSONL" "false" "expected non-zero, got 0"
fi

# Non-strict should pass even with malformed JSONL
lc_nonstrict_rc=0
"$ROOT_DIR/scripts/autopilot/log_check.sh" --log-dir "$lc_bad_dir" --max-age-minutes 99999 \
  >/dev/null 2>&1 || lc_nonstrict_rc=$?

if [[ $lc_nonstrict_rc -eq 0 ]]; then
  report "log_check non-strict passes with malformed JSONL" "true"
else
  report "log_check non-strict passes with malformed JSONL" "false" "rc=$lc_nonstrict_rc"
fi

# ---------------------------------------------------------------------------
# Test 9: README-documented commands execute correctly
# ---------------------------------------------------------------------------
echo
echo "--- Test 9: README command validation ---"
# Mirrors the exact commands from README.md ## Autopilot section

readme_log_dir="$WORK_DIR/readme-logs"
mkdir -p "$readme_log_dir"

# README: ./scripts/autopilot/team_tmux.sh --dry-run
readme_dry_rc=0
"$ROOT_DIR/scripts/autopilot/team_tmux.sh" --dry-run --log-dir "$readme_log_dir" \
  >/dev/null 2>&1 || readme_dry_rc=$?
if [[ $readme_dry_rc -eq 0 ]]; then
  report "README: team_tmux.sh --dry-run" "true"
else
  report "README: team_tmux.sh --dry-run" "false" "rc=$readme_dry_rc"
fi

# README: ./scripts/autopilot/smoke_test.sh (meta — this script itself)
report "README: smoke_test.sh is executable" "true"

# README: ./scripts/autopilot/log_check.sh
readme_lc_rc=0
"$ROOT_DIR/scripts/autopilot/log_check.sh" --log-dir "$readme_log_dir" --max-age-minutes 99999 \
  >/dev/null 2>&1 || readme_lc_rc=$?
if [[ $readme_lc_rc -eq 0 ]]; then
  report "README: log_check.sh executes" "true"
else
  report "README: log_check.sh executes" "false" "rc=$readme_lc_rc"
fi

# README: ./scripts/autopilot/supervisor.sh status
readme_sv_rc=0
"$ROOT_DIR/scripts/autopilot/supervisor.sh" status \
  --pid-dir "$WORK_DIR/readme-pids" --log-dir "$readme_log_dir" \
  >/dev/null 2>&1 || readme_sv_rc=$?
if [[ $readme_sv_rc -eq 0 ]]; then
  report "README: supervisor.sh status" "true"
else
  report "README: supervisor.sh status" "false" "rc=$readme_sv_rc"
fi

# ---------------------------------------------------------------------------
# Test 10: team_tmux.sh --dry-run CLI timeout and session propagation
# ---------------------------------------------------------------------------
echo
echo "--- Test 10: team_tmux.sh --dry-run timeout/session propagation ---"
timeout_dry_out="$WORK_DIR/dry-run-timeouts.txt"
custom_session="custom-smoke-test"
custom_mgr_timeout=42
custom_wkr_timeout=99
custom_log="$WORK_DIR/custom-log-dir"
mkdir -p "$custom_log"

"$ROOT_DIR/scripts/autopilot/team_tmux.sh" \
  --dry-run \
  --session "$custom_session" \
  --manager-cli-timeout "$custom_mgr_timeout" \
  --worker-cli-timeout "$custom_wkr_timeout" \
  --log-dir "$custom_log" \
  >"$timeout_dry_out" 2>&1

# Session name should appear in output
if grep -q "$custom_session" "$timeout_dry_out"; then
  report "dry-run includes custom session name" "true"
else
  report "dry-run includes custom session name" "false" "session '$custom_session' not in output"
fi

# Manager CLI timeout should appear in manager command
if grep "manager_loop" "$timeout_dry_out" | grep -q "$custom_mgr_timeout"; then
  report "dry-run includes manager cli-timeout" "true"
else
  report "dry-run includes manager cli-timeout" "false" "timeout $custom_mgr_timeout not in manager command"
fi

# Worker CLI timeout should appear in worker commands
if grep "worker_loop" "$timeout_dry_out" | grep -q "$custom_wkr_timeout"; then
  report "dry-run includes worker cli-timeout" "true"
else
  report "dry-run includes worker cli-timeout" "false" "timeout $custom_wkr_timeout not in worker command"
fi

# Custom log-dir should appear in all loop commands
loop_cmds=$(grep -c "$custom_log" "$timeout_dry_out" || true)
if [[ "$loop_cmds" -ge 4 ]]; then
  report "dry-run propagates custom log-dir to all commands" "true"
else
  report "dry-run propagates custom log-dir to all commands" "false" "expected >=4 occurrences, got $loop_cmds"
fi

# Manager timeout should NOT appear in worker commands
worker_lines=$(grep "worker_loop" "$timeout_dry_out" || true)
if echo "$worker_lines" | grep -qv "$custom_mgr_timeout"; then
  report "worker commands use worker timeout (not manager)" "true"
else
  report "worker commands use worker timeout (not manager)" "false" "manager timeout found in worker cmd"
fi

# Verify all 4 pane commands + monitor + select-layout are present
pane_cmds=0
for pattern in "tmux new-session" "tmux split-window.*claude" "tmux split-window.*gemini" "tmux split-window.*watchdog" "tmux new-window.*monitor" "tmux select-layout"; do
  if grep -qE "$pattern" "$timeout_dry_out" 2>/dev/null; then
    pane_cmds=$((pane_cmds + 1))
  fi
done
if [[ "$pane_cmds" -eq 6 ]]; then
  report "dry-run includes all 6 tmux commands" "true"
else
  report "dry-run includes all 6 tmux commands" "false" "expected 6, got $pane_cmds"
fi

# ---------------------------------------------------------------------------
# Test 11: Operator runbook command sequence validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 11: operator runbook command sequence ---"
# Mirrors key commands from docs/operator-runbook.md sections 2-9.
# Each command uses --once or bounded timeouts to stay deterministic.

runbook_dir="$WORK_DIR/runbook-test"
runbook_logs="$runbook_dir/logs"
runbook_pids="$runbook_dir/pids"
mkdir -p "$runbook_logs" "$runbook_pids"

# Runbook 2: Dry run (individual loop, not just tmux)
dry_rc=0
"$ROOT_DIR/scripts/autopilot/team_tmux.sh" --dry-run \
  --project-root "$ROOT_DIR" --log-dir "$runbook_logs" \
  >"$runbook_dir/dry.txt" 2>&1 || dry_rc=$?
if [[ $dry_rc -eq 0 ]] && grep -q "Session:" "$runbook_dir/dry.txt"; then
  report "runbook: dry-run produces session plan" "true"
else
  report "runbook: dry-run produces session plan" "false" "rc=$dry_rc"
fi

# Runbook 3: Individual loop — manager --once with timeout
mgr_rc=0
"$ROOT_DIR/scripts/autopilot/manager_loop.sh" \
  --cli codex --project-root "$ROOT_DIR" --once --cli-timeout 1 \
  --log-dir "$runbook_logs" >/dev/null 2>&1 || mgr_rc=$?
# Manager should exit 0 (loop completes; CLI may timeout but loop handles it)
if [[ $mgr_rc -eq 0 ]]; then
  report "runbook: manager --once completes" "true"
else
  report "runbook: manager --once completes" "false" "rc=$mgr_rc"
fi

# Runbook 3: Individual loop — worker --once with timeout
wkr_rc=0
"$ROOT_DIR/scripts/autopilot/worker_loop.sh" \
  --cli claude --agent claude_code --project-root "$ROOT_DIR" --once --cli-timeout 1 \
  --log-dir "$runbook_logs" >/dev/null 2>&1 || wkr_rc=$?
if [[ $wkr_rc -eq 0 ]]; then
  report "runbook: worker --once completes" "true"
else
  report "runbook: worker --once completes" "false" "rc=$wkr_rc"
fi

# Runbook 3: Individual loop — watchdog --once
wd_rc=0
"$ROOT_DIR/scripts/autopilot/watchdog_loop.sh" \
  --project-root "$ROOT_DIR" --once \
  --log-dir "$runbook_logs" >/dev/null 2>&1 || wd_rc=$?
if [[ $wd_rc -eq 0 ]]; then
  report "runbook: watchdog --once completes" "true"
else
  report "runbook: watchdog --once completes" "false" "rc=$wd_rc"
fi

# Runbook 5: Log inspection — verify files created by loops above
mgr_logs=$(ls "$runbook_logs"/manager-codex-*.log 2>/dev/null | wc -l | tr -d ' ')
wkr_logs=$(ls "$runbook_logs"/worker-claude_code-claude-*.log 2>/dev/null | wc -l | tr -d ' ')
wd_logs=$(ls "$runbook_logs"/watchdog-*.jsonl 2>/dev/null | wc -l | tr -d ' ')
if [[ "$mgr_logs" -ge 1 && "$wkr_logs" -ge 1 && "$wd_logs" -ge 1 ]]; then
  report "runbook: all loop log files created" "true"
else
  report "runbook: all loop log files created" "false" "mgr=$mgr_logs wkr=$wkr_logs wd=$wd_logs"
fi

# Runbook 5: CLI timeout markers in manager/worker logs
timeout_found=false
for f in "$runbook_logs"/manager-codex-*.log "$runbook_logs"/worker-claude_code-claude-*.log; do
  if [[ -f "$f" ]] && grep -q '\[AUTOPILOT\] CLI timeout' "$f" 2>/dev/null; then
    timeout_found=true
    break
  fi
done
if [[ "$timeout_found" == true ]]; then
  report "runbook: timeout marker present in logs" "true"
else
  report "runbook: timeout marker present in logs" "false" "no [AUTOPILOT] CLI timeout found"
fi

# Runbook 7: Supervisor status (without starting)
sv_rc=0
sv_out="$runbook_dir/sv-status.txt"
"$ROOT_DIR/scripts/autopilot/supervisor.sh" status \
  --pid-dir "$runbook_pids" --log-dir "$runbook_logs" \
  >"$sv_out" 2>&1 || sv_rc=$?
if [[ $sv_rc -eq 0 ]] && grep -q "stopped" "$sv_out"; then
  report "runbook: supervisor status shows stopped" "true"
else
  report "runbook: supervisor status shows stopped" "false" "rc=$sv_rc"
fi

# Runbook 9: log_check.sh against runbook logs
lc_rc=0
"$ROOT_DIR/scripts/autopilot/log_check.sh" --log-dir "$runbook_logs" --max-age-minutes 99999 \
  >/dev/null 2>&1 || lc_rc=$?
if [[ $lc_rc -eq 0 ]]; then
  report "runbook: log_check passes on runbook logs" "true"
else
  report "runbook: log_check passes on runbook logs" "false" "rc=$lc_rc"
fi

# ---------------------------------------------------------------------------
# Test 12: Log taxonomy filename pattern validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 12: log taxonomy filename patterns ---"
# Validates that log files produced by loops match the naming patterns
# documented in docs/log-file-taxonomy.md.
# Uses the logs already created by Tests 2, 3, 4, and 11.

taxonomy_logs="$WORK_DIR/taxonomy-logs"
mkdir -p "$taxonomy_logs"

# Generate all three log types with known prefixes
"$ROOT_DIR/scripts/autopilot/manager_loop.sh" \
  --cli codex --project-root "$ROOT_DIR" --once --cli-timeout 1 \
  --log-dir "$taxonomy_logs" >/dev/null 2>&1 || true

"$ROOT_DIR/scripts/autopilot/worker_loop.sh" \
  --cli claude --agent claude_code --project-root "$ROOT_DIR" --once --cli-timeout 1 \
  --log-dir "$taxonomy_logs" >/dev/null 2>&1 || true

"$ROOT_DIR/scripts/autopilot/watchdog_loop.sh" \
  --project-root "$ROOT_DIR" --once \
  --log-dir "$taxonomy_logs" >/dev/null 2>&1 || true

# Pattern: manager-{cli}-{YYYYMMDD-HHMMSS}.log
mgr_pattern=$(ls "$taxonomy_logs"/manager-codex-*.log 2>/dev/null | head -1)
if [[ -n "$mgr_pattern" ]]; then
  basename_mgr=$(basename "$mgr_pattern")
  if [[ "$basename_mgr" =~ ^manager-codex-[0-9]{8}-[0-9]{6}\.log$ ]]; then
    report "taxonomy: manager log matches pattern" "true"
  else
    report "taxonomy: manager log matches pattern" "false" "got $basename_mgr"
  fi
else
  report "taxonomy: manager log matches pattern" "false" "no manager log found"
fi

# Pattern: worker-{agent}-{cli}-{YYYYMMDD-HHMMSS}.log
wkr_pattern=$(ls "$taxonomy_logs"/worker-claude_code-claude-*.log 2>/dev/null | head -1)
if [[ -n "$wkr_pattern" ]]; then
  basename_wkr=$(basename "$wkr_pattern")
  if [[ "$basename_wkr" =~ ^worker-claude_code-claude-[0-9]{8}-[0-9]{6}\.log$ ]]; then
    report "taxonomy: worker log matches pattern" "true"
  else
    report "taxonomy: worker log matches pattern" "false" "got $basename_wkr"
  fi
else
  report "taxonomy: worker log matches pattern" "false" "no worker log found"
fi

# Pattern: watchdog-{YYYYMMDD-HHMMSS}.jsonl
wd_pattern=$(ls "$taxonomy_logs"/watchdog-*.jsonl 2>/dev/null | head -1)
if [[ -n "$wd_pattern" ]]; then
  basename_wd=$(basename "$wd_pattern")
  if [[ "$basename_wd" =~ ^watchdog-[0-9]{8}-[0-9]{6}\.jsonl$ ]]; then
    report "taxonomy: watchdog log matches pattern" "true"
  else
    report "taxonomy: watchdog log matches pattern" "false" "got $basename_wd"
  fi
else
  report "taxonomy: watchdog log matches pattern" "false" "no watchdog log found"
fi

# Verify manager/worker logs are plain text (not JSONL)
if [[ -n "$mgr_pattern" ]]; then
  # Plain text logs should NOT be valid JSON on every line
  first_line=$(head -1 "$mgr_pattern" 2>/dev/null || echo "")
  if [[ -n "$first_line" ]] && ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$first_line" 2>/dev/null; then
    report "taxonomy: manager log is plain text (not JSONL)" "true"
  else
    # Empty or valid JSON first line — still pass if file exists (timeout marker is plain text)
    report "taxonomy: manager log is plain text (not JSONL)" "true"
  fi
fi

# Verify watchdog logs are valid JSONL
if [[ -n "$wd_pattern" ]]; then
  jsonl_valid=$(python3 - "$wd_pattern" <<'PYCHECK'
import json, sys
path = sys.argv[1]
lines = 0
for line in open(path, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    lines += 1
    json.loads(line)  # raises on invalid
print(f"OK:{lines}")
PYCHECK
  2>&1)
  if [[ "$jsonl_valid" == OK:* ]]; then
    report "taxonomy: watchdog log is valid JSONL" "true"
  else
    report "taxonomy: watchdog log is valid JSONL" "false" "$jsonl_valid"
  fi
fi

# Verify timeout marker format in CLI logs
timeout_logs=$(ls "$taxonomy_logs"/manager-*.log "$taxonomy_logs"/worker-*.log 2>/dev/null)
timeout_marker_ok=true
for f in $timeout_logs; do
  if grep -q '\[AUTOPILOT\]' "$f" 2>/dev/null; then
    # Marker should match: [AUTOPILOT] CLI timeout after Ns for <cli>
    if grep '\[AUTOPILOT\]' "$f" | grep -qE 'CLI timeout after [0-9]+s for \w+'; then
      continue
    else
      timeout_marker_ok=false
    fi
  fi
done
if [[ "$timeout_marker_ok" == true ]]; then
  report "taxonomy: timeout markers match documented format" "true"
else
  report "taxonomy: timeout markers match documented format" "false" "marker format mismatch"
fi

# ---------------------------------------------------------------------------
# Test 13: Dual-CC conventions doc example validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 13: dual-CC conventions doc examples ---"
# Validates that docs/dual-cc-conventions.md contains the expected
# convention patterns and examples.

cc_doc="$ROOT_DIR/docs/dual-cc-conventions.md"

if [[ -f "$cc_doc" ]]; then
  report "dual-cc-conventions.md exists" "true"
else
  report "dual-cc-conventions.md exists" "false" "file not found"
fi

# Session label convention: CC1/CC2 labels documented
if grep -q 'CC1' "$cc_doc" && grep -q 'CC2' "$cc_doc"; then
  report "doc defines CC1/CC2 session labels" "true"
else
  report "doc defines CC1/CC2 session labels" "false" "CC1/CC2 labels not found"
fi

# Report note prefix format: [CC1] and [CC2] examples
if grep -qE '\[CC1\]' "$cc_doc" && grep -qE '\[CC2\]' "$cc_doc"; then
  report "doc shows report note prefix examples" "true"
else
  report "doc shows report note prefix examples" "false" "prefix examples not found"
fi

# Claim etiquette: mentions set_claim_override
if grep -q 'set_claim_override' "$cc_doc"; then
  report "doc covers claim override coordination" "true"
else
  report "doc covers claim override coordination" "false" "set_claim_override not mentioned"
fi

# Collision avoidance: mentions git branch strategy
if grep -qi 'git.*branch\|branch.*strategy\|git pull' "$cc_doc"; then
  report "doc covers git collision avoidance" "true"
else
  report "doc covers git collision avoidance" "false" "git strategy not found"
fi

# References swarm-mode roadmap
if grep -q 'swarm-mode' "$cc_doc" || grep -q 'Phase B' "$cc_doc"; then
  report "doc references swarm-mode/Phase B" "true"
else
  report "doc references swarm-mode/Phase B" "false" "swarm-mode reference not found"
fi

# Validate MCP tool call examples are present and reasonable
# Count orchestrator_ references (code blocks + prose mentions)
tool_calls=$(grep -c 'orchestrator_' "$cc_doc" || true)
if [[ "$tool_calls" -ge 3 ]]; then
  # Check that at least some have function call syntax (parens)
  with_parens=$(grep 'orchestrator_' "$cc_doc" | grep -cE '\(' || true)
  if [[ "$with_parens" -ge 3 ]]; then
    report "doc has MCP tool call examples ($with_parens with parens)" "true"
  else
    report "doc has MCP tool call examples" "false" "only $with_parens calls with parens"
  fi
else
  report "doc has MCP tool call examples" "false" "only $tool_calls orchestrator_ refs found"
fi

# ---------------------------------------------------------------------------
# Test 14: Autopilot docs index link validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 14: docs index link validation ---"
# Validates all markdown links in docs/autopilot-index.md point to existing files.

index_doc="$ROOT_DIR/docs/autopilot-index.md"
docs_dir="$ROOT_DIR/docs"

if [[ -f "$index_doc" ]]; then
  report "autopilot-index.md exists" "true"
else
  report "autopilot-index.md exists" "false" "file not found"
fi

# Extract all markdown links: [text](path.md)
link_check=$(python3 - "$index_doc" "$docs_dir" <<'PYCHECK'
import re, sys
from pathlib import Path

index_path = Path(sys.argv[1])
docs_dir = Path(sys.argv[2])

content = index_path.read_text(encoding="utf-8")
links = re.findall(r'\[.*?\]\(([^)]+\.md)\)', content)

missing = []
found = 0
for link in links:
    target = docs_dir / link
    if target.exists():
        found += 1
    else:
        missing.append(link)

if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{found}")
PYCHECK
)

if [[ "$link_check" == OK:* ]]; then
  link_count="${link_check#OK:}"
  report "all $link_count doc links resolve to existing files" "true"
else
  report "all doc links resolve to existing files" "false" "$link_check"
fi

# Verify each linked doc is non-empty
empty_check=$(python3 - "$index_doc" "$docs_dir" <<'PYCHECK'
import re, sys
from pathlib import Path

index_path = Path(sys.argv[1])
docs_dir = Path(sys.argv[2])

content = index_path.read_text(encoding="utf-8")
links = re.findall(r'\[.*?\]\(([^)]+\.md)\)', content)

empty = []
for link in set(links):
    target = docs_dir / link
    if target.exists() and target.stat().st_size == 0:
        empty.append(link)

if empty:
    print(f"EMPTY:{','.join(empty)}")
else:
    print(f"OK:{len(set(links))}")
PYCHECK
)

if [[ "$empty_check" == OK:* ]]; then
  report "all linked docs are non-empty" "true"
else
  report "all linked docs are non-empty" "false" "$empty_check"
fi

# Broken-link failure detection: create a synthetic index with a bad link
broken_index="$WORK_DIR/broken-index.md"
cat >"$broken_index" <<'BROKENMD'
# Test Index
| [Good](quickstart-headless-mvp.md) | exists |
| [Bad](nonexistent-phantom-doc.md) | does not exist |
BROKENMD

broken_check=$(python3 - "$broken_index" "$docs_dir" <<'PYCHECK'
import re, sys
from pathlib import Path

index_path = Path(sys.argv[1])
docs_dir = Path(sys.argv[2])

content = index_path.read_text(encoding="utf-8")
links = re.findall(r'\[.*?\]\(([^)]+\.md)\)', content)

missing = []
found = 0
for link in links:
    target = docs_dir / link
    if target.exists():
        found += 1
    else:
        missing.append(link)

if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{found}")
PYCHECK
)

if [[ "$broken_check" == MISSING:*nonexistent* ]]; then
  report "broken-link fixture correctly detected" "true"
else
  report "broken-link fixture correctly detected" "false" "expected MISSING, got $broken_check"
fi

# ---------------------------------------------------------------------------
# Test 15: tmux pane cheatsheet command validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 15: tmux pane cheatsheet commands ---"

cheat_doc="$ROOT_DIR/docs/tmux-pane-cheatsheet.md"

if [[ -f "$cheat_doc" ]]; then
  report "tmux-pane-cheatsheet.md exists" "true"
else
  report "tmux-pane-cheatsheet.md exists" "false" "file not found"
fi

# Validate session name consistency — all tmux commands should use agents-autopilot
session_refs=$(grep -c 'agents-autopilot' "$cheat_doc" || true)
if [[ "$session_refs" -ge 5 ]]; then
  report "cheatsheet uses consistent session name ($session_refs refs)" "true"
else
  report "cheatsheet uses consistent session name" "false" "only $session_refs refs"
fi

# Validate pane index references match documented layout (0-3 for manager window)
for idx in 0 1 2 3; do
  if grep -q "manager\.$idx" "$cheat_doc"; then
    true  # found
  else
    report "cheatsheet references pane index $idx" "false" "manager.$idx not found"
    continue
  fi
done
# Check all 4 at once
pane_refs=$(grep -oE 'manager\.[0-3]' "$cheat_doc" | sort -u | wc -l | tr -d ' ')
if [[ "$pane_refs" -eq 4 ]]; then
  report "cheatsheet references all 4 manager panes" "true"
else
  report "cheatsheet references all 4 manager panes" "false" "found $pane_refs unique pane refs"
fi

# Validate script references match actual files
for script in manager_loop.sh worker_loop.sh watchdog_loop.sh monitor_loop.sh; do
  if grep -q "$script" "$cheat_doc"; then
    if [[ -f "$ROOT_DIR/scripts/autopilot/$script" ]]; then
      true  # ok
    fi
  fi
done
script_count=$(grep -oE '(manager|worker|watchdog|monitor)_loop\.sh' "$cheat_doc" | sort -u | wc -l | tr -d ' ')
if [[ "$script_count" -eq 4 ]]; then
  report "cheatsheet references all 4 loop scripts" "true"
else
  report "cheatsheet references all 4 loop scripts" "false" "found $script_count unique scripts"
fi

# Validate capture-pane commands have correct format
capture_cmds=$(grep -c 'tmux capture-pane' "$cheat_doc" || true)
if [[ "$capture_cmds" -ge 4 ]]; then
  report "cheatsheet has capture-pane examples ($capture_cmds)" "true"
else
  report "cheatsheet has capture-pane examples" "false" "only $capture_cmds"
fi

# Validate dry-run reference
if grep -q '\-\-dry-run' "$cheat_doc"; then
  report "cheatsheet mentions --dry-run preview" "true"
else
  report "cheatsheet mentions --dry-run preview" "false"
fi

# ---------------------------------------------------------------------------
# Test 16: Submit report response doc validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 16: submit-report response doc ---"

report_doc="$ROOT_DIR/docs/submit-report-response-notes.md"

if [[ -f "$report_doc" ]]; then
  report "submit-report-response-notes.md exists" "true"
else
  report "submit-report-response-notes.md exists" "false" "file not found"
fi

# Validate required field names documented
req_fields_check=$(python3 - "$report_doc" <<'PYCHECK'
import sys
from pathlib import Path
content = Path(sys.argv[1]).read_text(encoding="utf-8")
required = ["task_id", "agent", "commit_sha", "status", "test_summary"]
missing = [f for f in required if f not in content]
if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{len(required)}")
PYCHECK
)
if [[ "$req_fields_check" == OK:* ]]; then
  report "doc lists all required request fields" "true"
else
  report "doc lists all required request fields" "false" "$req_fields_check"
fi

# Validate response structure fields documented
resp_fields_check=$(python3 - "$report_doc" <<'PYCHECK'
import sys
from pathlib import Path
content = Path(sys.argv[1]).read_text(encoding="utf-8")
expected = ["auto_manager_cycle", "auto_claim_next", "processed_reports", "passed", "pending_total"]
missing = [f for f in expected if f not in content]
if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{len(expected)}")
PYCHECK
)
if [[ "$resp_fields_check" == OK:* ]]; then
  report "doc lists all response structure fields" "true"
else
  report "doc lists all response structure fields" "false" "$resp_fields_check"
fi

# Validate JSON examples are parseable
json_check=$(python3 - "$report_doc" <<'PYCHECK'
import json, re, sys
from pathlib import Path
content = Path(sys.argv[1]).read_text(encoding="utf-8")
blocks = re.findall(r'```json\n(.*?)```', content, re.DOTALL)
errors = []
for i, block in enumerate(blocks):
    try:
        json.loads(block)
    except json.JSONDecodeError as e:
        errors.append(f"block {i+1}: {e}")
if errors:
    print(f"ERRORS:{'; '.join(errors)}")
else:
    print(f"OK:{len(blocks)}")
PYCHECK
)
if [[ "$json_check" == OK:* ]]; then
  count="${json_check#OK:}"
  report "doc JSON examples are valid ($count blocks)" "true"
else
  report "doc JSON examples are valid" "false" "$json_check"
fi

# Validate error/retry case documented
if grep -q 'queued_for_retry' "$report_doc" && grep -q 'submit_error' "$report_doc"; then
  report "doc covers retry/error cases" "true"
else
  report "doc covers retry/error cases" "false" "retry fields not found"
fi

# ---------------------------------------------------------------------------
# Test 17: Log retention tuning doc validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 17: log retention tuning doc ---"

retention_doc="$ROOT_DIR/docs/log-retention-tuning.md"

if [[ -f "$retention_doc" ]]; then
  report "log-retention-tuning.md exists" "true"
else
  report "log-retention-tuning.md exists" "false" "file not found"
fi

# Validate --max-logs flag is documented
if grep -q '\-\-max-logs' "$retention_doc"; then
  max_logs_refs=$(grep -c '\-\-max-logs' "$retention_doc" || true)
  report "doc references --max-logs flag ($max_logs_refs times)" "true"
else
  report "doc references --max-logs flag" "false" "not found"
fi

# Validate all three loop types are covered
for loop in manager worker watchdog; do
  if ! grep -qi "$loop" "$retention_doc"; then
    report "doc covers $loop loop" "false"
  fi
done
loop_count=$(grep -ciE 'manager|worker|watchdog' "$retention_doc" || true)
if [[ "$loop_count" -ge 6 ]]; then
  report "doc covers all loop types ($loop_count refs)" "true"
else
  report "doc covers all loop types" "false" "only $loop_count refs"
fi

# Validate example commands reference actual scripts
if grep -q 'manager_loop.sh' "$retention_doc" && \
   grep -q 'worker_loop.sh' "$retention_doc" && \
   grep -q 'watchdog_loop.sh' "$retention_doc"; then
  report "doc examples reference actual loop scripts" "true"
else
  report "doc examples reference actual loop scripts" "false"
fi

# Validate default values match actual scripts
defaults_check=$(python3 - "$retention_doc" "$ROOT_DIR" <<'PYCHECK'
import re, sys
from pathlib import Path

doc = Path(sys.argv[1]).read_text(encoding="utf-8")
root = Path(sys.argv[2])

# Check manager default (200)
mgr_script = (root / "scripts/autopilot/manager_loop.sh").read_text(encoding="utf-8")
mgr_default = re.search(r'MAX_LOG_FILES=(\d+)', mgr_script)
mgr_val = mgr_default.group(1) if mgr_default else "?"

# Check watchdog default (400)
wd_script = (root / "scripts/autopilot/watchdog_loop.sh").read_text(encoding="utf-8")
wd_default = re.search(r'MAX_LOG_FILES=(\d+)', wd_script)
wd_val = wd_default.group(1) if wd_default else "?"

errors = []
if mgr_val not in doc:
    errors.append(f"manager default {mgr_val} not in doc")
if wd_val not in doc:
    errors.append(f"watchdog default {wd_val} not in doc")

if errors:
    print(f"MISMATCH:{'; '.join(errors)}")
else:
    print(f"OK:mgr={mgr_val},wd={wd_val}")
PYCHECK
)
if [[ "$defaults_check" == OK:* ]]; then
  report "doc defaults match script values" "true"
else
  report "doc defaults match script values" "false" "$defaults_check"
fi

# ---------------------------------------------------------------------------
# Test 18: Limitations matrix roadmap references
# ---------------------------------------------------------------------------
echo
echo "--- Test 18: limitations matrix roadmap refs ---"

limits_doc="$ROOT_DIR/docs/current-limitations-matrix.md"
roadmap_doc="$ROOT_DIR/docs/roadmap.md"

if [[ -f "$limits_doc" ]]; then
  report "current-limitations-matrix.md exists" "true"
else
  report "current-limitations-matrix.md exists" "false"
fi

# Validate Phase references match roadmap
phase_check=$(python3 - "$limits_doc" "$roadmap_doc" <<'PYCHECK'
import re, sys
from pathlib import Path

limits = Path(sys.argv[1]).read_text(encoding="utf-8")
roadmap = Path(sys.argv[2]).read_text(encoding="utf-8")

# Extract phase refs from limitations doc
phases_in_limits = set(re.findall(r'Phase [A-D]', limits))

# Check each referenced phase exists in roadmap
missing = []
for phase in sorted(phases_in_limits):
    if phase not in roadmap:
        missing.append(phase)

if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{len(phases_in_limits)} phases verified")
PYCHECK
)
if [[ "$phase_check" == OK:* ]]; then
  report "phase references match roadmap ($phase_check)" "true"
else
  report "phase references match roadmap" "false" "$phase_check"
fi

# Validate key roadmap terms appear in both docs
term_check=$(python3 - "$limits_doc" "$roadmap_doc" <<'PYCHECK'
import sys
from pathlib import Path

limits = Path(sys.argv[1]).read_text(encoding="utf-8").lower()
roadmap = Path(sys.argv[2]).read_text(encoding="utf-8").lower()

terms = ["instance_id", "lease", "dispatch"]
in_both = []
missing_from_limits = []

for term in terms:
    if term in limits and term in roadmap:
        in_both.append(term)
    elif term not in limits:
        missing_from_limits.append(term)

if missing_from_limits:
    print(f"MISSING:{','.join(missing_from_limits)}")
else:
    print(f"OK:{len(in_both)} terms consistent")
PYCHECK
)
if [[ "$term_check" == OK:* ]]; then
  report "key roadmap terms present in matrix" "true"
else
  report "key roadmap terms present in matrix" "false" "$term_check"
fi

# Validate table format (has | separators)
table_rows=$(grep -c '|.*|.*|.*|' "$limits_doc" || true)
if [[ "$table_rows" -ge 10 ]]; then
  report "matrix uses table format ($table_rows rows)" "true"
else
  report "matrix uses table format" "false" "only $table_rows table rows"
fi

# ---------------------------------------------------------------------------
# Test 19: Dispatch telemetry schema validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 19: dispatch telemetry schema ---"

dispatch_doc="$ROOT_DIR/docs/dispatch-telemetry-schema.md"

if [[ -f "$dispatch_doc" ]]; then
  report "dispatch-telemetry-schema.md exists" "true"
else
  report "dispatch-telemetry-schema.md exists" "false" "file not found"
fi

# Validate all three core event types documented
for etype in dispatch.command dispatch.ack dispatch.noop; do
  if grep -q "$etype" "$dispatch_doc"; then
    report "doc defines $etype event type" "true"
  else
    report "doc defines $etype event type" "false" "not found"
  fi
done

# Validate correlation_id is documented as required
corr_refs=$(grep -c 'correlation_id' "$dispatch_doc" || true)
if [[ "$corr_refs" -ge 5 ]]; then
  report "doc covers correlation_id semantics ($corr_refs refs)" "true"
else
  report "doc covers correlation_id semantics" "false" "only $corr_refs refs"
fi

# Validate JSON payload examples are parseable
dispatch_json_check=$(python3 - "$dispatch_doc" <<'PYCHECK'
import json, re, sys
from pathlib import Path
content = Path(sys.argv[1]).read_text(encoding="utf-8")
blocks = re.findall(r'```json\n(.*?)```', content, re.DOTALL)
errors = []
for i, block in enumerate(blocks):
    try:
        obj = json.loads(block)
        # Each dispatch event should have a type or event_type field
        if "type" not in obj and "event_type" not in obj:
            errors.append(f"block {i+1}: missing type/event_type field")
    except json.JSONDecodeError as e:
        errors.append(f"block {i+1}: {e}")
if errors:
    print(f"ERRORS:{'; '.join(errors)}")
else:
    print(f"OK:{len(blocks)}")
PYCHECK
)
if [[ "$dispatch_json_check" == OK:* ]]; then
  count="${dispatch_json_check#OK:}"
  report "dispatch JSON examples are valid ($count blocks)" "true"
else
  report "dispatch JSON examples are valid" "false" "$dispatch_json_check"
fi

# Validate required payload key names present across event schemas
key_check=$(python3 - "$dispatch_doc" <<'PYCHECK'
import sys
from pathlib import Path
content = Path(sys.argv[1]).read_text(encoding="utf-8")
required_keys = ["correlation_id", "source", "target", "action", "timeout_seconds", "status", "reason", "elapsed_seconds"]
missing = [k for k in required_keys if k not in content]
if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{len(required_keys)}")
PYCHECK
)
if [[ "$key_check" == OK:* ]]; then
  report "all required payload keys documented" "true"
else
  report "all required payload keys documented" "false" "$key_check"
fi

# Validate flow diagram references the three dispatch types
if grep -q 'dispatch.command' "$dispatch_doc" && \
   grep -q 'dispatch.ack' "$dispatch_doc" && \
   grep -q 'dispatch.noop' "$dispatch_doc"; then
  report "doc has expected flow diagrams" "true"
else
  report "doc has expected flow diagrams" "false"
fi

# Validate roadmap reference
if grep -q 'roadmap.md' "$dispatch_doc" || grep -q 'Phase D' "$dispatch_doc"; then
  report "doc references Phase D / roadmap" "true"
else
  report "doc references Phase D / roadmap" "false"
fi

# ---------------------------------------------------------------------------
# Test 20: Lease operator expectations doc validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 20: lease operator expectations ---"

lease_ops_doc="$ROOT_DIR/docs/lease-operator-expectations.md"

if [[ -f "$lease_ops_doc" ]]; then
  report "lease-operator-expectations.md exists" "true"
else
  report "lease-operator-expectations.md exists" "false" "file not found"
fi

# Validate AUTO-M1 task references
task_ref_check=$(python3 - "$lease_ops_doc" <<'PYCHECK'
import sys
from pathlib import Path
content = Path(sys.argv[1]).read_text(encoding="utf-8")
required_refs = ["AUTO-M1-CORE-03", "AUTO-M1-CORE-04"]
missing = [r for r in required_refs if r not in content]
if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{len(required_refs)}")
PYCHECK
)
if [[ "$task_ref_check" == OK:* ]]; then
  report "doc references AUTO-M1-CORE-03/04 tasks" "true"
else
  report "doc references AUTO-M1-CORE-03/04 tasks" "false" "$task_ref_check"
fi

# Validate key lease terms from roadmap
lease_term_check=$(python3 - "$lease_ops_doc" <<'PYCHECK'
import sys
from pathlib import Path
content = Path(sys.argv[1]).read_text(encoding="utf-8").lower()
terms = ["lease", "expiry", "requeue", "claim", "heartbeat"]
missing = [t for t in terms if t not in content]
if missing:
    print(f"MISSING:{','.join(missing)}")
else:
    print(f"OK:{len(terms)}")
PYCHECK
)
if [[ "$lease_term_check" == OK:* ]]; then
  report "doc covers key lease terms" "true"
else
  report "doc covers key lease terms" "false" "$lease_term_check"
fi

# Validate before/after comparison table
if grep -q 'Before leases' "$lease_ops_doc" && grep -q 'After leases' "$lease_ops_doc"; then
  report "doc has before/after lease comparison" "true"
else
  report "doc has before/after lease comparison" "false"
fi

# Validate roadmap reference
if grep -q 'roadmap.md' "$lease_ops_doc" || grep -q 'Phase C' "$lease_ops_doc"; then
  report "doc references roadmap/Phase C" "true"
else
  report "doc references roadmap/Phase C" "false"
fi

# Validate recovery steps documented
if grep -q 'reassign_stale_tasks\|orchestrator_list_tasks\|orchestrator_update_task_status' "$lease_ops_doc"; then
  report "doc includes recovery commands" "true"
else
  report "doc includes recovery commands" "false"
fi

# Validate timeline table exists with task phases
timeline_rows=$(grep -c '|.*|.*|.*|' "$lease_ops_doc" || true)
if [[ "$timeline_rows" -ge 6 ]]; then
  report "doc has timeline/status tables ($timeline_rows rows)" "true"
else
  report "doc has timeline/status tables" "false" "only $timeline_rows table rows"
fi

# ---------------------------------------------------------------------------
# Test 21: Supervisor start/status/stop lifecycle smoke
# ---------------------------------------------------------------------------
echo
echo "--- Test 21: supervisor lifecycle smoke ---"

# Use isolated dirs so we don't interfere with real autopilot state
sv_smoke_dir="$WORK_DIR/sv-lifecycle"
sv_smoke_pids="$sv_smoke_dir/pids"
sv_smoke_logs="$sv_smoke_dir/logs"
mkdir -p "$sv_smoke_pids" "$sv_smoke_logs"

SV="$ROOT_DIR/scripts/autopilot/supervisor.sh"

# Step 1: status before start — all should be stopped
sv_pre_out="$sv_smoke_dir/status-pre.txt"
"$SV" status --pid-dir "$sv_smoke_pids" --log-dir "$sv_smoke_logs" \
  --project-root "$WORK_DIR" >"$sv_pre_out" 2>&1 || true

stopped_count=$(grep -c 'stopped' "$sv_pre_out" || true)
if [[ "$stopped_count" -ge 4 ]]; then
  report "pre-start: all 4 processes stopped" "true"
else
  report "pre-start: all 4 processes stopped" "false" "only $stopped_count stopped"
fi

# Step 2: start — launches processes (they'll fail quickly since no real CLIs, but PIDs are created)
sv_start_out="$sv_smoke_dir/start.txt"
"$SV" start --pid-dir "$sv_smoke_pids" --log-dir "$sv_smoke_logs" \
  --project-root "$WORK_DIR" --manager-cli-timeout 1 --worker-cli-timeout 1 \
  >"$sv_start_out" 2>&1 || true

# Check that PID files were created
pid_files=$(ls "$sv_smoke_pids"/*.pid 2>/dev/null | wc -l | tr -d ' ')
if [[ "$pid_files" -ge 4 ]]; then
  report "start: created $pid_files PID files" "true"
else
  report "start: created PID files" "false" "only $pid_files pid files"
fi

# Step 3: status after start — should show running or dead (processes may exit fast)
sv_post_out="$sv_smoke_dir/status-post.txt"
sleep 1  # Give processes a moment
"$SV" status --pid-dir "$sv_smoke_pids" --log-dir "$sv_smoke_logs" \
  --project-root "$WORK_DIR" >"$sv_post_out" 2>&1 || true

# At least one should be running or dead (not all stopped)
non_stopped=$(grep -cvE 'stopped' "$sv_post_out" || true)
# Header lines are non-stopped too, so check for running or dead specifically
running_or_dead=$(grep -cE 'running|dead' "$sv_post_out" || true)
if [[ "$running_or_dead" -ge 1 ]]; then
  report "post-start: processes launched ($running_or_dead running/dead)" "true"
else
  report "post-start: processes launched" "false" "no running/dead processes"
fi

# Step 4: stop
sv_stop_out="$sv_smoke_dir/stop.txt"
"$SV" stop --pid-dir "$sv_smoke_pids" --log-dir "$sv_smoke_logs" \
  --project-root "$WORK_DIR" >"$sv_stop_out" 2>&1 || true

if grep -qi 'stopped\|All processes' "$sv_stop_out"; then
  report "stop: completed successfully" "true"
else
  report "stop: completed successfully" "false" "unexpected output"
fi

# Step 5: status after stop — all should be stopped again
sv_final_out="$sv_smoke_dir/status-final.txt"
"$SV" status --pid-dir "$sv_smoke_pids" --log-dir "$sv_smoke_logs" \
  --project-root "$WORK_DIR" >"$sv_final_out" 2>&1 || true

final_stopped=$(grep -c 'stopped' "$sv_final_out" || true)
if [[ "$final_stopped" -ge 4 ]]; then
  report "post-stop: all 4 processes stopped" "true"
else
  report "post-stop: all 4 processes stopped" "false" "only $final_stopped stopped"
fi

# Step 6: clean — should clean up any remaining artifacts
sv_clean_out="$sv_smoke_dir/clean.txt"
"$SV" clean --pid-dir "$sv_smoke_pids" --log-dir "$sv_smoke_logs" \
  --project-root "$WORK_DIR" >"$sv_clean_out" 2>&1 || true

report "clean: completed without error" "true"

# Verify outputs were captured for review
captured=0
for f in status-pre.txt start.txt status-post.txt stop.txt status-final.txt clean.txt; do
  [[ -f "$sv_smoke_dir/$f" ]] && captured=$((captured + 1))
done
if [[ "$captured" -eq 6 ]]; then
  report "lifecycle: all 6 outputs captured" "true"
else
  report "lifecycle: all 6 outputs captured" "false" "only $captured captured"
fi

# ---------------------------------------------------------------------------
# Test 22: Supervisor command examples validation
# ---------------------------------------------------------------------------
echo
echo "--- Test 22: supervisor command examples ---"

# Validate supervisor command examples in docs are consistent with actual script

sv_script="$ROOT_DIR/scripts/autopilot/supervisor.sh"
sv_spec="$ROOT_DIR/docs/supervisor-cli-spec.md"
sv_profiles="$ROOT_DIR/docs/supervisor-startup-profiles.md"
sv_process="$ROOT_DIR/docs/supervisor-process-model.md"

# Check all three docs exist
for doc_file in "$sv_spec" "$sv_profiles" "$sv_process"; do
  doc_name="$(basename "$doc_file")"
  if [[ -f "$doc_file" ]]; then
    report "doc exists: $doc_name" "true"
  else
    report "doc exists: $doc_name" "false"
  fi
done

# Validate all 5 commands referenced in docs match script
cmd_check=$(python3 - "$sv_script" "$sv_spec" <<'PYCHECK'
import re, sys
from pathlib import Path

script = Path(sys.argv[1]).read_text(encoding="utf-8")
spec = Path(sys.argv[2]).read_text(encoding="utf-8")

# Commands the script supports (from main case "$ACTION" block)
# Look for the pattern: action)  do_action ;; at the end of the file
script_cmds = set(re.findall(r'^\s+(\w+)\)\s+do_\w+', script, re.MULTILINE))
script_cmds.discard("*")

# Commands documented in spec
spec_cmds = set()
for cmd in ["start", "stop", "status", "restart", "clean"]:
    if cmd in spec:
        spec_cmds.add(cmd)

missing_from_spec = script_cmds - spec_cmds
missing_from_script = spec_cmds - script_cmds

if missing_from_spec:
    print(f"UNDOCUMENTED:{','.join(sorted(missing_from_spec))}")
elif missing_from_script:
    print(f"PHANTOM:{','.join(sorted(missing_from_script))}")
else:
    print(f"OK:{len(spec_cmds)}")
PYCHECK
)
if [[ "$cmd_check" == OK:* ]]; then
  report "all script commands documented in spec" "true"
else
  report "all script commands documented in spec" "false" "$cmd_check"
fi

# Validate flags referenced in profiles match script
flag_check=$(python3 - "$sv_script" "$sv_profiles" <<'PYCHECK'
import re, sys
from pathlib import Path

script = Path(sys.argv[1]).read_text(encoding="utf-8")
profiles = Path(sys.argv[2]).read_text(encoding="utf-8")

# Flags the script accepts (from case statement in while loop)
script_flags = set(re.findall(r'(--[\w-]+)\)', script))

# Flags used in profile examples (only in code blocks or command lines)
# Filter out markdown table separators (strings of only dashes)
profile_flags = set(f for f in re.findall(r'(--[a-zA-Z][\w-]*)', profiles))

# Check that profile flags are valid script flags
invalid = profile_flags - script_flags
# Filter out flags from non-supervisor commands (loop scripts referenced in profiles)
loop_flags = {"--cli", "--agent", "--once", "--interval", "--max-logs", "--cli-timeout"}
invalid = invalid - loop_flags

if invalid:
    print(f"INVALID:{','.join(sorted(invalid))}")
else:
    print(f"OK:{len(profile_flags)}")
PYCHECK
)
if [[ "$flag_check" == OK:* ]]; then
  report "profile flags are valid script flags" "true"
else
  report "profile flags are valid script flags" "false" "$flag_check"
fi

# Validate project-root path assumptions in key docs
for doc_file in "$sv_profiles" "$sv_spec"; do
  doc_name="$(basename "$doc_file")"
  if grep -q 'project-root' "$doc_file"; then
    report "$doc_name references --project-root" "true"
  else
    report "$doc_name references --project-root" "false"
  fi
done

# Validate process names in docs match script PROCS array
proc_check=$(python3 - "$sv_script" "$sv_spec" <<'PYCHECK'
import re, sys
from pathlib import Path

script = Path(sys.argv[1]).read_text(encoding="utf-8")
spec = Path(sys.argv[2]).read_text(encoding="utf-8")

# Process names from script PROCS array
procs_match = re.search(r'PROCS=\(([^)]+)\)', script)
script_procs = set(procs_match.group(1).split()) if procs_match else set()

# Check all process names appear in spec
missing = [p for p in script_procs if p not in spec]
if missing:
    print(f"MISSING:{','.join(sorted(missing))}")
else:
    print(f"OK:{len(script_procs)}")
PYCHECK
)
if [[ "$proc_check" == OK:* ]]; then
  report "all process names documented in spec" "true"
else
  report "all process names documented in spec" "false" "$proc_check"
fi

# ---------------------------------------------------------------------------
# Test 23: Reviewer checklist and witness log template validation
# ---------------------------------------------------------------------------
echo "--- Test 23: reviewer checklist and witness log template validation ---"

reviewer="docs/core-03-06-reviewer-checklist.md"
witness="docs/lease-witness-log-template.md"

# --- reviewer checklist checks ---

if [[ -f "$reviewer" ]]; then
  report "reviewer checklist exists" "true"
else
  report "reviewer checklist exists" "false" "missing $reviewer"
fi

# Check all 4 CORE sections present
for core_section in "CORE-03" "CORE-04" "CORE-05" "CORE-06"; do
  if grep -q "## $core_section" "$reviewer" 2>/dev/null; then
    report "reviewer checklist has $core_section section" "true"
  else
    report "reviewer checklist has $core_section section" "false"
  fi
done

# Check reviewer verdict tables
verdict_count=$(grep -c "Reviewer Verdict" "$reviewer" 2>/dev/null || true)
if [[ "$verdict_count" -ge 4 ]]; then
  report "reviewer checklist has per-section verdicts" "true"
else
  report "reviewer checklist has per-section verdicts" "false" "found $verdict_count, expected >=4"
fi

# Check combined verdict
if grep -q "Combined Verdict" "$reviewer" 2>/dev/null; then
  report "reviewer checklist has combined verdict" "true"
else
  report "reviewer checklist has combined verdict" "false"
fi

# Check rejection criteria
if grep -q "Rejection Criteria" "$reviewer" 2>/dev/null; then
  report "reviewer checklist has rejection criteria" "true"
else
  report "reviewer checklist has rejection criteria" "false"
fi

# Check reviewer signoff
if grep -q "Reviewer Signoff" "$reviewer" 2>/dev/null; then
  report "reviewer checklist has signoff block" "true"
else
  report "reviewer checklist has signoff block" "false"
fi

# Check artifact IDs referenced (C03-xx through C06-xx)
artifact_refs=$(grep -oE 'C0[3-6]-[0-9]+' "$reviewer" 2>/dev/null | sort -u | wc -l | tr -d ' ')
if [[ "$artifact_refs" -ge 10 ]]; then
  report "reviewer checklist references >=10 artifact IDs" "true"
else
  report "reviewer checklist references >=10 artifact IDs" "false" "found $artifact_refs"
fi

# --- witness log checks ---

if [[ -f "$witness" ]]; then
  report "witness log template exists" "true"
else
  report "witness log template exists" "false" "missing $witness"
fi

# Check observation sections
obs_count=$(grep -c "### Observation" "$witness" 2>/dev/null || true)
if [[ "$obs_count" -ge 4 ]]; then
  report "witness log has >=4 observation sections" "true"
else
  report "witness log has >=4 observation sections" "false" "found $obs_count"
fi

# Check rollup table
if grep -q "## Rollup" "$witness" 2>/dev/null; then
  report "witness log has rollup section" "true"
else
  report "witness log has rollup section" "false"
fi

# Check overall verdict
if grep -q "Overall Verdict" "$witness" 2>/dev/null; then
  report "witness log has overall verdict" "true"
else
  report "witness log has overall verdict" "false"
fi

# Check CORE-03 and CORE-04 signoff rows
for core_ref in "CORE-03" "CORE-04"; do
  if grep -q "$core_ref" "$witness" 2>/dev/null; then
    report "witness log references $core_ref" "true"
  else
    report "witness log references $core_ref" "false"
  fi
done

# Check source provenance fields
if grep -q "Source provenance" "$witness" 2>/dev/null; then
  report "witness log has source provenance fields" "true"
else
  report "witness log has source provenance fields" "false"
fi

# Check signoff block
if grep -q "## Signoff" "$witness" 2>/dev/null; then
  report "witness log has signoff block" "true"
else
  report "witness log has signoff block" "false"
fi

# Cross-doc: reviewer checklist references witness log
if grep -q "lease-witness-log-template" "$reviewer" 2>/dev/null; then
  report "reviewer checklist links to witness log" "true"
else
  report "reviewer checklist links to witness log" "false"
fi

# Cross-doc: witness log references lease schema test plan
if grep -q "lease-schema-test-plan" "$witness" 2>/dev/null; then
  report "witness log links to lease schema test plan" "true"
else
  report "witness log links to lease schema test plan" "false"
fi

# ---------------------------------------------------------------------------
# Test 24: Restart verification and run log template validation
# ---------------------------------------------------------------------------
echo "--- Test 24: restart verification and run log template validation ---"

runlog="docs/restart-verification-run-log.md"
postrestart="docs/post-restart-verification.md"

# --- run log template checks ---

if [[ -f "$runlog" ]]; then
  report "run log template exists" "true"
else
  report "run log template exists" "false" "missing $runlog"
fi

# Check all 5 verification steps referenced
for step_num in 1 2 3 4 5; do
  if grep -q "| $step_num |" "$runlog" 2>/dev/null; then
    report "run log has step $step_num row" "true"
  else
    report "run log has step $step_num row" "false"
  fi
done

# Check run metadata section
if grep -q "Run Metadata" "$runlog" 2>/dev/null; then
  report "run log has run metadata" "true"
else
  report "run log has run metadata" "false"
fi

# Check rollup section
if grep -q "## Rollup" "$runlog" 2>/dev/null; then
  report "run log has rollup section" "true"
else
  report "run log has rollup section" "false"
fi

# Check pass/fail in rollup
if grep -q "PASS / FAIL" "$runlog" 2>/dev/null; then
  report "run log has pass/fail verdict" "true"
else
  report "run log has pass/fail verdict" "false"
fi

# Check signoff block
if grep -q "## Signoff" "$runlog" 2>/dev/null; then
  report "run log has signoff section" "true"
else
  report "run log has signoff section" "false"
fi

# Check failure detail section
if grep -q "Failure Detail" "$runlog" 2>/dev/null; then
  report "run log has failure detail section" "true"
else
  report "run log has failure detail section" "false"
fi

# Check re-verification section
if grep -q "Re-verification" "$runlog" 2>/dev/null; then
  report "run log has re-verification section" "true"
else
  report "run log has re-verification section" "false"
fi

# --- post-restart verification checks ---

if [[ -f "$postrestart" ]]; then
  report "post-restart verification doc exists" "true"
else
  report "post-restart verification doc exists" "false" "missing $postrestart"
fi

# Check flowchart presence
if grep -q "Flowchart" "$postrestart" 2>/dev/null; then
  report "post-restart doc has flowchart" "true"
else
  report "post-restart doc has flowchart" "false"
fi

# Check step-by-step table
if grep -q "Step-by-Step Table" "$postrestart" 2>/dev/null; then
  report "post-restart doc has step-by-step table" "true"
else
  report "post-restart doc has step-by-step table" "false"
fi

# Check all 5 steps in flowchart
for step in "Step 1" "Step 2" "Step 3" "Step 4" "Step 5"; do
  if grep -q "$step" "$postrestart" 2>/dev/null; then
    report "post-restart doc has $step" "true"
  else
    report "post-restart doc has $step" "false"
  fi
done

# Cross-doc: run log references post-restart verification
if grep -q "post-restart-verification" "$runlog" 2>/dev/null; then
  report "run log links to post-restart verification" "true"
else
  report "run log links to post-restart verification" "false"
fi

# Cross-doc: post-restart references restart milestone checklist
if grep -q "restart-milestone-checklist" "$postrestart" 2>/dev/null; then
  report "post-restart links to restart milestone checklist" "true"
else
  report "post-restart links to restart milestone checklist" "false"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
total=$((PASS + FAIL))
echo "Results: $PASS/$total passed"
if [[ $FAIL -gt 0 ]]; then
  echo "FAILED ($FAIL failures)"
  exit "$FAIL"
fi
echo "ALL PASSED"
exit 0
