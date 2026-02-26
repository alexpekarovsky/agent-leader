"""Lease task-state transition table tests (TASK-c3d40c58).

Covers the full lease lifecycle through task status transitions:
- claim issues lease (assigned -> in_progress with lease fields)
- renew preserves in_progress status and extends expiry
- expired lease requeues task back to assigned
- reported task clears lease
Each test verifies expected task status and lease fields after transition.
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


def _full_metadata(root: Path, agent: str) -> dict:
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_agent(orch: Orchestrator, root: Path, agent: str) -> None:
    """Register and heartbeat an agent so it is operational."""
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))


class ClaimIssuesLeaseTests(unittest.TestCase):
    """Claiming a task transitions assigned -> in_progress with lease fields."""

    def test_claim_sets_status_to_in_progress(self) -> None:
        """After claim, task status must be in_progress."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Claim test task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])

    def test_claim_creates_lease_with_required_fields(self) -> None:
        """Lease dict must contain lease_id, owner, issued_at, expires_at, ttl_seconds."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Lease fields task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            lease = claimed.get("lease")
            self.assertIsNotNone(lease)
            self.assertIsInstance(lease, dict)
            self.assertTrue(lease["lease_id"].startswith("LEASE-"))
            self.assertEqual("claude_code", lease["owner"])
            self.assertIn("issued_at", lease)
            self.assertIn("renewed_at", lease)
            self.assertIn("expires_at", lease)
            self.assertIn("ttl_seconds", lease)
            self.assertEqual(300, lease["ttl_seconds"])

    def test_claim_persists_lease_to_disk(self) -> None:
        """Lease must be persisted to tasks.json on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Persist lease task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            tasks = orch._read_json(orch.tasks_path)
            persisted = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("in_progress", persisted["status"])
            self.assertIsNotNone(persisted.get("lease"))
            self.assertEqual(claimed["lease"]["lease_id"], persisted["lease"]["lease_id"])

    def test_claim_sets_claimed_at_timestamp(self) -> None:
        """Claimed task must have a claimed_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Timestamp task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertIn("claimed_at", claimed)
            self.assertIsNotNone(claimed["claimed_at"])

    def test_claim_owner_instance_id_populated(self) -> None:
        """Lease owner_instance_id should be populated after claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Instance id task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            lease = claimed["lease"]
            self.assertIn("owner_instance_id", lease)
            self.assertTrue(len(lease["owner_instance_id"]) > 0)


class RenewPreservesStatusTests(unittest.TestCase):
    """Renewing a lease preserves in_progress status and extends expiry."""

    def _claim_task(self, orch: Orchestrator, root: Path) -> dict:
        """Helper: create, register, claim a task."""
        _setup_agent(orch, root, "claude_code")
        orch.create_task(
            title="Renew test task",
            workstream="backend",
            owner="claude_code",
            acceptance_criteria=["done"],
        )
        return orch.claim_next_task("claude_code")

    def test_renew_keeps_status_in_progress(self) -> None:
        """After renewal, task status must remain in_progress."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = self._claim_task(orch, root)
            lease_id = claimed["lease"]["lease_id"]

            orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            tasks = orch._read_json(orch.tasks_path)
            task = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("in_progress", task["status"])

    def test_renew_extends_expires_at(self) -> None:
        """After renewal, expires_at must be later than original."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = self._claim_task(orch, root)
            lease_id = claimed["lease"]["lease_id"]
            original_expires = claimed["lease"]["expires_at"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertGreaterEqual(result["lease"]["expires_at"], original_expires)

    def test_renew_updates_renewed_at(self) -> None:
        """After renewal, renewed_at must differ from original."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = self._claim_task(orch, root)
            lease_id = claimed["lease"]["lease_id"]
            original_renewed = claimed["lease"]["renewed_at"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertNotEqual(original_renewed, result["lease"]["renewed_at"])

    def test_renew_preserves_lease_id(self) -> None:
        """Renewal must keep the same lease_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = self._claim_task(orch, root)
            lease_id = claimed["lease"]["lease_id"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertEqual(lease_id, result["lease"]["lease_id"])

    def test_renew_preserves_ttl_seconds(self) -> None:
        """Renewal must use the configured TTL from policy."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = self._claim_task(orch, root)
            lease_id = claimed["lease"]["lease_id"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertEqual(300, result["lease"]["ttl_seconds"])


class ExpiredLeaseRequeuesTests(unittest.TestCase):
    """Expired lease recovery transitions task back to assigned."""

    def _make_expired_task(self, orch: Orchestrator, root: Path) -> dict:
        """Create, claim, then expire a task lease."""
        _setup_agent(orch, root, "claude_code")
        orch.create_task(
            title="Expire me",
            workstream="backend",
            owner="claude_code",
            acceptance_criteria=["done"],
        )
        claimed = orch.claim_next_task("claude_code")
        # Manually expire the lease
        tasks = orch._read_json(orch.tasks_path)
        for t in tasks:
            if t["id"] == claimed["id"]:
                t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
        orch._write_json(orch.tasks_path, tasks)
        return claimed

    def test_expired_requeues_to_assigned(self) -> None:
        """Expired lease recovery must set status back to assigned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = self._make_expired_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("assigned", recovered["status"])

    def test_expired_clears_lease(self) -> None:
        """After recovery, the lease field must be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = self._make_expired_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(recovered.get("lease"))

    def test_expired_sets_lease_recovery_at(self) -> None:
        """Recovered task must have a lease_recovery_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = self._make_expired_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIn("lease_recovery_at", recovered)
            self.assertIsNotNone(recovered["lease_recovery_at"])

    def test_recovered_task_is_reclaimable(self) -> None:
        """After recovery to assigned, the task can be claimed again."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = self._make_expired_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(task["id"], reclaimed["id"])
            self.assertEqual("in_progress", reclaimed["status"])
            self.assertIsNotNone(reclaimed.get("lease"))


class ReportedTaskClearsLeaseTests(unittest.TestCase):
    """Submitting a report clears the lease from the task."""

    def test_report_clears_lease(self) -> None:
        """After ingest_report, lease must be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Report clears lease",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            # Confirm lease exists before report
            self.assertIsNotNone(claimed["lease"])

            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "python3 -m unittest", "passed": 1, "failed": 0},
            })

            tasks = orch._read_json(orch.tasks_path)
            reported = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(reported.get("lease"))

    def test_report_sets_status_to_reported(self) -> None:
        """After report, task status must be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Report status task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.claim_next_task("claude_code")

            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "def456",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 2, "failed": 0},
            })

            tasks = orch._read_json(orch.tasks_path)
            reported = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("reported", reported["status"])

    def test_report_sets_reported_at_timestamp(self) -> None:
        """After report, task must have reported_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Report timestamp task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.claim_next_task("claude_code")

            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "ghi789",
                "status": "done",
                "test_summary": {"command": "test", "passed": 1, "failed": 0},
            })

            tasks = orch._read_json(orch.tasks_path)
            reported = next(t for t in tasks if t["id"] == task["id"])
            self.assertIn("reported_at", reported)
            self.assertIsNotNone(reported["reported_at"])


class TransitionTableSummaryTests(unittest.TestCase):
    """Full transition sequence: assigned -> in_progress -> reported -> done."""

    def test_full_transition_sequence(self) -> None:
        """Walk through all lease-related transitions in one test."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            # Step 1: Create (status=assigned, no lease)
            task = orch.create_task(
                title="Full transition task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            self.assertEqual("assigned", task["status"])
            self.assertIsNone(task.get("lease"))

            # Step 2: Claim (status=in_progress, lease present)
            claimed = orch.claim_next_task("claude_code")
            self.assertEqual("in_progress", claimed["status"])
            self.assertIsNotNone(claimed["lease"])
            lease_id = claimed["lease"]["lease_id"]

            # Step 3: Renew (status=in_progress, lease extended)
            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)
            self.assertEqual("in_progress", orch._read_json(orch.tasks_path)[0]["status"])
            self.assertEqual(lease_id, result["lease"]["lease_id"])

            # Step 4: Report (status=reported, lease cleared)
            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "final",
                "status": "done",
                "test_summary": {"command": "test", "passed": 1, "failed": 0},
            })
            tasks = orch._read_json(orch.tasks_path)
            reported = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("reported", reported["status"])
            self.assertIsNone(reported.get("lease"))

            # Step 5: Validate (status=done)
            orch.validate_task(
                task_id=task["id"],
                passed=True,
                notes="All good",
                source="codex",
            )
            tasks = orch._read_json(orch.tasks_path)
            done = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("done", done["status"])


if __name__ == "__main__":
    unittest.main()
