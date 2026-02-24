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
  local timeout_seconds="${5:-300}"

  [[ "$timeout_seconds" =~ ^[0-9]+$ ]] || timeout_seconds=300
  (( timeout_seconds > 0 )) || timeout_seconds=300
  python3 - "$cli" "$cwd" "$prompt_file" "$output_file" "$timeout_seconds" <<'PY'
import os
import subprocess
import sys

cli, cwd, prompt_file, output_file, timeout_seconds = sys.argv[1:]
timeout_seconds = int(timeout_seconds)

if cli == "codex":
    cmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-C", cwd, "-"]
elif cli == "claude":
    cmd = ["claude", "--dangerously-skip-permissions", "-p", ""]
elif cli == "gemini":
    cmd = ["gemini", "--approval-mode", "yolo", "-p", ""]
else:
    print(f"Unsupported CLI: {cli}", file=sys.stderr)
    sys.exit(2)

env = os.environ.copy()
with open(prompt_file, "rb") as stdin_f, open(output_file, "wb") as out_f:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            stdin=stdin_f,
            stdout=out_f,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        out_f.write(
            f"\n[AUTOPILOT] CLI timeout after {timeout_seconds}s for {cli}\n".encode("utf-8")
        )
        sys.exit(124)
    sys.exit(result.returncode)
PY
}

sleep_with_jitter() {
  local base="${1:-15}"
  local jitter=$(( RANDOM % 5 ))
  sleep $(( base + jitter ))
}
