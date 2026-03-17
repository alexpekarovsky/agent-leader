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
from typing import Any, Dict, Iterable, List, Optional, Tuple

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


def build_snapshot(project_root: str, root: Path) -> DashboardSnapshot:
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

    events_tail = _tail_lines(root / "bus" / "events.jsonl", 400)
    review_events: List[Dict[str, Any]] = []
    for line in reversed(events_tail):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        et = str(ev.get("type", ""))
        if et in {"validation.passed", "validation.failed", "task.reported"}:
            review_events.append(
                {
                    "time": ev.get("timestamp", ""),
                    "type": et,
                    "source": ev.get("source", ""),
                    "task_id": (ev.get("payload") or {}).get("task_id", ""),
                }
            )
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


def _render(snapshot: DashboardSnapshot, completed: bool, auto_stopped: bool) -> str:
    width = _term_width()
    sep = "=" * max(80, width)
    lines: List[str] = []
    now = _now_utc().strftime("%Y-%m-%d %H:%M:%SZ")
    mode = "COMPLETED (100%)" if completed else "RUNNING"
    lines.append(sep)
    lines.append(f"Agent Leader Headless TUI | {mode} | {now}")
    lines.append(f"Project: {snapshot.project_root}")
    lines.append(
        f"Progress: {snapshot.progress_percent}% | Total={snapshot.total_tasks} Open={snapshot.open_tasks} Done={snapshot.done_tasks} "
        f"| Blockers(open)={snapshot.blockers_open} Bugs(open)={snapshot.bugs_open}"
    )
    lines.append(
        f"Code Output: reports={snapshot.reports_count} LOC +{snapshot.loc_added_total} -{snapshot.loc_deleted_total} net={snapshot.loc_net_total}"
    )
    token_line = "Token Usage: n/a (report token fields not present)"
    if snapshot.token_total is not None:
        token_line = (
            f"Token Usage: total={snapshot.token_total} "
            f"prompt={snapshot.token_prompt_total or 0} completion={snapshot.token_completion_total or 0}"
        )
    lines.append(token_line)
    lines.append(f"Headless Call Budget (today): {snapshot.budget_calls_today}")
    if snapshot.budget_by_process:
        budget_parts = [f"{k}={v}" for k, v in sorted(snapshot.budget_by_process.items())[:8]]
        lines.append("  " + " | ".join(budget_parts))
    if auto_stopped:
        lines.append("Supervisor: auto-stopped after completion to prevent token leakage")

    lines.append("-")
    lines.append("Status Counts: " + ", ".join(f"{k}:{v}" for k, v in sorted(snapshot.status_counts.items())))

    lines.append("-")
    lines.append("Active Agents")
    for a in snapshot.active_agents[:8]:
        lines.append(f"  {a['agent']:<12} {a['status']:<8} age={_format_age(a['age_s']):>7} instance={a['instance_id']}")

    lines.append("-")
    lines.append("In Progress Tasks")
    if snapshot.in_progress:
        for t in snapshot.in_progress[:10]:
            lines.append(
                f"  {t.get('id','-')} | {t.get('owner','-')} | {t.get('title','')[:80]}"
            )
    else:
        lines.append("  none")

    lines.append("-")
    lines.append("Queued Tasks")
    if snapshot.assigned:
        for t in snapshot.assigned[:10]:
            lines.append(
                f"  {t.get('id','-')} | {t.get('status','-'):>9} | {t.get('owner','-')} | {t.get('title','')[:70]}"
            )
    else:
        lines.append("  none")

    lines.append("-")
    lines.append("Recent Review / Validation Events")
    if snapshot.review_events:
        for ev in snapshot.review_events:
            lines.append(f"  {ev.get('type')} | {ev.get('task_id')} | {ev.get('source')}")
    else:
        lines.append("  none")

    lines.append(sep)
    lines.append("Controls: Ctrl+C to exit dashboard")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Headless live TUI dashboard")
    p.add_argument("--project-root", required=True)
    p.add_argument("--refresh-seconds", type=float, default=2.0)
    p.add_argument("--auto-stop-on-complete", action="store_true")
    p.add_argument("--complete-streak", type=int, default=3)
    args = p.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    project_root = str(Path(args.project_root).resolve())

    completed = False
    auto_stopped = False
    complete_streak = 0

    stop = False

    def _handle_sig(_sig, _frm):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    while not stop:
        snap = build_snapshot(project_root, root)
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
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write(out + "\n")
        sys.stdout.flush()

        time.sleep(max(0.5, args.refresh_seconds))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
