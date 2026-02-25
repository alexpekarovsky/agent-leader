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

# Create a minimal state dir with a stale task to trigger diagnostics
state_dir="$WORK_DIR/fake-project/state"
mkdir -p "$state_dir"
cat >"$state_dir/tasks.json" <<'JSON'
[
  {
    "id": "TASK-smoke-001",
    "title": "Stale smoke test task",
    "status": "assigned",
    "owner": "test_agent",
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
