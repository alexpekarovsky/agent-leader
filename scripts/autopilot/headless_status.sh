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


def heartbeat_state(age):
    if age is None:
        return "missing"
    if age <= 600:
        return "active"
    if age <= 1800:
        return "stale"
    return "offline"


def process_names_for_agent(agent_name: str, proc_map):
    names = []
    for name in proc_map.keys():
        if agent_name == "codex" and (name == "manager" or name.startswith("codex")):
            names.append(name)
        elif agent_name == "ccm" and name == "wingman":
            names.append(name)
        elif agent_name == "claude_code" and (name == "claude" or name.startswith("claude_") or name.startswith("claude-")):
            names.append(name)
        elif agent_name == "gemini" and name.startswith("gemini"):
            names.append(name)
    return names


def task_activity_for_agent(agent_name: str, task_rows):
    statuses = {str(t.get("status", "")).strip().lower() for t in task_rows if str(t.get("owner", "")).strip() == agent_name}
    if "in_progress" in statuses:
        return "working"
    if "blocked" in statuses:
        return "blocked"
    if statuses.intersection({"assigned", "reported", "bug_open"}):
        return "queued"
    return "idle"


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
done = [t for t in tasks if t.get("status") == "done"]
open_blockers = [b for b in blockers if b.get("status") != "resolved"]
open_bugs = [b for b in bugs if b.get("status") != "closed"]

# Team lane counters (parity with MCP orchestrator_status)
team_lane_counters = {}
for t in tasks:
    team_id = t.get("team_id") or "default"
    if team_id not in team_lane_counters:
        team_lane_counters[team_id] = {"total": 0, "in_progress": 0, "done": 0, "reported": 0, "assigned": 0}
    team_lane_counters[team_id]["total"] += 1
    s = t.get("status", "unknown")
    if s in team_lane_counters[team_id]:
        team_lane_counters[team_id][s] += 1

# Wingman Lane Visibility
wingman_pending = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "pending"]
wingman_rejected = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "rejected"]
wingman_count = len(wingman_pending) + len(wingman_rejected)

# Suggested Recovery Actions
recovery_actions = []
now = datetime.now(timezone.utc)
for t in tasks:
    if t.get("status") == "in_progress":
        claimed_at = parse_iso(t.get("claimed_at"))
        if claimed_at:
            age = (now - claimed_at).total_seconds()
            if age > 1800:
                recovery_actions.append({
                    "type": "stale_task",
                    "task_id": t["id"],
                    "message": f"Task {t['id']} IP for {int(age//60)}m",
                    "action": "orchestrator_reassign_stale_tasks(stale_after_seconds=600)"
                })
for blk in blockers:
    if blk.get("status") == "open":
        recovery_actions.append({
            "type": "open_blocker",
            "blocker_id": blk["id"],
            "message": f"Blocker {blk['id']} on {blk.get('task_id')}",
            "action": f"orchestrator_resolve_blocker(blocker_id='{blk['id']}', ...)"
        })

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
known = set(proc.keys())
if pid_dir.exists():
    for pf in pid_dir.glob("*.pid"):
        name = pf.stem
        if name not in known:
            proc[name] = proc_status(name)
            known.add(name)

operator_agents = []
operator_names = {"codex", "ccm", "claude_code", "gemini"} | set(agents.keys())
for agent_name in sorted(operator_names):
    if not agent_name:
        continue
    entry = agents.get(agent_name, {}) if isinstance(agents, dict) else {}
    last_seen = parse_iso(str(entry.get("last_seen", "")))
    age = age_seconds(last_seen)
    hb_state = heartbeat_state(age)
    pnames = process_names_for_agent(agent_name, proc)
    running = [name for name in pnames if proc.get(name, {}).get("status") == "running"]
    operator_agents.append({
        "agent": agent_name,
        "heartbeat_state": hb_state,
        "heartbeat_age_seconds": age,
        "process_state": "up" if running else "down",
        "process_count": len(running),
        "task_activity": task_activity_for_agent(agent_name, tasks),
        "instance_id": (entry.get("metadata") or {}).get("instance_id") if isinstance(entry.get("metadata"), dict) else None,
    })

def _collect_budget_metrics(budgets_dir: Path):
    """Read .budget-*-YYYYMMDD.count files and report daily consumption."""
    import fnmatch
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    result = {}
    if not budgets_dir.exists():
        return result
    try:
        for name in sorted(budgets_dir.iterdir()):
            if not name.name.startswith(".budget-") or not name.name.endswith(".count"):
                continue
            if stamp not in name.name:
                continue
            # .budget-{key}-{YYYYMMDD}.count
            parts = name.stem  # .budget-worker-codex-codex-20260314
            key = parts[len(".budget-"):-len(f"-{stamp}")]
            try:
                count = int(name.read_text(encoding="utf-8").strip())
            except Exception:
                count = 0
            result[key] = count
    except Exception:
        pass
    return result


payload = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "project_root": str(project_root),
    "manager": roles.get("leader", "codex"),
    "roles": roles,
    "task_count": len(tasks),
    "task_status_counts": dict(status_counts),
    "team_lane_counters": team_lane_counters,
    "bug_count": len(open_bugs),
    "in_progress": [
        {
            "id": t.get("id"),
            "owner": t.get("owner"),
            "title": t.get("title"),
            "updated_at": t.get("updated_at"),
        }
        for t in sorted(in_progress, key=lambda x: str(x.get("updated_at", "")), reverse=True)[:8]
    ],
    "wingman_count": wingman_count,
    "recovery_actions": recovery_actions,
    "active_agents": [a["agent"] for a in active_agents if a["state"] == "active"],
    "active_agent_identities": active_agents,
    "operator_agents": operator_agents,
    "processes": proc,
    "metrics": {
        "throughput": {
            "tasks_total": len(tasks),
            "tasks_done": len(done),
            "tasks_reported": len(reported),
            "tasks_in_progress": len(in_progress),
        },
        "reliability": {
            "open_bugs": len(open_bugs),
            "open_blockers": len(open_blockers),
        },
    },
    "budget": _collect_budget_metrics(log_dir),
    "log_dir_exists": log_dir.exists(),
}

if as_json:
    print(json.dumps(payload, indent=2))
    raise SystemExit(0)

# Unified Header
leader = payload["manager"]
team_members = payload["roles"].get("team_members", [])
team = ", ".join(sorted(team_members))
status_state = "Active" if any(a["state"] == "active" for a in active_agents) else "Idle"

print(f"ORCHESTRATOR STATUS: {status_state}")
print(f"PROJECT: {payload['project_root']}")
print(f"LEADER: {leader} | TEAM: {team or 'none'}")
sc = payload["task_status_counts"]
print(f"PIPELINE: {payload['task_count']} Tasks | {sc.get('assigned', 0)} Assigned | {sc.get('in_progress', 0)} IP | {sc.get('reported', 0)} Review | {sc.get('done', 0)} Done")
print(f"BLOCKERS: {payload['metrics']['reliability']['open_blockers']} Open | BUGS: {payload['bug_count']} Open")

by_agent_name = {a["agent"]: a for a in active_agents}
if wingman_count > 0 or "ccm" in by_agent_name or "wingman" in team.lower():
    wingman_agent = "ccm" if "ccm" in by_agent_name else "none"
    wingman_status = by_agent_name.get(wingman_agent, {}).get("state", "offline") if wingman_agent != "none" else "n/a"
    print(f"WINGMAN LANE: {wingman_agent} [{wingman_status}] | {wingman_count} Tasks Awaiting Review")

if recovery_actions:
    print()
    print("Suggested recovery actions:")
    for action in recovery_actions[:5]:
        print(f"  [{action['type']}] {action['message']}")
        print(f"    Suggested: {action['action']}")

print()
print("Processes")
preferred = ("manager", "wingman", "claude", "gemini", "codex_worker", "watchdog")
ordered = [name for name in preferred if name in payload["processes"]]
ordered.extend(sorted([name for name in payload["processes"].keys() if name not in preferred]))
for k in ordered:
    p = payload["processes"][k]
    print(f"  {k:8s} {p['status']:7s} pid={p['pid'] if p['pid'] is not None else '-'}")
print()
print("Agents")
for a in payload["operator_agents"]:
    age = "-" if a["heartbeat_age_seconds"] is None else f"{a['heartbeat_age_seconds']}s"
    inst = a["instance_id"] or "-"
    print(
        f"  {a['agent']:12s} proc={a['process_state']:<4s} hb={a['heartbeat_state']:<7s} "
        f"task={a['task_activity']:<7s} age={age:>6s} instance={inst:20s}"
    )
budget = payload.get("budget", {})
if budget:
    print()
    print("Daily Budget")
    for bkey, bcount in sorted(budget.items()):
        print(f"  {bkey}: {bcount} calls today")

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
