"""Tests for dedupe_open_tasks and requeue_stale_in_progress_tasks.

Validates deduplication of open tasks by fingerprint and requeuing
of stale in-progress tasks back to assigned status.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
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


class DedupeOpenTasksTests(unittest.TestCase):
    """Tests for dedupe_open_tasks."""

    def test_no_duplicates_returns_zero(self) -> None:
        """When no duplicate tasks exist, deduped_count should be 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.create_task(title="Task A", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.create_task(title="Task B", workstream="backend", owner="claude_code", acceptance_criteria=["done"])

            result = orch.dedupe_open_tasks(source="codex")

            self.assertEqual(0, result["deduped_count"])
            self.assertEqual([], result["deduped"])

    def test_duplicates_closed_keeps_oldest(self) -> None:
        """Duplicate tasks should be closed, keeping the oldest as canonical."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            t1 = orch.create_task(title="Same title", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            # create_task deduplicates on creation, so inject duplicate directly
            t2_id = f"TASK-{uuid.uuid4().hex[:8]}"
            tasks = orch._read_json(orch.tasks_path)
            tasks.append({
                "id": t2_id, "title": "Same title", "workstream": "backend",
                "owner": "claude_code", "status": "assigned",
                "created_at": orch._now(), "updated_at": orch._now(),
            })
            orch._write_json(orch.tasks_path, tasks)

            result = orch.dedupe_open_tasks(source="codex")

            self.assertEqual(1, result["deduped_count"])
            tasks = orch.list_tasks()
            t1_task = next(t for t in tasks if t["id"] == t1["id"])
            t2_task = next(t for t in tasks if t["id"] == t2_id)
            self.assertEqual("assigned", t1_task["status"])
            self.assertEqual("duplicate_closed", t2_task["status"])
            self.assertEqual(t1["id"], t2_task["duplicate_of"])

    def test_different_workstream_not_duplicate(self) -> None:
        """Tasks with same title but different workstream are not duplicates."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.create_task(title="Same title", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.create_task(title="Same title", workstream="frontend", owner="gemini", acceptance_criteria=["done"])

            result = orch.dedupe_open_tasks(source="codex")

            self.assertEqual(0, result["deduped_count"])

    def test_different_owner_not_duplicate(self) -> None:
        """Tasks with same title but different owner are not duplicates."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.create_task(title="Same title", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.create_task(title="Same title", workstream="backend", owner="codex", acceptance_criteria=["done"])

            result = orch.dedupe_open_tasks(source="codex")

            self.assertEqual(0, result["deduped_count"])

    def test_closed_tasks_not_considered(self) -> None:
        """Tasks with done status should not be considered for dedup."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            t1 = orch.create_task(title="Same title", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            # Manually close the first task
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == t1["id"]:
                    t["status"] = "done"
            orch._write_json(orch.tasks_path, tasks)

            t2 = orch.create_task(title="Same title", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            result = orch.dedupe_open_tasks(source="codex")

            self.assertEqual(0, result["deduped_count"])

    def test_multiple_duplicates_all_closed(self) -> None:
        """Three tasks with same fingerprint: keep oldest, close other two."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            t1 = orch.create_task(title="Repeated", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            # Inject duplicates directly to bypass create_task dedup
            t2_id = f"TASK-{uuid.uuid4().hex[:8]}"
            t3_id = f"TASK-{uuid.uuid4().hex[:8]}"
            tasks = orch._read_json(orch.tasks_path)
            tasks.append({
                "id": t2_id, "title": "Repeated", "workstream": "backend",
                "owner": "claude_code", "status": "assigned",
                "created_at": orch._now(), "updated_at": orch._now(),
            })
            tasks.append({
                "id": t3_id, "title": "Repeated", "workstream": "backend",
                "owner": "claude_code", "status": "assigned",
                "created_at": orch._now(), "updated_at": orch._now(),
            })
            orch._write_json(orch.tasks_path, tasks)

            result = orch.dedupe_open_tasks(source="codex")

            self.assertEqual(2, result["deduped_count"])
            tasks = orch.list_tasks()
            statuses = {t["id"]: t["status"] for t in tasks}
            self.assertEqual("assigned", statuses[t1["id"]])
            self.assertEqual("duplicate_closed", statuses[t2_id])
            self.assertEqual("duplicate_closed", statuses[t3_id])

    def test_empty_task_list(self) -> None:
        """dedupe_open_tasks on empty task list should be a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.dedupe_open_tasks(source="codex")

            self.assertEqual(0, result["deduped_count"])


class RequeueStaleInProgressTests(unittest.TestCase):
    """Tests for requeue_stale_in_progress_tasks."""

    def test_no_stale_tasks_returns_empty(self) -> None:
        """When no in-progress tasks are stale, should return empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            orch.create_task(title="Active task", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.claim_next_task("claude_code")

            requeued = orch.requeue_stale_in_progress_tasks(stale_after_seconds=1800)

            self.assertEqual([], requeued)

    def test_stale_task_requeued_to_assigned(self) -> None:
        """A stale in-progress task should be returned to assigned status."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            task = orch.create_task(title="Stale task", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.claim_next_task("claude_code")

            # Make agent stale by setting last_seen to old time
            agents = orch._read_json(orch.agents_path)
            old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            agents["claude_code"]["last_seen"] = old_time
            orch._write_json(orch.agents_path, agents)

            requeued = orch.requeue_stale_in_progress_tasks(stale_after_seconds=60)

            self.assertEqual(1, len(requeued))
            self.assertEqual(task["id"], requeued[0]["task_id"])

            # Verify task is assigned
            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("assigned", t["status"])

    def test_assigned_task_not_requeued(self) -> None:
        """Tasks not in in_progress status should not be requeued."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            orch.create_task(title="Assigned task", workstream="backend", owner="claude_code", acceptance_criteria=["done"])

            # Make agent stale
            agents = orch._read_json(orch.agents_path)
            old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            agents["claude_code"]["last_seen"] = old_time
            orch._write_json(orch.agents_path, agents)

            requeued = orch.requeue_stale_in_progress_tasks(stale_after_seconds=60)

            self.assertEqual([], requeued)

    def test_multiple_stale_tasks(self) -> None:
        """Multiple stale in-progress tasks should all be requeued."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            t1 = orch.create_task(title="Stale 1", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            t2 = orch.create_task(title="Stale 2", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.claim_next_task("claude_code")
            orch.claim_next_task("claude_code")

            # Make agent stale
            agents = orch._read_json(orch.agents_path)
            old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            agents["claude_code"]["last_seen"] = old_time
            orch._write_json(orch.agents_path, agents)

            requeued = orch.requeue_stale_in_progress_tasks(stale_after_seconds=60)

            self.assertEqual(2, len(requeued))
            requeued_ids = {r["task_id"] for r in requeued}
            self.assertIn(t1["id"], requeued_ids)
            self.assertIn(t2["id"], requeued_ids)

    def test_stale_threshold_respected(self) -> None:
        """Tasks with owner seen within threshold should not be requeued."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            orch.create_task(title="Recent task", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.claim_next_task("claude_code")

            # Set last_seen to 30 seconds ago
            agents = orch._read_json(orch.agents_path)
            recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
            agents["claude_code"]["last_seen"] = recent
            orch._write_json(orch.agents_path, agents)

            # With 60s threshold, should not requeue
            requeued = orch.requeue_stale_in_progress_tasks(stale_after_seconds=60)
            self.assertEqual([], requeued)

    def test_requeue_includes_reason(self) -> None:
        """Requeued records should include a reason with timing info."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            orch.create_task(title="Reason task", workstream="backend", owner="claude_code", acceptance_criteria=["done"])
            orch.claim_next_task("claude_code")

            agents = orch._read_json(orch.agents_path)
            old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            agents["claude_code"]["last_seen"] = old_time
            orch._write_json(orch.agents_path, agents)

            requeued = orch.requeue_stale_in_progress_tasks(stale_after_seconds=60)

            self.assertEqual(1, len(requeued))
            self.assertIn("reason", requeued[0])
            self.assertIn("stale", requeued[0]["reason"])


if __name__ == "__main__":
    unittest.main()
