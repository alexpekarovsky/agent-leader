"""Lease edge-case tests — renewal validation, identity binding, ownership
mismatch, cooldown throttling, and error rejection paths.
"""

from __future__ import annotations

import json
import tempfile
import time
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


# ── Renewal rejection paths ──────────────────────────────────────────


class LeaseRenewalRejectionTests(unittest.TestCase):

    def test_empty_lease_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", "")
            self.assertIn("non-empty", str(ctx.exception))

    def test_task_not_found_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease("TASK-nonexistent", "claude_code", "LEASE-abc")
            self.assertIn("not found", str(ctx.exception).lower())

    def test_owner_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            _reg(orch, root, "gemini")
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "gemini", claimed["lease"]["lease_id"])
            msg = str(ctx.exception)
            self.assertIn("lease_owner_mismatch", msg)
            self.assertIn("claude_code", msg)
            self.assertIn("gemini", msg)

    def test_lease_id_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", "LEASE-wrong")
            self.assertIn("lease_id_mismatch", str(ctx.exception))

    def test_lease_missing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            task = _create(orch, "claude_code")
            orch.set_task_status(task["id"], "in_progress", "codex")
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(task["id"], "claude_code", "LEASE-fake")
            self.assertIn("lease_missing", str(ctx.exception))

    def test_expired_lease_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _claim(orch, root)
            _expire_lease(orch, claimed["id"])
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])
            self.assertIn("lease_expired", str(ctx.exception))

    def test_instance_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code", instance_id="cc#old")
            _create(orch, "claude_code")
            claimed = orch.claim_next_task("claude_code")
            lid = claimed["lease"]["lease_id"]
            _reg(orch, root, "claude_code", session_id="sess-new", instance_id="cc#new", connection_id="conn-new")
            with self.assertRaises(ValueError) as ctx:
                orch.renew_task_lease(claimed["id"], "claude_code", lid)
            msg = str(ctx.exception)
            self.assertIn("lease_instance_mismatch", msg)
            self.assertIn("cc#old", msg)
            self.assertIn("cc#new", msg)

    def test_ttl_minimum_is_30(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, lease_ttl_seconds=5)
            claimed = _claim(orch, root)
            r = orch.renew_task_lease(claimed["id"], "claude_code", claimed["lease"]["lease_id"])
            self.assertGreaterEqual(r["lease"]["ttl_seconds"], 30)


# ── Override edge cases ──────────────────────────────────────────────


class OverrideEdgeCaseTests(unittest.TestCase):

    def test_override_task_must_be_assigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            task = _create(orch, "claude_code")
            orch.set_task_status(task["id"], "in_progress", "codex")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            self.assertIsNone(orch.claim_next_task("claude_code"))

    def test_override_requires_leader_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            task = _create(orch, "claude_code")
            with self.assertRaises(ValueError) as ctx:
                orch.set_claim_override(agent="claude_code", task_id=task["id"], source="claude_code")
            self.assertIn("leader_mismatch", str(ctx.exception))


# ── Cooldown throttling ──────────────────────────────────────────────


class CooldownTests(unittest.TestCase):

    def test_first_empty_claim_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            self.assertIsNone(orch.claim_next_task("claude_code"))

    def test_rapid_second_empty_claim_throttled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            orch.claim_next_task("claude_code")
            second = orch.claim_next_task("claude_code")
            self.assertTrue(second.get("throttled"))
            for key in ("backoff_seconds", "cooldown_seconds", "message"):
                self.assertIn(key, second)
            self.assertGreater(second["backoff_seconds"], 0)

    def test_cooldown_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, claim_cooldown_seconds=0.1)
            _reg(orch, root, "claude_code")
            orch.claim_next_task("claude_code")
            time.sleep(0.15)
            self.assertIsNone(orch.claim_next_task("claude_code"))

    def test_successful_claim_clears_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            orch.claim_next_task("claude_code")  # sets cooldown
            _create(orch, "claude_code")          # mtime change bypasses cooldown
            claimed = orch.claim_next_task("claude_code")
            self.assertEqual("in_progress", claimed["status"])
            self.assertIsNone(orch.claim_next_task("claude_code"))  # cooldown cleared

    def test_cooldown_per_agent_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            _reg(orch, root, "gemini")
            orch.claim_next_task("claude_code")
            self.assertTrue(orch.claim_next_task("claude_code").get("throttled"))
            self.assertIsNone(orch.claim_next_task("gemini"))

    def test_zero_cooldown_disables_throttle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, claim_cooldown_seconds=0)
            _reg(orch, root, "claude_code")
            self.assertIsNone(orch.claim_next_task("claude_code"))
            self.assertIsNone(orch.claim_next_task("claude_code"))

    def test_default_cooldown_is_5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = {
                "name": "test-policy",
                "roles": {"manager": "codex"},
                "routing": {"default": "codex"},
                "decisions": {},
                "triggers": {"heartbeat_timeout_minutes": 10},
            }
            p = Path(tmp) / "policy.json"
            p.write_text(json.dumps(raw), encoding="utf-8")
            orch = Orchestrator(root=Path(tmp), policy=Policy.load(p))
            orch.bootstrap()
            self.assertEqual(5.0, orch._claim_cooldown_seconds())

    def test_engine_initiated_empty_claim_no_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            self.assertIsNone(orch.claim_next_task("claude_code", engine_initiated=True))
            self.assertIsNone(orch.claim_next_task("claude_code"))  # not throttled

    def test_override_bypasses_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, root, "claude_code")
            orch.claim_next_task("claude_code")  # sets cooldown
            task = _create(orch, "claude_code")
            orch.set_claim_override("claude_code", task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])


if __name__ == "__main__":
    unittest.main()
