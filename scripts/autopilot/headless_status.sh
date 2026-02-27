#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_ROOT="$ROOT_DIR"
INTERVAL=10
WATCH=false
JSON=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --watch) WATCH=true; shift ;;
    --once) WATCH=false; shift ;;
    --json) JSON=true; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

render_once() {
python3 - "$PROJECT_ROOT" "$JSON" <<'PY'
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(sys.argv[1])
as_json = sys.argv[2].lower() == "true"
state_dir = project_root / "state"
log_dir = project_root / ".autopilot-logs"
pid_dir = project_root / ".autopilot-pids"


def load_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def parse_iso(s: str):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def age_seconds(dt: datetime | None):
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    try:
        return max(0, int((now - dt).total_seconds()))
    except Exception:
        return None


def proc_status(name: str):
    pf = pid_dir / f"{name}.pid"
    if not pf.exists():
        return {"status": "stopped", "pid": None}
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except Exception:
        return {"status": "dead", "pid": None}
    alive = False
    try:
        os.kill(pid, 0)
        alive = True
    except Exception:
        alive = False
    return {"status": "running" if alive else "dead", "pid": pid}


tasks = load_json(state_dir / "tasks.json", [])
agents = load_json(state_dir / "agents.json", {})
roles = load_json(state_dir / "roles.json", {})
blockers = load_json(state_dir / "blockers.json", [])
bugs = load_json(state_dir / "bugs.json", [])

if not isinstance(tasks, list):
    tasks = []
if not isinstance(agents, dict):
    agents = {}
if not isinstance(blockers, list):
    blockers = []
if not isinstance(bugs, list):
    bugs = []

status_counts = Counter(str(t.get("status", "unknown")) for t in tasks)
in_progress = [t for t in tasks if t.get("status") == "in_progress"]
reported = [t for t in tasks if t.get("status") == "reported"]
assigned = [t for t in tasks if t.get("status") == "assigned"]
open_blockers = [b for b in blockers if b.get("status") != "resolved"]
open_bugs = [b for b in bugs if b.get("status") != "closed"]

active_agents = []
for name, entry in agents.items():
    last_seen = parse_iso(str(entry.get("last_seen", "")))
    age = age_seconds(last_seen)
    state = "active" if age is not None and age <= 600 else "offline"
    md = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
    active_agents.append(
        {
            "agent": name,
            "state": state,
            "age_seconds": age,
            "instance_id": md.get("instance_id"),
            "role": md.get("role"),
        }
    )
active_agents.sort(key=lambda x: x["agent"])

proc = {
    "manager": proc_status("manager"),
    "wingman": proc_status("wingman"),
    "claude": proc_status("claude"),
    "gemini": proc_status("gemini"),
    "codex_worker": proc_status("codex_worker"),
    "watchdog": proc_status("watchdog"),
}

payload = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "project_root": str(project_root),
    "leader": roles.get("leader", "codex"),
    "team_members": roles.get("team_members", []),
    "task_total": len(tasks),
    "task_status_counts": dict(status_counts),
    "in_progress": [
        {
            "id": t.get("id"),
            "owner": t.get("owner"),
            "title": t.get("title"),
            "updated_at": t.get("updated_at"),
        }
        for t in sorted(in_progress, key=lambda x: str(x.get("updated_at", "")), reverse=True)[:8]
    ],
    "reported_count": len(reported),
    "assigned_count": len(assigned),
    "open_blockers": len(open_blockers),
    "open_bugs": len(open_bugs),
    "agents": active_agents,
    "processes": proc,
    "log_dir_exists": log_dir.exists(),
}

if as_json:
    print(json.dumps(payload, indent=2))
    raise SystemExit(0)

print("Headless Swarm Status")
print(f"time={payload['timestamp']}")
print(f"project={payload['project_root']}")
print(f"leader={payload['leader']} team_members={payload['team_members']}")
print()
print("Pipeline")
print(f"  total={payload['task_total']} assigned={payload['assigned_count']} in_progress={len(in_progress)} reported={payload['reported_count']} done={status_counts.get('done', 0)}")
print(f"  blockers={payload['open_blockers']} bugs={payload['open_bugs']}")
print()
print("Processes")
for k in ("manager", "wingman", "claude", "gemini", "codex_worker", "watchdog"):
    p = payload["processes"][k]
    print(f"  {k:8s} {p['status']:7s} pid={p['pid'] if p['pid'] is not None else '-'}")
print()
print("Agents")
for a in payload["agents"]:
    age = "-" if a["age_seconds"] is None else f"{a['age_seconds']}s"
    inst = a["instance_id"] or "-"
    role = a["role"] or "-"
    print(f"  {a['agent']:12s} {a['state']:7s} age={age:>6s} instance={inst:20s} role={role}")
print()
print("Active Tasks")
if not payload["in_progress"]:
    print("  (none)")
else:
    for t in payload["in_progress"]:
        print(f"  {t['id']} owner={t['owner']} title={t['title']}")
PY
}

if [[ "$WATCH" == true ]]; then
  while true; do
    clear || true
    render_once
    sleep "$INTERVAL"
  done
else
  render_once
fi
