"""Integration tests for full task lifecycle with report validation.

Exercises: create -> claim -> heartbeat -> submit report -> validate -> done.
Verifies all state transitions and task record consistency at each step.
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


class FullLifecycleTests(unittest.TestCase):
    """End-to-end task lifecycle: create -> claim -> heartbeat -> report -> validate -> done."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_full_lifecycle_happy_path(self) -> None:
        """Complete lifecycle from create through validate to done."""
        # 1. Create task
        task = self.orch.create_task(
            title="Test lifecycle task",
            workstream="backend",
            acceptance_criteria=["Criterion A", "Criterion B"],
            description="Integration test task",
        )
        task_id = task["id"]
        self.assertEqual(task["status"], "assigned")
        self.assertEqual(task["owner"], "claude_code")

        # 2. Claim task
        claimed = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], task_id)
        self.assertEqual(claimed["status"], "in_progress")

        # Verify persisted state
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(found["status"], "in_progress")

        # 3. Heartbeat
        hb = self.orch.heartbeat(agent="claude_code")
        self.assertEqual(hb["status"], "active")

        # 4. Submit report
        report = self.orch.ingest_report({
            "task_id": task_id,
            "agent": "claude_code",
            "commit_sha": "abc123",
            "status": "done",
            "test_summary": {"command": "python3 -m unittest", "passed": 5, "failed": 0},
        })
        self.assertEqual(report["task_id"], task_id)

        # Verify task is now 'reported'
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(found["status"], "reported")

        # 5. Validate (manager accepts)
        result = self.orch.validate_task(
            task_id=task_id,
            passed=True,
            notes="All criteria met",
            source="codex",
        )
        self.assertEqual(result["task_id"], task_id)

        # 6. Verify final state is 'done'
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(found["status"], "done")

    def test_lifecycle_validation_failure_reopens_task(self) -> None:
        """When validation fails, task goes to bug_open instead of done."""
        task = self.orch.create_task(
            title="Failing validation task",
            workstream="backend",
            acceptance_criteria=["Must pass"],
        )
        task_id = task["id"]

        self.orch.claim_next_task(owner="claude_code")
        self.orch.ingest_report({
            "task_id": task_id,
            "agent": "claude_code",
            "commit_sha": "def456",
            "status": "done",
            "test_summary": {"command": "pytest", "passed": 0, "failed": 1},
        })

        result = self.orch.validate_task(
            task_id=task_id,
            passed=False,
            notes="Criterion not met",
            source="codex",
        )
        self.assertIn("bug_id", result)

        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(found["status"], "bug_open")

    def test_lifecycle_claim_returns_none_when_no_tasks(self) -> None:
        """claim_next_task returns None when no tasks are assigned."""
        result = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNone(result)

    def test_lifecycle_double_claim_returns_none(self) -> None:
        """Second claim after first returns None (no more assigned tasks)."""
        self.orch.create_task(
            title="Single task",
            workstream="backend",
            acceptance_criteria=["Done"],
        )
        first = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNotNone(first)
        second = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNone(second)

    def test_lifecycle_report_wrong_agent_rejected(self) -> None:
        """Report from non-owner agent is rejected."""
        _register_agent(self.orch, "gemini")
        task = self.orch.create_task(
            title="Owner-check task",
            workstream="backend",
            acceptance_criteria=["Check"],
        )
        self.orch.claim_next_task(owner="claude_code")

        with self.assertRaises(ValueError) as ctx:
            self.orch.ingest_report({
                "task_id": task["id"],
                "agent": "gemini",
                "commit_sha": "bad",
                "status": "done",
                "test_summary": {"command": "test", "passed": 1, "failed": 0},
            })
        self.assertIn("does not match", str(ctx.exception))

    def test_lifecycle_validate_non_leader_rejected(self) -> None:
        """Validation from non-leader source is rejected."""
        task = self.orch.create_task(
            title="Leader-check task",
            workstream="backend",
            acceptance_criteria=["Check"],
        )
        self.orch.claim_next_task(owner="claude_code")
        self.orch.ingest_report({
            "task_id": task["id"],
            "agent": "claude_code",
            "commit_sha": "xyz",
            "status": "done",
            "test_summary": {"command": "test", "passed": 1, "failed": 0},
        })

        with self.assertRaises(ValueError) as ctx:
            self.orch.validate_task(
                task_id=task["id"],
                passed=True,
                notes="Unauthorized",
                source="claude_code",
            )
        self.assertIn("leader_mismatch", str(ctx.exception))


class LifecycleEventTests(unittest.TestCase):
    """Verify events emitted during the task lifecycle."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_lifecycle_events_emitted_in_order(self) -> None:
        """Full lifecycle should emit task.assigned, task.reported, validation.passed."""
        task = self.orch.create_task(
            title="Event tracking task",
            workstream="backend",
            acceptance_criteria=["Events checked"],
        )
        task_id = task["id"]

        self.orch.claim_next_task(owner="claude_code")
        self.orch.heartbeat(agent="claude_code")
        self.orch.ingest_report({
            "task_id": task_id,
            "agent": "claude_code",
            "commit_sha": "evt123",
            "status": "done",
            "test_summary": {"command": "test", "passed": 1, "failed": 0},
        })
        self.orch.validate_task(
            task_id=task_id, passed=True, notes="OK", source="codex",
        )

        all_events = list(self.orch.bus.iter_events())
        event_types = [e["type"] for e in all_events]
        self.assertIn("task.assigned", event_types)
        self.assertIn("task.reported", event_types)
        self.assertIn("validation.passed", event_types)

        # Verify ordering: assigned before reported before passed
        assigned_idx = next(i for i, t in enumerate(event_types) if t == "task.assigned")
        reported_idx = next(i for i, t in enumerate(event_types) if t == "task.reported")
        passed_idx = next(i for i, t in enumerate(event_types) if t == "validation.passed")
        self.assertLess(assigned_idx, reported_idx)
        self.assertLess(reported_idx, passed_idx)

    def test_heartbeat_emits_event(self) -> None:
        """Heartbeat should emit agent.heartbeat event."""
        self.orch.heartbeat(agent="claude_code")
        all_events = list(self.orch.bus.iter_events())
        hb_events = [e for e in all_events if e["type"] == "agent.heartbeat"]
        self.assertGreater(len(hb_events), 0)
        self.assertEqual(hb_events[-1]["payload"]["agent"], "claude_code")

    def test_validation_failed_emits_event(self) -> None:
        """Failed validation emits validation.failed event."""
        task = self.orch.create_task(
            title="Fail event task",
            workstream="backend",
            acceptance_criteria=["Check"],
        )
        self.orch.claim_next_task(owner="claude_code")
        self.orch.ingest_report({
            "task_id": task["id"],
            "agent": "claude_code",
            "commit_sha": "fail1",
            "status": "done",
            "test_summary": {"command": "test", "passed": 0, "failed": 1},
        })
        self.orch.validate_task(
            task_id=task["id"], passed=False, notes="Bad", source="codex",
        )

        all_events = list(self.orch.bus.iter_events())
        fail_events = [e for e in all_events if e["type"] == "validation.failed"]
        self.assertGreater(len(fail_events), 0)
        self.assertEqual(fail_events[-1]["payload"]["task_id"], task["id"])


class LifecycleConsistencyTests(unittest.TestCase):
    """Verify task record consistency at each step."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_task_record_fields_at_each_step(self) -> None:
        """Task should have all expected fields and correct owner throughout."""
        task = self.orch.create_task(
            title="Consistency task",
            workstream="backend",
            acceptance_criteria=["A"],
            description="desc",
        )
        task_id = task["id"]

        # After create
        self.assertIn("id", task)
        self.assertIn("title", task)
        self.assertIn("workstream", task)
        self.assertIn("owner", task)
        self.assertIn("status", task)
        self.assertIn("acceptance_criteria", task)
        self.assertIn("created_at", task)
        self.assertIn("updated_at", task)
        self.assertEqual(task["owner"], "claude_code")

        # After claim
        self.orch.claim_next_task(owner="claude_code")
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(found["owner"], "claude_code")
        self.assertEqual(found["status"], "in_progress")

        # After report
        self.orch.ingest_report({
            "task_id": task_id,
            "agent": "claude_code",
            "commit_sha": "con123",
            "status": "done",
            "test_summary": {"command": "test", "passed": 1, "failed": 0},
        })
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(found["owner"], "claude_code")
        self.assertEqual(found["status"], "reported")

        # After validate
        self.orch.validate_task(
            task_id=task_id, passed=True, notes="OK", source="codex",
        )
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(found["owner"], "claude_code")
        self.assertEqual(found["status"], "done")

    def test_updated_at_advances_each_step(self) -> None:
        """updated_at should change at claim, report, and validate."""
        task = self.orch.create_task(
            title="Timestamp task",
            workstream="backend",
            acceptance_criteria=["A"],
        )
        task_id = task["id"]
        created_at = task["updated_at"]

        self.orch.claim_next_task(owner="claude_code")
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        claimed_at = found["updated_at"]
        self.assertGreaterEqual(claimed_at, created_at)

        self.orch.ingest_report({
            "task_id": task_id,
            "agent": "claude_code",
            "commit_sha": "ts1",
            "status": "done",
            "test_summary": {"command": "test", "passed": 1, "failed": 0},
        })
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        reported_at = found["updated_at"]
        self.assertGreaterEqual(reported_at, claimed_at)

        self.orch.validate_task(
            task_id=task_id, passed=True, notes="OK", source="codex",
        )
        tasks = self.orch.list_tasks()
        found = next(t for t in tasks if t["id"] == task_id)
        done_at = found["updated_at"]
        self.assertGreaterEqual(done_at, reported_at)

    def test_report_missing_fields_rejected(self) -> None:
        """Report with missing required fields should raise ValueError."""
        task = self.orch.create_task(
            title="Missing fields task",
            workstream="backend",
            acceptance_criteria=["A"],
        )
        self.orch.claim_next_task(owner="claude_code")

        with self.assertRaises(ValueError) as ctx:
            self.orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                # missing commit_sha, status, test_summary
            })
        self.assertIn("Missing report fields", str(ctx.exception))

    def test_multiple_tasks_lifecycle(self) -> None:
        """Two tasks can go through full lifecycle independently."""
        t1 = self.orch.create_task(
            title="Multi task A",
            workstream="backend",
            acceptance_criteria=["A"],
        )
        t2 = self.orch.create_task(
            title="Multi task B",
            workstream="backend",
            acceptance_criteria=["B"],
        )

        # Claim and complete first
        self.orch.claim_next_task(owner="claude_code")
        self.orch.ingest_report({
            "task_id": t1["id"],
            "agent": "claude_code",
            "commit_sha": "m1",
            "status": "done",
            "test_summary": {"command": "test", "passed": 1, "failed": 0},
        })
        self.orch.validate_task(task_id=t1["id"], passed=True, notes="OK", source="codex")

        # Second task still claimable
        claimed = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], t2["id"])

        self.orch.ingest_report({
            "task_id": t2["id"],
            "agent": "claude_code",
            "commit_sha": "m2",
            "status": "done",
            "test_summary": {"command": "test", "passed": 1, "failed": 0},
        })
        self.orch.validate_task(task_id=t2["id"], passed=True, notes="OK", source="codex")

        # Both done
        tasks = self.orch.list_tasks()
        statuses = {t["id"]: t["status"] for t in tasks}
        self.assertEqual(statuses[t1["id"]], "done")
        self.assertEqual(statuses[t2["id"]], "done")


if __name__ == "__main__":
    unittest.main()
