"""Integration test for the full task lifecycle.

Exercises the complete path: create -> claim -> heartbeat -> report ->
validate -> done, verifying state at each transition.
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


def _get_task(orch: Orchestrator, task_id: str) -> dict:
    return next(t for t in orch.list_tasks() if t["id"] == task_id)


class TaskLifecycleIntegrationTests(unittest.TestCase):
    """End-to-end task lifecycle: create -> claim -> heartbeat -> report -> validate -> done."""

    def test_happy_path_lifecycle(self) -> None:
        """Full lifecycle should transition through all expected states."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            # 1. Create task
            task = orch.create_task(
                title="Integration test task",
                workstream="backend",
                acceptance_criteria=["Tests pass", "No regressions"],
                owner="claude_code",
            )
            task_id = task["id"]
            self.assertEqual("assigned", _get_task(orch, task_id)["status"])

            # 2. Claim task
            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual(task_id, claimed["id"])
            self.assertEqual("in_progress", _get_task(orch, task_id)["status"])

            # 3. Heartbeat during work
            orch.heartbeat("claude_code")
            self.assertEqual("in_progress", _get_task(orch, task_id)["status"])

            # 4. Submit report
            report = {
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "python -m pytest", "passed": 10, "failed": 0},
                "notes": "All tests pass",
            }
            orch.ingest_report(report)
            self.assertEqual("reported", _get_task(orch, task_id)["status"])

            # 5. Validate (manager approves)
            result = orch.validate_task(task_id, passed=True, notes="Looks good", source="codex")
            self.assertEqual("done", _get_task(orch, task_id)["status"])
            self.assertEqual(task_id, result["task_id"])

    def test_failed_validation_opens_bug(self) -> None:
        """Failed validation should transition to bug_open and create a bug."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            task = orch.create_task(
                title="Bug test task",
                workstream="backend",
                acceptance_criteria=["Must compile"],
                owner="claude_code",
            )
            task_id = task["id"]
            orch.claim_next_task("claude_code")

            report = {
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "def456",
                "status": "done",
                "test_summary": {"command": "make test", "passed": 5, "failed": 2},
                "notes": "Some tests fail",
            }
            orch.ingest_report(report)

            result = orch.validate_task(task_id, passed=False, notes="Tests still failing", source="codex")
            self.assertEqual("bug_open", _get_task(orch, task_id)["status"])
            self.assertIn("bug_id", result)

            bugs = orch.list_bugs()
            self.assertGreaterEqual(len(bugs), 1)
            bug = next(b for b in bugs if b.get("source_task") == task_id)
            self.assertEqual("open", bug["status"])

    def test_blocked_then_resolved_lifecycle(self) -> None:
        """Task blocked by blocker, then unblocked after resolution."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            task = orch.create_task(
                title="Blocker lifecycle",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
            )
            task_id = task["id"]
            orch.claim_next_task("claude_code")
            self.assertEqual("in_progress", _get_task(orch, task_id)["status"])

            # Raise blocker
            blocker = orch.raise_blocker(task_id, "claude_code", "Need API spec")
            self.assertEqual("blocked", _get_task(orch, task_id)["status"])

            # Resolve blocker — agent is active, task should unblock
            orch.heartbeat("claude_code", metadata={
                "client": "test-client", "model": "test-model",
                "cwd": str(root), "project_root": str(root),
                "permissions_mode": "default", "sandbox_mode": "workspace-write",
                "session_id": "sess-cc", "connection_id": "cid-cc",
                "server_version": "0.1.0", "verification_source": "test",
            })
            orch.resolve_blocker(blocker["id"], "Spec provided", "codex")
            task_after = _get_task(orch, task_id)
            self.assertIn(task_after["status"], ("in_progress", "assigned"))

            # Now complete the task normally
            report = {
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "ghi789",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 3, "failed": 0},
            }
            orch.ingest_report(report)
            orch.validate_task(task_id, passed=True, notes="Complete", source="codex")
            self.assertEqual("done", _get_task(orch, task_id)["status"])

    def test_multiple_tasks_sequential(self) -> None:
        """Agent can complete multiple tasks sequentially."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            for i in range(3):
                task = orch.create_task(
                    title=f"Sequential task {i}",
                    workstream="backend",
                    acceptance_criteria=["done"],
                    owner="claude_code",
                )
                tid = task["id"]
                orch.claim_next_task("claude_code")
                orch.ingest_report({
                    "task_id": tid,
                    "agent": "claude_code",
                    "commit_sha": f"sha-{i}",
                    "status": "done",
                    "test_summary": {"command": "test", "passed": 1, "failed": 0},
                })
                orch.validate_task(tid, passed=True, notes="OK", source="codex")
                self.assertEqual("done", _get_task(orch, tid)["status"])

            # All 3 tasks should be done
            done_tasks = [t for t in orch.list_tasks() if t["status"] == "done"]
            self.assertGreaterEqual(len(done_tasks), 3)

    def test_report_wrong_owner_rejected(self) -> None:
        """Report from wrong agent should be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            task = orch.create_task(
                title="Owner check",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
            )
            tid = task["id"]
            orch.claim_next_task("claude_code")

            with self.assertRaises(ValueError) as ctx:
                orch.ingest_report({
                    "task_id": tid,
                    "agent": "gemini",
                    "commit_sha": "wrong",
                    "status": "done",
                    "test_summary": {"command": "test", "passed": 1, "failed": 0},
                })
            self.assertIn("does not match", str(ctx.exception))

    def test_validate_wrong_source_rejected(self) -> None:
        """Validation from non-leader should be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            task = orch.create_task(
                title="Leader check",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
            )
            tid = task["id"]
            orch.claim_next_task("claude_code")
            orch.ingest_report({
                "task_id": tid,
                "agent": "claude_code",
                "commit_sha": "abc",
                "status": "done",
                "test_summary": {"command": "test", "passed": 1, "failed": 0},
            })

            with self.assertRaises(ValueError) as ctx:
                orch.validate_task(tid, passed=True, notes="OK", source="claude_code")
            self.assertIn("leader_mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
