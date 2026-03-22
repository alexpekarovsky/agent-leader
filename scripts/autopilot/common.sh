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
  local now_seconds=$(date +%s)
  local two_days_ago=$(( now_seconds - (2 * 24 * 60 * 60) ))
  local seven_days_ago=$(( now_seconds - (7 * 24 * 60 * 60) ))

  # Collect all files matching the pattern, including potential .gz files
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
        # Check for both original pattern and compressed pattern
        if not fnmatch.fnmatch(name, pattern) and not fnmatch.fnmatch(name, pattern + ".gz"):
            continue
        items.append((os.path.getmtime(path), path))
except FileNotFoundError:
    pass
# Sort oldest first for easier processing
for _, path in sorted(items, reverse=False):
    print(path)
PY
  )

  # If no files were found for this prefix, exit gracefully
  if [[ "${#files[@]}" -eq 0 ]]; then
    log DEBUG "No files found for prefix '$prefix'. Exiting prune_old_logs."
    return 0
  fi

  local files_to_keep=()
  local compressed_files_count=0
  local uncompressed_files_count=0

  for file in "${files[@]}"; do
    local file_mtime
    # Use 'stat -f %m' for macOS and 'stat -c %Y' for Linux
    if [[ "$OSTYPE" == "darwin"* ]]; then
      file_mtime=$(stat -f %m "$file")
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
      file_mtime=$(stat -c %Y "$file")
    else
      log ERROR "Unsupported OS for stat command: $OSTYPE"
      exit 1
    fi

    # 1. Delete files older than 7 days
    if (( file_mtime < seven_days_ago )); then
      log INFO "Deleting old log file (older than 7 days): $file"
      rm -f -- "$file"
      continue # Skip to next file
    fi

    # 2. Compress files older than 2 days if not already compressed
    if (( file_mtime < two_days_ago )) && [[ "$file" != *.gz ]]; then
      log INFO "Compressing old log file (older than 2 days): $file"
      gzip "$file" || log ERROR "Failed to compress $file"
      local compressed_file="${file}.gz"
      if [[ -f "$compressed_file" ]]; then
        files_to_keep+=("$compressed_file")
        compressed_files_count=$((compressed_files_count + 1))
      else
        log ERROR "Compressed file $compressed_file not found after gzip operation."
      fi
    elif [[ "$file" == *.gz ]]; then
      files_to_keep+=("$file")
      compressed_files_count=$((compressed_files_count + 1))
    else # Keep uncompressed file
      files_to_keep+=("$file")
      uncompressed_files_count=$((uncompressed_files_count + 1))
    fi
  done

  log DEBUG "Files to keep after age-based filtering for prefix '$prefix': ${files_to_keep[*]}"

  # Re-sort files_to_keep by modification time (newest first) for pruning by count
  # This step is crucial because the previous loop modified and added files out of order
  local sorted_files_to_keep=()
  if [[ "${#files_to_keep[@]}" -gt 0 ]]; then
    while IFS= read -r f; do
      [[ -n "$f" ]] && sorted_files_to_keep+=("$f")
    done < <(
      python3 - "${files_to_keep[@]}" <<'PY'
import os
import sys
items = []
for path in sys.argv[1:]:
    path = path.strip()
    if not path:
        continue
    try:
        items.append((os.path.getmtime(path), path))
    except FileNotFoundError:
        pass
for _, path in sorted(items, reverse=True):
    print(path)
PY

      )
    log DEBUG "Sorted files to keep for prefix '$prefix': ${sorted_files_to_keep[*]:-}"
    # 3. Prune excess files, keeping only MAX_LOG_FILES_PER_WORKER (newest)
    local total_current="${#sorted_files_to_keep[@]}"
    log DEBUG "Total current files for prefix '$prefix': $total_current, Max files to keep: $max_files"
    if (( total_current > max_files )); then
      for (( i=max_files; i<total_current; i++ )); do
        log INFO "Pruning excess log file (beyond max_files) for prefix '$prefix': ${sorted_files_to_keep[$i]}"
        rm -f -- "${sorted_files_to_keep[$i]}"
      done
    fi
  fi
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
import time

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

gemini_retry_limit = 0
gemini_retry_backoff = 15.0
gemini_fallback_model = env.get("ORCHESTRATOR_GEMINI_FALLBACK_MODEL", "").strip()
if cli == "gemini":
    try:
        gemini_retry_limit = max(0, int(env.get("ORCHESTRATOR_GEMINI_CAPACITY_RETRIES", "2").strip() or "2"))
    except Exception:
        gemini_retry_limit = 2
    try:
        gemini_retry_backoff = max(0.0, float(env.get("ORCHESTRATOR_GEMINI_CAPACITY_BACKOFF_SECONDS", "15").strip() or "15"))
    except Exception:
        gemini_retry_backoff = 15.0

def _read_output_text() -> str:
    try:
        return open(output_file, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""

def _is_gemini_capacity_error() -> bool:
    if cli != "gemini":
        return False
    text = _read_output_text()
    markers = (
        "MODEL_CAPACITY_EXHAUSTED",
        "No capacity available for model",
        '"status": "RESOURCE_EXHAUSTED"',
        "rateLimitExceeded",
    )
    return any(marker in text for marker in markers)

def _run_once(command: list[str], append: bool = False) -> int:
    mode = "ab" if append else "wb"
    with open(prompt_file, "rb") as stdin_f, open(output_file, mode) as out_f:
        try:
            result = subprocess.run(
                command,
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
            return 124
        return result.returncode

result_code = _run_once(cmd, append=False)
if cli == "gemini" and result_code != 0 and _is_gemini_capacity_error():
    current_model = env.get("ORCHESTRATOR_GEMINI_MODEL", "").strip() or env.get("GEMINI_MODEL", "").strip()
    for attempt in range(1, gemini_retry_limit + 1):
        with open(output_file, "ab") as out_f:
            out_f.write(
                f"\n[AUTOPILOT] Gemini capacity exhausted; retry {attempt}/{gemini_retry_limit} after {gemini_retry_backoff * attempt:.1f}s\n".encode("utf-8")
            )
        if gemini_retry_backoff > 0:
            time.sleep(gemini_retry_backoff * attempt)
        result_code = _run_once(cmd, append=True)
        if result_code == 0 or not _is_gemini_capacity_error():
            break
    if (
        result_code != 0
        and _is_gemini_capacity_error()
        and gemini_fallback_model
        and gemini_fallback_model != current_model
    ):
        fallback_cmd = list(cmd)
        try:
            model_index = fallback_cmd.index("-m")
            fallback_cmd[model_index + 1] = gemini_fallback_model
        except ValueError:
            fallback_cmd.extend(["-m", gemini_fallback_model])
        with open(output_file, "ab") as out_f:
            out_f.write(
                f"\n[AUTOPILOT] Gemini capacity exhausted; trying fallback model {gemini_fallback_model}\n".encode("utf-8")
            )
        result_code = _run_once(fallback_cmd, append=True)

sys.exit(result_code)
PY
}

detect_gemini_capacity_error() {
  local output_file="$1"
  [[ -f "$output_file" ]] || return 1
  python3 - "$output_file" <<'PY'
import sys
try:
    with open(sys.argv[1], "r", errors="replace") as f:
        text = f.read()
except Exception:
    sys.exit(1)
markers = (
    "MODEL_CAPACITY_EXHAUSTED",
    "No capacity available for model",
    "RESOURCE_EXHAUSTED",
    "rateLimitExceeded",
    "429",
    "Too Many Requests",
    "quota exceeded",
)
lower = text.lower()
for m in markers:
    if m.lower() in lower:
        sys.exit(0)
sys.exit(1)
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

# ---------------------------------------------------------------------------
# Token budget tracking
# ---------------------------------------------------------------------------
# Tracks cumulative token usage per budget window (daily/hourly).
# Budget files:
#   .budget-tokens-daily-{key}-{YYYYMMDD}.count
#   .budget-tokens-hourly-{key}-{YYYYMMDD}T{HH}.count
# Returns 0 if budget OK, 1 if either ceiling exceeded.

consume_token_budget() {
  local daily_ceiling="${1:-0}"
  local hourly_ceiling="${2:-0}"
  local tokens="${3:-10000}"
  local key="${4:-default}"
  local root="${5:-.}"

  # Both ceilings disabled → always OK.
  if { [[ ! "$daily_ceiling" =~ ^[0-9]+$ ]] || (( daily_ceiling <= 0 )); } &&
     { [[ ! "$hourly_ceiling" =~ ^[0-9]+$ ]] || (( hourly_ceiling <= 0 )); }; then
    return 0
  fi

  mkdir -p "$root"
  local safe_key
  safe_key="$(echo "$key" | tr -cs 'a-zA-Z0-9._-' '_')"
  local day_stamp hour_stamp
  day_stamp="$(date '+%Y%m%d')"
  hour_stamp="$(date '+%Y%m%dT%H')"

  # --- daily check ---
  if [[ "$daily_ceiling" =~ ^[0-9]+$ ]] && (( daily_ceiling > 0 )); then
    local daily_file="$root/.budget-tokens-daily-${safe_key}-${day_stamp}.count"
    local daily_current=0
    if [[ -f "$daily_file" ]]; then
      daily_current="$(cat "$daily_file" 2>/dev/null || echo 0)"
    fi
    [[ "$daily_current" =~ ^[0-9]+$ ]] || daily_current=0
    if (( daily_current + tokens > daily_ceiling )); then
      return 1
    fi
    echo $(( daily_current + tokens )) > "$daily_file"
  fi

  # --- hourly check ---
  if [[ "$hourly_ceiling" =~ ^[0-9]+$ ]] && (( hourly_ceiling > 0 )); then
    local hourly_file="$root/.budget-tokens-hourly-${safe_key}-${hour_stamp}.count"
    local hourly_current=0
    if [[ -f "$hourly_file" ]]; then
      hourly_current="$(cat "$hourly_file" 2>/dev/null || echo 0)"
    fi
    [[ "$hourly_current" =~ ^[0-9]+$ ]] || hourly_current=0
    if (( hourly_current + tokens > hourly_ceiling )); then
      return 1
    fi
    echo $(( hourly_current + tokens )) > "$hourly_file"
  fi

  return 0
}

# Write a budget-exhaustion marker so the supervisor knows not to restart.
# Args: pid_dir, process_key, window (daily|hourly)
write_budget_exhaustion_marker() {
  local pid_dir="$1"
  local process_key="$2"
  local window="${3:-daily}"
  mkdir -p "$pid_dir"
  local marker_file="$pid_dir/${process_key}.token_budget_exhausted"
  local now next_window
  now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  if [[ "$window" == "hourly" ]]; then
    # Next window = top of next hour (approximate: add 3600s)
    if [[ "$OSTYPE" == "darwin"* ]]; then
      next_window="$(date -u -v+1H '+%Y-%m-%dT%H:00:00Z')"
    else
      next_window="$(date -u -d '+1 hour' '+%Y-%m-%dT%H:00:00Z')"
    fi
  else
    # Next window = midnight tomorrow
    if [[ "$OSTYPE" == "darwin"* ]]; then
      next_window="$(date -u -v+1d '+%Y-%m-%dT00:00:00Z')"
    else
      next_window="$(date -u -d '+1 day' '+%Y-%m-%dT00:00:00Z')"
    fi
  fi
  cat > "$marker_file" <<MARKER
{"window":"${window}","exhausted_at":"${now}","next_window_at":"${next_window}"}
MARKER
  log WARN "token budget exhausted: wrote marker $marker_file (window=$window next=$next_window)"
}

# Emit a token budget exhaustion event via the orchestrator event bus.
# Args: project_root, agent, window (daily|hourly), ceiling, used
emit_token_budget_alert() {
  local project_root="$1"
  local agent="$2"
  local window="${3:-daily}"
  local ceiling="${4:-0}"
  local used="${5:-0}"

  python3 - "$ROOT_DIR" "$project_root" "$agent" "$window" "$ceiling" "$used" <<'PY'
import os
import sys
from pathlib import Path

repo_root = Path(os.environ.get("ORCHESTRATOR_ROOT", sys.argv[1])).resolve()
project_root = str(Path(sys.argv[2]).resolve())
agent = sys.argv[3]
window = sys.argv[4]
ceiling = int(sys.argv[5])
used = int(sys.argv[6])

sys.path.insert(0, str(repo_root))

try:
    from orchestrator.engine import Orchestrator
    from orchestrator.policy import Policy
except Exception:
    raise SystemExit(0)

policy_path = repo_root / "config" / "policy.codex-manager.json"
if not policy_path.exists():
    raise SystemExit(0)

try:
    policy = Policy.load(policy_path)
    orch = Orchestrator(root=repo_root, policy=policy)
    orch.bus.emit(
        event_type="budget.token_exhausted",
        payload={
            "agent": agent,
            "window": window,
            "ceiling": ceiling,
            "used": used,
            "project_root": project_root,
        },
        source=agent,
    )
except Exception:
    raise SystemExit(0)
PY
}

emit_agent_heartbeat() {
  local work_project_root="$1"
  local agent="$2"
  local cli="${3:-}"
  local lane="${4:-default}"
  local instance_id="${5:-${agent}#headless-${lane}}"
  local task_activity="${6:-idle}"

  python3 - "$ROOT_DIR" "$work_project_root" "$agent" "$cli" "$lane" "$instance_id" "$task_activity" <<'PY'
import os
import sys
from pathlib import Path

repo_root = Path(os.environ.get("ORCHESTRATOR_ROOT", sys.argv[1])).resolve()
work_project_root = str(Path(sys.argv[2]).resolve())
agent = sys.argv[3]
cli = sys.argv[4]
lane = sys.argv[5]
instance_id = sys.argv[6]
task_activity = sys.argv[7]

sys.path.insert(0, str(repo_root))

try:
    from orchestrator.engine import Orchestrator
    from orchestrator.policy import Policy
except Exception:
    raise SystemExit(0)

policy_path = repo_root / "config" / "policy.codex-manager.json"
if not policy_path.exists():
    raise SystemExit(0)

try:
    policy = Policy.load(policy_path)
    orch = Orchestrator(root=repo_root, policy=policy)
except Exception:
    raise SystemExit(0)

model = "-"
if cli == "gemini":
    model = os.environ.get("ORCHESTRATOR_GEMINI_MODEL", "").strip() or os.environ.get("GEMINI_MODEL", "").strip() or "-"
elif cli == "claude":
    model = os.environ.get("ORCHESTRATOR_CLAUDE_MODEL", "").strip() or "-"
elif cli == "codex":
    model = os.environ.get("ORCHESTRATOR_CODEX_MODEL", "").strip() or "-"

client = {
    "codex": "Codex CLI",
    "claude": "Claude Code",
    "gemini": "Gemini CLI",
}.get(cli, cli or "Unknown")

metadata = {
    "role": "team_member",
    "client": client,
    "model": model,
    "cwd": work_project_root,
    "project_root": work_project_root,
    "permissions_mode": "headless",
    "sandbox_mode": "danger-full-access",
    "instance_id": instance_id or f"{agent}#default",
    "lane": lane or "default",
    "headless_state": task_activity,
    "task_activity": task_activity,
    "process_state": "running",
}
try:
    orch.heartbeat(agent=agent, metadata=metadata)
except Exception:
    raise SystemExit(0)
PY
}

# Check if project.yaml roadmap has any items with status: backlog.
# Returns 0 if backlog items exist, 1 otherwise.
roadmap_has_backlog() {
  local project_root="$1"
  python3 - "$project_root" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(1)

root = Path(sys.argv[1])
project_yaml = root / "project.yaml"
if not project_yaml.exists():
    sys.exit(1)

try:
    raw = yaml.safe_load(project_yaml.read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)

if not isinstance(raw, dict):
    sys.exit(1)

roadmap = raw.get("roadmap")
if not isinstance(roadmap, list):
    sys.exit(1)

for block in roadmap:
    if not isinstance(block, dict):
        continue
    items = block.get("items")
    if not isinstance(items, list):
        continue
    for item in items:
        if isinstance(item, dict) and item.get("status") == "backlog":
            sys.exit(0)

sys.exit(1)
PY
}

# Trigger plan_from_roadmap via the orchestrator engine to create tasks from
# roadmap backlog items.  Returns 0 if new tasks were created, 1 otherwise.
# Stdout receives the number of tasks created (e.g. "3").
auto_resume_from_roadmap() {
  local project_root="$1"
  local agent="$2"
  local team_id="${3:-}"
  python3 - "$ROOT_DIR" "$project_root" "$agent" "$team_id" <<'PY'
import os
import sys
from pathlib import Path

repo_root = Path(os.environ.get("ORCHESTRATOR_ROOT", sys.argv[1])).resolve()
project_root = str(Path(sys.argv[2]).resolve())
agent = sys.argv[3]
team_id = sys.argv[4].strip() if len(sys.argv) > 4 and sys.argv[4].strip() else None

sys.path.insert(0, str(repo_root))

try:
    from orchestrator.engine import Orchestrator
    from orchestrator.policy import Policy
except Exception:
    print("0")
    sys.exit(1)

policy_path = repo_root / "config" / "policy.codex-manager.json"
if not policy_path.exists():
    print("0")
    sys.exit(1)

try:
    policy = Policy.load(policy_path)
    orch = Orchestrator(root=repo_root, policy=policy)
    result = orch.plan_from_roadmap(source=agent, team_id=team_id, limit=5)
    created = len(result.get("created", []))
    print(str(created))
    if created > 0:
        # Touch the wakeup signal so event-driven workers notice immediately.
        signal_file = Path(project_root) / "state" / f".wakeup-{agent}"
        signal_file.parent.mkdir(parents=True, exist_ok=True)
        signal_file.write_text(str(created), encoding="utf-8")
        sys.exit(0)
    else:
        sys.exit(1)
except Exception:
    print("0")
    sys.exit(1)
PY
}

wait_for_task_signal() {
  local project_root="$1"
  local agent="$2"
  local max_wait="${3:-300}"
  local poll_interval="${4:-2}"
  local heartbeat_interval="${5:-0}"
  local cli="${6:-}"
  local lane="${7:-default}"
  local instance_id="${8:-${agent}#headless-${lane}}"
  local signal_file="$project_root/state/.wakeup-${agent}"
  local fswatcher
  fswatcher="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fswatcher.py"

  # Record baseline mtime (0 if file doesn't exist yet).
  local baseline_mtime=0
  if [[ -f "$signal_file" ]]; then
    baseline_mtime="$(python3 -c "import os; print(int(os.path.getmtime('$signal_file') * 1000))" 2>/dev/null || echo 0)"
  fi

  local waited=0
  local last_heartbeat=0
  if [[ "$heartbeat_interval" =~ ^[0-9]+$ ]] && (( heartbeat_interval > 0 )); then
    emit_agent_heartbeat "$project_root" "$agent" "$cli" "$lane" "$instance_id" "idle"
  fi

  # Use OS-native file watcher (kqueue/inotify) with polling fallback.
  # Run in chunks of heartbeat_interval (or max_wait) to allow heartbeat emission.
  while (( waited < max_wait )); do
    local remaining=$((max_wait - waited))
    local chunk="$remaining"
    if [[ "$heartbeat_interval" =~ ^[0-9]+$ ]] && (( heartbeat_interval > 0 )) && (( heartbeat_interval < chunk )); then
      chunk="$heartbeat_interval"
    fi

    if [[ -f "$fswatcher" ]]; then
      # Use OS-native watcher (kqueue on macOS, inotify on Linux, poll fallback)
      if python3 "$fswatcher" "$signal_file" "$chunk" --baseline-mtime "$baseline_mtime" 2>/dev/null; then
        return 0  # Signal detected — new work available
      fi
    else
      # Inline fallback: sleep-based polling (legacy path)
      local chunk_waited=0
      while (( chunk_waited < chunk )); do
        sleep "$poll_interval"
        chunk_waited=$((chunk_waited + poll_interval))
        if [[ -f "$signal_file" ]]; then
          local current_mtime
          current_mtime="$(python3 -c "import os; print(int(os.path.getmtime('$signal_file') * 1000))" 2>/dev/null || echo 0)"
          if [[ "$current_mtime" != "$baseline_mtime" ]]; then
            return 0  # Signal detected — new work available
          fi
        fi
      done
    fi

    waited=$((waited + chunk))
    if [[ "$heartbeat_interval" =~ ^[0-9]+$ ]] && (( heartbeat_interval > 0 )) && (( waited - last_heartbeat >= heartbeat_interval )); then
      emit_agent_heartbeat "$project_root" "$agent" "$cli" "$lane" "$instance_id" "idle"
      last_heartbeat="$waited"
    fi
  done
  return 1  # Timeout — no signal
}
