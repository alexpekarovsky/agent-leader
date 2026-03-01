"""Tests for unsupervised run stop/escalation policy.

Validates that evaluate_stop_policy() fires the correct triggers
based on policy thresholds and live state, and remains inert when
the policy is disabled.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, **trigger_overrides: object) -> Policy:
    triggers = {
        "heartbeat_timeout_minutes": 10,
        "unsupervised_stop_enabled": True,
        "stop_max_open_bugs": 3,
        "stop_max_open_blockers": 4,
        "stop_max_validation_failures_per_task": 2,
        "stop_on_integrity_mismatch": True,
        "stop_on_deploy_mismatch": False,
    }
    triggers.update(trigger_overrides)
    raw = {
        "name": "test-stop-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "default": "codex"},
        "decisions": {},
        "triggers": triggers,
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, **trigger_overrides: object) -> Orchestrator:
    policy = _make_policy(root / "policy.json", **trigger_overrides)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


_AGENT_META = {
    "client": "test", "model": "test",
    "permissions_mode": "default", "sandbox_mode": "workspace-write",
    "session_id": "test-session", "connection_id": "test-conn",
    "server_version": "0.1.0", "verification_source": "test",
}


def _create_and_claim(orch: Orchestrator, title: str, owner: str) -> str:
    task = orch.create_task(
        title=title, workstream="backend",
        acceptance_criteria=["done"], owner=owner,
    )
    task_id = task["id"]
    meta = dict(_AGENT_META, cwd=str(orch.root), project_root=str(orch.root))
    orch.register_agent(owner, meta)
    orch.claim_next_task(owner)
    return task_id


def _submit_report(orch: Orchestrator, task_id: str, agent: str) -> None:
    """Submit a minimal report to transition a task to 'reported'."""
    orch.ingest_report({
        "task_id": task_id,
        "agent": agent,
        "commit_sha": "abc123",
        "status": "done",
        "test_summary": {"command": "echo ok", "passed": 1, "failed": 0},
    })


class StopPolicyDisabledTests(unittest.TestCase):
    """When the policy is disabled, evaluate_stop_policy should be inert."""

    def test_disabled_returns_no_stop(self) -> None:
        """With unsupervised_stop_enabled=False, no triggers fire."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, unsupervised_stop_enabled=False)

            # Create state that would normally fire triggers.
            task_id = _create_and_claim(orch, "Task 1", "claude_code")
            orch.raise_blocker(task_id=task_id, agent="claude_code", question="Q")

            result = orch.evaluate_stop_policy()

            self.assertFalse(result["stop_required"])
            self.assertFalse(result["policy_enabled"])
            self.assertEqual([], result["triggers"])
            self.assertEqual([], result["reason_codes"])


class BugThresholdTriggerTests(unittest.TestCase):
    """Tests for the bug_threshold_exceeded trigger."""

    def test_fires_when_bugs_exceed_threshold(self) -> None:
        """Stop should fire when open bug count >= threshold."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, stop_max_open_bugs=2)

            # Create tasks and generate bugs via failed validations.
            for i in range(2):
                tid = _create_and_claim(orch, f"Bug task {i}", "claude_code")
                # Submit a report then fail validation to create an open bug.
                _submit_report(orch, tid, "claude_code")
                orch.validate_task(tid, passed=False, notes=f"fail {i}", source="codex")

            result = orch.evaluate_stop_policy()

            self.assertTrue(result["stop_required"])
            self.assertIn("bug_threshold_exceeded", result["reason_codes"])

    def test_does_not_fire_below_threshold(self) -> None:
        """No trigger when bug count is below threshold."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, stop_max_open_bugs=5)

            # Create one bug - below threshold of 5.
            tid = _create_and_claim(orch, "Single bug task", "claude_code")
            _submit_report(orch, tid, "claude_code")
            orch.validate_task(tid, passed=False, notes="fail once", source="codex")

            result = orch.evaluate_stop_policy()

            self.assertNotIn("bug_threshold_exceeded", result["reason_codes"])


class BlockerGrowthTriggerTests(unittest.TestCase):
    """Tests for the blocker_growth_exceeded trigger."""

    def test_fires_when_blockers_exceed_threshold(self) -> None:
        """Stop should fire when open blocker count >= threshold."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, stop_max_open_blockers=2)

            # Create separate tasks so each can have its own blocker.
            for i in range(2):
                tid = _create_and_claim(orch, f"Blocker task {i}", "claude_code")
                orch.raise_blocker(task_id=tid, agent="claude_code", question=f"Q{i}")

            result = orch.evaluate_stop_policy()

            self.assertTrue(result["stop_required"])
            self.assertIn("blocker_growth_exceeded", result["reason_codes"])


class ValidationFailureTriggerTests(unittest.TestCase):
    """Tests for the repeated_validation_failure trigger."""

    def test_fires_on_repeated_failures(self) -> None:
        """Stop should fire when a single task has >= threshold validation failures."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, stop_max_validation_failures_per_task=2)

            tid = _create_and_claim(orch, "Repeated fail task", "claude_code")

            # First failure.
            _submit_report(orch, tid, "claude_code")
            orch.validate_task(tid, passed=False, notes="attempt 1", source="codex")
            # Task is now bug_open.  Submit again and fail again.
            _submit_report(orch, tid, "claude_code")
            orch.validate_task(tid, passed=False, notes="attempt 2", source="codex")

            result = orch.evaluate_stop_policy()

            self.assertTrue(result["stop_required"])
            codes = result["reason_codes"]
            self.assertIn("repeated_validation_failure", codes)
            # Verify the trigger references the specific task.
            trigger = next(t for t in result["triggers"] if t["code"] == "repeated_validation_failure")
            self.assertEqual(tid, trigger["task_id"])


class ContinueCaseTests(unittest.TestCase):
    """When all metrics are within bounds, no stop is required."""

    def test_clean_state_no_stop(self) -> None:
        """Policy enabled but no thresholds exceeded -> continue."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Create a healthy task that passes validation.
            tid = _create_and_claim(orch, "Healthy task", "claude_code")
            _submit_report(orch, tid, "claude_code")
            orch.validate_task(tid, passed=True, notes="all good", source="codex")

            result = orch.evaluate_stop_policy()

            self.assertFalse(result["stop_required"])
            self.assertTrue(result["policy_enabled"])
            self.assertEqual([], result["triggers"])

    def test_below_all_thresholds_no_stop(self) -> None:
        """One bug and one blocker, both below thresholds -> continue."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, stop_max_open_bugs=3, stop_max_open_blockers=4)

            # One failed validation = 1 bug (threshold 3).
            t1 = _create_and_claim(orch, "Some task", "claude_code")
            _submit_report(orch, t1, "claude_code")
            orch.validate_task(t1, passed=False, notes="minor", source="codex")

            # One blocker (threshold 4).
            t2 = _create_and_claim(orch, "Blocked task", "claude_code")
            orch.raise_blocker(task_id=t2, agent="claude_code", question="Q")

            result = orch.evaluate_stop_policy()

            self.assertFalse(result["stop_required"])
            self.assertEqual([], result["reason_codes"])


class AuditTrailTests(unittest.TestCase):
    """Verify that stop policy triggers emit audit events."""

    def test_audit_emitted_on_stop(self) -> None:
        """When stop fires, an audit record with category=stop_policy is written."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, stop_max_open_bugs=1)

            tid = _create_and_claim(orch, "Audit task", "claude_code")
            _submit_report(orch, tid, "claude_code")
            orch.validate_task(tid, passed=False, notes="fail", source="codex")

            result = orch.evaluate_stop_policy()
            self.assertTrue(result["stop_required"])

            # Check audit log for stop_policy entry.
            audits = list(orch.bus.read_audit(limit=50))
            stop_audits = [a for a in audits if a.get("category") == "stop_policy"]
            self.assertGreaterEqual(len(stop_audits), 1)
            self.assertEqual("stop_triggered", stop_audits[-1]["action"])
            self.assertIn("bug_threshold_exceeded", stop_audits[-1]["reason_codes"])

    def test_no_audit_when_clean(self) -> None:
        """No audit entry emitted when no triggers fire."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.evaluate_stop_policy()
            self.assertFalse(result["stop_required"])

            audits = list(orch.bus.read_audit(limit=50))
            stop_audits = [a for a in audits if a.get("category") == "stop_policy"]
            self.assertEqual(0, len(stop_audits))


if __name__ == "__main__":
    unittest.main()
