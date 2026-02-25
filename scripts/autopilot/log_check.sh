#!/usr/bin/env bash
# Autopilot log sanity checker — operator diagnostic for .autopilot-logs.
#
# Usage:
#   ./scripts/autopilot/log_check.sh [options]
#
# Options:
#   --log-dir DIR       Log directory (default: .autopilot-logs)
#   --max-age-minutes N Warn if newest log per loop is older than N minutes (default: 10)
#   --strict            Exit non-zero on missing required logs or malformed JSONL
#
# Reports:
#   - Per-loop log presence and newest file age
#   - Watchdog JSONL parse check
#   - Timeout marker frequency across manager/worker logs
#   - Stale log age warnings

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

LOG_DIR="$ROOT_DIR/.autopilot-logs"
MAX_AGE_MINUTES=10
STRICT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --max-age-minutes) MAX_AGE_MINUTES="$2"; shift 2 ;;
    --strict) STRICT=true; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -d "$LOG_DIR" ]]; then
  echo "Log directory not found: $LOG_DIR"
  if [[ "$STRICT" == true ]]; then
    exit 1
  fi
  exit 0
fi

# Run all checks via Python for consistent parsing
python3 - "$LOG_DIR" "$MAX_AGE_MINUTES" "$STRICT" <<'PY'
import json
import os
import sys
import time
from pathlib import Path

log_dir = Path(sys.argv[1])
max_age_minutes = int(sys.argv[2])
strict = sys.argv[3] == "true"
max_age_seconds = max_age_minutes * 60
now = time.time()
errors = []
warnings = []

# Define loop prefixes and their expected log patterns
loops = {
    "manager": {"glob": "manager-*.log", "required": True},
    "worker": {"glob": "worker-*.log", "required": True},
    "watchdog": {"glob": "watchdog-*.jsonl", "required": True},
    "supervisor": {"glob": "supervisor-*.log", "required": False},
}

print("Autopilot log sanity check")
print(f"Log dir: {log_dir}")
print(f"Max age: {max_age_minutes} minutes")
print(f"Strict: {strict}")
print()

# --- Per-loop log presence and age ---
print("--- Log presence and age ---")
for name, cfg in loops.items():
    files = sorted(log_dir.glob(cfg["glob"]), key=lambda p: p.stat().st_mtime, reverse=True)
    count = len(files)
    if count == 0:
        status = "MISSING" if cfg["required"] else "none"
        print(f"  {name:12s}  files={count:4d}  newest=n/a  status={status}")
        if cfg["required"]:
            msg = f"{name}: no log files found"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)
        continue

    newest = files[0]
    age_sec = int(now - newest.stat().st_mtime)
    age_min = age_sec // 60

    if age_sec > max_age_seconds:
        status = f"STALE ({age_min}m old)"
        warnings.append(f"{name}: newest log is {age_min}m old (threshold: {max_age_minutes}m)")
    else:
        status = "ok"

    print(f"  {name:12s}  files={count:4d}  newest={age_min}m ago  status={status}")

print()

# --- Watchdog JSONL parse check ---
print("--- Watchdog JSONL validation ---")
watchdog_files = sorted(log_dir.glob("watchdog-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
jsonl_total = 0
jsonl_ok = 0
jsonl_bad = 0
kind_counts = {}

for wf in watchdog_files[:10]:  # Check last 10 files
    try:
        for line_num, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            jsonl_total += 1
            try:
                rec = json.loads(line)
                jsonl_ok += 1
                kind = rec.get("kind", "unknown")
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
            except json.JSONDecodeError:
                jsonl_bad += 1
                if jsonl_bad <= 3:
                    errors.append(f"Malformed JSONL in {wf.name} line {line_num}")
    except Exception as e:
        errors.append(f"Cannot read {wf.name}: {e}")

if jsonl_total == 0:
    print("  No JSONL entries found")
else:
    print(f"  Checked {min(len(watchdog_files), 10)} file(s): {jsonl_ok}/{jsonl_total} lines valid")
    if jsonl_bad > 0:
        print(f"  BAD LINES: {jsonl_bad}")
    if kind_counts:
        print("  Diagnostic kinds:")
        for kind, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
            print(f"    {kind}: {count}")

print()

# --- Timeout marker frequency ---
print("--- Timeout markers in CLI logs ---")
timeout_counts = {"manager": 0, "worker": 0}
for prefix, label in [("manager-*.log", "manager"), ("worker-*.log", "worker")]:
    cli_files = sorted(log_dir.glob(prefix), key=lambda p: p.stat().st_mtime, reverse=True)
    for cf in cli_files[:20]:  # Check last 20 files
        try:
            content = cf.read_text(encoding="utf-8", errors="replace")
            timeout_counts[label] += content.count("[AUTOPILOT] CLI timeout")
        except Exception:
            pass

for label, count in timeout_counts.items():
    status = "ok" if count == 0 else f"{count} timeout(s)"
    print(f"  {label:12s}  {status}")

print()

# --- Summary ---
if warnings:
    print("Warnings:")
    for w in warnings:
        print(f"  - {w}")
    print()

if errors:
    print("Errors:")
    for e in errors:
        print(f"  - {e}")
    print()

total_issues = len(errors) + len(warnings)
if total_issues == 0:
    print("All checks passed.")
else:
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")

if strict and errors:
    sys.exit(1)
PY
