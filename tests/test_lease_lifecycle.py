"""Lease lifecycle tests — core claim/renew/report/validate behavior.

Covers: full transition sequence, claim field population, persistence,
backward compatibility, override claims, and multi-agent leasing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ── Shared helpers ────────────────────────────────────────────────────

def _make_policy(path: Path, **trigger_overrides) -> Policy:
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


def _make_orch(root: Path, **trigger_overrides) -> Orchestrator:
    policy = _make_policy(root / "policy.json", **trigger_overrides)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _meta(root: Path, agent: str, **overrides) -> dict:
    m = {
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
    m.update(overrides)
    return m


def _reg(orch: Orchestrator, root: Path, agent: str, **overrides) -> None:
    m = _meta(root, agent, **overrides)
    orch.register_agent(agent, m)
    orch.heartbeat(agent, m)


def _create(orch: Orchestrator, agent: str, title: str = "test task", ws: str = "backend") -> dict:
    return orch.create_task(title=title, workstream=ws, owner=agent, acceptance_criteria=["done"])


def _claim(orch: Orchestrator, root: Path, agent: str = "claude_code", title: str = "test task") -> dict:
    _reg(orch, root, agent)
    _create(orch, agent, title)
    return orch.claim_next_task(agent)


def _report(orch: Orchestrator, task_id: str, agent: str = "claude_code") -> None:
    orch.ingest_report({
        "task_id": task_id,
        "agent": agent,
        "commit_sha": "abc123",
        "status": "done",
        "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
    })


LEASE_FIELDS = {"lease_id", "owner", "owner_instance_id", "issued_at", "renewed_at", "expires_at", "ttl_seconds"}


# ── Lifecycle: claim -> renew -> report -> validate ───────────────────


class LeaseLifecycleTests(unittest.TestCase):

    def test_full_transition_sequence(self):
        """assigned -> in_progress (claim) -> renew -> reported -> done."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")

            # Create: assigned, no lease
            task = _create(orch, "claude_code")
            self.assertEqual("assigned", task["status"])
            self.assertIsNone(task.get("lease"))

            # Claim: in_progress, lease present
            claimed = orch.claim_next_task("claude_code")
            self.assertEqual("in_progress", claimed["status"])
            lease = claimed["lease"]
            self.assertIsNotNone(lease)
            self.assertTrue(lease["lease_id"].startswith("LEASE-"))

            # Renew: still in_progress, same lease_id, extended
            result = orch.renew_task_lease(claimed["id"], "claude_code", lease["lease_id"])
            self.assertEqual(lease["lease_id"], result["lease"]["lease_id"])
            self.assertGreaterEqual(result["lease"]["expires_at"], lease["expires_at"])

            # Report: reported, lease cleared
            _report(orch, task["id"])
            tasks = orch._read_json(orch.tasks_path)
            reported = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("reported", reported["status"])
            self.assertIsNone(reported.get("lease"))
            self.assertIn("reported_at", reported)

            # Validate: done
            orch.validate_task(task_id=task["id"], passed=True, notes="ok", source="codex")
            tasks = orch._read_json(orch.tasks_path)
            self.assertEqual("done", next(t for t in tasks if t["id"] == task["id"])["status"])

    def test_claim_creates_lease_with_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            lease = claimed["lease"]
            for field in LEASE_FIELDS:
                self.assertIn(field, lease, f"Missing: {field}")
            self.assertTrue(lease["lease_id"].startswith("LEASE-"))
            self.assertEqual("claude_code", lease["owner"])
            self.assertEqual(300, lease["ttl_seconds"])
            self.assertTrue(len(lease["owner_instance_id"]) > 0)

    def test_claim_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            tasks = orch._read_json(orch.tasks_path)
            persisted = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("in_progress", persisted["status"])
            self.assertEqual(claimed["lease"]["lease_id"], persisted["lease"]["lease_id"])

    def test_claim_response_backward_compat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            for field in ("id", "status", "owner", "title"):
                self.assertIn(field, claimed, f"Missing legacy field: {field}")
            serialized = json.dumps(claimed)
            self.assertIn("lease", json.loads(serialized))

    def test_claim_sets_claimed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            self.assertIn("T", claimed["claimed_at"])

    def test_second_claim_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            self.assertIsNotNone(claimed)
            self.assertIsNone(orch.claim_next_task("claude_code"))

    def test_no_task_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            orch._claim_cooldowns.clear()
            self.assertIsNone(orch.claim_next_task("claude_code"))

    def test_renew_extends_and_updates_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            lid = claimed["lease"]["lease_id"]
            result = orch.renew_task_lease(claimed["id"], "claude_code", lid)
            self.assertEqual(lid, result["lease"]["lease_id"])
            self.assertGreaterEqual(result["lease"]["expires_at"], claimed["lease"]["expires_at"])
            self.assertNotEqual(claimed["lease"]["renewed_at"], result["lease"]["renewed_at"])
            self.assertEqual(300, result["lease"]["ttl_seconds"])

    def test_multiple_renewals_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            lid = claimed["lease"]["lease_id"]
            for _ in range(3):
                r = orch.renew_task_lease(claimed["id"], "claude_code", lid)
                self.assertEqual(lid, r["lease"]["lease_id"])

    def test_renew_emits_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])
            events = [e for e in orch.bus.iter_events() if e.get("type") == "task.lease_renewed"]
            self.assertEqual(1, len(events))
            self.assertEqual(claimed["id"], events[0]["payload"]["task_id"])

    def test_report_by_non_owner_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            _reg(orch, root, "gemini")
            with self.assertRaises(ValueError) as ctx:
                _report(orch, claimed["id"], agent="gemini")
            msg = str(ctx.exception)
            self.assertIn("gemini", msg)
            self.assertIn("claude_code", msg)

    # -- Override claims --

    def test_override_claim_issues_lease_with_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            task = _create(orch, "claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual(task["id"], claimed["id"])
            lease = claimed["lease"]
            for field in LEASE_FIELDS:
                self.assertIn(field, lease, f"Missing: {field}")
            self.assertTrue(lease["lease_id"].startswith("LEASE-"))
            self.assertEqual("claude_code", lease["owner"])

    def test_override_and_normal_lease_structure_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            t1 = _create(orch, "claude_code", "normal")
            orch.claim_next_task("claude_code")
            t2 = _create(orch, "claude_code", "override")
            orch.set_claim_override(agent="claude_code", task_id=t2["id"], source="codex")
            orch.claim_next_task("claude_code")
            tasks = orch.list_tasks()
            l1 = next(t for t in tasks if t["id"] == t1["id"])["lease"]
            l2 = next(t for t in tasks if t["id"] == t2["id"])["lease"]
            self.assertEqual(set(l1.keys()), set(l2.keys()))

    def test_override_ttl_matches_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, lease_ttl_seconds=180)
            _reg(orch, root, "claude_code")
            task = _create(orch, "claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            orch.claim_next_task("claude_code")
            tasks = orch.list_tasks()
            t = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual(180, t["lease"]["ttl_seconds"])

    def test_override_consumed_after_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            task = _create(orch, "claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            self.assertIn("claude_code", orch._read_json(orch.claim_overrides_path))
            orch.claim_next_task("claude_code")
            self.assertNotIn("claude_code", orch._read_json(orch.claim_overrides_path))

    def test_override_instance_id_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code", instance_id="cc#w42")
            task = _create(orch, "claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")
            self.assertEqual("cc#w42", claimed["lease"]["owner_instance_id"])

    def test_different_agent_gets_own_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "gemini")
            _create(orch, "gemini", ws="frontend")
            claimed = orch.claim_next_task("gemini")
            self.assertEqual("gemini", claimed["lease"]["owner"])
            self.assertEqual("in_progress", claimed["status"])


if __name__ == "__main__":
    unittest.main()
