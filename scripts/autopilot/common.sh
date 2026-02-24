#!/usr/bin/env bash
set -euo pipefail

log() {
  local level="$1"; shift
  printf '[%s] [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$*" >&2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    log ERROR "Missing required command: $1"
    exit 1
  }
}

mkdir_logs() {
  local root="$1"
  mkdir -p "$root"
}

run_cli_prompt() {
  local cli="$1"
  local cwd="$2"
  local prompt_file="$3"
  local output_file="$4"

  case "$cli" in
    codex)
      codex exec --dangerously-bypass-approvals-and-sandbox -C "$cwd" - <"$prompt_file" >"$output_file" 2>&1
      ;;
    claude)
      (cd "$cwd" && claude --dangerously-skip-permissions -p "$(cat "$prompt_file")") >"$output_file" 2>&1
      ;;
    gemini)
      (cd "$cwd" && gemini --approval-mode yolo -p "$(cat "$prompt_file")") >"$output_file" 2>&1
      ;;
    *)
      log ERROR "Unsupported CLI: $cli"
      return 2
      ;;
  esac
}

sleep_with_jitter() {
  local base="${1:-15}"
  local jitter=$(( RANDOM % 5 ))
  sleep $(( base + jitter ))
}
