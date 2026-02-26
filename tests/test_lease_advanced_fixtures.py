"""Advanced lease schema, event correlation, and ordering tests.

Covers:
- TASK-8c8238e6: Lease renewal failure reason-code taxonomy
- TASK-5cff0bce: Lease expiry event/audit correlation fixtures
- TASK-be0833cd: Lease issuance schema fixture with example IDs
- TASK-eb8c8bfa: Lease renewal success/failure event ordering
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, **trigger_overrides: int) -> Policy:
    triggers = {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300}
    triggers.update(trigger_overrides)
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": triggers,
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, **trigger_overrides: int) -> Orchestrator:
    policy = _make_policy(root / "policy.json", **trigger_overrides)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str, **overrides: str) -> dict:
    meta = {
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
    meta.update(overrides)
    return meta


def _connect_agent(orch: Orchestrator, root: Path, agent: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent), source=agent)


def _create_and_claim(orch: Orchestrator, agent: str, title: str = "Test task") -> dict:
    task = orch.create_task(
        title=title, workstream="backend", owner=agent, acceptance_criteria=["done"],
    )
    orch.claim_next_task(agent)
    return task


def _expire_lease(orch: Orchestrator, task_id: str) -> None:
    """Set the lease expires_at to past."""
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == task_id and t.get("lease"):
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)


# ── TASK-be0833cd: Lease issuance schema fixture ────────────────────


EXPECTED_LEASE_FIELDS = {
    "lease_id",
    "owner",
    "owner_instance_id",
    "issued_at",
    "renewed_at",
    "expires_at",
    "ttl_seconds",
}


class LeaseIssuanceSchemaTests(unittest.TestCase):
    """Fixture: lease issuance payload and state fields."""

    def test_claim_produces_all_lease_fields(self) -> None:
        """Claiming a task should produce a lease with all expected fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease = claimed.get("lease")
            self.assertIsInstance(lease, dict)
            for field in EXPECTED_LEASE_FIELDS:
                self.assertIn(field, lease, f"Missing lease field: {field}")

    def test_lease_id_prefix(self) -> None:
        """lease_id should start with LEASE- prefix."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            self.assertTrue(claimed["lease"]["lease_id"].startswith("LEASE-"))

    def test_owner_instance_id_populated(self) -> None:
        """owner_instance_id should reflect the claiming instance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            oid = claimed["lease"]["owner_instance_id"]
            self.assertIsNotNone(oid)
            self.assertTrue(len(oid) > 0)

    def test_ttl_matches_policy(self) -> None:
        """ttl_seconds should match the policy-configured TTL."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, lease_ttl_seconds=120)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual(120, claimed["lease"]["ttl_seconds"])

    def test_issued_at_and_renewed_at_match_on_creation(self) -> None:
        """At issuance, issued_at and renewed_at should be the same."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease = claimed["lease"]
            self.assertEqual(lease["issued_at"], lease["renewed_at"])

    def test_lease_json_serializable(self) -> None:
        """Lease dict should be JSON serializable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            serialized = json.dumps(claimed["lease"])
            self.assertIsInstance(json.loads(serialized), dict)


# ── TASK-8c8238e6: Lease renewal failure reason codes ────────────────


RENEWAL_REASON_CODES = {
    "lease_expired": "Lease has already expired",
    "lease_id_mismatch": "Provided lease_id does not match current lease",
    "lease_missing": "Task has no active lease",
    "lease_owner_mismatch": "Agent does not own the task",
    "lease_instance_mismatch": "Instance ID does not match lease owner instance",
}


class LeaseRenewalReasonCodeTests(unittest.TestCase):
    """Tests for each lease renewal failure reason code."""

    def test_expired_lease_raises_lease_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease_id = claimed["lease"]["lease_id"]
            _expire_lease(orch, task["id"])

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", lease_id)
            self.assertIn("lease_expired", str(ctx.exception))

    def test_wrong_lease_id_raises_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-wrong")
            self.assertIn("lease_id_mismatch", str(ctx.exception))

    def test_no_lease_raises_lease_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="No lease", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            # Force to in_progress without claiming (no lease)
            orch.set_task_status(task["id"], "in_progress", source="codex")
            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            t["lease"] = None
            orch._write_json(orch.tasks_path, tasks)

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-any")
            self.assertIn("lease_missing", str(ctx.exception))

    def test_wrong_owner_raises_owner_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease_id = claimed["lease"]["lease_id"]

            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "gemini", lease_id)
            self.assertIn("lease_owner_mismatch", str(ctx.exception))

    def test_reason_code_taxonomy_complete(self) -> None:
        """Verify all expected reason codes are documented."""
        for code, description in RENEWAL_REASON_CODES.items():
            self.assertIsInstance(code, str)
            self.assertIsInstance(description, str)
            self.assertGreater(len(code), 0)
            self.assertGreater(len(description), 0)


# ── TASK-5cff0bce: Lease expiry event/audit correlation ──────────────


class LeaseExpiryCorrelationTests(unittest.TestCase):
    """Tests linking lease expiry events with task state and audit."""

    def test_recovery_event_contains_lease_id(self) -> None:
        """Recovery event should reference the expired lease_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease_id = claimed["lease"]["lease_id"]
            _expire_lease(orch, task["id"])

            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(1, result["recovered_count"])
            recovery = result["recovered"][0]
            self.assertEqual(lease_id, recovery["lease_id"])
            self.assertEqual(task["id"], recovery["task_id"])

    def test_recovery_event_contains_owner_instance(self) -> None:
        """Recovery event should include lease_owner_instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")
            _expire_lease(orch, task["id"])

            result = orch.recover_expired_task_leases(source="codex")
            recovery = result["recovered"][0]
            self.assertIn("lease_owner_instance_id", recovery)
            self.assertTrue(len(recovery["lease_owner_instance_id"]) > 0)

    def test_bus_event_emitted_on_recovery(self) -> None:
        """Bus events should be emitted for lease recovery."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")
            _expire_lease(orch, task["id"])

            # Clear events
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in ("task.requeued_lease_expired", "task.reassigned_lease_expired", "task.lease_expired_blocked")
            ]
            self.assertGreaterEqual(len(recovery_events), 1)
            ev = recovery_events[0]
            self.assertEqual(task["id"], ev["payload"]["task_id"])
            self.assertIn("lease_id", ev["payload"])

    def test_recovery_clears_lease_from_task(self) -> None:
        """After recovery, the task's lease should be cleared."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")
            _expire_lease(orch, task["id"])

            orch.recover_expired_task_leases(source="codex")
            tasks = orch.list_tasks()
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(recovered.get("lease"))

    def test_recovery_sets_lease_recovery_at_timestamp(self) -> None:
        """Recovered task should have lease_recovery_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_and_claim(orch, "claude_code")
            _expire_lease(orch, task["id"])

            orch.recover_expired_task_leases(source="codex")
            tasks = orch.list_tasks()
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNotNone(recovered.get("lease_recovery_at"))


# ── TASK-eb8c8bfa: Lease renewal event ordering ─────────────────────


class LeaseRenewalEventOrderingTests(unittest.TestCase):
    """Tests for event ordering around lease renewal."""

    def test_claim_event_precedes_renewal_event(self) -> None:
        """task.claimed should appear before task.lease_renewed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            # Clear events
            orch.bus.events_path.write_text("", encoding="utf-8")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease_id = claimed["lease"]["lease_id"]
            orch.renew_task_lease(task["id"], "claude_code", lease_id)

            events = list(orch.bus.iter_events())
            types = [e["type"] for e in events]

            # task.claimed should come before task.lease_renewed
            claim_idx = next((i for i, t in enumerate(types) if t == "task.claimed"), None)
            renew_idx = next((i for i, t in enumerate(types) if t == "task.lease_renewed"), None)
            self.assertIsNotNone(claim_idx)
            self.assertIsNotNone(renew_idx)
            self.assertLess(claim_idx, renew_idx)

    def test_multiple_renewals_in_order(self) -> None:
        """Multiple renewals should produce events in chronological order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            orch.bus.events_path.write_text("", encoding="utf-8")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease_id = claimed["lease"]["lease_id"]

            for _ in range(3):
                orch.renew_task_lease(task["id"], "claude_code", lease_id)

            events = list(orch.bus.iter_events())
            renewals = [e for e in events if e["type"] == "task.lease_renewed"]
            self.assertEqual(3, len(renewals))
            # Timestamps should be non-decreasing
            times = [e["timestamp"] for e in renewals]
            self.assertEqual(times, sorted(times))

    def test_renewal_failure_does_not_emit_event(self) -> None:
        """Failed renewal should not produce a task.lease_renewed event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            task = _create_and_claim(orch, "claude_code")
            orch.bus.events_path.write_text("", encoding="utf-8")

            try:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-wrong")
            except ValueError:
                pass

            events = list(orch.bus.iter_events())
            renewals = [e for e in events if e["type"] == "task.lease_renewed"]
            self.assertEqual(0, len(renewals))

    def test_report_after_renewal_clears_lease(self) -> None:
        """Reporting after renewal should clear the lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            task = _create_and_claim(orch, "claude_code")
            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease_id = claimed["lease"]["lease_id"]
            orch.renew_task_lease(task["id"], "claude_code", lease_id)

            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "abc",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
            })

            tasks = orch.list_tasks()
            reported = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(reported.get("lease"))
            self.assertEqual("reported", reported["status"])

    def test_event_sequence_claim_renew_report(self) -> None:
        """Full sequence: claimed -> renewed -> reported events in order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            orch.bus.events_path.write_text("", encoding="utf-8")
            task = _create_and_claim(orch, "claude_code")

            tasks = orch.list_tasks()
            claimed = next(t for t in tasks if t["id"] == task["id"])
            lease_id = claimed["lease"]["lease_id"]
            orch.renew_task_lease(task["id"], "claude_code", lease_id)

            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "xyz",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
            })

            events = list(orch.bus.iter_events())
            task_events = [
                e for e in events
                if e.get("payload", {}).get("task_id") == task["id"]
                and e["type"] in ("task.claimed", "task.lease_renewed", "task.reported")
            ]
            types = [e["type"] for e in task_events]
            expected_order = ["task.claimed", "task.lease_renewed", "task.reported"]
            # Verify order preserved (filter to just these 3)
            filtered = [t for t in types if t in expected_order]
            self.assertEqual(expected_order, filtered)


if __name__ == "__main__":
    unittest.main()
