"""CORE-02 post-restart three-worker visibility acceptance scenario fixture.

Simulates the exact post-restart acceptance scenario:
- 1 Codex manager instance
- 3 Claude Code worker instances (same agent family, different sessions)
- 1 Gemini worker instance

All must be visible in list_agent_instances with correct fields, sorted
by (agent_name, instance_id), with Claude family duplicates distinguished
by instance_id.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _full_metadata(root: Path, agent: str, instance_id: str, session_id: str) -> dict:
    return {
        "role": "team_member" if agent != "codex" else "leader",
        "instance_id": instance_id,
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": session_id,
        "connection_id": f"conn-{instance_id}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_full_team(orch: Orchestrator, root: Path) -> None:
    """Register and heartbeat the full 5-instance team."""
    agents = [
        ("codex", "codex-mgr-01", "sess-codex-01"),
        ("claude_code", "cc-sess-alpha", "sess-cc-alpha"),
        ("claude_code", "cc-sess-beta", "sess-cc-beta"),
        ("claude_code", "cc-sess-gamma", "sess-cc-gamma"),
        ("gemini", "gem-sess-01", "sess-gem-01"),
    ]
    for agent, inst_id, sess_id in agents:
        meta = _full_metadata(root, agent, inst_id, sess_id)
        orch.register_agent(agent, meta)
        orch.heartbeat(agent, meta)


# ---------------------------------------------------------------------------
# 1. Full team visibility
# ---------------------------------------------------------------------------

class FullTeamVisibilityTests(unittest.TestCase):
    """All 5 instances must be visible in list_agent_instances."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _setup_full_team(self.orch, self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_total_instance_count(self) -> None:
        instances = self.orch.list_agent_instances()
        self.assertEqual(len(instances), 5)

    def test_claude_code_has_three_instances(self) -> None:
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        self.assertEqual(len(cc), 3)

    def test_codex_has_one_instance(self) -> None:
        instances = self.orch.list_agent_instances()
        codex = [i for i in instances if i["agent_name"] == "codex"]
        self.assertEqual(len(codex), 1)

    def test_gemini_has_one_instance(self) -> None:
        instances = self.orch.list_agent_instances()
        gem = [i for i in instances if i["agent_name"] == "gemini"]
        self.assertEqual(len(gem), 1)

    def test_all_instances_have_agent_name(self) -> None:
        instances = self.orch.list_agent_instances()
        for inst in instances:
            self.assertIn("agent_name", inst)
            self.assertIsNotNone(inst["agent_name"])

    def test_all_instances_have_instance_id(self) -> None:
        instances = self.orch.list_agent_instances()
        for inst in instances:
            self.assertIn("instance_id", inst)
            self.assertIsNotNone(inst["instance_id"])


# ---------------------------------------------------------------------------
# 2. Claude family duplicate distinction
# ---------------------------------------------------------------------------

class ClaudeFamilyDuplicateTests(unittest.TestCase):
    """Three Claude instances must have distinct instance_ids."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _setup_full_team(self.orch, self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_claude_instances_have_distinct_ids(self) -> None:
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        ids = [i["instance_id"] for i in cc]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 3)

    def test_claude_instances_are_all_active(self) -> None:
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        for inst in cc:
            self.assertEqual(inst["status"], "active")

    def test_claude_instance_ids_are_expected(self) -> None:
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        ids = {i["instance_id"] for i in cc}
        self.assertEqual(ids, {"cc-sess-alpha", "cc-sess-beta", "cc-sess-gamma"})

    def test_claude_instances_share_agent_name(self) -> None:
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        for inst in cc:
            self.assertEqual(inst["agent_name"], "claude_code")
            self.assertEqual(inst["agent"], "claude_code")


# ---------------------------------------------------------------------------
# 3. Sort order with duplicates
# ---------------------------------------------------------------------------

class SortOrderWithDuplicatesTests(unittest.TestCase):
    """Sorted by (agent_name, instance_id) ascending with family duplicates."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _setup_full_team(self.orch, self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_agents_sorted_alphabetically(self) -> None:
        instances = self.orch.list_agent_instances()
        names = [i["agent_name"] for i in instances]
        # claude_code (x3) < codex (x1) < gemini (x1)
        self.assertEqual(names[:3], ["claude_code"] * 3)
        self.assertEqual(names[3], "codex")
        self.assertEqual(names[4], "gemini")

    def test_claude_instances_sorted_by_instance_id(self) -> None:
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        ids = [i["instance_id"] for i in cc]
        self.assertEqual(ids, sorted(ids))

    def test_full_sort_is_deterministic(self) -> None:
        first = [(i["agent_name"], i["instance_id"]) for i in self.orch.list_agent_instances()]
        second = [(i["agent_name"], i["instance_id"]) for i in self.orch.list_agent_instances()]
        self.assertEqual(first, second)

    def test_pairs_are_fully_sorted(self) -> None:
        instances = self.orch.list_agent_instances()
        pairs = [(i["agent_name"], i["instance_id"]) for i in instances]
        self.assertEqual(pairs, sorted(pairs))


# ---------------------------------------------------------------------------
# 4. Post-restart: all previously active, re-registered
# ---------------------------------------------------------------------------

class PostRestartReRegistrationTests(unittest.TestCase):
    """Simulates restart: deregister all, re-register, verify visibility."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_restart_sequence_recovers_full_visibility(self) -> None:
        """Register team → make stale → re-register → all active."""
        _setup_full_team(self.orch, self.root)
        instances = self.orch.list_agent_instances()
        self.assertEqual(len(instances), 5)

        # Simulate restart: all agents go stale
        agents_data = self.orch._read_json(self.orch.agents_path)
        for name in agents_data:
            agents_data[name]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch._write_json(self.orch.agents_path, agents_data)
        inst_data = self.orch._read_json(self.orch.agent_instances_path)
        for key in inst_data:
            inst_data[key]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch._write_json(self.orch.agent_instances_path, inst_data)

        # All should be offline now
        offline = self.orch.list_agent_instances()
        for inst in offline:
            self.assertEqual(inst["status"], "offline")

        # Re-register (simulates restart)
        _setup_full_team(self.orch, self.root)

        # All should be active again
        restarted = self.orch.list_agent_instances()
        self.assertEqual(len(restarted), 5)
        for inst in restarted:
            self.assertEqual(inst["status"], "active",
                             f"{inst['agent_name']}:{inst['instance_id']} not active")

    def test_restart_preserves_instance_ids(self) -> None:
        """After restart, instance_ids should match original registration."""
        _setup_full_team(self.orch, self.root)
        original_ids = {i["instance_id"] for i in self.orch.list_agent_instances()}

        # Make stale then re-register
        agents_data = self.orch._read_json(self.orch.agents_path)
        for name in agents_data:
            agents_data[name]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch._write_json(self.orch.agents_path, agents_data)
        inst_data = self.orch._read_json(self.orch.agent_instances_path)
        for key in inst_data:
            inst_data[key]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch._write_json(self.orch.agent_instances_path, inst_data)

        _setup_full_team(self.orch, self.root)

        restarted_ids = {i["instance_id"] for i in self.orch.list_agent_instances()}
        self.assertEqual(original_ids, restarted_ids)


# ---------------------------------------------------------------------------
# 5. Field completeness on all instances
# ---------------------------------------------------------------------------

class AllInstancesFieldCompletenessTests(unittest.TestCase):
    """Every instance in the 5-agent team must have all required fields."""

    REQUIRED_FIELDS = frozenset({
        "agent_name", "instance_id", "status", "agent",
        "metadata", "last_seen", "identity", "project_root",
    })

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _setup_full_team(self.orch, self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_instances_have_required_fields(self) -> None:
        instances = self.orch.list_agent_instances()
        for inst in instances:
            for field in self.REQUIRED_FIELDS:
                self.assertIn(field, inst,
                              f"{inst.get('agent_name')}:{inst.get('instance_id')} missing {field}")

    def test_all_instances_have_nonempty_last_seen(self) -> None:
        instances = self.orch.list_agent_instances()
        for inst in instances:
            self.assertTrue(len(str(inst["last_seen"])) > 0)

    def test_all_instances_have_identity_dict(self) -> None:
        instances = self.orch.list_agent_instances()
        for inst in instances:
            self.assertIsInstance(inst["identity"], dict)
            self.assertIn("instance_id", inst["identity"])


if __name__ == "__main__":
    unittest.main()
