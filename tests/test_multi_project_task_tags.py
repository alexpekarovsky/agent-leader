from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, allow_cross_project_agents: bool = True) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "qa": "codex", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "allow_cross_project_agents": allow_cross_project_agents,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _register_agent(orch: Orchestrator, agent: str, project_root: Path) -> None:
    orch.register_agent(
        agent,
        metadata={
            "client": agent,
            "model": agent,
            "cwd": str(project_root),
            "project_root": str(project_root),
            "project_name": project_root.name,
            "permissions_mode": "default",
            "sandbox_mode": "none",
            "session_id": f"{agent}-session",
            "connection_id": f"{agent}-conn",
            "server_version": "1.0.0",
            "verification_source": "test",
            "instance_id": f"{agent}#worker",
            "role": "team_member",
        },
    )
    orch.heartbeat(
        agent,
        metadata={
            "client": agent,
            "model": agent,
            "cwd": str(project_root),
            "project_root": str(project_root),
            "project_name": project_root.name,
            "permissions_mode": "default",
            "sandbox_mode": "none",
            "session_id": f"{agent}-session",
            "connection_id": f"{agent}-conn",
            "server_version": "1.0.0",
            "verification_source": "test",
            "instance_id": f"{agent}#worker",
            "role": "team_member",
        },
    )


class MultiProjectTaskTagTests(unittest.TestCase):
    def test_create_task_adds_project_and_workstream_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "policy.json"))
            orch.bootstrap()

            task = orch.create_task(
                title="Implement endpoint",
                workstream="backend",
                acceptance_criteria=["done"],
                tags=["api", "Project:my-api", "api"],
                project_name="my-api",
                project_root="/tmp/my-api",
            )

            tags = set(task.get("tags", []))
            self.assertIn("api", tags)
            self.assertIn("project:my-api", tags)
            self.assertIn("workstream:backend", tags)
            self.assertEqual("/tmp/my-api", task["project_root"])
            self.assertEqual("my-api", task["project_name"])

    def test_list_tasks_filters_by_project_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "policy.json"))
            orch.bootstrap()

            orch.create_task(
                title="A",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
                project_name="proj-a",
                project_root="/tmp/proj-a",
                tags=["service", "priority:p1"],
            )
            orch.create_task(
                title="B",
                workstream="frontend",
                acceptance_criteria=["done"],
                owner="gemini",
                project_name="proj-b",
                project_root="/tmp/proj-b",
                tags=["ui"],
            )

            filtered = orch.list_tasks(project_name="proj-a", tags=["service"])
            self.assertEqual(1, len(filtered))
            self.assertEqual("A", filtered[0]["title"])

    def test_claim_next_task_is_scoped_to_agent_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state-root"
            state_root.mkdir(parents=True, exist_ok=True)
            orch = Orchestrator(root=state_root, policy=_make_policy(state_root / "policy.json"))
            orch.bootstrap()

            project_a = Path(tmp) / "project-a"
            project_b = Path(tmp) / "project-b"
            project_a.mkdir(parents=True, exist_ok=True)
            project_b.mkdir(parents=True, exist_ok=True)

            _register_agent(orch, "claude_code", project_root=project_b)

            task_a = orch.create_task(
                title="Task A",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
                project_root=str(project_a),
                project_name=project_a.name,
            )
            task_b = orch.create_task(
                title="Task B",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
                project_root=str(project_b),
                project_name=project_b.name,
            )

            claimed = orch.claim_next_task(owner="claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual(task_b["id"], claimed["id"])
            self.assertNotEqual(task_a["id"], claimed["id"])


if __name__ == "__main__":
    unittest.main()

