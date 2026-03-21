#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT_DIR/scripts/autopilot/common.sh"

LOG_DIR="$ROOT_DIR/.autopilot-logs"
DEFAULT_MAX_LOG_FILES_PER_WORKER=50
MAX_LOG_FILES_PER_WORKER="$DEFAULT_MAX_LOG_FILES_PER_WORKER"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-logs) MAX_LOG_FILES_PER_WORKER="$2"; shift 2 ;;
    *) log ERROR "Unknown arg for log_rotator.sh: $1"; exit 1 ;;
  esac
done

log INFO "Starting log rotation for .autopilot-logs/"

# Manager logs
prune_old_logs "$LOG_DIR" "manager-" "$MAX_LOG_FILES_PER_WORKER" # General manager logs

# Worker logs
# Assuming agents are 'claude', 'gemini', 'codex', 'wingman'
# We need to consider all possible CLIs that can run workers.
prune_old_logs "$LOG_DIR" "worker-claude-" "$MAX_LOG_FILES_PER_WORKER"
prune_old_logs "$LOG_DIR" "worker-gemini-" "$MAX_LOG_FILES_PER_WORKER"
prune_old_logs "$LOG_DIR" "worker-codex-" "$MAX_LOG_FILES_PER_WORKER"
prune_old_logs "$LOG_DIR" "worker-wingman-" "$MAX_LOG_FILES_PER_WORKER" # Added wingman worker logs

# Watchdog logs
prune_old_logs "$LOG_DIR" "watchdog-" "$MAX_LOG_FILES_PER_WORKER" # Added watchdog logs

log INFO "Log rotation for .autopilot-logs/ completed."