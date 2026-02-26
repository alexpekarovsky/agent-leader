"""CORE-03 lease ownership mismatch and stale-instance renewal rejection tests.

Covers: renewal by wrong agent, renewal by wrong instance_id, correct
agent+instance renewal succeeds, report by wrong agent, stale instance
renewal after re-registration, and descriptive error messages.
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
        "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str, session_id: str = "", instance_id: str = "") -> dict:
    sid = session_id or f"sess-{agent}"
    meta = {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": sid,
        "connection_id": f"conn-{agent}-{sid}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }
    if instance_id:
        meta["instance_id"] = instance_id
    return meta


def _setup_agent(orch: Orchestrator, root: Path, agent: str, session_id: str = "", instance_id: str = "") -> None:
    meta = _full_metadata(root, agent, session_id=session_id, instance_id=instance_id)
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


def _create_and_claim(orch: Orchestrator, root: Path, agent: str) -> dict:
    """Create a backend task owned by agent, then claim it."""
    task = orch.create_task(
        title="Ownership mismatch test task",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["done"],
    )
    claimed = orch.claim_next_task(agent)
    return claimed


class RenewalByWrongAgentTests(unittest.TestCase):
    """Renewal by a completely different agent should fail."""

    def test_wrong_agent_renewal_raises(self) -> None:
        """codex trying to renew claude_code's lease should fail with lease_owner_mismatch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "codex")
            claimed = _create_and_claim(orch, root, "claude_code")
            lease_id = claimed["lease"]["lease_id"]

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "codex", lease_id)
            self.assertIn("lease_owner_mismatch", str(ctx.exception))

    def test_wrong_agent_error_contains_both_names(self) -> None:
        """Error message should mention both the task owner and the requesting agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")
            claimed = _create_and_claim(orch, root, "claude_code")
            lease_id = claimed["lease"]["lease_id"]

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "gemini", lease_id)
            msg = str(ctx.exception)
            self.assertIn("claude_code", msg)
            self.assertIn("gemini", msg)


class RenewalByWrongInstanceTests(unittest.TestCase):
    """Renewal by the correct agent but wrong instance_id should fail."""

    def test_wrong_instance_id_raises_instance_mismatch(self) -> None:
        """Same agent with different instance_id should fail with lease_instance_mismatch."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Register with instance A
            _setup_agent(orch, root, "claude_code", instance_id="cc#instance-A")
            claimed = _create_and_claim(orch, root, "claude_code")
            lease_id = claimed["lease"]["lease_id"]

            # Now re-register with instance B (simulating a new session)
            _setup_agent(orch, root, "claude_code", session_id="sess-new", instance_id="cc#instance-B")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
            self.assertIn("lease_instance_mismatch", str(ctx.exception))

    def test_instance_mismatch_error_contains_both_instances(self) -> None:
        """Error message should mention both the lease instance and current instance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code", instance_id="cc#old-inst")
            claimed = _create_and_claim(orch, root, "claude_code")
            lease_id = claimed["lease"]["lease_id"]

            _setup_agent(orch, root, "claude_code", session_id="sess-new", instance_id="cc#new-inst")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
            msg = str(ctx.exception)
            self.assertIn("cc#old-inst", msg)
            self.assertIn("cc#new-inst", msg)


class CorrectRenewalTests(unittest.TestCase):
    """Renewal by correct agent + instance should succeed."""

    def test_correct_agent_and_instance_renews(self) -> None:
        """Renewal by the original agent with matching instance succeeds."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code", instance_id="cc#worker-01")
            claimed = _create_and_claim(orch, root, "claude_code")
            lease_id = claimed["lease"]["lease_id"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertEqual(claimed["id"], result["task_id"])
            self.assertEqual("claude_code", result["agent"])
            self.assertEqual(lease_id, result["lease"]["lease_id"])


class ReportByWrongAgentTests(unittest.TestCase):
    """Report submission by wrong agent should fail with owner mismatch."""

    def test_report_by_non_owner_raises(self) -> None:
        """gemini trying to report on claude_code's task should fail."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")
            claimed = _create_and_claim(orch, root, "claude_code")

            report = {
                "task_id": claimed["id"],
                "agent": "gemini",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
            }

            with self.assertRaises(ValueError) as ctx:
                orch.ingest_report(report)
            msg = str(ctx.exception)
            self.assertIn("gemini", msg)
            self.assertIn("claude_code", msg)


class StaleInstanceRenewalTests(unittest.TestCase):
    """Stale instance (re-registered with new session) trying to renew old lease."""

    def test_stale_instance_renewal_fails(self) -> None:
        """Agent that re-registered with a new session should not renew old lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Original session
            _setup_agent(orch, root, "claude_code", session_id="sess-original", instance_id="cc#orig")
            claimed = _create_and_claim(orch, root, "claude_code")
            lease_id = claimed["lease"]["lease_id"]

            # Re-register with new session (simulating restart)
            _setup_agent(orch, root, "claude_code", session_id="sess-restarted", instance_id="cc#restarted")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
            self.assertIn("lease_instance_mismatch", str(ctx.exception))

    def test_stale_instance_error_is_descriptive(self) -> None:
        """Error from stale instance renewal should contain instance identifiers."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code", session_id="sess-v1", instance_id="cc#v1")
            claimed = _create_and_claim(orch, root, "claude_code")
            lease_id = claimed["lease"]["lease_id"]

            _setup_agent(orch, root, "claude_code", session_id="sess-v2", instance_id="cc#v2")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
            msg = str(ctx.exception)
            # Should contain both old and new instance ids
            self.assertIn("cc#v1", msg)
            self.assertIn("cc#v2", msg)
            # Should be the instance mismatch error type
            self.assertIn("lease_instance_mismatch", msg)


if __name__ == "__main__":
    unittest.main()
