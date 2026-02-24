#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

PROJECT_ROOT="$ROOT_DIR"
INTERVAL=15
ONCE=false
LOG_DIR="$ROOT_DIR/.autopilot-logs"
MAX_LOG_FILES=400
ASSIGNED_TIMEOUT=180
INPROGRESS_TIMEOUT=900
REPORTED_TIMEOUT=180

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --max-logs) MAX_LOG_FILES="$2"; shift 2 ;;
    --assigned-timeout) ASSIGNED_TIMEOUT="$2"; shift 2 ;;
    --inprogress-timeout) INPROGRESS_TIMEOUT="$2"; shift 2 ;;
    --reported-timeout) REPORTED_TIMEOUT="$2"; shift 2 ;;
    --once) ONCE=true; shift ;;
    *) log ERROR "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir_logs "$LOG_DIR"

cycle=0
while true; do
  cycle=$((cycle + 1))
  ts="$(date '+%Y%m%d-%H%M%S')"
  out_file="$LOG_DIR/watchdog-${ts}.jsonl"
  python3 - "$PROJECT_ROOT" "$ASSIGNED_TIMEOUT" "$INPROGRESS_TIMEOUT" "$REPORTED_TIMEOUT" "$out_file" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
assigned_timeout = int(sys.argv[2])
inprogress_timeout = int(sys.argv[3])
reported_timeout = int(sys.argv[4])
out_file = Path(sys.argv[5])
state = root / "state"

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def emit(kind, payload):
    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **payload,
    }
    with out_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")

for name in ("bugs.json", "blockers.json"):
    p = state / name
    data = load_json(p, [])
    if isinstance(data, dict):
        emit("state_corruption_detected", {"path": str(p), "previous_type": "dict", "expected_type": "list"})
    elif not isinstance(data, list):
        emit("state_corruption_detected", {"path": str(p), "previous_type": type(data).__name__, "expected_type": "list"})

tasks = load_json(state / "tasks.json", [])
if not isinstance(tasks, list):
    tasks = []

now = datetime.now(timezone.utc)
for t in tasks:
    status = str(t.get("status", ""))
    stamp = str(t.get("updated_at") or t.get("created_at") or "")
    if not stamp:
        continue
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:
        continue
    age = int((now - dt).total_seconds())
    timeout = None
    if status == "assigned":
        timeout = assigned_timeout
    elif status == "in_progress":
        timeout = inprogress_timeout
    elif status == "reported":
        timeout = reported_timeout
    if timeout is not None and age > timeout:
        emit("stale_task", {
            "task_id": t.get("id"),
            "owner": t.get("owner"),
            "status": status,
            "age_seconds": age,
            "timeout_seconds": timeout,
            "title": t.get("title"),
        })
PY
  log INFO "watchdog cycle=$cycle project=$PROJECT_ROOT log=$out_file"
  prune_old_logs "$LOG_DIR" "watchdog-" "$MAX_LOG_FILES"
  if [[ "$ONCE" == true ]]; then
    break
  fi
  sleep_with_jitter "$INTERVAL"
done
