"""Tests for list_bugs and list_tasks_for_owner.

Validates filtering by status, owner, combined filters,
empty results, and result correctness.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _register_agent(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"cid-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    })


def _create_task(orch: Orchestrator, title: str, owner: str) -> str:
    task = orch.create_task(
        title=title,
        workstream="backend",
        acceptance_criteria=["done"],
        owner=owner,
    )
    return task["id"]


def _full_lifecycle_to_bug(orch: Orchestrator, title: str, owner: str) -> str:
    """Create task, claim, report, and fail validation to produce a bug."""
    task_id = _create_task(orch, title, owner)
    orch.claim_next_task(owner)
    orch.ingest_report({
        "task_id": task_id,
        "agent": owner,
        "commit_sha": "sha-" + task_id[:8],
        "status": "done",
        "test_summary": {"command": "test", "passed": 1, "failed": 1},
    })
    orch.validate_task(task_id, passed=False, notes="Tests failing", source="codex")
    return task_id


class ListTasksForOwnerTests(unittest.TestCase):
    """Tests for list_tasks_for_owner."""

    def test_returns_only_owned_tasks(self) -> None:
        """Should only return tasks owned by the specified agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _create_task(orch, "CC task 1", "claude_code")
            _create_task(orch, "CC task 2", "claude_code")
            _create_task(orch, "Gemini task", "gemini")

            cc_tasks = orch.list_tasks_for_owner("claude_code")
            self.assertEqual(2, len(cc_tasks))
            for t in cc_tasks:
                self.assertEqual("claude_code", t["owner"])

    def test_with_status_filter(self) -> None:
        """Should filter by both owner and status when status provided."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _create_task(orch, "Task A", "claude_code")
            task_id_b = _create_task(orch, "Task B", "claude_code")
            orch.claim_next_task("claude_code")

            assigned = orch.list_tasks_for_owner("claude_code", status="assigned")
            in_progress = orch.list_tasks_for_owner("claude_code", status="in_progress")

            self.assertEqual(1, len(assigned))
            self.assertEqual(1, len(in_progress))

    def test_empty_when_no_tasks_for_owner(self) -> None:
        """Should return empty list when owner has no tasks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _create_task(orch, "Other task", "gemini")

            result = orch.list_tasks_for_owner("claude_code")
            self.assertEqual([], result)

    def test_empty_when_no_matching_status(self) -> None:
        """Should return empty when owner has tasks but none with matching status."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _create_task(orch, "Assigned task", "claude_code")

            result = orch.list_tasks_for_owner("claude_code", status="in_progress")
            self.assertEqual([], result)

    def test_no_status_returns_all_statuses(self) -> None:
        """Without status filter, should return tasks in any status."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _create_task(orch, "Task 1", "claude_code")
            _create_task(orch, "Task 2", "claude_code")
            orch.claim_next_task("claude_code")  # Claims one, making it in_progress

            all_tasks = orch.list_tasks_for_owner("claude_code")
            statuses = {t["status"] for t in all_tasks}
            self.assertEqual(2, len(all_tasks))
            self.assertIn("assigned", statuses)
            self.assertIn("in_progress", statuses)

    def test_returns_list_type(self) -> None:
        """Should always return a list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.list_tasks_for_owner("nonexistent")
            self.assertIsInstance(result, list)


class ListBugsTests(unittest.TestCase):
    """Tests for list_bugs."""

    def test_empty_when_no_bugs(self) -> None:
        """Should return empty list when no bugs exist."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.list_bugs()
            self.assertEqual([], result)

    def test_returns_created_bugs(self) -> None:
        """Bugs created via failed validation should appear in list_bugs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _full_lifecycle_to_bug(orch, "Bug task", "claude_code")

            bugs = orch.list_bugs()
            self.assertGreaterEqual(len(bugs), 1)

    def test_filter_by_status_open(self) -> None:
        """list_bugs(status='open') should return only open bugs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _full_lifecycle_to_bug(orch, "Open bug task", "claude_code")

            open_bugs = orch.list_bugs(status="open")
            self.assertGreaterEqual(len(open_bugs), 1)
            for bug in open_bugs:
                self.assertEqual("open", bug["status"])

    def test_filter_by_status_no_match(self) -> None:
        """list_bugs with non-matching status should return empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _full_lifecycle_to_bug(orch, "Bug for filter", "claude_code")

            result = orch.list_bugs(status="closed")
            self.assertEqual([], result)

    def test_filter_by_owner(self) -> None:
        """list_bugs(owner=...) should return only bugs for that owner."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _full_lifecycle_to_bug(orch, "CC bug", "claude_code")

            cc_bugs = orch.list_bugs(owner="claude_code")
            self.assertGreaterEqual(len(cc_bugs), 1)
            for bug in cc_bugs:
                self.assertEqual("claude_code", bug["owner"])

    def test_filter_by_owner_no_match(self) -> None:
        """list_bugs with non-matching owner should return empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _full_lifecycle_to_bug(orch, "CC only bug", "claude_code")

            result = orch.list_bugs(owner="gemini")
            self.assertEqual([], result)

    def test_combined_status_and_owner_filter(self) -> None:
        """list_bugs with both status and owner should apply both filters."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            _full_lifecycle_to_bug(orch, "Combined filter", "claude_code")

            result = orch.list_bugs(status="open", owner="claude_code")
            self.assertGreaterEqual(len(result), 1)
            for bug in result:
                self.assertEqual("open", bug["status"])
                self.assertEqual("claude_code", bug["owner"])

    def test_returns_list_type(self) -> None:
        """Should always return a list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.list_bugs()
            self.assertIsInstance(result, list)

    def test_bug_has_source_task(self) -> None:
        """Bugs from failed validation should reference the source task."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            task_id = _full_lifecycle_to_bug(orch, "Source ref", "claude_code")

            bugs = orch.list_bugs()
            bug = next((b for b in bugs if b.get("source_task") == task_id), None)
            self.assertIsNotNone(bug)


if __name__ == "__main__":
    unittest.main()
