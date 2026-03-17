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
  local agent="${6:-}"
  local role="${7:-}"
  local instance_id="${8:-}"

  [[ "$timeout_seconds" =~ ^[0-9]+$ ]] || timeout_seconds=300
  (( timeout_seconds > 0 )) || timeout_seconds=300
  python3 - "$cli" "$cwd" "$prompt_file" "$output_file" "$timeout_seconds" "$agent" "$role" "$instance_id" <<'PY'
import os
import subprocess
import sys

cli, cwd, prompt_file, output_file, timeout_seconds, agent, role, instance_id = sys.argv[1:]
timeout_seconds = int(timeout_seconds)

# Identity mapping check (Basic Safety)
valid_agents = {
    "codex": ["codex"],
    "claude": ["claude_code", "ccm"],
    "gemini": ["gemini"]
}
if agent and cli in valid_agents and agent not in valid_agents[cli]:
    msg = f"ERROR: Agent identity mismatch. CLI '{cli}' cannot act as agent '{agent}'."
    print(msg, file=sys.stderr)
    with open(output_file, "wb") as f:
        f.write(msg.encode("utf-8"))
    sys.exit(1)

env = os.environ.copy()

if cli == "codex":
    cmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-C", cwd, "-"]
elif cli == "claude":
    cmd = ["claude", "--dangerously-skip-permissions", "-p", ""]
elif cli == "gemini":
    cmd = ["gemini", "--approval-mode", "yolo"]
    gemini_model = env.get("ORCHESTRATOR_GEMINI_MODEL", "").strip() or env.get("GEMINI_MODEL", "").strip()
    if gemini_model:
        cmd.extend(["-m", gemini_model])
    cmd.extend(["-p", ""])
else:
    print(f"Unsupported CLI: {cli}", file=sys.stderr)
    sys.exit(2)
if agent: env["ORCHESTRATOR_AGENT"] = agent
if role: env["ORCHESTRATOR_ROLE"] = role
if instance_id: env["ORCHESTRATOR_INSTANCE_ID"] = instance_id

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

backoff_interval_for_streak() {
  local streak="${1:-1}"
  local csv="${2:-30,60,120,300,900}"
  local fallback="${3:-60}"
  local arr=()
  local IFS=','
  read -r -a arr <<< "$csv"
  local idx=$(( streak - 1 ))
  if (( idx < 0 )); then
    idx=0
  fi
  if (( idx >= ${#arr[@]} )); then
    idx=$(( ${#arr[@]} - 1 ))
  fi
  local val="${arr[$idx]:-$fallback}"
  if [[ ! "$val" =~ ^[0-9]+$ ]] || (( val <= 0 )); then
    val="$fallback"
  fi
  echo "$val"
}

consume_daily_budget() {
  local budget="${1:-0}"
  local key="${2:-default}"
  local root="${3:-.}"
  if [[ ! "$budget" =~ ^[0-9]+$ ]] || (( budget <= 0 )); then
    return 0
  fi
  mkdir -p "$root"
  local stamp
  stamp="$(date '+%Y%m%d')"
  local safe_key
  safe_key="$(echo "$key" | tr -cs 'a-zA-Z0-9._-' '_')"
  local file="$root/.budget-${safe_key}-${stamp}.count"
  local current=0
  if [[ -f "$file" ]]; then
    current="$(cat "$file" 2>/dev/null || echo 0)"
  fi
  if [[ ! "$current" =~ ^[0-9]+$ ]]; then
    current=0
  fi
  if (( current >= budget )); then
    return 1
  fi
  echo $(( current + 1 )) > "$file"
  return 0
}

wait_for_task_signal() {
  local project_root="$1"
  local agent="$2"
  local max_wait="${3:-300}"
  local poll_interval="${4:-2}"
  local signal_file="$project_root/state/.wakeup-${agent}"

  # Record baseline mtime (0 if file doesn't exist yet).
  local baseline_mtime=0
  if [[ -f "$signal_file" ]]; then
    baseline_mtime="$(python3 -c "import os; print(int(os.path.getmtime('$signal_file') * 1000))" 2>/dev/null || echo 0)"
  fi

  local waited=0
  while (( waited < max_wait )); do
    sleep "$poll_interval"
    waited=$((waited + poll_interval))
    if [[ -f "$signal_file" ]]; then
      local current_mtime
      current_mtime="$(python3 -c "import os; print(int(os.path.getmtime('$signal_file') * 1000))" 2>/dev/null || echo 0)"
      if [[ "$current_mtime" != "$baseline_mtime" ]]; then
        return 0  # Signal detected — new work available
      fi
    fi
  done
  return 1  # Timeout — no signal
}
