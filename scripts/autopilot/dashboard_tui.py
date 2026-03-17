#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OPEN_STATUSES = {"assigned", "in_progress", "reported", "needs_review", "blocked", "bug_open"}
ACTIVE_STATUSES = {"assigned", "in_progress", "reported", "bug_open"}


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
    stale_in_progress = sum(1 for t in in_progress if (_age_s(t.get("updated_at")) or 0) >= max(1, stale_seconds))

    blockers_open = sum(1 for b in blockers if str(b.get("status", "")).lower() == "open")
    bugs_open = sum(1 for b in bugs if str(b.get("status", "")).lower() == "open")

    active_agents: List[Dict[str, Any]] = []
    if isinstance(agents_map, dict):
        for agent, entry in agents_map.items():
            active_agents.append(
                {
                    "agent": agent,
                    "status": str(entry.get("status", "unknown")),
                    "age_s": _age_s(entry.get("last_seen")),
                    "instance_id": (entry.get("metadata") or {}).get("instance_id", "-") if isinstance(entry.get("metadata"), dict) else "-",
                }
            )
    active_agents.sort(key=lambda a: (a["status"] != "active", a["agent"]))

    review_events: List[Dict[str, Any]] = []
    recent_events = _read_recent_events(root, limit=12)
    for ev in recent_events:
        et = str(ev.get("type", ""))
        if et in {"validation.passed", "validation.failed", "task.reported"}:
            review_events.append({"time": ev.get("time", ""), "type": et, "source": ev.get("source", ""), "task_id": ev.get("task_id", "")})
        if len(review_events) >= 8:
            break

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

    done_last_hour = sum(1 for t in scoped if str(t.get("status", "")).strip().lower() == "done" and (_age_s(t.get("updated_at")) or 999999) <= 3600)
    throughput_per_hour: Optional[float] = float(done_last_hour) if done_last_hour > 0 else None
    eta_minutes: Optional[int] = None
    if open_tasks > 0 and throughput_per_hour and throughput_per_hour > 0:
        eta_minutes = int((open_tasks / throughput_per_hour) * 60)

    supervisor_processes = _read_supervisor_processes(root)
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


def _render(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool, color_enabled: bool = True) -> str:
    width = max(100, _term_width())
    sep = "=" * width
    lines: List[str] = []
    now = _now_utc().strftime("%Y-%m-%d %H:%M:%SZ")
    mode = "COMPLETED" if completed else "RUNNING"
    mode_color = "32;1" if completed else "33;1"
    title = _color(color_enabled, "35;1", "AGENT LEADER // BTOP STYLE DASHBOARD")
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
    lines.append("controls: Ctrl+C exit | this is btop-inspired (layout/theme), adapted for agent-leader ops")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Headless live TUI dashboard")
    p.add_argument("--project-root", required=True)
    p.add_argument("--refresh-seconds", type=float, default=2.0)
    p.add_argument("--auto-stop-on-complete", action="store_true")
    p.add_argument("--complete-streak", type=int, default=3)
    p.add_argument("--stale-seconds", type=int, default=1800)
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

        out = _render(snap, completed=completed, auto_stopped=auto_stopped)
        out_lines = out.splitlines()
        if args.full_clear:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.write(out + "\n")
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
