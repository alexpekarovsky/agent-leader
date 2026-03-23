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

# Add project root to sys.path to allow importing orchestrator modules
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from orchestrator.supervisor import Supervisor, SupervisorConfig
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy

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

# --- Supervisor and Orchestrator Setup ---
# Use default config values as this script is for read-only status.
cfg = SupervisorConfig(project_root=str(project_root))
cfg.finalise()

policy_path = project_root / "config" / "policy.balanced.json"
policy = Policy.load(path=policy_path)
orchestrator = Orchestrator(root=project_root, policy=policy)
sup = Supervisor(cfg, orchestrator)

all_process_status = sup.status_json()
# Convert list of dicts to a dict keyed by process name for easier lookup
all_process_status_map = {p["name"]: p for p in all_process_status}
# Re-populate proc for backward compatibility with some existing blocks
# In the future, these blocks should be refactored to use all_process_status_map directly
proc = {p["name"]: {"status": p["state"], "pid": p["pid"]} for p in all_process_status}
# --- End Supervisor and Orchestrator Setup ---


def heartbeat_state(age):
    if age is None:
        return "missing"
    if age <= 600:
        return "active"
    if age <= 1800:
        return "stale"
    return "offline"


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

# Create a temporary dictionary to build operator_agents
temp_operator_agents = {}

for p_status in all_process_status:
    agent_name = p_status.get("agent") # Use 'agent' instead of 'type'
    process_name = p_status["name"] # This is the specific process, e.g., 'claude', 'claude_2', 'manager'

    if not agent_name:
        continue # Skip if no agent_name

    if agent_name not in temp_operator_agents:
        temp_operator_agents[agent_name] = {
            "agent": agent_name,
            "heartbeat_state": "offline",
            "heartbeat_age_seconds": None,
            "process_state": "down",
            "process_count": 0,
            "task_activity": "idle",
            "instance_id": None, # Will try to get this from roles or a lane
            "lane_details": [],
        }

    # Derive lane_label
    lane_label = process_name
    if process_name == "manager":
        lane_label = "leader"
    elif process_name == "wingman":
        lane_label = "wingman"
    elif process_name == "claude":
        lane_label = "lane 1"
    elif process_name.startswith("claude_") and "_" in process_name:
        lane_label = process_name.replace("claude_", "lane ")
    # For gemini, codex_worker, watchdog, the process_name is often the best label.
    # 'role' from p_status will be better for individual lane_details.

    # Add this process as a lane detail
    temp_operator_agents[agent_name]["lane_details"].append({
        "process_name": process_name,
        "lane_label": lane_label,
        "status": p_status["state"],
        "pid": p_status["pid"],
        "instance_id": p_status.get("instance_id", "-"),
        "role": p_status.get("role", "N/A"), # Use the role from the process status
    })

    # Update overall agent status from its lanes
    if p_status["state"] == "running":
        temp_operator_agents[agent_name]["process_state"] = "up"
        temp_operator_agents[agent_name]["process_count"] += 1
    
    if p_status["heartbeat_status"] == "active":
        temp_operator_agents[agent_name]["heartbeat_state"] = "active"
        if p_status.get("heartbeat_age_seconds") is not None:
             temp_operator_agents[agent_name]["heartbeat_age_seconds"] = p_status["heartbeat_age_seconds"]
    
    # Aggregate task activity: if any lane is working/blocked/assigned, the agent is.
    current_activity = temp_operator_agents[agent_name]["task_activity"]
    if p_status["task_activity"] == "working":
        temp_operator_agents[agent_name]["task_activity"] = "working"
    elif p_status["task_activity"] == "blocked" and current_activity != "working":
        temp_operator_agents[agent_name]["task_activity"] = "blocked"
    elif p_status["task_activity"] == "assigned" and current_activity not in ("working", "blocked"):
        temp_operator_agents[agent_name]["task_activity"] = "queued"

    # Set the main instance_id for the agent. Prefer leader_instance_id from roles if it's the leader agent.
    # Otherwise, use the first instance_id from a running lane.
    if agent_name == roles.get("leader"):
        temp_operator_agents[agent_name]["instance_id"] = roles.get("leader_instance_id")
    elif p_status.get("instance_id") and temp_operator_agents[agent_name]["instance_id"] is None:
        temp_operator_agents[agent_name]["instance_id"] = p_status["instance_id"]

# Finalize operator_agents list
operator_agents = sorted(temp_operator_agents.values(), key=lambda x: x["agent"])

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
for op_agent in operator_agents:
    state = "active" if op_agent["heartbeat_state"] == "active" else "offline"
    # Derive age from heartbeat_age_seconds if available, otherwise use a default or calculate from task history
    agent_age = op_agent["heartbeat_age_seconds"] if op_agent["heartbeat_age_seconds"] is not None else (
        age_seconds(parse_iso(str(agents.get(op_agent["agent"], {}).get("last_seen", ""))))
    )
    active_agents.append(
        {
            "agent": op_agent["agent"],
            "state": state,
            "age_seconds": agent_age,
            "instance_id": op_agent["instance_id"],
            "role": op_agent["lane_details"][0].get("role", "N/A") if op_agent["lane_details"] else "N/A", # Assuming first lane detail can represent the agent's role.
        }
    )
active_agents.sort(key=lambda x: x["agent"])


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
preferred = ("manager", "wingman", "claude", "claude_2", "claude_3", "gemini", "codex_worker", "watchdog")
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
    lane_details = a.get("lane_details", [])
    if len(lane_details) > 1:
        for ld in lane_details:
            state_str = "up" if ld["status"] == "running" else "down"
            lid = ld.get("instance_id") or "-"
            print(f"    {ld['lane_label']:<10s} {state_str:<5s} pid={ld['pid'] if ld['pid'] is not None else '-':<8} instance={lid}")
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
