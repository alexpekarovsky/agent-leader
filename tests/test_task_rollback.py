"""Tests for task queue rollback workflow documented in docs/task-queue-hygiene.md.

Validates the operator procedure for cancelling mistaken tasks:
1. Create tasks
2. Block with cancellation note
3. Publish correction event
4. Verify blocked tasks don't appear in claimable queue
5. Verify deduplication handles open duplicates
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
import unittest

from orchestrator.bus import EventBus
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


def _register_agent(orch: Orchestrator, agent: str, root: Path) -> None:
    meta = {
        "role": "team_member",
        "client": "test",
        "model": "test",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "none",
        "session_id": "test-session",
        "connection_id": "test-conn",
        "server_version": "0.1.0",
        "verification_source": "test",
    }
    orch.register_agent(agent, metadata=meta)
    orch.heartbeat(agent, metadata=meta)


def _filter_tasks(tasks: List[Dict[str, Any]], status: Optional[str] = None) -> List[Dict[str, Any]]:
    if status is None:
        return tasks
    return [t for t in tasks if t.get("status") == status]


class TestTaskRollback(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        policy_path = self.root / "policy.json"
        self.policy = _make_policy(policy_path)
        self.orch = Orchestrator(root=self.root, policy=self.policy)
        self.orch.bootstrap()
        _register_agent(self.orch, "claude_code", self.root)
        _register_agent(self.orch, "codex", self.root)

    def test_block_cancels_task_from_claimable_queue(self) -> None:
        """Blocking a task with cancellation note removes it from claim."""
        task = self.orch.create_task(
            title="Mistaken task",
            workstream="backend",
            acceptance_criteria=["test"],
            description="Created in error",
        )
        task_id = task["id"]

        # Task should be assigned before blocking
        all_tasks = self.orch.list_tasks()
        assigned = _filter_tasks(all_tasks, "assigned")
        assigned_ids = [t["id"] for t in assigned]
        self.assertIn(task_id, assigned_ids)

        # Block with cancellation note (rollback step 1)
        self.orch.set_task_status(
            task_id=task_id,
            status="blocked",
            source="codex",
            note="Cancelled: created in error. Do not implement.",
        )

        # Task should NOT be claimable after blocking
        claim_result = self.orch.claim_next_task(owner="claude_code")
        if claim_result is not None:
            self.assertNotEqual(claim_result["id"], task_id)

        # Task should appear in blocked list
        all_tasks = self.orch.list_tasks()
        blocked = _filter_tasks(all_tasks, "blocked")
        blocked_ids = [t["id"] for t in blocked]
        self.assertIn(task_id, blocked_ids)

    def test_correction_event_published(self) -> None:
        """Publishing a correction event records the cancellation."""
        task = self.orch.create_task(
            title="Another mistaken task",
            workstream="backend",
            acceptance_criteria=["test"],
        )
        task_id = task["id"]

        self.orch.set_task_status(
            task_id=task_id,
            status="blocked",
            source="codex",
            note="Cancelled",
        )

        # Publish correction event (rollback step 3)
        self.orch.bus.emit(
            "manager.correction",
            {
                "action": "task_cancelled",
                "task_id": task_id,
                "reason": "Created in error",
            },
            source="operator",
        )

        # Event should be recorded
        events = list(self.orch.bus.iter_events())
        correction_events = [
            e for e in events
            if e.get("type") == "manager.correction"
            and e.get("payload", {}).get("task_id") == task_id
        ]
        self.assertGreaterEqual(len(correction_events), 1)

    def test_blocked_task_not_reassigned(self) -> None:
        """Blocked tasks are not reassigned by reassign_stale_tasks."""
        task = self.orch.create_task(
            title="Task to cancel for reassign test",
            workstream="backend",
            acceptance_criteria=["test"],
        )
        task_id = task["id"]

        self.orch.set_task_status(
            task_id=task_id,
            status="blocked",
            source="codex",
            note="Cancelled",
        )

        # Run reassign — blocked tasks should stay blocked (include_blocked=False)
        self.orch.reassign_stale_tasks_to_active_workers(
            source="codex",
            stale_after_seconds=0,
            include_blocked=False,
        )

        # Verify task is still blocked
        all_tasks = self.orch.list_tasks()
        blocked = _filter_tasks(all_tasks, "blocked")
        blocked_ids = [t["id"] for t in blocked]
        self.assertIn(task_id, blocked_ids)

    def test_deduplication_keeps_oldest(self) -> None:
        """Deduplication closes newer duplicates and keeps oldest."""
        task1 = self.orch.create_task(
            title="Unique task title for dedup test",
            workstream="backend",
            acceptance_criteria=["test"],
        )
        # Creating same title should return deduplicated result
        task2 = self.orch.create_task(
            title="Unique task title for dedup test",
            workstream="backend",
            acceptance_criteria=["test"],
        )

        # Should be deduplicated (same task returned)
        self.assertEqual(task1["id"], task2["id"])

    def test_bulk_cancellation(self) -> None:
        """Multiple tasks can be cancelled in sequence."""
        ids = []
        for i in range(3):
            task = self.orch.create_task(
                title=f"Bulk cancel task {i}",
                workstream="backend",
                acceptance_criteria=["test"],
            )
            ids.append(task["id"])

        # Block all
        for tid in ids:
            self.orch.set_task_status(
                task_id=tid,
                status="blocked",
                source="codex",
                note="Cancelled: batch cleanup",
            )

        # Verify all blocked
        all_tasks = self.orch.list_tasks()
        blocked = _filter_tasks(all_tasks, "blocked")
        blocked_ids = {t["id"] for t in blocked}
        for tid in ids:
            self.assertIn(tid, blocked_ids)

        # Verify none are assigned
        assigned = _filter_tasks(all_tasks, "assigned")
        assigned_ids = {t["id"] for t in assigned}
        for tid in ids:
            self.assertNotIn(tid, assigned_ids)

    def test_claim_skips_blocked_tasks(self) -> None:
        """Claiming returns None when only blocked tasks exist."""
        task = self.orch.create_task(
            title="Only task, will be blocked for claim test",
            workstream="backend",
            acceptance_criteria=["test"],
        )
        self.orch.set_task_status(
            task_id=task["id"],
            status="blocked",
            source="codex",
            note="Cancelled",
        )

        result = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
