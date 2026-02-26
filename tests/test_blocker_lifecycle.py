"""Tests for blocker lifecycle: raise_blocker, list_blockers, resolve_blocker.

Validates the full blocker lifecycle from raising through resolution,
including task status transitions and filtering.
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


def _create_and_claim(orch: Orchestrator, title: str, owner: str) -> str:
    """Create a task, assign to owner, and claim it. Returns task_id."""
    task = orch.create_task(title=title, workstream="backend", acceptance_criteria=["done"], owner=owner)
    task_id = task["id"]
    orch.register_agent(owner, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": "test-session",
        "connection_id": "test-connection",
        "server_version": "0.1.0",
        "verification_source": "test",
    })
    orch.claim_next_task(owner)
    return task_id


class RaiseBlockerTests(unittest.TestCase):
    """Tests for raise_blocker."""

    def test_raise_creates_blocker_record(self) -> None:
        """raise_blocker should return a blocker dict with expected fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Test task", "claude_code")

            blocker = orch.raise_blocker(
                task_id=task_id,
                agent="claude_code",
                question="Need clarification on API format",
            )

            self.assertTrue(blocker["id"].startswith("BLK-"))
            self.assertEqual(task_id, blocker["task_id"])
            self.assertEqual("claude_code", blocker["agent"])
            self.assertEqual("Need clarification on API format", blocker["question"])
            self.assertEqual("open", blocker["status"])
            self.assertEqual("medium", blocker["severity"])
            self.assertIsNotNone(blocker["created_at"])

    def test_raise_sets_task_status_to_blocked(self) -> None:
        """raise_blocker should transition the task to blocked status."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Blocking task", "claude_code")

            orch.raise_blocker(task_id=task_id, agent="claude_code", question="Blocked")

            tasks = orch.list_tasks()
            task = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("blocked", task["status"])

    def test_raise_with_options_and_severity(self) -> None:
        """raise_blocker should store options and custom severity."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Options task", "claude_code")

            blocker = orch.raise_blocker(
                task_id=task_id,
                agent="claude_code",
                question="Which approach?",
                options=["Option A", "Option B"],
                severity="high",
            )

            self.assertEqual(["Option A", "Option B"], blocker["options"])
            self.assertEqual("high", blocker["severity"])

    def test_raise_wrong_owner_raises_error(self) -> None:
        """raise_blocker from non-owner agent should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Owner mismatch", "claude_code")

            with self.assertRaises(ValueError) as ctx:
                orch.raise_blocker(task_id=task_id, agent="gemini", question="Wrong owner")
            self.assertIn("does not match", str(ctx.exception))

    def test_raise_nonexistent_task_raises_error(self) -> None:
        """raise_blocker on a non-existent task should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError) as ctx:
                orch.raise_blocker(task_id="TASK-nonexistent", agent="claude_code", question="Missing")
            self.assertIn("not found", str(ctx.exception))


class ListBlockersTests(unittest.TestCase):
    """Tests for list_blockers."""

    def test_empty_state_returns_empty(self) -> None:
        """list_blockers with no blockers should return empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self.assertEqual([], orch.list_blockers())

    def test_list_returns_all_blockers(self) -> None:
        """list_blockers without filters returns all blockers."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            t1 = _create_and_claim(orch, "Task 1", "claude_code")
            orch.raise_blocker(task_id=t1, agent="claude_code", question="Q1")

            t2 = orch.create_task(title="Task 2", workstream="frontend", acceptance_criteria=["done"], owner="gemini")["id"]
            orch.register_agent("gemini", {
                "client": "gemini-cli", "model": "gemini-2.5",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gm", "connection_id": "cid-gm",
                "server_version": "0.1.0", "verification_source": "test",
            })
            orch.claim_next_task("gemini")
            orch.raise_blocker(task_id=t2, agent="gemini", question="Q2")

            blockers = orch.list_blockers()
            self.assertEqual(2, len(blockers))

    def test_list_filter_by_status(self) -> None:
        """list_blockers(status='open') should only return open blockers."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Filter task", "claude_code")

            blk = orch.raise_blocker(task_id=task_id, agent="claude_code", question="Q")
            orch.resolve_blocker(blk["id"], "Fixed", "codex")

            open_blockers = orch.list_blockers(status="open")
            resolved_blockers = orch.list_blockers(status="resolved")
            self.assertEqual(0, len(open_blockers))
            self.assertEqual(1, len(resolved_blockers))

    def test_list_filter_by_agent(self) -> None:
        """list_blockers(agent='claude_code') should filter by agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            t1 = _create_and_claim(orch, "CC task", "claude_code")
            orch.raise_blocker(task_id=t1, agent="claude_code", question="CC Q")

            t2 = orch.create_task(title="GM task", workstream="frontend", acceptance_criteria=["done"], owner="gemini")["id"]
            orch.register_agent("gemini", {
                "client": "gemini-cli", "model": "gemini-2.5",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-gm2", "connection_id": "cid-gm2",
                "server_version": "0.1.0", "verification_source": "test",
            })
            orch.claim_next_task("gemini")
            orch.raise_blocker(task_id=t2, agent="gemini", question="GM Q")

            cc_blockers = orch.list_blockers(agent="claude_code")
            self.assertEqual(1, len(cc_blockers))
            self.assertEqual("claude_code", cc_blockers[0]["agent"])


class ResolveBlockerTests(unittest.TestCase):
    """Tests for resolve_blocker."""

    def test_resolve_marks_blocker_resolved(self) -> None:
        """resolve_blocker should set status to resolved with resolution details."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Resolve task", "claude_code")

            blk = orch.raise_blocker(task_id=task_id, agent="claude_code", question="Q")
            resolved = orch.resolve_blocker(blk["id"], "Answer provided", "codex")

            self.assertEqual("resolved", resolved["status"])
            self.assertEqual("Answer provided", resolved["resolution"])
            self.assertEqual("codex", resolved["resolved_by"])
            self.assertIsNotNone(resolved["resolved_at"])

    def test_resolve_unblocks_task_for_active_owner(self) -> None:
        """resolve_blocker should transition task back from blocked when owner is active."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Unblock task", "claude_code")
            # Heartbeat to ensure agent is active
            orch.heartbeat("claude_code", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "test-session", "connection_id": "test-connection",
                "server_version": "0.1.0", "verification_source": "test",
            })

            blk = orch.raise_blocker(task_id=task_id, agent="claude_code", question="Q")

            # Verify task is blocked
            tasks = orch.list_tasks()
            task = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("blocked", task["status"])

            # Resolve
            orch.resolve_blocker(blk["id"], "Done", "codex")

            # Task should no longer be blocked
            tasks = orch.list_tasks()
            task = next(t for t in tasks if t["id"] == task_id)
            self.assertIn(task["status"], ("in_progress", "assigned"))

    def test_resolve_idempotent(self) -> None:
        """Resolving an already-resolved blocker should be a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Idempotent task", "claude_code")

            blk = orch.raise_blocker(task_id=task_id, agent="claude_code", question="Q")
            first = orch.resolve_blocker(blk["id"], "First resolution", "codex")
            second = orch.resolve_blocker(blk["id"], "Second resolution", "codex")

            # Should return the already-resolved blocker without changing resolution
            self.assertEqual("resolved", second["status"])
            self.assertEqual("First resolution", second["resolution"])

    def test_resolve_nonexistent_raises_error(self) -> None:
        """resolve_blocker on non-existent blocker should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError) as ctx:
                orch.resolve_blocker("BLK-nonexistent", "Fix", "codex")
            self.assertIn("not found", str(ctx.exception))


class BlockerLifecycleTests(unittest.TestCase):
    """End-to-end blocker lifecycle tests."""

    def test_full_lifecycle_raise_list_resolve(self) -> None:
        """Full lifecycle: raise -> list shows open -> resolve -> list shows resolved."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task_id = _create_and_claim(orch, "Lifecycle task", "claude_code")

            # Raise
            blk = orch.raise_blocker(task_id=task_id, agent="claude_code", question="Need help")
            blk_id = blk["id"]

            # List open
            open_blks = orch.list_blockers(status="open")
            self.assertEqual(1, len(open_blks))
            self.assertEqual(blk_id, open_blks[0]["id"])

            # Resolve
            orch.resolve_blocker(blk_id, "Help provided", "codex")

            # List open should be empty now
            open_blks = orch.list_blockers(status="open")
            self.assertEqual(0, len(open_blks))

            # List resolved should have the blocker
            resolved_blks = orch.list_blockers(status="resolved")
            self.assertEqual(1, len(resolved_blks))
            self.assertEqual(blk_id, resolved_blks[0]["id"])

    def test_multiple_blockers_independent_resolution(self) -> None:
        """Multiple blockers on different tasks can be resolved independently."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            t1 = _create_and_claim(orch, "Task A", "claude_code")

            t2 = orch.create_task(title="Task B", workstream="backend", acceptance_criteria=["done"], owner="claude_code")["id"]
            orch.claim_next_task("claude_code")

            blk1 = orch.raise_blocker(task_id=t1, agent="claude_code", question="Q1")
            blk2 = orch.raise_blocker(task_id=t2, agent="claude_code", question="Q2")

            # Resolve only the first
            orch.resolve_blocker(blk1["id"], "Fixed Q1", "codex")

            open_blks = orch.list_blockers(status="open")
            self.assertEqual(1, len(open_blks))
            self.assertEqual(blk2["id"], open_blks[0]["id"])

            resolved_blks = orch.list_blockers(status="resolved")
            self.assertEqual(1, len(resolved_blks))
            self.assertEqual(blk1["id"], resolved_blks[0]["id"])


if __name__ == "__main__":
    unittest.main()
