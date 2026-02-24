#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$(pwd)}"
INTERVAL="${2:-10}"

while true; do
  clear || true
  echo "project=$PROJECT_ROOT"
  echo
  ls -1 "$PROJECT_ROOT/.autopilot-logs" 2>/dev/null | tail -n 10 || true
  echo
  codex mcp list 2>/dev/null | sed -n '1,5p' || true
  sleep "$INTERVAL"
done
