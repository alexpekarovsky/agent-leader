"""Tests for superseded and archived task statuses.

Verifies that the engine accepts superseded/archived as valid status
transitions, restricts them to manager-only, tracks timestamps, and
exposes them in status counters without breaking existing consumers.
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
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": False,
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })


class SupersededStatusTests(unittest.TestCase):
    """Tests for the superseded task status."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_manager_can_set_superseded(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="old task", workstream="backend", owner="claude_code")
        result = self.orch.set_task_status(task["id"], "superseded", source="codex", note="replaced by new task")
        self.assertEqual(result["status"], "superseded")

    def test_team_member_cannot_set_superseded(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="old task", workstream="backend", owner="claude_code")
        with self.assertRaises(ValueError) as ctx:
            self.orch.set_task_status(task["id"], "superseded", source="claude_code")
        self.assertIn("manager authority", str(ctx.exception))

    def test_superseded_sets_timestamp(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="old task", workstream="backend", owner="claude_code")
        result = self.orch.set_task_status(task["id"], "superseded", source="codex")
        self.assertIn("superseded_at", result)
        self.assertEqual(result["superseded_at"], result["updated_at"])

    def test_superseded_not_in_open_statuses(self) -> None:
        """Superseded tasks should not be treated as open/active work."""
        task = self.orch.create_task(acceptance_criteria=["test"], title="old task", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "superseded", source="codex")
        # Dedupe should not consider superseded tasks as open
        result = self.orch.dedupe_open_tasks(source="codex")
        self.assertEqual(result["deduped_count"], 0)

    def test_superseded_not_claimable(self) -> None:
        """Superseded tasks should not be picked up by claim_next_task."""
        task = self.orch.create_task(acceptance_criteria=["test"], title="old task", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "superseded", source="codex")
        claimed = self.orch.claim_next_task("claude_code")
        self.assertIsNone(claimed)


class ArchivedStatusTests(unittest.TestCase):
    """Tests for the archived task status."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_manager_can_set_archived(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="deferred task", workstream="backend", owner="claude_code")
        result = self.orch.set_task_status(task["id"], "archived", source="codex", note="out of scope")
        self.assertEqual(result["status"], "archived")

    def test_team_member_cannot_set_archived(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="deferred task", workstream="backend", owner="claude_code")
        with self.assertRaises(ValueError) as ctx:
            self.orch.set_task_status(task["id"], "archived", source="claude_code")
        self.assertIn("manager authority", str(ctx.exception))

    def test_archived_sets_timestamp(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="deferred task", workstream="backend", owner="claude_code")
        result = self.orch.set_task_status(task["id"], "archived", source="codex")
        self.assertIn("archived_at", result)
        self.assertEqual(result["archived_at"], result["updated_at"])

    def test_archived_not_in_open_statuses(self) -> None:
        """Archived tasks should not be treated as open/active work."""
        task = self.orch.create_task(acceptance_criteria=["test"], title="deferred task", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "archived", source="codex")
        result = self.orch.dedupe_open_tasks(source="codex")
        self.assertEqual(result["deduped_count"], 0)

    def test_archived_not_claimable(self) -> None:
        """Archived tasks should not be picked up by claim_next_task."""
        task = self.orch.create_task(acceptance_criteria=["test"], title="deferred task", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "archived", source="codex")
        claimed = self.orch.claim_next_task("claude_code")
        self.assertIsNone(claimed)


class StatusCounterTests(unittest.TestCase):
    """Verify new statuses appear in task_counts on list_agents."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_task_counts_include_superseded(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="t1", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "superseded", source="codex")
        agents = self.orch.list_agents(active_only=False)
        cc = next(a for a in agents if a.get("agent") == "claude_code")
        self.assertIn("superseded", cc["task_counts"])
        self.assertEqual(cc["task_counts"]["superseded"], 1)

    def test_task_counts_include_archived(self) -> None:
        task = self.orch.create_task(acceptance_criteria=["test"], title="t2", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "archived", source="codex")
        agents = self.orch.list_agents(active_only=False)
        cc = next(a for a in agents if a.get("agent") == "claude_code")
        self.assertIn("archived", cc["task_counts"])
        self.assertEqual(cc["task_counts"]["archived"], 1)

    def test_existing_counters_unaffected(self) -> None:
        """Existing done/assigned/in_progress/blocked counters still work."""
        t1 = self.orch.create_task(acceptance_criteria=["test"], title="done-task", workstream="backend", owner="claude_code")
        # Move through lifecycle to done via claim + report + validate
        self.orch.claim_next_task("claude_code")
        self.orch.ingest_report({
            "task_id": t1["id"], "agent": "claude_code", "commit_sha": "abc123",
            "status": "done", "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
        })
        self.orch.validate_task(t1["id"], passed=True, notes="ok", source="codex")

        t2 = self.orch.create_task(acceptance_criteria=["test"], title="superseded-task", workstream="backend", owner="claude_code")
        self.orch.set_task_status(t2["id"], "superseded", source="codex")

        agents = self.orch.list_agents(active_only=False)
        cc = next(a for a in agents if a.get("agent") == "claude_code")
        self.assertEqual(cc["task_counts"]["done"], 1)
        self.assertEqual(cc["task_counts"]["superseded"], 1)


class BackwardCompatTests(unittest.TestCase):
    """Superseded/archived tasks should not break existing open_statuses logic."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_superseded_excluded_from_duplicate_detection(self) -> None:
        """Superseded task with same title should not count as duplicate of new task."""
        t1 = self.orch.create_task(acceptance_criteria=["test"], title="feature X", workstream="backend", owner="claude_code")
        self.orch.set_task_status(t1["id"], "superseded", source="codex")
        # Creating a new task with same title should succeed (no duplicate)
        t2 = self.orch.create_task(acceptance_criteria=["test"], title="feature X", workstream="backend", owner="claude_code")
        self.assertNotEqual(t1["id"], t2["id"])
        self.assertEqual(t2["status"], "assigned")

    def test_archived_excluded_from_duplicate_detection(self) -> None:
        """Archived task with same title should not count as duplicate of new task."""
        t1 = self.orch.create_task(acceptance_criteria=["test"], title="feature Y", workstream="backend", owner="claude_code")
        self.orch.set_task_status(t1["id"], "archived", source="codex")
        t2 = self.orch.create_task(acceptance_criteria=["test"], title="feature Y", workstream="backend", owner="claude_code")
        self.assertNotEqual(t1["id"], t2["id"])
        self.assertEqual(t2["status"], "assigned")

    def test_reassign_stale_ignores_superseded(self) -> None:
        """Reassign stale tasks should not touch superseded tasks."""
        task = self.orch.create_task(acceptance_criteria=["test"], title="stale check", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "superseded", source="codex")
        requeued = self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=0)
        self.assertEqual(len(requeued), 0)

    def test_reassign_stale_ignores_archived(self) -> None:
        """Reassign stale tasks should not touch archived tasks."""
        task = self.orch.create_task(acceptance_criteria=["test"], title="stale check", workstream="backend", owner="claude_code")
        self.orch.set_task_status(task["id"], "archived", source="codex")
        requeued = self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=0)
        self.assertEqual(len(requeued), 0)

    def test_list_tasks_includes_all_statuses(self) -> None:
        """list_tasks should include tasks with any status."""
        t1 = self.orch.create_task(acceptance_criteria=["test"], title="s1", workstream="backend", owner="claude_code")
        t2 = self.orch.create_task(acceptance_criteria=["test"], title="s2", workstream="backend", owner="claude_code")
        self.orch.set_task_status(t1["id"], "superseded", source="codex")
        self.orch.set_task_status(t2["id"], "archived", source="codex")
        tasks = self.orch.list_tasks()
        statuses = {t["status"] for t in tasks}
        self.assertIn("superseded", statuses)
        self.assertIn("archived", statuses)


if __name__ == "__main__":
    unittest.main()
