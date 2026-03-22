#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OPEN_STATUSES = {"assigned", "in_progress", "reported", "needs_review", "blocked", "bug_open"}
ACTIVE_STATUSES = {"assigned", "in_progress", "reported", "bug_open"}
# Valid claude lane process names — anything else (e.g. claude_b, claude_c from
# old supervisor sessions) is a zombie and must be filtered out of the roster.
_VALID_CLAUDE_LANES = frozenset(("claude", "claude_2", "claude_3"))

AGENT_ROLE_ORDER = {
    "Leader/Manager": 0,
    "Wingman/Reviewer": 1,
    "Implementation Worker": 2,
    "Worker": 3,
}
AGENT_OPERATOR_PROFILES: Dict[str, Dict[str, str]] = {
    "codex": {
        "display_name": "Codex",
        "role_label": "Leader/Manager",
        "provider": "OpenAI",
        "type_label": "Codex CLI",
        "default_model": "-",
    },
    "claude_code": {
        "display_name": "Claude Code",
        "role_label": "Implementation Worker",
        "provider": "Anthropic",
        "type_label": "Claude Code",
        "default_model": "-",
    },
    "ccm": {
        "display_name": "Claude Wingman",
        "role_label": "Wingman/Reviewer",
        "provider": "Anthropic",
        "type_label": "Claude Code",
        "default_model": "-",
    },
    "gemini": {
        "display_name": "Gemini",
        "role_label": "Worker",
        "provider": "Google",
        "type_label": "Gemini CLI",
        "default_model": "-",
    },
}
TASK_PREFIX_PATTERNS = (
    "Milestone:",
    "Planned Next:",
    "Backlog Feature Live:",
    "Wingman QA pass:",
)
GENERIC_TASK_SUFFIXES = (
    " - phase execution",
    " - policy enforcement phase",
    " - task type rollout",
    " loop scaffold",
    " design gated on CI/GitHub integration",
    " MCP workflow",
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _day_start_utc() -> datetime:
    local_now = _now_local()
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc)


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _age_s(value: Any) -> Optional[int]:
    dt = _parse_iso(value)
    if dt is None:
        return None
    return max(0, int((_now_utc() - dt).total_seconds()))


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _tail_lines(path: Path, max_lines: int = 300) -> List[str]:
    if not path.exists():
        return []
    dq: deque[str] = deque(maxlen=max_lines)
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                dq.append(line.rstrip("\n"))
    except Exception:
        return []
    return list(dq)


def _format_age(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def _term_width(default: int = 120) -> int:
    try:
        return shutil.get_terminal_size((default, 40)).columns
    except Exception:
        return default


def _term_height(default: int = 40) -> int:
    try:
        return shutil.get_terminal_size((120, default)).lines
    except Exception:
        return default


def _split_rows(total: int, mins: List[int], weights: List[int]) -> List[int]:
    if len(mins) != len(weights):
        raise ValueError("mins and weights length mismatch")
    rows = mins[:]
    remaining = max(0, total - sum(rows))
    wsum = max(1, sum(weights))
    for i, w in enumerate(weights):
        rows[i] += (remaining * w) // wsum
    i = 0
    while sum(rows) < total:
        rows[i % len(rows)] += 1
        i += 1
    return rows


def _progress_bar(percent: int, width: int = 30) -> str:
    pct = max(0, min(100, percent))
    filled = int((pct / 100) * width)
    return "[" + ("#" * filled) + ("-" * (width - filled)) + f"] {pct:>3d}%"


def _truncate(text: Any, width: int) -> str:
    s = str(text or "")
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width <= 3:
        return s[:width]
    return s[: width - 3] + "..."


def _color(enabled: bool, code: str, text: str) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _normalize_model_label(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "-"


def _normalize_type_label(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    lower = value.strip().lower()
    if "claude" in lower:
        return "Claude Code"
    if "gemini" in lower:
        return "Gemini CLI"
    if "codex" in lower or "openai" in lower:
        return "Codex CLI"
    return value.strip()


def _agent_profile(agent: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    base = dict(
        AGENT_OPERATOR_PROFILES.get(
            str(agent).strip(),
            {
                "display_name": str(agent).strip() or "Unknown Agent",
                "role_label": "Worker",
                "provider": "Unknown",
                "type_label": "Unknown",
                "default_model": "-",
            },
        )
    )
    md = metadata if isinstance(metadata, dict) else {}
    base["type_label"] = _normalize_type_label(md.get("client"), base["type_label"])
    base["model_label"] = _normalize_model_label(md.get("model") or base.get("default_model"))
    return base


def _clean_task_title(title: Any) -> str:
    raw = str(title or "").strip()
    if not raw:
        return "-"
    cleaned = raw
    for prefix in TASK_PREFIX_PATTERNS:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    for suffix in GENERIC_TASK_SUFFIXES:
        if cleaned.lower().endswith(suffix.lower()):
            cleaned = cleaned[: -len(suffix)].rstrip(" -:")
            break
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:")
    return cleaned or raw


def _clean_task_description(description: Any) -> str:
    desc = str(description or "").strip()
    if not desc:
        return "-"
    desc = desc.split(".", 1)[0].strip()
    replacements = (
        ("Implement ", ""),
        ("Design and scaffold ", ""),
        ("Define ", ""),
        ("Run QA/validation review for ", "QA review for "),
        ("Add ", ""),
    )
    for old, new in replacements:
        if desc.startswith(old):
            desc = new + desc[len(old):]
            break
    return re.sub(r"\s+", " ", desc).strip()


def _read_project_meta(root: Path) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "project_name": root.name,
        "version_current": None,
        "version_name": None,
        "active_milestones": [],
        "milestones_total": 0,
        "milestones_done": 0,
    }
    path = root / "project.yaml"
    if not path.exists():
        return meta
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            if isinstance(data.get("name"), str) and data.get("name", "").strip():
                meta["project_name"] = data["name"].strip()
            version = data.get("version")
            if isinstance(version, dict):
                current = version.get("current")
                if isinstance(current, str) and current.strip():
                    meta["version_current"] = current.strip()
                version_name = version.get("name")
                if isinstance(version_name, str) and version_name.strip():
                    meta["version_name"] = version_name.strip()
                milestones = version.get("milestones")
                if isinstance(milestones, list):
                    valid = [m for m in milestones if isinstance(m, dict)]
                    meta["milestones_total"] = len(valid)
                    meta["milestones_done"] = sum(
                        1 for m in valid if str(m.get("status", "")).strip() == "done"
                    )
                    meta["active_milestones"] = [
                        _clean_task_title(m.get("title") or m.get("id"))
                        for m in valid
                        if str(m.get("status", "")).strip() == "in_progress"
                    ]
        return meta
    except Exception:
        text = path.read_text(encoding="utf-8", errors="ignore")
        name_match = re.search(r"^name:\s*(.+)$", text, flags=re.MULTILINE)
        current_match = re.search(r"^\s*current:\s*(.+)$", text, flags=re.MULTILINE)
        version_name_match = re.search(r'^\s{2}name:\s*"?(.*?)"?\s*$', text, flags=re.MULTILINE)
        if name_match:
            meta["project_name"] = name_match.group(1).strip().strip('"')
        if current_match:
            meta["version_current"] = current_match.group(1).strip().strip('"')
        if version_name_match:
            meta["version_name"] = version_name_match.group(1).strip().strip('"')
        lines = text.splitlines()
        active: List[str] = []
        ms_total = 0
        ms_done = 0
        for idx, line in enumerate(lines):
            if re.match(r"^\s*-\s+id:\s+", line):
                ms_total += 1
                title = None
                status = None
                for look_ahead in lines[idx + 1 : idx + 8]:
                    if re.match(r"^\s*-\s+id:\s+", look_ahead):
                        break
                    title_match = re.match(r'^\s*title:\s*"?(.*?)"?\s*$', look_ahead)
                    status_match = re.match(r"^\s*status:\s*(\S+)\s*$", look_ahead)
                    if title_match:
                        title = title_match.group(1)
                    if status_match:
                        status = status_match.group(1)
                if status == "done":
                    ms_done += 1
                if title and status == "in_progress":
                    active.append(_clean_task_title(title))
        meta["active_milestones"] = active
        meta["milestones_total"] = ms_total
        meta["milestones_done"] = ms_done
        return meta


def _panel(title: str, rows: List[str], width: int, color_enabled: bool = True) -> List[str]:
    inner = max(10, width - 4)
    header = f"+- {_truncate(title, inner - 1)} " + "-" * max(0, inner - len(title) - 2) + "+"
    out = [_color(color_enabled, "36;1", header)]
    if not rows:
        rows = ["-"]
    for row in rows:
        out.append("| " + _truncate(row, inner).ljust(inner) + " |")
    out.append(_color(color_enabled, "36;1", "+" + "-" * (width - 2) + "+"))
    return out


def _panel_fixed(title: str, rows: List[str], width: int, body_rows: int, color_enabled: bool = True) -> List[str]:
    clipped = rows[: max(0, body_rows)]
    if len(clipped) < body_rows:
        clipped = clipped + [""] * (body_rows - len(clipped))
    return _panel(title, clipped, width, color_enabled=color_enabled)


def _fmt_number(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if abs(value - int(value)) < 1e-9:
        return str(int(value))
    return f"{value:.1f}"


def _fmt_int(value: Optional[int]) -> str:
    if value is None:
        return "-"
    return str(int(value))


def _compact_role_label(label: str) -> str:
    mapping = {
        "Leader/Manager": "Leader",
        "Wingman/Reviewer": "Wingman",
        "Implementation Worker": "Builder",
        "Worker": "Worker",
    }
    return mapping.get(label, label)


def _compact_type(provider: str, type_label: str) -> str:
    if provider == "OpenAI":
        return "OpenAI/Codex"
    if provider == "Anthropic":
        return "Anthropic/Claude"
    if provider == "Google":
        return "Google/Gemini"
    return f"{provider}/{type_label}"


def _extract_task_id(payload: Dict[str, Any]) -> str:
    keys = ("task_id", "id", "task")
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _merge_columns(left: List[str], right: List[str], total_width: int, gap: int = 2) -> List[str]:
    left_w = max(38, (total_width - gap) // 2)
    right_w = max(38, total_width - gap - left_w)
    height = max(len(left), len(right))
    out: List[str] = []
    for i in range(height):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
        out.append(l.ljust(left_w) + (" " * gap) + r.ljust(right_w))
    return out


@dataclass
class DashboardSnapshot:
    project_root: str
    total_tasks: int
    open_tasks: int
    done_tasks: int
    progress_percent: int
    status_counts: Dict[str, int]
    in_progress: List[Dict[str, Any]]
    assigned: List[Dict[str, Any]]
    blockers_open: int
    bugs_open: int
    active_agents: List[Dict[str, Any]]
    review_events: List[Dict[str, Any]]
    budget_calls_today: int
    budget_by_process: Dict[str, int]
    loc_added_total: int
    loc_deleted_total: int
    loc_net_total: int
    reports_count: int
    token_prompt_total: Optional[int]
    token_completion_total: Optional[int]
    token_total: Optional[int]
    team_lane_counts: Dict[str, Dict[str, int]]
    stale_in_progress: int
    recent_events: List[Dict[str, Any]]
    supervisor_processes: List[Dict[str, Any]]
    done_last_hour: int
    throughput_per_hour: Optional[float]
    eta_minutes: Optional[int]
    next_actions: List[str]
    validation_passed: int
    validation_failed: int
    review_pass_rate: Optional[float]
    oldest_open_task_age_s: Optional[int]
    queue_pressure: Optional[float]
    active_agent_count: int
    idle_agent_count: int
    avg_loc_per_report: Optional[float]
    avg_tokens_per_report: Optional[float]
    # V3B Dense Telemetry
    avg_task_lead_time_s: Optional[int] = None
    avg_validation_cycle_time_s: Optional[int] = None
    agent_utilization_percent: Optional[float] = None
    task_failure_rate_percent: Optional[float] = None
    cost_efficiency_loc_per_k_tokens: Optional[float] = None
    # Add 5 more metrics
    avg_blocker_resolution_time_s: Optional[int] = None
    stale_task_percent: Optional[float] = None
    agent_diversity: int = 0
    total_validations: int = 0
    avg_review_loop_depth: Optional[float] = None
    # Claude-specific telemetry
    claude_throughput_per_hour: Optional[float] = None
    claude_validation_contribution_percent: Optional[float] = None
    claude_latest_lane_event_time: Optional[datetime] = None
    claude_latest_lane_event_type: Optional[str] = None
    wingman_throughput_per_hour: Optional[float] = None
    wingman_validation_contribution_percent: Optional[float] = None
    wingman_latest_lane_event_time: Optional[datetime] = None
    wingman_latest_lane_event_type: Optional[str] = None
    project_name_display: str = ""
    version_current: Optional[str] = None
    version_name: Optional[str] = None
    active_milestones: Optional[List[str]] = None
    milestones_total: int = 0
    milestones_done: int = 0
    session_started_at: Optional[datetime] = None
    session_duration_s: Optional[int] = None
    commits_total: int = 0
    commits_today: int = 0
    commits_session: int = 0
    tasks_done_today: int = 0
    tasks_done_session: int = 0
    reports_today: int = 0
    reports_session: int = 0
    files_changed_total: int = 0
    files_changed_today: int = 0
    files_changed_session: int = 0
    loc_added_today: int = 0
    loc_deleted_today: int = 0
    loc_added_session: int = 0
    loc_deleted_session: int = 0
    token_total_today: Optional[int] = None
    token_total_session: Optional[int] = None
    validations_today: int = 0
    validations_session: int = 0
    queued_tasks: Optional[List[Dict[str, Any]]] = None
    blocked_tasks: Optional[List[Dict[str, Any]]] = None
    attention_tasks: Optional[List[Dict[str, Any]]] = None
    agent_delivery_stats: Optional[List[Dict[str, Any]]] = None


def _task_matches_project(task: Dict[str, Any], project_root: str) -> bool:
    return str(task.get("project_root", "")).strip() == project_root


def _extract_token_usage(report: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    # Accept multiple shapes without failing if absent.
    prompt = completion = total = None
    usage = report.get("token_usage")
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else prompt
        completion = usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else completion
        total = usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else total
    usage2 = report.get("usage")
    if isinstance(usage2, dict):
        prompt = usage2.get("prompt_tokens") if isinstance(usage2.get("prompt_tokens"), int) else prompt
        completion = usage2.get("completion_tokens") if isinstance(usage2.get("completion_tokens"), int) else completion
        total = usage2.get("total_tokens") if isinstance(usage2.get("total_tokens"), int) else total
    if total is None and isinstance(prompt, int) and isinstance(completion, int):
        total = prompt + completion
    return prompt, completion, total


def _read_recent_events(root: Path, limit: int = 12) -> List[Dict[str, Any]]:
    events_tail = _tail_lines(root / "bus" / "events.jsonl", 600)
    events: List[Dict[str, Any]] = []
    for line in reversed(events_tail):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        et = str(ev.get("type", "")).strip()
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        events.append(
            {
                "time": str(ev.get("timestamp", "")),
                "type": et,
                "source": str(ev.get("source", "")),
                "task_id": _extract_task_id(payload),
            }
        )
        if len(events) >= limit:
            break
    return events


def _read_agent_events(root: Path, agent_name: str, limit: int = 12) -> List[Dict[str, Any]]:
    events_tail = _tail_lines(root / "bus" / "events.jsonl", 600)
    agent_events: List[Dict[str, Any]] = []
    for line in reversed(events_tail):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        et = str(ev.get("type", "")).strip()
        source = str(ev.get("source", "")).strip()
        if source == agent_name:
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            agent_events.append(
                {
                    "time": str(ev.get("timestamp", "")),
                    "type": et,
                    "source": source,
                    "task_id": _extract_task_id(payload),
                }
            )
            if len(agent_events) >= limit:
                break
    return agent_events


def _read_supervisor_processes(root: Path) -> List[Dict[str, Any]]:
    pid_dir = root / ".autopilot-pids"
    if not pid_dir.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for pid_file in sorted(pid_dir.glob("*.pid")):
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            continue
        alive = False
        try:
            os.kill(pid, 0)
            alive = True
        except Exception:
            alive = False
        rows.append(
            {
                "name": pid_file.stem,
                "pid": pid,
                "alive": alive,
                "age_s": _age_s(datetime.fromtimestamp(pid_file.stat().st_mtime, tz=timezone.utc).isoformat()),
                "started_at": datetime.fromtimestamp(pid_file.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return rows


def _heartbeat_state(age_s: Optional[int]) -> str:
    if age_s is None:
        return "missing"
    if age_s <= 600:
        return "active"
    if age_s <= 1800:
        return "stale"
    return "offline"


def _process_names_for_agent(agent: str, processes: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for proc in processes:
        name = str(proc.get("name", "")).strip()
        if not name:
            continue
        if agent == "codex" and (name == "manager" or name.startswith("codex")):
            names.append(name)
        elif agent == "ccm" and name == "wingman":
            names.append(name)
        elif agent == "claude_code" and name in _VALID_CLAUDE_LANES:
            names.append(name)
        elif agent == "gemini" and name.startswith("gemini"):
            names.append(name)
    return names


def _task_activity_for_agent(agent: str, tasks: List[Dict[str, Any]]) -> str:
    owned = [t for t in tasks if str(t.get("owner", "")).strip() == agent]
    statuses = {str(t.get("status", "")).strip().lower() for t in owned}
    if "in_progress" in statuses:
        return "working"
    if "blocked" in statuses:
        return "blocked"
    if statuses.intersection({"assigned", "reported", "bug_open"}):
        return "queued"
    return "idle"


def _compute_next_actions(
    open_tasks: int,
    assigned_count: int,
    in_progress_count: int,
    blockers_open: int,
    bugs_open: int,
    stale_in_progress: int,
    supervisor_processes: List[Dict[str, Any]],
    active_agents: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    actions: List[str] = []
    if blockers_open > 0:
        actions.append(f"Resolve blockers: {blockers_open} open blocker(s).")
    if stale_in_progress > 0:
        actions.append(f"Investigate stale work: {stale_in_progress} in-progress task(s) exceeded stale threshold.")
    if bugs_open > 0:
        actions.append(f"Run bug triage: {bugs_open} bug(s) are still open.")
    if in_progress_count == 0 and assigned_count > 0:
        actions.append("Workers appear idle while queue is non-empty; verify claim loop health.")
    if open_tasks == 0:
        actions.append("All scoped tasks are complete. Keep dashboard open or stop supervisor.")
    dead = [p for p in supervisor_processes if not p.get("alive")]
    if dead:
        actions.append(f"Supervisor has stale pid files for {len(dead)} process(es); run clean if needed.")
    # Stale leader heartbeat: leader process up but orchestrator heartbeat stale.
    if active_agents:
        for agent in active_agents:
            if (
                str(agent.get("role_label", "")) == "Leader/Manager"
                and str(agent.get("process_state", "")) == "up"
                and str(agent.get("heartbeat_state", "")) in ("stale", "offline", "missing")
            ):
                actions.append(
                    "Leader heartbeat stale: manager process is running but orchestrator heartbeat is not active. "
                    "Check manager_loop health or restart supervisor."
                )
                break
    if not actions:
        actions.append("Flow healthy. Continue monitoring throughput and review cadence.")
    return actions


def build_snapshot(project_root: str, root: Path, stale_seconds: int = 1800) -> DashboardSnapshot:
    tasks = _load_json(root / "state" / "tasks.json", [])
    blockers = _load_json(root / "state" / "blockers.json", [])
    bugs = _load_json(root / "state" / "bugs.json", [])
    agents_map = _load_json(root / "state" / "agents.json", {})
    project_meta = _read_project_meta(root)

    scoped = [t for t in tasks if _task_matches_project(t, project_root)]
    if not scoped:
        # Fallback for legacy tasks without project_root tagging.
        scoped = [t for t in tasks if not str(t.get("project_root", "")).strip()]

    status_counts = Counter(str(t.get("status", "unknown")) for t in scoped)
    total_tasks = len(scoped)
    open_tasks = sum(1 for t in scoped if str(t.get("status", "")).strip().lower() in OPEN_STATUSES)
    done_tasks = status_counts.get("done", 0)
    progress_percent = int((done_tasks / total_tasks) * 100) if total_tasks else 100

    in_progress = [t for t in scoped if str(t.get("status", "")).strip().lower() == "in_progress"]
    assigned = [t for t in scoped if str(t.get("status", "")).strip().lower() in {"assigned", "bug_open", "reported"}]
    queued_tasks = [t for t in scoped if str(t.get("status", "")).strip().lower() == "assigned"]
    blocked_tasks = [t for t in scoped if str(t.get("status", "")).strip().lower() == "blocked"]
    attention_tasks = [t for t in scoped if str(t.get("status", "")).strip().lower() in {"reported", "bug_open"}]
    stale_in_progress = sum(
        1 for t in in_progress
        if (lambda a: a is not None and a >= max(1, stale_seconds))(_age_s(t.get("updated_at")))
    )
    open_ages = [_age_s(t.get("updated_at")) for t in scoped if str(t.get("status", "")).strip().lower() in OPEN_STATUSES]
    open_ages = [a for a in open_ages if isinstance(a, int)]
    oldest_open_task_age_s = max(open_ages) if open_ages else None
    tasks_by_id = {str(t.get("id")): t for t in scoped if isinstance(t.get("id"), str)}

    blockers_open = sum(1 for b in blockers if str(b.get("status", "")).lower() == "open")
    bugs_open = sum(1 for b in bugs if str(b.get("status", "")).lower() == "open")

    roles = _load_json(root / "state" / "roles.json", {})
    live_leader = str(roles.get("leader", "")).strip()

    supervisor_processes = _read_supervisor_processes(root)
    active_agents: List[Dict[str, Any]] = []
    operator_agent_names = set(AGENT_OPERATOR_PROFILES.keys())
    if isinstance(agents_map, dict):
        operator_agent_names.update(str(agent).strip() for agent in agents_map.keys())
    for agent in sorted(a for a in operator_agent_names if a):
        entry = agents_map.get(agent, {}) if isinstance(agents_map, dict) else {}
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        profile = _agent_profile(agent, metadata)
        age_s = _age_s(entry.get("last_seen"))
        heartbeat_state = _heartbeat_state(age_s)
        process_names = _process_names_for_agent(agent, supervisor_processes)
        running_processes = [
            proc for proc in supervisor_processes
            if str(proc.get("name", "")) in process_names and bool(proc.get("alive"))
        ]
        process_state = "up" if running_processes else "down"
        task_activity = _task_activity_for_agent(agent, scoped)
        # Build per-lane details for agents with multiple processes (e.g. claude lanes).
        # Only include alive processes to filter out zombie lanes from old sessions.
        lane_details: List[Dict[str, Any]] = []
        for pname in process_names:
            proc_entry = next((p for p in supervisor_processes if p.get("name") == pname), None)
            if proc_entry and proc_entry.get("alive"):
                lane_label = "lane 1" if pname == "claude" else (pname.replace("claude_", "lane ") if "_" in pname and pname.startswith("claude") else pname)
                lane_details.append({
                    "process_name": pname,
                    "lane_label": lane_label,
                    "alive": bool(proc_entry.get("alive")),
                    "pid": proc_entry.get("pid"),
                    "age_s": proc_entry.get("age_s"),
                    "started_at": proc_entry.get("started_at"),
                })
        # Override role_label from live roles.json — the actual leader may differ from the hardcoded profile.
        effective_role = profile["role_label"]
        if live_leader and agent == live_leader:
            effective_role = "Leader/Manager"
        elif live_leader and agent != live_leader and effective_role == "Leader/Manager":
            effective_role = "Worker"

        active_agents.append(
            {
                "agent": agent,
                "status": heartbeat_state,
                "heartbeat_state": heartbeat_state,
                "age_s": age_s,
                "instance_id": metadata.get("instance_id", "-"),
                "client": profile["type_label"],
                "model": profile["model_label"],
                "display_name": profile["display_name"],
                "role_label": effective_role,
                "provider": profile["provider"],
                "process_state": process_state,
                "process_count": len(running_processes),
                "process_names": process_names,
                "lane_details": lane_details,
                "task_activity": task_activity,
            }
        )
    active_agents.sort(
        key=lambda a: (
            a.get("process_state") != "up",
            a.get("heartbeat_state") != "active",
            AGENT_ROLE_ORDER.get(str(a.get("role_label", "")), 99),
            str(a["agent"]),
        )
    )

    review_events: List[Dict[str, Any]] = []
    recent_events = _read_recent_events(root, limit=12)
    validation_passed = 0
    validation_failed = 0
    for ev in recent_events:
        et = str(ev.get("type", ""))
        if et in {"validation.passed", "validation.failed", "task.reported"}:
            review_events.append({"time": ev.get("time", ""), "type": et, "source": ev.get("source", ""), "task_id": ev.get("task_id", "")})
        if et == "validation.passed":
            validation_passed += 1
        elif et == "validation.failed":
            validation_failed += 1
        if len(review_events) >= 8:
            break
    review_pass_rate: Optional[float] = None
    if (validation_passed + validation_failed) > 0:
        review_pass_rate = (validation_passed / (validation_passed + validation_failed)) * 100.0

    budget_by_process: Dict[str, int] = {}
    stamp = _now_utc().strftime("%Y%m%d")
    log_dir = root / ".autopilot-logs"
    for f in log_dir.glob(f".budget-*-{stamp}.count"):
        n = f.name
        prefix = ".budget-"
        suffix = f"-{stamp}.count"
        if not (n.startswith(prefix) and n.endswith(suffix)):
            continue
        key = n[len(prefix):-len(suffix)]
        try:
            budget_by_process[key] = int(f.read_text(encoding="utf-8").strip())
        except Exception:
            budget_by_process[key] = 0
    budget_calls_today = sum(budget_by_process.values())

    # LOC/token data from report artifacts for this project.
    reports_dir = root / "bus" / "reports"
    loc_added_total = 0
    loc_deleted_total = 0
    reports_count = 0
    token_prompt_total = 0
    token_completion_total = 0
    token_total = 0
    token_present = False
    local_day_start = _day_start_utc()
    session_start_candidates = [
        _parse_iso(proc.get("started_at"))
        for proc in supervisor_processes
        if proc.get("alive")
    ]
    session_start_candidates = [dt for dt in session_start_candidates if dt is not None]
    session_started_at = min(session_start_candidates) if session_start_candidates else None
    session_duration_s = int((_now_utc() - session_started_at).total_seconds()) if session_started_at else None
    commits_today: set[str] = set()
    commits_session: set[str] = set()
    commits_total: set[str] = set()
    reports_today = 0
    reports_session = 0
    files_changed_total = 0
    files_changed_today = 0
    files_changed_session = 0
    loc_added_today = 0
    loc_deleted_today = 0
    loc_added_session = 0
    loc_deleted_session = 0
    token_total_today = 0
    token_total_session = 0
    token_today_present = False
    token_session_present = False
    agent_stats_acc: Dict[str, Dict[str, Any]] = {}

    def _agent_bucket(agent_name: str) -> Dict[str, Any]:
        bucket = agent_stats_acc.setdefault(
            agent_name,
            {
                "agent": agent_name,
                "commits_total": set(),
                "commits_session": set(),
                "tasks_done_total": 0,
                "tasks_done_session": 0,
                "loc_net_total": 0,
                "loc_net_session": 0,
                "files_total": 0,
                "files_session": 0,
            },
        )
        return bucket

    def _report_timestamp(report: Dict[str, Any], path: Path) -> Optional[datetime]:
        for key in ("reported_at", "validated_at", "updated_at", "created_at"):
            parsed = _parse_iso(report.get(key))
            if parsed is not None:
                return parsed
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            pass
        task = tasks_by_id.get(str(report.get("task_id", "")))
        if isinstance(task, dict):
            for key in ("reported_at", "validated_at", "updated_at", "created_at"):
                parsed = _parse_iso(task.get(key))
                if parsed is not None:
                    return parsed
        return None

    if reports_dir.exists():
        for path in reports_dir.glob("*.json"):
            try:
                r = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if r.get("project_root") and str(r.get("project_root")) != project_root:
                continue
            reports_count += 1
            cm = r.get("commit_metrics")
            report_ts = _report_timestamp(r, path)
            if isinstance(cm, dict):
                la = cm.get("lines_added")
                ld = cm.get("lines_deleted")
                fc = cm.get("files_changed")
                if isinstance(fc, int):
                    files_changed_total += fc
                if isinstance(la, int):
                    loc_added_total += la
                if isinstance(ld, int):
                    loc_deleted_total += ld
                if report_ts is not None and report_ts >= local_day_start:
                    if isinstance(fc, int):
                        files_changed_today += fc
                    if isinstance(la, int):
                        loc_added_today += la
                    if isinstance(ld, int):
                        loc_deleted_today += ld
                if report_ts is not None and session_started_at is not None and report_ts >= session_started_at:
                    if isinstance(fc, int):
                        files_changed_session += fc
                    if isinstance(la, int):
                        loc_added_session += la
                    if isinstance(ld, int):
                        loc_deleted_session += ld
            p, c, t = _extract_token_usage(r)
            if isinstance(p, int):
                token_present = True
                token_prompt_total += p
            if isinstance(c, int):
                token_present = True
                token_completion_total += c
            if isinstance(t, int):
                token_present = True
                token_total += t
            if report_ts is not None and report_ts >= local_day_start:
                reports_today += 1
                if isinstance(r.get("commit_sha"), str) and r.get("commit_sha", "").strip():
                    commits_today.add(r["commit_sha"].strip())
                if isinstance(t, int):
                    token_today_present = True
                    token_total_today += t
            if report_ts is not None and session_started_at is not None and report_ts >= session_started_at:
                reports_session += 1
                if isinstance(r.get("commit_sha"), str) and r.get("commit_sha", "").strip():
                    commits_session.add(r["commit_sha"].strip())
                if isinstance(t, int):
                    token_session_present = True
                    token_total_session += t
            agent_name = str(r.get("agent", "")).strip()
            if agent_name:
                bucket = _agent_bucket(agent_name)
                commit_sha = str(r.get("commit_sha", "")).strip()
                if commit_sha:
                    bucket["commits_total"].add(commit_sha)
                    commits_total.add(commit_sha)
                    if report_ts is not None and session_started_at is not None and report_ts >= session_started_at:
                        bucket["commits_session"].add(commit_sha)
                if isinstance(cm, dict):
                    net = cm.get("net_lines")
                    if not isinstance(net, int):
                        la = cm.get("lines_added") if isinstance(cm.get("lines_added"), int) else 0
                        ld = cm.get("lines_deleted") if isinstance(cm.get("lines_deleted"), int) else 0
                        net = la - ld
                    bucket["loc_net_total"] += int(net)
                    if report_ts is not None and session_started_at is not None and report_ts >= session_started_at:
                        bucket["loc_net_session"] += int(net)
                    if isinstance(cm.get("files_changed"), int):
                        bucket["files_total"] += int(cm["files_changed"])
                        if report_ts is not None and session_started_at is not None and report_ts >= session_started_at:
                            bucket["files_session"] += int(cm["files_changed"])

    team_lane_counts: Dict[str, Dict[str, int]] = {}
    for task in scoped:
        team_id = str(task.get("team_id", "") or "default")
        status = str(task.get("status", "unknown")).strip().lower()
        lane = team_lane_counts.setdefault(team_id, {"total": 0, "open": 0, "done": 0, "in_progress": 0, "assigned": 0, "blocked": 0})
        lane["total"] += 1
        if status in OPEN_STATUSES:
            lane["open"] += 1
        if status == "done":
            lane["done"] += 1
        if status == "in_progress":
            lane["in_progress"] += 1
        if status == "assigned":
            lane["assigned"] += 1
        if status == "blocked":
            lane["blocked"] += 1

    done_last_hour = sum(
        1 for t in scoped
        if str(t.get("status", "")).strip().lower() == "done"
        and (lambda a: a is not None and a <= 3600)(_age_s(t.get("updated_at")))
    )
    throughput_per_hour: Optional[float] = float(done_last_hour) if done_last_hour > 0 else None
    eta_minutes: Optional[int] = None
    if open_tasks > 0 and throughput_per_hour and throughput_per_hour > 0:
        eta_minutes = int((open_tasks / throughput_per_hour) * 60)

    active_agent_count = sum(1 for a in active_agents if str(a.get("heartbeat_state", "")).lower() == "active")
    idle_agent_count = sum(
        1
        for a in active_agents
        if str(a.get("process_state", "")).lower() == "up" and str(a.get("task_activity", "")).lower() == "idle"
    )
    queue_pressure: Optional[float] = None
    if active_agent_count > 0:
        queue_pressure = open_tasks / active_agent_count
    avg_loc_per_report: Optional[float] = None
    if reports_count > 0:
        avg_loc_per_report = (loc_added_total + loc_deleted_total) / reports_count
    avg_tokens_per_report: Optional[float] = None
    if reports_count > 0 and token_present:
        avg_tokens_per_report = token_total / reports_count

    # Lead time and validation cycle time
    lead_times = []
    validation_cycle_times = []
    for t in scoped:
        if str(t.get("status", "")).strip().lower() == "done":
            created = _parse_iso(t.get("created_at"))
            validated = _parse_iso(t.get("validated_at") or t.get("updated_at"))
            reported = _parse_iso(t.get("reported_at"))
            if created and validated:
                lead_times.append((validated - created).total_seconds())
            if reported and validated:
                validation_cycle_times.append((validated - reported).total_seconds())

    avg_task_lead_time_s = int(sum(lead_times) / len(lead_times)) if lead_times else None
    avg_validation_cycle_time_s = int(sum(validation_cycle_times) / len(validation_cycle_times)) if validation_cycle_times else None

    # Agent Utilization
    active_agent_count = sum(1 for a in active_agents if str(a.get("heartbeat_state", "")).lower() == "active")
    agent_utilization_percent = (len(in_progress) / active_agent_count * 100.0) if active_agent_count > 0 else 0.0

    # Task Failure Rate
    task_failure_rate_percent = (validation_failed / (validation_passed + validation_failed) * 100.0) if (validation_passed + validation_failed) > 0 else 0.0

    # Cost Efficiency
    cost_efficiency_loc_per_k_tokens = (loc_added_total + loc_deleted_total) / (token_total / 1000.0) if (token_total and token_total > 0) else None

    # 5 New Metrics
    # 1. Blocker Resolution Time
    resolved_blocker_times = []
    for b in blockers:
        b_task_id = b.get("task_id")
        is_scoped = any(t.get("id") == b_task_id for t in scoped)
        if is_scoped and b.get("status") == "resolved":
            c_at = _parse_iso(b.get("created_at"))
            r_at = _parse_iso(b.get("resolved_at"))
            if c_at and r_at:
                resolved_blocker_times.append((r_at - c_at).total_seconds())
    avg_blocker_resolution_time_s = int(sum(resolved_blocker_times) / len(resolved_blocker_times)) if resolved_blocker_times else None

    # 2. Stale Task Percent
    stale_task_percent = (stale_in_progress / len(in_progress) * 100.0) if in_progress else 0.0

    # 3. Agent Diversity
    done_owners = {t.get("owner") for t in scoped if t.get("status") == "done" and t.get("owner")}
    agent_diversity = len(done_owners)

    # 4. Total Validations
    total_validations = validation_passed + validation_failed

    # 5. Review Loop Depth (Approximated from recent events or task failures if tracked)
    # Since we only have recent events, we'll use a larger sample for this specific metric if possible,
    # or just use the ratio of failures to successes as a proxy for depth.
    avg_review_loop_depth = (validation_failed / validation_passed) if validation_passed > 0 else (float(validation_failed) if validation_failed > 0 else 0.0)

    tasks_done_today = 0
    tasks_done_session = 0
    for task in scoped:
        if str(task.get("status", "")).strip().lower() != "done":
            continue
        task_ts = None
        for key in ("validated_at", "reported_at", "updated_at", "created_at"):
            task_ts = _parse_iso(task.get(key))
            if task_ts is not None:
                break
        if task_ts is None:
            continue
        if task_ts >= local_day_start:
            tasks_done_today += 1
        if session_started_at is not None and task_ts >= session_started_at:
            tasks_done_session += 1
        agent_name = str(task.get("owner", "")).strip()
        if agent_name:
            bucket = _agent_bucket(agent_name)
            bucket["tasks_done_total"] += 1
            if session_started_at is not None and task_ts >= session_started_at:
                bucket["tasks_done_session"] += 1

    validations_today = 0
    validations_session = 0

    # Claude-only telemetry (claude_code + ccm lanes)
    claude_done_last_hour = sum(
        1
        for t in scoped
        if str(t.get("status", "")).strip().lower() == "done"
        and str(t.get("owner", "")).strip() == "claude_code"
        and (lambda a: a is not None and a <= 3600)(_age_s(t.get("updated_at")))
    )
    wingman_done_last_hour = sum(
        1
        for t in scoped
        if str(t.get("status", "")).strip().lower() == "done"
        and str(t.get("owner", "")).strip() == "ccm"
        and (lambda a: a is not None and a <= 3600)(_age_s(t.get("updated_at")))
    )
    claude_throughput_per_hour: Optional[float] = float(claude_done_last_hour) if claude_done_last_hour > 0 else 0.0
    wingman_throughput_per_hour: Optional[float] = float(wingman_done_last_hour) if wingman_done_last_hour > 0 else 0.0

    validation_total = 0
    validation_by_source: Dict[str, int] = {}
    for line in _tail_lines(root / "bus" / "events.jsonl", 1200):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        et = str(ev.get("type", "")).strip()
        if et not in {"validation.passed", "validation.failed"}:
            continue
        ev_time = _parse_iso(ev.get("timestamp"))
        validation_total += 1
        src = str(ev.get("source", "")).strip() or "unknown"
        validation_by_source[src] = validation_by_source.get(src, 0) + 1
        if ev_time is not None and ev_time >= local_day_start:
            validations_today += 1
        if ev_time is not None and session_started_at is not None and ev_time >= session_started_at:
            validations_session += 1

    claude_validation_contribution_percent: Optional[float] = None
    wingman_validation_contribution_percent: Optional[float] = None
    if validation_total > 0:
        claude_validation_contribution_percent = (validation_by_source.get("claude_code", 0) / validation_total) * 100.0
        wingman_validation_contribution_percent = (validation_by_source.get("ccm", 0) / validation_total) * 100.0

    claude_events = _read_agent_events(root, "claude_code", limit=1)
    wingman_events = _read_agent_events(root, "ccm", limit=1)
    claude_latest_lane_event_time = _parse_iso(claude_events[0]["time"]) if claude_events else None
    claude_latest_lane_event_type = str(claude_events[0]["type"]) if claude_events else None
    wingman_latest_lane_event_time = _parse_iso(wingman_events[0]["time"]) if wingman_events else None
    wingman_latest_lane_event_type = str(wingman_events[0]["type"]) if wingman_events else None

    next_actions = _compute_next_actions(
        open_tasks=open_tasks,
        assigned_count=len(assigned),
        in_progress_count=len(in_progress),
        blockers_open=blockers_open,
        bugs_open=bugs_open,
        stale_in_progress=stale_in_progress,
        supervisor_processes=supervisor_processes,
        active_agents=active_agents,
    )

    agent_delivery_stats: List[Dict[str, Any]] = []
    for agent_name, bucket in agent_stats_acc.items():
        profile = _agent_profile(agent_name)
        agent_delivery_stats.append(
            {
                "agent": agent_name,
                "display_name": profile["display_name"],
                "role_label": profile["role_label"],
                "commits_total": len(bucket["commits_total"]),
                "commits_session": len(bucket["commits_session"]),
                "tasks_done_total": int(bucket["tasks_done_total"]),
                "tasks_done_session": int(bucket["tasks_done_session"]),
                "loc_net_total": int(bucket["loc_net_total"]),
                "loc_net_session": int(bucket["loc_net_session"]),
                "files_total": int(bucket["files_total"]),
                "files_session": int(bucket["files_session"]),
            }
        )
    agent_delivery_stats.sort(
        key=lambda row: (
            -int(row.get("tasks_done_session", 0)),
            -int(row.get("commits_session", 0)),
            -int(row.get("loc_net_session", 0)),
            str(row.get("agent", "")),
        )
    )

    return DashboardSnapshot(
        project_root=project_root,
        total_tasks=total_tasks,
        open_tasks=open_tasks,
        done_tasks=done_tasks,
        progress_percent=progress_percent,
        status_counts=dict(status_counts),
        in_progress=in_progress,
        assigned=assigned,
        blockers_open=blockers_open,
        bugs_open=bugs_open,
        active_agents=active_agents,
        review_events=review_events,
        budget_calls_today=budget_calls_today,
        budget_by_process=budget_by_process,
        loc_added_total=loc_added_total,
        loc_deleted_total=loc_deleted_total,
        loc_net_total=loc_added_total - loc_deleted_total,
        reports_count=reports_count,
        token_prompt_total=token_prompt_total if token_present else None,
        token_completion_total=token_completion_total if token_present else None,
        token_total=token_total if token_present else None,
        team_lane_counts=team_lane_counts,
        stale_in_progress=stale_in_progress,
        recent_events=recent_events,
        supervisor_processes=supervisor_processes,
        done_last_hour=done_last_hour,
        throughput_per_hour=throughput_per_hour,
        eta_minutes=eta_minutes,
        next_actions=next_actions,
        validation_passed=validation_passed,
        validation_failed=validation_failed,
        review_pass_rate=review_pass_rate,
        oldest_open_task_age_s=oldest_open_task_age_s,
        queue_pressure=queue_pressure,
        active_agent_count=active_agent_count,
        idle_agent_count=max(0, active_agent_count - len(in_progress)),
        avg_loc_per_report=avg_loc_per_report,
        avg_tokens_per_report=avg_tokens_per_report,
        # V3B
        avg_task_lead_time_s=avg_task_lead_time_s,
        avg_validation_cycle_time_s=avg_validation_cycle_time_s,
        agent_utilization_percent=agent_utilization_percent,
        task_failure_rate_percent=task_failure_rate_percent,
        cost_efficiency_loc_per_k_tokens=cost_efficiency_loc_per_k_tokens,
        avg_blocker_resolution_time_s=avg_blocker_resolution_time_s,
        stale_task_percent=stale_task_percent,
        agent_diversity=agent_diversity,
        total_validations=total_validations,
        avg_review_loop_depth=avg_review_loop_depth,
        claude_throughput_per_hour=claude_throughput_per_hour,
        claude_validation_contribution_percent=claude_validation_contribution_percent,
        claude_latest_lane_event_time=claude_latest_lane_event_time,
        claude_latest_lane_event_type=claude_latest_lane_event_type,
        wingman_throughput_per_hour=wingman_throughput_per_hour,
        wingman_validation_contribution_percent=wingman_validation_contribution_percent,
        wingman_latest_lane_event_time=wingman_latest_lane_event_time,
        wingman_latest_lane_event_type=wingman_latest_lane_event_type,
        project_name_display=str(project_meta.get("project_name") or root.name),
        version_current=project_meta.get("version_current"),
        version_name=project_meta.get("version_name"),
        active_milestones=project_meta.get("active_milestones") or [],
        milestones_total=project_meta.get("milestones_total", 0),
        milestones_done=project_meta.get("milestones_done", 0),
        session_started_at=session_started_at,
        session_duration_s=session_duration_s,
        commits_total=len(commits_total),
        commits_today=len(commits_today),
        commits_session=len(commits_session),
        tasks_done_today=tasks_done_today,
        tasks_done_session=tasks_done_session,
        reports_today=reports_today,
        reports_session=reports_session,
        files_changed_total=files_changed_total,
        files_changed_today=files_changed_today,
        files_changed_session=files_changed_session,
        loc_added_today=loc_added_today,
        loc_deleted_today=loc_deleted_today,
        loc_added_session=loc_added_session,
        loc_deleted_session=loc_deleted_session,
        token_total_today=token_total_today if token_today_present else None,
        token_total_session=token_total_session if token_session_present else None,
        validations_today=validations_today,
        validations_session=validations_session,
        queued_tasks=queued_tasks,
        blocked_tasks=blocked_tasks,
        attention_tasks=attention_tasks,
        agent_delivery_stats=agent_delivery_stats,
    )


def _is_supervisor_running(root: Path) -> bool:
    pid_dir = root / ".autopilot-pids"
    if not pid_dir.exists():
        return False
    for pid_file in pid_dir.glob("*.pid"):
        try:
            pid = int(pid_file.read_text().strip())
        except Exception:
            continue
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            continue
    return False


def _stop_supervisor(project_root: str, root: Path) -> None:
    cmd = [str(root / "scripts" / "autopilot" / "supervisor.sh"), "stop", "--project-root", project_root]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    cmd = [str(root / "scripts" / "autopilot" / "supervisor.sh"), "clean", "--project-root", project_root]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def _health_score(snap: DashboardSnapshot) -> int:
    """Composite operational health 0-100 for executive dashboard."""
    score = 0.0
    # Progress: 0-20 pts
    score += (snap.progress_percent / 100.0) * 20
    # Review pass rate: 0-20 pts
    rpr = snap.review_pass_rate if snap.review_pass_rate is not None else 75.0
    score += (rpr / 100.0) * 20
    # Agent utilization: 0-15 pts
    util = snap.agent_utilization_percent if snap.agent_utilization_percent is not None else 50.0
    score += min(1.0, util / 100.0) * 15
    # Low failure rate: 0-15 pts
    fail = snap.task_failure_rate_percent if snap.task_failure_rate_percent is not None else 0.0
    score += (1.0 - fail / 100.0) * 15
    # No blockers: 0-15 pts
    score += 15 if snap.blockers_open == 0 else (8 if snap.blockers_open <= 2 else 0)
    # No stale work: 0-15 pts
    score += 15 if snap.stale_in_progress == 0 else (8 if snap.stale_in_progress <= 2 else 0)
    return max(0, min(100, int(score)))


def _render_claude_v3a(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool, color_enabled: bool = True) -> str:
    width = max(72, _term_width())
    height = max(24, _term_height())
    sep = _color(color_enabled, "35;1", "=" * width)
    lines: List[str] = []
    now = _now_utc().strftime("%Y-%m-%d %H:%M:%SZ")
    mode = "COMPLETED" if completed else "RUNNING"
    mode_color = "32;1" if completed else "33;1"

    # ── Header ──
    lines.append(sep)
    title = _color(color_enabled, "35;1", "AGENT LEADER // CLAUDE V3A EXECUTIVE")
    lines.append(f"{title}  {_color(color_enabled, mode_color, mode)}  {now}")
    lines.append(f"Project: {_truncate(snapshot.project_root, width - 9)}")
    lines.append(sep)

    # ── Health Pulse ──
    score = _health_score(snapshot)
    bar_w = 20
    filled = int((score / 100) * bar_w)
    bar_str = "#" * filled + "-" * (bar_w - filled)
    if score >= 70:
        score_color = "32;1"
    elif score >= 40:
        score_color = "33;1"
    else:
        score_color = "31;1"
    health_bar = _color(color_enabled, score_color, f"[{bar_str}] {score}/100")

    indicators = []
    if snapshot.blockers_open > 0:
        indicators.append(_color(color_enabled, "31;1", f"BLOCKERS:{snapshot.blockers_open}"))
    else:
        indicators.append(_color(color_enabled, "32", "BLOCKERS:0"))
    if snapshot.bugs_open > 0:
        indicators.append(_color(color_enabled, "33;1", f"BUGS:{snapshot.bugs_open}"))
    else:
        indicators.append(_color(color_enabled, "32", "BUGS:0"))
    if snapshot.stale_in_progress > 0:
        indicators.append(_color(color_enabled, "31;1", f"STALE:{snapshot.stale_in_progress}"))
    else:
        indicators.append(_color(color_enabled, "32", "STALE:0"))

    lines.append(f"HEALTH {health_bar}  {' | '.join(indicators)}")
    if auto_stopped:
        lines.append(_color(color_enabled, "32;1", ">> AUTO-STOP: supervisor stopped after completion"))
    lines.append("")

    # ── Two-column: Progress & Throughput | Cost & Efficiency ──
    panel_w = (width - 2) // 2
    narrow = width < 120
    fixed_lines = 8
    remaining = max(12, height - fixed_lines)
    top_rows, mid_rows, bot_rows = _split_rows(remaining, [4, 6, 2], [2, 3, 1])
    eta = f"{snapshot.eta_minutes}m" if snapshot.eta_minutes is not None else "-"
    prog_rows = [
        f"Done: {snapshot.done_tasks}/{snapshot.total_tasks} ({snapshot.progress_percent}%)",
        f"{_progress_bar(snapshot.progress_percent, width=max(10, panel_w - 4))}",
        f"Rate: {_fmt_number(snapshot.throughput_per_hour)} done/h  |  ETA: {eta}",
        f"Avg Lead Time: {_format_age(snapshot.avg_task_lead_time_s)}  |  Avg Validation: {_format_age(snapshot.avg_validation_cycle_time_s)}",
        f"Queue Pressure: {_fmt_number(snapshot.queue_pressure)}  |  Oldest Open: {_format_age(snapshot.oldest_open_task_age_s)}",
        f"Review Pass: {_fmt_number(snapshot.review_pass_rate)}% ({snapshot.validation_passed}/{snapshot.validation_passed + snapshot.validation_failed})",
    ]

    cost_rows = [
        f"Tokens: {snapshot.token_total if snapshot.token_total is not None else '-'} total",
        f"  Prompt: {snapshot.token_prompt_total or '-'}  Completion: {snapshot.token_completion_total or '-'}",
        f"Avg Tokens/Report: {_fmt_number(snapshot.avg_tokens_per_report)}",
        f"LOC: +{snapshot.loc_added_total} / -{snapshot.loc_deleted_total} (net {snapshot.loc_net_total})",
        f"Avg LOC/Report: {_fmt_number(snapshot.avg_loc_per_report)}",
        f"Efficiency: {_fmt_number(snapshot.cost_efficiency_loc_per_k_tokens)} LOC/k-tok",
        f"Budget Today: {snapshot.budget_calls_today} calls",
    ]
    if snapshot.budget_by_process:
        for k, v in sorted(snapshot.budget_by_process.items())[:3]:
            cost_rows.append(f"  {k}: {v}")

    if narrow:
        lines.extend(_panel_fixed("Progress & Throughput", prog_rows, width, body_rows=top_rows, color_enabled=color_enabled))
        lines.extend(_panel_fixed("Cost & Efficiency", cost_rows, width, body_rows=max(2, top_rows), color_enabled=color_enabled))
    else:
        left = _panel_fixed("Progress & Throughput", prog_rows, panel_w, body_rows=top_rows, color_enabled=color_enabled)
        right = _panel_fixed("Cost & Efficiency", cost_rows, panel_w, body_rows=top_rows, color_enabled=color_enabled)
        lines.extend(_merge_columns(left, right, width))

    # ── Two-column: Fleet | Active Work ──
    fleet_rows: List[str] = []
    for a in snapshot.active_agents[:6]:
        fleet_rows.append(f"{a['agent']:<12} {a['status']:<8} age={_format_age(a['age_s']):>7}")
        lane_details = a.get("lane_details", [])
        if len(lane_details) > 1:
            for ld in lane_details:
                state_str = "UP" if ld.get("alive") else "DOWN"
                fleet_rows.append(f"  {ld.get('lane_label', '-'):<10} {state_str:<6} pid={ld.get('pid', '-')}")
    if not fleet_rows:
        fleet_rows.append("no agents connected")
    fleet_rows.append(
        f"[{snapshot.active_agent_count} active / {snapshot.idle_agent_count} idle / util={_fmt_number(snapshot.agent_utilization_percent)}%]"
    )
    for proc in snapshot.supervisor_processes[:4]:
        state = _color(color_enabled, "32", "UP") if proc.get("alive") else _color(color_enabled, "31;1", "DEAD")
        fleet_rows.append(f"{proc.get('name','-'):<14} pid={proc.get('pid','-'):<7} {state}")
    fleet_rows.append("-")
    for team_id, c in sorted(snapshot.team_lane_counts.items()):
        fleet_rows.append(f"{team_id:<12} {c.get('done',0)}/{c.get('total',0)} done  ip={c.get('in_progress',0)}")

    work_rows: List[str] = []
    if snapshot.in_progress:
        for t in snapshot.in_progress[:5]:
            age = _format_age(_age_s(t.get("updated_at")))
            work_rows.append(f"> {t.get('id','-')} {t.get('owner','-')} age={age}")
            work_rows.append(f"  {_truncate(t.get('title',''), panel_w - 6)}")
    else:
        work_rows.append("(no in-progress work)")
    if snapshot.assigned:
        work_rows.append("-")
        work_rows.append("queued:")
        for t in snapshot.assigned[:4]:
            work_rows.append(f"  {t.get('id','-')} {t.get('status','-')} {t.get('owner','-')}")
    work_rows.append("-")
    work_rows.append(f"Failure Rate: {_fmt_number(snapshot.task_failure_rate_percent)}%  |  Stale IP: {snapshot.stale_in_progress}")

    if narrow:
        lines.extend(_panel_fixed("Fleet", fleet_rows, width, body_rows=mid_rows, color_enabled=color_enabled))
        lines.extend(_panel_fixed("Active Work", work_rows, width, body_rows=mid_rows, color_enabled=color_enabled))
    else:
        left2 = _panel_fixed("Fleet", fleet_rows, panel_w, body_rows=mid_rows, color_enabled=color_enabled)
        right2 = _panel_fixed("Active Work", work_rows, panel_w, body_rows=mid_rows, color_enabled=color_enabled)
        lines.extend(_merge_columns(left2, right2, width))

    # ── Full-width: Alerts & Actions ──
    alert_rows: List[str] = []
    for action in snapshot.next_actions[:6]:
        alert_rows.append(f">> {action}")
    if not alert_rows:
        alert_rows.append(">> No actions required.")
    lines.extend(_panel_fixed("Alerts & Actions", alert_rows, width, body_rows=bot_rows, color_enabled=color_enabled))

    lines.append(sep)
    lines.append("controls: Ctrl+C exit | style=claude-v3a")
    return "\n".join(lines)


def _render_claude(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool, color_enabled: bool = True) -> str:
    width = max(100, _term_width())
    sep = "=" * width
    lines: List[str] = []
    now = _now_utc().strftime("%Y-%m-%d %H:%M:%SZ")
    mode = "COMPLETED" if completed else "RUNNING"
    mode_color = "32;1" if completed else "33;1"
    title = _color(color_enabled, "35;1", "AGENT LEADER // CLAUDE STYLE")
    lines.append(sep)
    lines.append(f"{title}  {_color(color_enabled, mode_color, mode)}  {now}")
    lines.append(f"Project: {_truncate(snapshot.project_root, width - 9)}")

    top_stats = [
        f"tasks:{snapshot.total_tasks}",
        f"open:{snapshot.open_tasks}",
        f"done:{snapshot.done_tasks}",
        f"in_progress:{len(snapshot.in_progress)}",
        f"queued:{len(snapshot.assigned)}",
        f"blockers:{snapshot.blockers_open}",
        f"bugs:{snapshot.bugs_open}",
    ]
    lines.append(" | ".join(top_stats))
    lines.append(f"progress {_progress_bar(snapshot.progress_percent, width=40)}")
    eta = f"{snapshot.eta_minutes}m" if snapshot.eta_minutes is not None else "-"
    lines.append(
        f"throughput done_last_hour={snapshot.done_last_hour} done_per_hour={_fmt_number(snapshot.throughput_per_hour)} eta={eta} "
        f"| loc +{snapshot.loc_added_total} -{snapshot.loc_deleted_total} net={snapshot.loc_net_total}"
    )
    lines.append(
        f"review pass={_fmt_number(snapshot.review_pass_rate)}% ({snapshot.validation_passed}/{snapshot.validation_passed + snapshot.validation_failed}) "
        f"| queue_pressure={_fmt_number(snapshot.queue_pressure)} | oldest_open_age={_format_age(snapshot.oldest_open_task_age_s)}"
    )
    if snapshot.token_total is None:
        lines.append("tokens total=- prompt=- completion=-")
    else:
        lines.append(
            f"tokens total={snapshot.token_total} prompt={snapshot.token_prompt_total or 0} completion={snapshot.token_completion_total or 0}"
        )
    lines.append(f"budget_calls_today={snapshot.budget_calls_today}")
    if snapshot.budget_by_process:
        lines.append("budget_by_proc: " + " | ".join(f"{k}:{v}" for k, v in sorted(snapshot.budget_by_process.items())[:6]))
    if auto_stopped:
        lines.append(_color(color_enabled, "32;1", "auto-stop engaged: supervisor stopped after completion"))
    lines.append(sep)

    panel_w = (width - 2) // 2
    team_rows = ["status_counts: " + ", ".join(f"{k}:{v}" for k, v in sorted(snapshot.status_counts.items()))]
    for team_id, c in sorted(snapshot.team_lane_counts.items()):
        team_rows.append(
            f"{team_id:<12} total={c.get('total',0):<3} open={c.get('open',0):<3} done={c.get('done',0):<3} ip={c.get('in_progress',0):<3} blocked={c.get('blocked',0):<3}"
        )
    if not snapshot.team_lane_counts:
        team_rows.append("no team lanes for current scope")

    agent_rows: List[str] = []
    for a in snapshot.active_agents[:8]:
        agent_rows.append(f"{a['agent']:<11} {a['status']:<8} age={_format_age(a['age_s']):>7}")
        lane_details = a.get("lane_details", [])
        if len(lane_details) > 1:
            for ld in lane_details:
                state = _color(color_enabled, "32", "UP") if ld.get("alive") else _color(color_enabled, "31;1", "DOWN")
                agent_rows.append(f"  {ld.get('lane_label', '-'):<9} {state} pid={ld.get('pid', '-')}")
    if not agent_rows:
        agent_rows = ["none"]
    for proc in snapshot.supervisor_processes[:8]:
        state = _color(color_enabled, "32", "up") if proc.get("alive") else _color(color_enabled, "31;1", "dead")
        agent_rows.append(f"{proc.get('name','-'):<14} pid={proc.get('pid','-'):<7} {state}")

    left_top = _panel_fixed("Team/Pipeline", team_rows, panel_w, body_rows=8, color_enabled=color_enabled)
    right_top = _panel_fixed("Agents/Processes", agent_rows, panel_w, body_rows=8, color_enabled=color_enabled)
    lines.extend(_merge_columns(left_top, right_top, width))

    queue_rows: List[str] = []
    if snapshot.in_progress:
        queue_rows.append("in-progress:")
        for t in snapshot.in_progress[:8]:
            queue_rows.append(f"{t.get('id','-')} {t.get('owner','-')} age={_format_age(_age_s(t.get('updated_at')))}")
            queue_rows.append("  " + str(t.get("title", "")))
    else:
        queue_rows.append("in-progress: none")
    if snapshot.assigned:
        queue_rows.append("queued:")
        for t in snapshot.assigned[:6]:
            queue_rows.append(f"{t.get('id','-')} {t.get('status','-')} {t.get('owner','-')}")
            queue_rows.append("  " + str(t.get("title", "")))

    review_rows: List[str] = []
    review_rows.append("review/validation:")
    if snapshot.review_events:
        for ev in snapshot.review_events[:6]:
            review_rows.append(f"{ev.get('type')} {ev.get('task_id') or '-'} by {ev.get('source')}")
    else:
        review_rows.append("none")
    review_rows.append("timeline:")
    for ev in snapshot.recent_events[:6]:
        review_rows.append(f"{ev.get('type')} {ev.get('task_id') or '-'} by {ev.get('source')}")
    if not snapshot.recent_events:
        review_rows.append("none")

    left_bottom = _panel_fixed("Work Queue", queue_rows, panel_w, body_rows=14, color_enabled=color_enabled)
    right_bottom = _panel_fixed("Reviews/Timeline", review_rows, panel_w, body_rows=14, color_enabled=color_enabled)
    lines.extend(_merge_columns(left_bottom, right_bottom, width))

    action_rows = snapshot.next_actions[:8] or ["none"]
    lines.extend(_panel_fixed("Next Actions", action_rows, width, body_rows=4, color_enabled=color_enabled))
    lines.append(sep)
    lines.append("controls: Ctrl+C exit | style=claude")
    return "\n".join(lines)


def _render_gemini(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool, color_enabled: bool = True) -> str:
    width = max(100, _term_width())
    sep = _color(color_enabled, "34;1", "=" * width)
    lines: List[str] = []
    now = _now_utc().strftime("%Y-%m-%d %H:%M:%SZ")
    mode = _color(color_enabled, "32;1" if completed else "33;1", "COMPLETED" if completed else "RUNNING")
    lines.append(sep)
    lines.append(_color(color_enabled, "34;1", f"AGENT LEADER // GEMINI STYLE // {now} // {mode}"))
    lines.append(f"project={snapshot.project_root}")
    lines.append(
        " | ".join(
            [
                f"tasks:{snapshot.total_tasks}",
                f"open:{snapshot.open_tasks}",
                f"done:{snapshot.done_tasks}",
                f"ip:{len(snapshot.in_progress)}",
                f"assigned:{len(snapshot.assigned)}",
                f"active_agents:{snapshot.active_agent_count}",
                f"idle_agents:{snapshot.idle_agent_count}",
            ]
        )
    )
    lines.append(
        " | ".join(
            [
                f"progress:{snapshot.progress_percent}%",
                f"queue_pressure:{_fmt_number(snapshot.queue_pressure)}",
                f"done/h:{_fmt_number(snapshot.throughput_per_hour)}",
                f"eta:{(str(snapshot.eta_minutes) + 'm') if snapshot.eta_minutes is not None else '-'}",
                f"oldest_open:{_format_age(snapshot.oldest_open_task_age_s)}",
                f"stale_ip:{snapshot.stale_in_progress}",
            ]
        )
    )
    lines.append(
        " | ".join(
            [
                f"loc:+{snapshot.loc_added_total}/-{snapshot.loc_deleted_total}/net{snapshot.loc_net_total}",
                f"reports:{snapshot.reports_count}",
                f"avg_loc/report:{_fmt_number(snapshot.avg_loc_per_report)}",
                f"avg_tokens/report:{_fmt_number(snapshot.avg_tokens_per_report)}",
                f"review_pass:{_fmt_number(snapshot.review_pass_rate)}%",
            ]
        )
    )
    lines.append(
        " | ".join(
            [
                f"token_total:{snapshot.token_total if snapshot.token_total is not None else '-'}",
                f"prompt:{snapshot.token_prompt_total if snapshot.token_prompt_total is not None else '-'}",
                f"completion:{snapshot.token_completion_total if snapshot.token_completion_total is not None else '-'}",
                f"budget_today:{snapshot.budget_calls_today}",
            ]
        )
    )
    lines.append(sep)

    panel_w = (width - 2) // 2
    left_rows: List[str] = ["team lanes:"]
    for team_id, c in sorted(snapshot.team_lane_counts.items()):
        left_rows.append(
            f"{team_id:<12} total={c.get('total',0):<3} open={c.get('open',0):<3} ip={c.get('in_progress',0):<3} done={c.get('done',0):<3} blocked={c.get('blocked',0):<3}"
        )
    if not snapshot.team_lane_counts:
        left_rows.append("none")
    left_rows.append("-")
    left_rows.append("status counts:")
    for k, v in sorted(snapshot.status_counts.items()):
        left_rows.append(f"{k:<14} {v}")
    left_rows.append("-")
    left_rows.append("agents:")
    for a in snapshot.active_agents[:8]:
        left_rows.append(f"{a['agent']:<11} {a['status']:<8} age={_format_age(a['age_s'])}")

    right_rows: List[str] = ["queue/in-progress:"]
    if snapshot.in_progress:
        for t in snapshot.in_progress[:6]:
            right_rows.append(f"{t.get('id','-')} | {t.get('owner','-')} | age={_format_age(_age_s(t.get('updated_at')))}")
            right_rows.append("  " + str(t.get("title", "")))
    else:
        right_rows.append("none")
    right_rows.append("-")
    right_rows.append("assigned/review:")
    for t in snapshot.assigned[:6]:
        right_rows.append(f"{t.get('id','-')} | {t.get('status','-')} | {t.get('owner','-')}")
        right_rows.append("  " + str(t.get("title", "")))
    right_rows.append("-")
    for ev in snapshot.recent_events[:6]:
        right_rows.append(f"{ev.get('type')} | {ev.get('task_id') or '-'} | {ev.get('source')}")

    left_panel = _panel_fixed("Fleet/Pipeline", left_rows, panel_w, body_rows=24, color_enabled=color_enabled)
    right_panel = _panel_fixed("Queue/Timeline", right_rows, panel_w, body_rows=24, color_enabled=color_enabled)
    lines.extend(_merge_columns(left_panel, right_panel, width))
    lines.extend(_panel_fixed("Actions", snapshot.next_actions[:6] or ["none"], width, body_rows=4, color_enabled=color_enabled))
    lines.append(sep)
    lines.append("controls: Ctrl+C exit | style=gemini")
    return "\n".join(lines)


def _ubar(pct, w=20):
    pct = max(0, min(100, int(pct)))
    fill = int(w * pct / 100)
    return "\u2588" * fill + "\u2591" * (w - fill)


def _box(title, rows, w, h, color_enabled=True):
    """Render a bordered box with title, fixed width and height."""
    c = lambda code, text: _color(color_enabled, code, text)
    inner = w - 2
    out = []
    out.append(c("34", "\u250c\u2500 ") + c("1", title) + c("34", " " + "\u2500" * max(0, inner - len(title) - 3) + "\u2510"))
    for i in range(h):
        content = rows[i] if i < len(rows) else ""
        # Strip ANSI for length calculation
        import re
        visible = re.sub(r"\x1b\[[0-9;]*m", "", content)
        pad = max(0, inner - len(visible))
        out.append(c("34", "\u2502") + content + " " * pad + c("34", "\u2502"))
    out.append(c("34", "\u2514" + "\u2500" * inner + "\u2518"))
    return out


def _merge_boxes(left_lines, right_lines):
    """Merge two box column lists side by side."""
    h = max(len(left_lines), len(right_lines))
    merged = []
    for i in range(h):
        l = left_lines[i] if i < len(left_lines) else ""
        r = right_lines[i] if i < len(right_lines) else ""
        merged.append(l + " " + r)
    return merged


def _render_gemini_v3b(snapshot, completed, auto_stopped, color_enabled=True):
    tw = min(160, max(80, _term_width()))
    th = max(30, _term_height())
    lines = []
    now = _now_utc().strftime("%H:%M:%S UTC")
    c = lambda code, text: _color(color_enabled, code, text)
    thick = c("34;1", "\u2550" * tw)
    bar = lambda p, w=20: "\u2588" * int(w * max(0, min(100, p)) / 100) + "\u2591" * (w - int(w * max(0, min(100, p)) / 100))

    if completed:
        st = c("32;1", "\u2714 ALL DONE")
    elif snapshot.in_progress:
        st = c("33;1", "\u25b6 WORKING")
    elif snapshot.blockers_open:
        st = c("31;1", "\u26a0 BLOCKED")
    elif snapshot.assigned:
        st = c("33", "\u23f3 QUEUED")
    else:
        st = c("36", "\u23f8 IDLE")

    # HEADER
    lines.append(thick)
    lines.append(c("1", f"  AGENT LEADER   {st}   {c('34', now)}"))
    lines.append(f"  {snapshot.project_name_display} | v{snapshot.version_current or '?'} {snapshot.version_name or ''}")
    lines.append(f"  Progress:   [{bar(snapshot.progress_percent, 30)}] {snapshot.progress_percent:>3}%  ({snapshot.done_tasks}/{snapshot.total_tasks} tasks)")
    if snapshot.milestones_total > 0:
        ms_pct = int((snapshot.milestones_done / snapshot.milestones_total) * 100)
        lines.append(f"  Milestones: [{bar(ms_pct, 30)}] {ms_pct:>3}%  ({snapshot.milestones_done}/{snapshot.milestones_total})")
    if snapshot.bugs_open or snapshot.blockers_open:
        lines.append(c("31;1", f"  \u26a0 {snapshot.blockers_open} blocker(s) | {snapshot.bugs_open} bug(s) open"))
    lines.append(thick)

    # Calculate panel dimensions
    half_w = tw // 2
    panel_h = max(6, (th - 14) // 3)  # divide remaining height into 3 rows of panels

    # ── ROW 1: LIVE STATUS + WORK QUEUE ──
    live_rows = []
    if snapshot.in_progress:
        for t in snapshot.in_progress[:panel_h - 1]:
            own = _agent_profile(str(t.get("owner", ""))).get("display_name", "?")
            age = _format_age(_age_s(t.get("updated_at")))
            title = _clean_task_title(t.get("title", "-"))
            live_rows.append(f" {c('32', '\u25cf')} {c('1', own):<14} {_truncate(title, half_w - 25)}")
            live_rows.append(f"   {age} ago  [{t.get('id','-')}]")
    elif snapshot.assigned:
        live_rows.append(f" {c('33', '\u25cb')} {len(snapshot.assigned)} task(s) queued")
    else:
        live_rows.append(f" {c('36', '\u25cb')} All work done. Swarm idle.")

    queue_rows = []
    queued = snapshot.queued_tasks or []
    blocked = snapshot.blocked_tasks or []
    if not queued and not blocked and not snapshot.in_progress:
        queue_rows.append(f" {c('32', '\u2714')} Empty \u2014 all complete")
    else:
        for t in queued[:panel_h - 1]:
            own = _agent_profile(str(t.get("owner", ""))).get("display_name", "?")
            title = _clean_task_title(t.get("title", "-"))
            queue_rows.append(f" {c('33', '\u25b7')} {own:<12} {_truncate(title, half_w - 22)}")
        for t in blocked[:2]:
            title = _clean_task_title(t.get("title", "-"))
            queue_rows.append(c("31", f" \u2716 BLOCKED {_truncate(title, half_w - 14)}"))

    p1 = _box("LIVE STATUS", live_rows, half_w, panel_h, color_enabled)
    p2 = _box("WORK QUEUE", queue_rows, half_w, panel_h, color_enabled)
    lines.extend(_merge_boxes(p1, p2))

    # ── ROW 2: TEAM ROSTER + VELOCITY ──
    stats_by = {r.get("display_name", ""): r for r in (snapshot.agent_delivery_stats or [])}
    team_rows = []
    for a in snapshot.active_agents[:12]:
        dn = a.get("display_name", a["agent"])
        inst = str(a.get("instance_id", "") or "")
        tag = inst[-4:] if len(inst) >= 4 else inst
        role = _compact_role_label(str(a.get("role_label", "-")))
        activity = str(a.get("task_activity", "idle"))
        hb = str(a.get("heartbeat_state", "?"))
        ps = a.get("process_state", "down")
        lane_details = a.get("lane_details", [])

        def _badge(act, pstate, hbeat):
            if act == "working":
                return c("32;1", "\u25cf WRK")
            if act == "queued":
                return c("33", "\u25d4 QUE")
            if pstate == "up" and hbeat == "active":
                return c("36", "\u25cb RDY")
            if hbeat in ("stale", "offline", "missing"):
                return c("31", "\u25cf OFF")
            return c("34", "\u25cb IDL")

        # If agent has multiple lanes, show each lane as a separate row
        if len(lane_details) > 1:
            s = stats_by.get(dn, {})
            td = s.get("tasks_done_session", 0)
            cm = s.get("commits_session", 0)
            lo = s.get("loc_net_session", 0)
            for ld in lane_details:
                lane_name = ld.get("lane_label", "?")
                lane_inst = str(ld.get("instance_id", "") or "")
                lane_tag = lane_inst[-4:] if len(lane_inst) >= 4 else lane_inst
                lane_alive = ld.get("alive", False)
                lane_badge = c("36", "\u25cb RDY") if lane_alive else c("31", "\u25cf OFF")
                label = f"{dn} #{lane_tag}"
                team_rows.append(f" {label:<18} {lane_name:<8} {lane_badge}  t={td} c={cm} L={lo}")
        else:
            label = f"{dn} #{tag}" if tag else dn
            badge = _badge(activity, ps, hb)
            s = stats_by.get(dn, {})
            td = s.get("tasks_done_session", 0)
            cm = s.get("commits_session", 0)
            lo = s.get("loc_net_session", 0)
            team_rows.append(f" {label:<18} {role:<8} {badge}  t={td} c={cm} L={lo}")

    tp = snapshot.throughput_per_hour or 0
    eta = snapshot.eta_minutes
    hrs = (snapshot.session_duration_s or 1) / 3600.0
    net_s = snapshot.loc_added_session - snapshot.loc_deleted_session
    loc_h = int(net_s / hrs) if hrs > 0.1 else 0
    com_h = round(snapshot.commits_session / hrs, 1) if hrs > 0.1 else 0
    vel_rows = [
        f" Tasks/hour:    {c('1', _fmt_number(tp))}",
        f" Commits/hour:  {c('1', str(com_h))}",
        f" Lines/hour:    {c('1', str(loc_h))}",
        f" Lead time:     {c('1', _format_age(snapshot.avg_task_lead_time_s))}",
        f" ETA:           {c('1', (str(eta) + ' min') if eta is not None else 'done')}",
        f" Failure rate:  {c('32' if (snapshot.task_failure_rate_percent or 0) < 10 else '31', _fmt_number(snapshot.task_failure_rate_percent))}%",
        f" Stale tasks:   {c('32' if (snapshot.stale_task_percent or 0) == 0 else '33', _fmt_number(snapshot.stale_task_percent))}%",
        f" Utilization:   {_fmt_number(snapshot.agent_utilization_percent)}%",
    ]

    p3 = _box("TEAM ROSTER", team_rows, half_w, panel_h, color_enabled)
    p4 = _box("VELOCITY & QUALITY", vel_rows, half_w, panel_h, color_enabled)
    lines.extend(_merge_boxes(p3, p4))

    # ── ROW 3: CODE OUTPUT + TIMELINE ──
    net_t = snapshot.loc_added_today - snapshot.loc_deleted_today
    out_rows = [
        f" {c('1', 'Today')}:    {snapshot.tasks_done_today} tasks  {snapshot.commits_today} commits  {c('32', '+' + str(snapshot.loc_added_today))}/{c('31', '-' + str(snapshot.loc_deleted_today))} ({net_t} net)",
        f" {c('1', 'Session')}:  {snapshot.tasks_done_session} tasks  {snapshot.commits_session} commits  {c('32', '+' + str(snapshot.loc_added_session))}/{c('31', '-' + str(snapshot.loc_deleted_session))} ({net_s} net)",
        f" {c('1', 'Total')}:    {snapshot.done_tasks} tasks  {snapshot.commits_total} commits  {snapshot.loc_net_total} net lines",
    ]
    budget_today = snapshot.budget_calls_today or 0
    blimit = 100
    if budget_today > 0 or snapshot.budget_by_process:
        bp = min(100, int(budget_today / blimit * 100)) if blimit > 0 else 0
        left = max(0, blimit - budget_today)
        out_rows.append("")
        out_rows.append(f" Budget: [{bar(bp, 15)}] {left} calls left")
        for k, v in sorted(snapshot.budget_by_process.items())[:3]:
            kp = min(100, int(v / blimit * 100)) if blimit > 0 else 0
            out_rows.append(f"   {k:<16} [{bar(kp, 10)}] {v}/{blimit}")

    time_rows = []
    for ev in snapshot.recent_events[:panel_h]:
        t = ev.get("time", "")[11:19]  # HH:MM:SS
        etype = str(ev.get("type", ""))
        src = ev.get("source", "")
        tid = ev.get("task_id") or ""
        sn = _agent_profile(src).get("display_name", src) if src else ""
        if "validation.passed" in etype:
            ico, desc = c("32", "\u2714"), f"{tid[:13]} passed"
        elif "validation.failed" in etype:
            ico, desc = c("31", "\u2716"), f"{tid[:13]} failed"
        elif "task.reported" in etype:
            ico, desc = c("33", "\u25b2"), f"{tid[:13]} by {sn}"
        elif "task.claimed" in etype:
            ico, desc = c("36", "\u25b6"), f"{sn} claimed {tid[:13]}"
        elif "idle_heartbeat" in etype:
            ico, desc = c("34", "\u25cb"), f"{sn} idle"
        elif "heartbeat" in etype:
            ico, desc = c("34", "\u00b7"), f"{sn}"
        elif "task_contracts" in etype:
            ico, desc = c("34", "\u25a0"), "assignments published"
        else:
            ico, desc = c("34", "\u00b7"), etype[:20]
        time_rows.append(f" {c('34', t)} {ico} {desc}")

    p5 = _box("CODE OUTPUT & BUDGET", out_rows, half_w, panel_h, color_enabled)
    p6 = _box("TIMELINE", time_rows, half_w, panel_h, color_enabled)
    lines.extend(_merge_boxes(p5, p6))

    lines.append(thick)
    lines.append(c("34", f"  Ctrl+C exit | 5s refresh | {snapshot.commits_total} commits | {snapshot.loc_net_total} lines | {snapshot.active_agent_count} agents"))
    return "\n".join(lines)


def _render(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool, style: str, color_enabled: bool = True) -> str:
    if style == "gemini":
        return _render_gemini(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)
    if style == "gemini-v3b":
        return _render_gemini_v3b(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)
    if style == "claude-v3a":
        return _render_claude_v3a(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)
    return _render_claude(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)


# ─── File-system state watcher ──────────────────────────────────────────────


class _StateWatcher:
    """Watch state directories for changes using the best available OS primitive.

    Backends (selected automatically):
    - kqueue: macOS/BSD — blocks on kernel event queue, near-zero idle CPU.
    - inotify: Linux — blocks on inotify fd via select().
    - poll: fallback — stat-based mtime polling at 1 s intervals.
    """

    def __init__(self, dirs: List[Path]):
        self._dirs = [d for d in dirs if d.is_dir()]
        self._backend = "poll"
        self._kq: Any = None
        self._fds: List[int] = []
        self._inotify_fd: Optional[int] = None
        self._poll_baseline: Dict[str, float] = self._stat_mtimes()
        self._init_backend()

    def _init_backend(self) -> None:
        # Try kqueue (macOS / BSD)
        try:
            import select as _sel

            if hasattr(_sel, "kqueue"):
                kq = _sel.kqueue()
                fds: List[int] = []
                changelist = []
                for d in self._dirs:
                    fd = os.open(str(d), os.O_RDONLY)
                    fds.append(fd)
                    changelist.append(
                        _sel.kevent(
                            fd,
                            filter=_sel.KQ_FILTER_VNODE,
                            flags=_sel.KQ_EV_ADD | _sel.KQ_EV_CLEAR,
                            fflags=_sel.KQ_NOTE_WRITE | _sel.KQ_NOTE_DELETE | _sel.KQ_NOTE_RENAME,
                        )
                    )
                if changelist:
                    kq.control(changelist, 0, 0)
                self._kq = kq
                self._fds = fds
                self._backend = "kqueue"
                return
        except Exception:
            pass

        # Try inotify (Linux)
        if sys.platform.startswith("linux"):
            try:
                import ctypes
                import ctypes.util

                libc_name = ctypes.util.find_library("c")
                if libc_name:
                    libc = ctypes.CDLL(libc_name, use_errno=True)
                    IN_MODIFY = 0x00000002
                    IN_CREATE = 0x00000100
                    IN_DELETE = 0x00000200
                    IN_MOVED_TO = 0x00000080
                    IN_NONBLOCK = 0x00000800
                    ifd = libc.inotify_init1(IN_NONBLOCK)
                    if ifd >= 0:
                        mask = IN_MODIFY | IN_CREATE | IN_DELETE | IN_MOVED_TO
                        for d in self._dirs:
                            libc.inotify_add_watch(ifd, str(d).encode("utf-8"), mask)
                        self._inotify_fd = ifd
                        self._backend = "inotify"
                        return
            except Exception:
                pass

    # -- public API -----------------------------------------------------------

    @property
    def backend(self) -> str:
        return self._backend

    def wait(self, timeout: float) -> bool:
        """Block until a state change is detected or *timeout* seconds elapse.

        Returns ``True`` when a change was detected, ``False`` on timeout.
        """
        if self._backend == "kqueue" and self._kq is not None:
            return self._wait_kqueue(timeout)
        if self._backend == "inotify" and self._inotify_fd is not None:
            return self._wait_inotify(timeout)
        return self._wait_poll(timeout)

    def close(self) -> None:
        if self._kq is not None:
            try:
                self._kq.close()
            except OSError:
                pass
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()
        if self._inotify_fd is not None:
            try:
                os.close(self._inotify_fd)
            except OSError:
                pass
            self._inotify_fd = None

    # -- backend implementations ----------------------------------------------

    def _wait_kqueue(self, timeout: float) -> bool:
        import select as _sel

        try:
            events = self._kq.control(None, max(1, len(self._fds)), timeout)
            return len(events) > 0
        except (OSError, InterruptedError):
            return True

    def _wait_inotify(self, timeout: float) -> bool:
        import select as _sel

        try:
            ready, _, _ = _sel.select([self._inotify_fd], [], [], timeout)
            if ready:
                try:
                    os.read(self._inotify_fd, 4096)  # type: ignore[arg-type]
                except OSError:
                    pass
                return True
            return False
        except (OSError, InterruptedError):
            return True

    def _wait_poll(self, timeout: float) -> bool:
        """Stat-based mtime polling at 1 s intervals."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(1.0, remaining))
            current = self._stat_mtimes()
            if current != self._poll_baseline:
                self._poll_baseline = current
                return True

    def _stat_mtimes(self) -> Dict[str, float]:
        mtimes: Dict[str, float] = {}
        for d in self._dirs:
            try:
                for child in d.iterdir():
                    if child.name.startswith("."):
                        continue
                    try:
                        mtimes[str(child)] = child.stat().st_mtime
                    except OSError:
                        pass
            except OSError:
                pass
        return mtimes


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Headless live TUI dashboard")
    p.add_argument("--project-root", required=True)
    p.add_argument("--refresh-seconds", type=float, default=5.0)
    p.add_argument("--auto-stop-on-complete", action="store_true")
    p.add_argument("--complete-streak", type=int, default=3)
    p.add_argument("--stale-seconds", type=int, default=1800)
    p.add_argument("--style", choices=["claude", "claude-v3a", "gemini", "gemini-v3b"], default="gemini-v3b")
    p.add_argument("--full-clear", action="store_true", help="Use full screen clear each refresh (default is static top-style redraw)")
    args = p.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    project_root = str(Path(args.project_root).resolve())

    # Set up OS-native file watcher on state directories.
    watch_dirs = [root / "state", root / "bus", root / ".autopilot-pids"]
    watcher = _StateWatcher(watch_dirs)

    completed = False
    auto_stopped = False
    complete_streak = 0
    last_lines = 0
    last_render_hash = ""
    _FORCE_REFRESH_S = 30.0
    last_refresh_at = 0.0

    stop = False

    def _handle_sig(_sig, _frm):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    first_pass = True
    while not stop:
        # Wait for file-system change or timeout (skipped on first iteration).
        if not first_pass:
            changed = watcher.wait(timeout=max(0.5, args.refresh_seconds))
            if not changed and (time.monotonic() - last_refresh_at) < _FORCE_REFRESH_S:
                continue  # No state change and forced refresh not yet due.
        first_pass = False

        snap = build_snapshot(project_root, root, stale_seconds=max(1, args.stale_seconds))
        # Completion requires: no open tasks, no open blockers,
        # no in-progress milestones, and no live supervisor processes.
        has_open_blockers = snap.blockers_open > 0
        has_pending_milestones = snap.milestones_total > 0 and snap.milestones_done < snap.milestones_total
        has_live_supervisor = any(p.get("alive") for p in snap.supervisor_processes)
        truly_complete = (
            snap.open_tasks == 0
            and not has_open_blockers
            and not has_pending_milestones
            and not has_live_supervisor
        )
        if truly_complete:
            complete_streak += 1
        else:
            complete_streak = 0

        if complete_streak >= max(1, args.complete_streak):
            completed = True
            if args.auto_stop_on_complete and not auto_stopped and _is_supervisor_running(root):
                _stop_supervisor(project_root, root)
                auto_stopped = True

        out = _render(snap, completed=completed, auto_stopped=auto_stopped, style=args.style)

        # Hash-based re-render: skip screen write when output is unchanged.
        render_hash = hashlib.md5(out.encode("utf-8")).hexdigest()
        if render_hash == last_render_hash:
            continue
        last_render_hash = render_hash
        last_refresh_at = time.monotonic()

        out_lines = out.splitlines()
        term_cols = min(180, max(72, _term_width()))
        term_rows = max(10, _term_height())
        # Truncate lines to terminal width to prevent wrapping artifacts.
        out_lines = [line[:term_cols] for line in out_lines]
        if len(out_lines) > term_rows:
            out_lines = out_lines[:term_rows]
        elif len(out_lines) < term_rows:
            out_lines = out_lines + ([""] * (term_rows - len(out_lines)))
        # Clear screen and redraw — handles resize cleanly.
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write("\n".join(out_lines) + "\n")
        last_lines = len(out_lines)
        sys.stdout.flush()

    watcher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
