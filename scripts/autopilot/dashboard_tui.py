#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
                    meta["active_milestones"] = [
                        _clean_task_title(m.get("title") or m.get("id"))
                        for m in milestones
                        if isinstance(m, dict) and str(m.get("status", "")).strip() == "in_progress"
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
        for idx, line in enumerate(lines):
            if re.match(r"^\s*-\s+id:\s+", line):
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
                if title and status == "in_progress":
                    active.append(_clean_task_title(title))
        meta["active_milestones"] = active
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
            }
        )
    return rows


def _compute_next_actions(
    open_tasks: int,
    assigned_count: int,
    in_progress_count: int,
    blockers_open: int,
    bugs_open: int,
    stale_in_progress: int,
    supervisor_processes: List[Dict[str, Any]],
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
    stale_in_progress = sum(
        1 for t in in_progress
        if (lambda a: a is not None and a >= max(1, stale_seconds))(_age_s(t.get("updated_at")))
    )
    open_ages = [_age_s(t.get("updated_at")) for t in scoped if str(t.get("status", "")).strip().lower() in OPEN_STATUSES]
    open_ages = [a for a in open_ages if isinstance(a, int)]
    oldest_open_task_age_s = max(open_ages) if open_ages else None

    blockers_open = sum(1 for b in blockers if str(b.get("status", "")).lower() == "open")
    bugs_open = sum(1 for b in bugs if str(b.get("status", "")).lower() == "open")

    active_agents: List[Dict[str, Any]] = []
    if isinstance(agents_map, dict):
        for agent, entry in agents_map.items():
            metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            profile = _agent_profile(agent, metadata)
            active_agents.append(
                {
                    "agent": agent,
                    "status": str(entry.get("status", "unknown")),
                    "age_s": _age_s(entry.get("last_seen")),
                    "instance_id": metadata.get("instance_id", "-"),
                    "client": profile["type_label"],
                    "model": profile["model_label"],
                    "display_name": profile["display_name"],
                    "role_label": profile["role_label"],
                    "provider": profile["provider"],
                }
            )
    active_agents.sort(
        key=lambda a: (
            a["status"] != "active",
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
            if isinstance(cm, dict):
                la = cm.get("lines_added")
                ld = cm.get("lines_deleted")
                if isinstance(la, int):
                    loc_added_total += la
                if isinstance(ld, int):
                    loc_deleted_total += ld
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

    supervisor_processes = _read_supervisor_processes(root)
    active_agent_count = sum(1 for a in active_agents if str(a.get("status", "")).lower() == "active")
    idle_agent_count = max(0, active_agent_count - len(in_progress))
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
    active_agent_count = sum(1 for a in active_agents if str(a.get("status", "")).lower() == "active")
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
        validation_total += 1
        src = str(ev.get("source", "")).strip() or "unknown"
        validation_by_source[src] = validation_by_source.get(src, 0) + 1

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


def _render_gemini_v3b(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool, color_enabled: bool = True) -> str:
    width = max(72, _term_width())
    height = max(24, _term_height())
    sep = _color(color_enabled, "34;1", "=" * width)
    lines: List[str] = []
    now = _now_utc().strftime("%Y-%m-%d %H:%M:%SZ")
    mode = _color(color_enabled, "32;1" if completed else "33;1", "COMPLETED" if completed else "RUNNING")
    
    # Header
    lines.append(sep)
    lines.append(_color(color_enabled, "34;1", f"AGENT LEADER // GEMINI V3B DENSE TELEMETRY // {now} // {mode}"))
    project_line = f"Project: {snapshot.project_name_display} ({Path(snapshot.project_root).name})"
    if snapshot.version_current or snapshot.version_name:
        project_line += f" | Version: {snapshot.version_current or '-'} - {snapshot.version_name or '-'}"
    lines.append(_truncate(project_line, width))
    if snapshot.active_milestones:
        lines.append(_truncate("Version focus: " + " | ".join((snapshot.active_milestones or [])[:3]), width))
    else:
        lines.append(_truncate(f"Project root: {snapshot.project_root}", width))
    
    # Quick Stats Row
    stats = [
        f"Tasks: {snapshot.done_tasks}/{snapshot.total_tasks} ({snapshot.progress_percent}%)",
        f"Active: {snapshot.active_agent_count} (div:{snapshot.agent_diversity})",
        f"IP/Assigned: {len(snapshot.in_progress)}/{len(snapshot.assigned)}",
        f"Bugs: {snapshot.bugs_open}",
        f"Blockers: {snapshot.blockers_open}",
        f"Claude/h: {_fmt_number(snapshot.claude_throughput_per_hour)}",
    ]
    lines.append("  |  ".join(stats))
    # Human-readable state summary to reduce operator confusion.
    now_rows: List[str] = []
    if snapshot.in_progress:
        t = snapshot.in_progress[0]
        owner_profile = _agent_profile(str(t.get("owner", "")))
        now_rows.append(
            f"STATE: WORKING | {owner_profile['display_name']} | {owner_profile['role_label']} | task={t.get('id','-')} | age={_format_age(_age_s(t.get('updated_at')))}"
        )
        now_rows.append(f"NOW: {_truncate(_clean_task_title(t.get('title','-')), max(20, width - 10))}")
        now_rows.append(f"GOAL: {_truncate(_clean_task_description(t.get('description','-')), max(20, width - 11))}")
    elif snapshot.blockers_open > 0:
        now_rows.append(f"STATE: BLOCKED | blockers_open={snapshot.blockers_open} | bugs_open={snapshot.bugs_open}")
        now_rows.append("NOW: waiting for blocker resolution before new execution can continue")
    elif snapshot.assigned:
        t = snapshot.assigned[0]
        now_rows.append(f"STATE: QUEUED | next_owner={t.get('owner','-')} | next_task={t.get('id','-')}")
        now_rows.append(f"NOW: {_truncate(t.get('title','-'), max(20, width - 10))}")
    else:
        now_rows.append("STATE: IDLE | no open work in current project scope")
        now_rows.append("NOW: waiting for manager assignment")
    if snapshot.recent_events:
        ev = snapshot.recent_events[0]
        now_rows.append(f"LATEST EVENT: {ev.get('type','-')} | source={ev.get('source','-')} | task={ev.get('task_id') or '-'}")
    if snapshot.next_actions:
        now_rows.append(f"NEXT ACTION: {snapshot.next_actions[0]}")
    lines.extend(_panel_fixed("NOW (Operator Summary)", now_rows, width, body_rows=5, color_enabled=color_enabled))
    lines.append(sep)

    three_col = width >= 165
    two_col = 120 <= width < 165
    panel_w = (width - 2) // 3 if three_col else (width - 2) // 2
    fixed_lines = 7
    remaining = max(12, height - fixed_lines)
    top_rows, bottom_rows, action_rows_n = _split_rows(remaining, [7, 6, 2], [3, 3, 1])
    
    # Panel 1: Velocity & Quality
    vel_rows = [
        f"Throughput: {_fmt_number(snapshot.throughput_per_hour)} done/h",
        f"ETA: {(str(snapshot.eta_minutes) + 'm') if snapshot.eta_minutes is not None else '-'}",
        f"Lead Time: {_format_age(snapshot.avg_task_lead_time_s)}",
        f"Validation: {_format_age(snapshot.avg_validation_cycle_time_s)}",
        f"Utilization: {_fmt_number(snapshot.agent_utilization_percent)}%",
        f"Queue Pressure: {_fmt_number(snapshot.queue_pressure)}",
        "-",
        f"Total Validations: {snapshot.total_validations}",
        f"Failure Rate: {_fmt_number(snapshot.task_failure_rate_percent)}%",
        f"Review Depth: {_fmt_number(snapshot.avg_review_loop_depth)}x",
        f"Stale Tasks: {_fmt_number(snapshot.stale_task_percent)}%",
        f"Blocker Res: {_format_age(snapshot.avg_blocker_resolution_time_s)}",
    ]
    
    # Panel 2: Team Topology
    fleet_rows = ["Operator Topology:"]
    for a in snapshot.active_agents[:10]:
        fleet_rows.append(
            f"{a.get('display_name', a['agent'])} ({a['agent']}) | {a.get('role_label','-')} | "
            f"{a.get('provider','-')} {a.get('client','-')} | model:{a.get('model','-')} | "
            f"{a['status']} age={_format_age(a['age_s'])}"
        )
    fleet_rows.append("-")
    fleet_rows.append("Team Lanes:")
    for tid, c in sorted(snapshot.team_lane_counts.items()):
        fleet_rows.append(f"{tid:<12} {c.get('done',0)}/{c.get('total',0)} done (ip={c.get('in_progress',0)})")
    fleet_rows.append("-")
    fleet_rows.append("Claude-only signals:")
    fleet_rows.append(f"claude validation share: {_fmt_number(snapshot.claude_validation_contribution_percent)}%")
    fleet_rows.append(f"wingman validation share: {_fmt_number(snapshot.wingman_validation_contribution_percent)}%")
    fleet_rows.append(
        f"claude last event: {snapshot.claude_latest_lane_event_type or '-'} age={_format_age(_age_s(snapshot.claude_latest_lane_event_time.isoformat() if snapshot.claude_latest_lane_event_time else None))}"
    )
    fleet_rows.append(
        f"wingman last event: {snapshot.wingman_latest_lane_event_type or '-'} age={_format_age(_age_s(snapshot.wingman_latest_lane_event_time.isoformat() if snapshot.wingman_latest_lane_event_time else None))}"
    )
    
    # Panel 3: Costs & Systems
    cost_rows = [
        f"Total Tokens: {snapshot.token_total or '-'}",
        f"Avg Tokens/Task: {_fmt_number(snapshot.avg_tokens_per_report)}",
        f"LOC net: {snapshot.loc_net_total} (+{snapshot.loc_added_total}/-{snapshot.loc_deleted_total})",
        f"Efficiency: {_fmt_number(snapshot.cost_efficiency_loc_per_k_tokens)} loc/k-tok",
        f"Claude throughput: {_fmt_number(snapshot.claude_throughput_per_hour)}/h",
        f"Wingman throughput: {_fmt_number(snapshot.wingman_throughput_per_hour)}/h",
        "-",
        "Processes:",
    ]
    for proc in snapshot.supervisor_processes[:5]:
        state = _color(color_enabled, "32", "up") if proc.get("alive") else _color(color_enabled, "31;1", "dead")
        cost_rows.append(f"{proc.get('name','-'):<14} {state} age={_format_age(proc.get('age_s'))}")
    cost_rows.append("-")
    cost_rows.append(f"Budget Today: {snapshot.budget_calls_today} calls")
    for k, v in sorted(snapshot.budget_by_process.items())[:3]:
        cost_rows.append(f"  {k:<12} {v}")

    # Render top panels (responsive)
    p1 = _panel_fixed("Velocity & Quality", vel_rows, panel_w, body_rows=top_rows, color_enabled=color_enabled)
    p2 = _panel_fixed("Team Topology", fleet_rows, panel_w, body_rows=top_rows, color_enabled=color_enabled)
    p3 = _panel_fixed("Costs & Systems", cost_rows, panel_w, body_rows=top_rows, color_enabled=color_enabled)

    if three_col:
        h = max(len(p1), len(p2), len(p3))
        for i in range(h):
            l1 = p1[i] if i < len(p1) else " " * panel_w
            l2 = p2[i] if i < len(p2) else " " * panel_w
            l3 = p3[i] if i < len(p3) else " " * panel_w
            lines.append(l1 + " " + l2 + " " + l3)
    elif two_col:
        lines.extend(_merge_columns(p1, p2, width))
        lines.extend(_panel_fixed("Costs & Systems", cost_rows, width, body_rows=max(3, top_rows // 2), color_enabled=color_enabled))
    else:
        lines.extend(_panel_fixed("Velocity & Quality", vel_rows, width, body_rows=top_rows, color_enabled=color_enabled))
        lines.extend(_panel_fixed("Team Topology", fleet_rows, width, body_rows=top_rows, color_enabled=color_enabled))
        lines.extend(_panel_fixed("Costs & Systems", cost_rows, width, body_rows=max(3, top_rows // 2), color_enabled=color_enabled))

    lines.append(sep)

    # Bottom Panels: Queue and Timeline (2 columns)
    bot_w = (width - 2) // 2
    queue_rows = ["In-Progress:"]
    for t in snapshot.in_progress[:5]:
        owner_profile = _agent_profile(str(t.get("owner", "")))
        queue_rows.append(
            f"{owner_profile['display_name']} | {owner_profile['role_label']} | {t.get('id','-')} | age={_format_age(_age_s(t.get('updated_at')))}"
        )
        queue_rows.append("  " + _truncate(_clean_task_title(t.get("title", "")), bot_w - 4))
        queue_rows.append("  " + _truncate(_clean_task_description(t.get("description", "")), bot_w - 4))
    queue_rows.append("-")
    queue_rows.append("Recently Assigned/Blocked:")
    for t in snapshot.assigned[:5]:
        owner_profile = _agent_profile(str(t.get("owner", "")))
        queue_rows.append(f"{owner_profile['display_name']} | {t.get('status','-')} | {t.get('id','-')}")
        queue_rows.append("  " + _truncate(_clean_task_title(t.get("title", "")), bot_w - 4))
    
    timeline_rows = ["Activity:"]
    for ev in snapshot.recent_events[:10]:
        timeline_rows.append(f"{ev.get('time')[11:16]} {ev.get('type'):<20} {ev.get('task_id') or '-':<10} {ev.get('source')}")

    if width >= 120:
        p_queue = _panel_fixed("Work Queue", queue_rows, bot_w, body_rows=bottom_rows, color_enabled=color_enabled)
        p_time = _panel_fixed("Timeline", timeline_rows, bot_w, body_rows=bottom_rows, color_enabled=color_enabled)
        lines.extend(_merge_columns(p_queue, p_time, width))
    else:
        lines.extend(_panel_fixed("Work Queue", queue_rows, width, body_rows=bottom_rows, color_enabled=color_enabled))
        lines.extend(_panel_fixed("Timeline", timeline_rows, width, body_rows=bottom_rows, color_enabled=color_enabled))

    lines.extend(_panel_fixed("Recommended Actions", snapshot.next_actions[:4] or ["none"], width, body_rows=action_rows_n, color_enabled=color_enabled))
    lines.append(sep)
    lines.append("controls: Ctrl+C exit | style=gemini-v3b")
    return "\n".join(lines)


def _render(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool, style: str, color_enabled: bool = True) -> str:
    if style == "gemini":
        return _render_gemini(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)
    if style == "gemini-v3b":
        return _render_gemini_v3b(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)
    if style == "claude-v3a":
        return _render_claude_v3a(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)
    return _render_claude(snapshot, completed=completed, auto_stopped=auto_stopped, color_enabled=color_enabled)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Headless live TUI dashboard")
    p.add_argument("--project-root", required=True)
    p.add_argument("--refresh-seconds", type=float, default=2.0)
    p.add_argument("--auto-stop-on-complete", action="store_true")
    p.add_argument("--complete-streak", type=int, default=3)
    p.add_argument("--stale-seconds", type=int, default=1800)
    p.add_argument("--style", choices=["claude", "claude-v3a", "gemini", "gemini-v3b"], default="claude")
    p.add_argument("--full-clear", action="store_true", help="Use full screen clear each refresh (default is static top-style redraw)")
    args = p.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    project_root = str(Path(args.project_root).resolve())

    completed = False
    auto_stopped = False
    complete_streak = 0
    last_lines = 0

    stop = False

    def _handle_sig(_sig, _frm):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    while not stop:
        snap = build_snapshot(project_root, root, stale_seconds=max(1, args.stale_seconds))
        if snap.open_tasks == 0:
            complete_streak += 1
        else:
            complete_streak = 0

        if complete_streak >= max(1, args.complete_streak):
            completed = True
            if args.auto_stop_on_complete and not auto_stopped and _is_supervisor_running(root):
                _stop_supervisor(project_root, root)
                auto_stopped = True

        out = _render(snap, completed=completed, auto_stopped=auto_stopped, style=args.style)
        out_lines = out.splitlines()
        term_rows = max(10, _term_height())
        if len(out_lines) > term_rows:
            out_lines = out_lines[:term_rows]
        elif len(out_lines) < term_rows:
            out_lines = out_lines + ([""] * (term_rows - len(out_lines)))
        if args.full_clear:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.write("\n".join(out_lines) + "\n")
        else:
            # top-like static redraw: move cursor home and overwrite old content.
            sys.stdout.write("\x1b[H")
            sys.stdout.write("\n".join(out_lines) + "\n")
            if last_lines > len(out_lines):
                sys.stdout.write(("\n" * (last_lines - len(out_lines))))
        last_lines = len(out_lines)
        sys.stdout.flush()

        time.sleep(max(0.5, args.refresh_seconds))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
