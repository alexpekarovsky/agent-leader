from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configurable multi-agent orchestrator")
    parser.add_argument("--policy", default="config/policy.codex-manager.json", help="Path to policy JSON")
    parser.add_argument("--root", default=".", help="Workspace root")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap", help="Initialize state and bus artifacts")

    create_task = sub.add_parser("create-task", help="Create and assign a task")
    create_task.add_argument("--title", required=True)
    create_task.add_argument("--workstream", required=True, choices=["backend", "frontend", "qa", "devops", "default"])
    create_task.add_argument("--description", default="")
    create_task.add_argument("--accept", action="append", default=[], help="Acceptance criteria (repeatable)")
    create_task.add_argument("--owner", default=None)

    sub.add_parser("list-tasks", help="List tasks")

    report = sub.add_parser("ingest-report", help="Ingest agent report JSON")
    report.add_argument("--file", required=True, help="Path to report JSON")

    validate = sub.add_parser("validate", help="Record validation result")
    validate.add_argument("--task-id", required=True)
    validate.add_argument("--pass", action="store_true", dest="passed")
    validate.add_argument("--fail", action="store_false", dest="passed")
    validate.set_defaults(passed=None)
    validate.add_argument("--notes", required=True)

    decision = sub.add_parser("decide-architecture", help="Record architecture consensus vote")
    decision.add_argument("--topic", required=True)
    decision.add_argument("--options", action="append", required=True, help="Option string (repeatable)")
    decision.add_argument("--votes", required=True, help='JSON object: {"codex":"optionA", ...}')
    decision.add_argument("--rationale", default="{}", help='JSON object: {"codex":"...", ...}')

    return parser


def _load_orchestrator(policy_path: str, root: str) -> Orchestrator:
    policy = Policy.load(Path(policy_path))
    return Orchestrator(root=Path(root), policy=policy)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    orch = _load_orchestrator(args.policy, args.root)

    if args.command == "bootstrap":
        orch.bootstrap()
        print(f"Bootstrapped with policy '{orch.policy.name}' and manager '{orch.policy.manager()}'")
        return

    if args.command == "create-task":
        accept: List[str] = args.accept or ["Tests pass", "Acceptance criteria satisfied"]
        task = orch.create_task(
            title=args.title,
            workstream=args.workstream,
            acceptance_criteria=accept,
            description=args.description,
            owner=args.owner,
        )
        print(json.dumps(task, indent=2))
        return

    if args.command == "list-tasks":
        print(json.dumps(orch.list_tasks(), indent=2))
        return

    if args.command == "ingest-report":
        with Path(args.file).open("r", encoding="utf-8") as fh:
            report = json.load(fh)
        print(json.dumps(orch.ingest_report(report), indent=2))
        return

    if args.command == "validate":
        if args.passed is None:
            raise SystemExit("Specify exactly one of --pass or --fail")
        result = orch.validate_task(task_id=args.task_id, passed=args.passed, notes=args.notes)
        print(json.dumps(result, indent=2))
        return

    if args.command == "decide-architecture":
        votes: Dict[str, str] = json.loads(args.votes)
        rationale: Dict[str, str] = json.loads(args.rationale)
        path = orch.record_architecture_decision(
            topic=args.topic,
            options=args.options,
            votes=votes,
            rationale=rationale,
        )
        print(str(path))
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
