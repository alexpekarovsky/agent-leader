#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy

SUPERVISOR = REPO_ROOT / "scripts" / "autopilot" / "supervisor.sh"
DASHBOARD = REPO_ROOT / "scripts" / "autopilot" / "dashboard_tui.py"


def _run(cmd: List[str]) -> int:
    return subprocess.run(cmd, check=False).returncode


def _seed_tasks(
    project_root: str,
    feature: str,
    task_titles: List[str],
    team_id: str,
    workstream: str,
) -> List[str]:
    orch = Orchestrator(root=REPO_ROOT, policy=Policy.load(REPO_ROOT / "config" / "policy.codex-manager.json"))
    orch.bootstrap()
    created: List[str] = []
    for title in task_titles:
        t = orch.create_task(
            title=f"[{feature}] {title}",
            workstream=workstream,
            acceptance_criteria=["Implemented", "Tested", "Reviewed"],
            description=f"Feature: {feature}",
            project_root=project_root,
            project_name=Path(project_root).name,
            team_id=team_id,
            tags=["tui-run", f"feature:{feature}"]
        )
        created.append(str(t.get("id")))

    orch.publish_event(
        event_type="manager.announcement",
        source="codex",
        payload={
            "message": "TUI run started. Team consultation requested.",
            "feature": feature,
            "task_ids": created,
        },
        audience=["claude_code", "gemini", "codex"],
    )
    orch.publish_event(
        event_type="manager.execution_plan",
        source="codex",
        payload={
            "message": "Consultation + execution: process these tasks under low-burn headless mode.",
            "feature": feature,
            "task_ids": created,
        },
        audience=["claude_code", "gemini"],
    )
    return created


def main() -> int:
    p = argparse.ArgumentParser(description="Run headless team with live TUI dashboard")
    p.add_argument("--project-root", default=str(REPO_ROOT))
    p.add_argument("--feature", required=True)
    p.add_argument("--task", action="append", default=[])
    p.add_argument("--team-id", default="team-parity")
    p.add_argument("--workstream", default="backend")
    p.add_argument("--leader-agent", default="claude_code")
    p.add_argument("--seed", action="store_true", help="Create tasks from --task entries before startup")
    p.add_argument("--refresh-seconds", type=float, default=2.0)
    p.add_argument("--daily-call-budget", type=int, default=120)
    p.add_argument("--max-idle-cycles", type=int, default=30)
    args = p.parse_args()

    project_root = str(Path(args.project_root).resolve())

    if args.seed:
        if not args.task:
            print("--seed requires at least one --task", file=sys.stderr)
            return 2
        created = _seed_tasks(project_root, args.feature, args.task, args.team_id, args.workstream)
        print("Seeded tasks:", ", ".join(created))

    # Clean previous headless run state and start in low-burn mode.
    _run([str(SUPERVISOR), "stop", "--project-root", project_root])
    _run([str(SUPERVISOR), "clean", "--project-root", project_root])
    rc = _run([
        str(SUPERVISOR), "start",
        "--project-root", project_root,
        "--leader-agent", args.leader_agent,
        "--daily-call-budget", str(args.daily_call_budget),
        "--max-idle-cycles", str(args.max_idle_cycles),
        "--event-driven",
        "--low-burn",
    ])
    if rc != 0:
        return rc

    # Foreground TUI; auto-stop supervisor once tasks are complete.
    return _run([
        str(DASHBOARD),
        "--project-root", project_root,
        "--refresh-seconds", str(args.refresh_seconds),
        "--auto-stop-on-complete",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
