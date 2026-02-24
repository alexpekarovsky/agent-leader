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

prune_old_logs() {
  local root="$1"
  local prefix="${2:-}"
  local max_files="${3:-200}"
  [[ -d "$root" ]] || return 0
  [[ "$max_files" =~ ^[0-9]+$ ]] || return 0
  (( max_files > 0 )) || return 0

  local pattern='*'
  if [[ -n "$prefix" ]]; then
    pattern="${prefix}*"
  fi

  local files=()
  while IFS= read -r f; do
    [[ -n "$f" ]] && files+=("$f")
  done < <(
    python3 - "$root" "$pattern" <<'PY'
import fnmatch
import os
import sys
root, pattern = sys.argv[1], sys.argv[2]
items = []
try:
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        if not fnmatch.fnmatch(name, pattern):
            continue
        items.append((os.path.getmtime(path), path))
except FileNotFoundError:
    pass
for _, path in sorted(items, reverse=True):
    print(path)
PY
  )

  local total="${#files[@]}"
  if (( total <= max_files )); then
    return 0
  fi

  local i
  for (( i=max_files; i<total; i++ )); do
    rm -f -- "${files[$i]}"
  done
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
      (cd "$cwd" && claude --dangerously-skip-permissions -p "") <"$prompt_file" >"$output_file" 2>&1
      ;;
    gemini)
      (cd "$cwd" && gemini --approval-mode yolo -p "") <"$prompt_file" >"$output_file" 2>&1
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
