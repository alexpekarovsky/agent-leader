"""Lease recovery tests — expired lease detection, requeue, reclaim,
multi-task recovery, and result structure validation.
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


def _expire_lease(orch: Orchestrator, task_id: str) -> None:
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == task_id:
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)


# ── Recovery ──────────────────────────────────────────────────────────


class LeaseRecoveryTests(unittest.TestCase):

    def test_expired_requeues_clears_and_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            _expire_lease(orch, claimed["id"])
            orch.heartbeat("claude_code", _meta(root, "claude_code"))
            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(1, result["recovered_count"])
            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("assigned", recovered["status"])
            self.assertIsNone(recovered.get("lease"))
            self.assertIn("T", recovered["lease_recovery_at"])

    def test_recovered_task_is_reclaimable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            _expire_lease(orch, claimed["id"])
            orch.heartbeat("claude_code", _meta(root, "claude_code"))
            orch.recover_expired_task_leases(source="codex")
            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(claimed["id"], reclaimed["id"])
            self.assertEqual("in_progress", reclaimed["status"])
            self.assertTrue(reclaimed["lease"]["lease_id"].startswith("LEASE-"))

    def test_non_expired_lease_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(0, result["recovered_count"])
            tasks = orch._read_json(orch.tasks_path)
            task = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("in_progress", task["status"])
            self.assertIsNotNone(task.get("lease"))

    def test_multiple_expired_all_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            ids = []
            for i in range(3):
                task = _create(orch, "claude_code", title=f"expire-{i}")
                c = orch.claim_next_task("claude_code")
                _expire_lease(orch, c["id"])
                ids.append(c["id"])
            orch.heartbeat("claude_code", _meta(root, "claude_code"))
            result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(3, result["recovered_count"])
            tasks = orch._read_json(orch.tasks_path)
            for tid in ids:
                r = next(t for t in tasks if t["id"] == tid)
                self.assertEqual("assigned", r["status"])
                self.assertIsNone(r.get("lease"))

    def test_recovery_result_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            _expire_lease(orch, claimed["id"])
            orch.heartbeat("claude_code", _meta(root, "claude_code"))
            result = orch.recover_expired_task_leases(source="codex")
            for key in ("recovered_count", "recovered", "active_agents", "threshold_seconds"):
                self.assertIn(key, result)
            self.assertIsInstance(result["recovered"], list)
            self.assertIsInstance(result["active_agents"], list)


if __name__ == "__main__":
    unittest.main()
