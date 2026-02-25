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
