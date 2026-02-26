"""CORE-02 agent_instances row field presence and ordering fixture snapshots.

Regression protection for list_agent_instances output schema. Ensures all
expected fields are present, in deterministic sort order, across single-agent,
multi-agent, and mixed-state scenarios.

Field Schema (from engine.py list_agent_instances):
- agent_name:       str   — Agent name (e.g. "claude_code")
- instance_id:      str   — Derived instance ID
- status:           str   — "active" or "offline"
- age_seconds:      int|None — Seconds since last_seen
- role:             str|None — From metadata.role
- project_root:     str|None — From identity snapshot
- current_task_id:  str|None — From metadata.current_task_id
- agent:            str   — Raw agent name (same as agent_name)
- metadata:         dict  — Full metadata dict
- last_seen:        str   — ISO-8601 last heartbeat timestamp
- identity:         dict  — Identity snapshot with verification fields
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Expected field sets for snapshot assertions
# ---------------------------------------------------------------------------

# Fields that must always be present in every list_agent_instances entry
REQUIRED_FIELDS = frozenset({
    "agent_name",
    "instance_id",
    "status",
    "age_seconds",
    "role",
    "project_root",
    "current_task_id",
    "agent",
    "metadata",
    "last_seen",
    "identity",
})

# Fields within the identity sub-dict
IDENTITY_FIELDS = frozenset({
    "instance_id",
    "verified",
    "same_project",
    "project_root",
})


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


def _setup_agent(orch: Orchestrator, root: Path, agent: str, instance_id: str | None = None) -> None:
    meta = _full_metadata(root, agent)
    if instance_id:
        meta["instance_id"] = instance_id
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


# ---------------------------------------------------------------------------
# 1. Single agent field presence snapshot
# ---------------------------------------------------------------------------

class SingleAgentFieldPresenceTests(unittest.TestCase):
    """Single agent entry must contain all required fields."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_single_agent_has_all_required_fields(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-inst-1")
        instances = self.orch.list_agent_instances()
        self.assertEqual(len(instances), 1)
        entry = instances[0]
        for field in REQUIRED_FIELDS:
            self.assertIn(field, entry, f"missing field: {field}")

    def test_single_agent_identity_has_required_fields(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-inst-1")
        instances = self.orch.list_agent_instances()
        identity = instances[0]["identity"]
        for field in IDENTITY_FIELDS:
            self.assertIn(field, identity, f"missing identity field: {field}")

    def test_agent_name_matches_agent(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-inst-1")
        instances = self.orch.list_agent_instances()
        entry = instances[0]
        self.assertEqual(entry["agent_name"], entry["agent"])
        self.assertEqual(entry["agent_name"], "claude_code")

    def test_instance_id_matches_identity(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-inst-1")
        instances = self.orch.list_agent_instances()
        entry = instances[0]
        self.assertEqual(entry["instance_id"], entry["identity"]["instance_id"])

    def test_status_is_active_for_fresh_agent(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-inst-1")
        instances = self.orch.list_agent_instances()
        self.assertEqual(instances[0]["status"], "active")

    def test_metadata_is_dict(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-inst-1")
        instances = self.orch.list_agent_instances()
        self.assertIsInstance(instances[0]["metadata"], dict)

    def test_last_seen_is_string(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-inst-1")
        instances = self.orch.list_agent_instances()
        self.assertIsInstance(instances[0]["last_seen"], str)
        self.assertTrue(len(instances[0]["last_seen"]) > 0)


# ---------------------------------------------------------------------------
# 2. Multi-agent deterministic ordering
# ---------------------------------------------------------------------------

class MultiAgentOrderingTests(unittest.TestCase):
    """Multiple agents must be sorted by (agent_name, instance_id) ascending."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_three_agents_sorted_alphabetically(self) -> None:
        _setup_agent(self.orch, self.root, "gemini", "g-1")
        _setup_agent(self.orch, self.root, "codex", "x-1")
        _setup_agent(self.orch, self.root, "claude_code", "c-1")
        instances = self.orch.list_agent_instances()
        names = [i["agent_name"] for i in instances]
        self.assertEqual(names, ["claude_code", "codex", "gemini"])

    def test_same_agent_multiple_instances_sorted_by_instance_id(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-beta")
        _setup_agent(self.orch, self.root, "claude_code", "cc-alpha")
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        ids = [i["instance_id"] for i in cc]
        self.assertEqual(ids, sorted(ids))

    def test_mixed_agents_fully_sorted(self) -> None:
        _setup_agent(self.orch, self.root, "gemini", "g-2")
        _setup_agent(self.orch, self.root, "claude_code", "cc-2")
        _setup_agent(self.orch, self.root, "gemini", "g-1")
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        instances = self.orch.list_agent_instances()
        pairs = [(i["agent_name"], i["instance_id"]) for i in instances]
        self.assertEqual(pairs, sorted(pairs))

    def test_ordering_is_stable_across_calls(self) -> None:
        _setup_agent(self.orch, self.root, "gemini", "g-1")
        _setup_agent(self.orch, self.root, "claude_code", "c-1")
        _setup_agent(self.orch, self.root, "codex", "x-1")
        first = [(i["agent_name"], i["instance_id"]) for i in self.orch.list_agent_instances()]
        second = [(i["agent_name"], i["instance_id"]) for i in self.orch.list_agent_instances()]
        self.assertEqual(first, second)

    def test_all_entries_have_required_fields(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        _setup_agent(self.orch, self.root, "gemini", "g-1")
        _setup_agent(self.orch, self.root, "codex", "x-1")
        instances = self.orch.list_agent_instances()
        self.assertEqual(len(instances), 3)
        for entry in instances:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, entry,
                              f"agent {entry.get('agent_name')} missing field: {field}")


# ---------------------------------------------------------------------------
# 3. Snapshot field value consistency
# ---------------------------------------------------------------------------

class FieldValueConsistencyTests(unittest.TestCase):
    """Field values should be consistent with registration metadata."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_role_reflects_metadata(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        instances = self.orch.list_agent_instances()
        self.assertEqual(instances[0]["role"], "team_member")

    def test_project_root_reflects_cwd(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        instances = self.orch.list_agent_instances()
        pr = instances[0]["project_root"]
        self.assertTrue(pr is not None and len(str(pr)) > 0)

    def test_instance_id_from_explicit_metadata(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "my-custom-id")
        instances = self.orch.list_agent_instances()
        self.assertEqual(instances[0]["instance_id"], "my-custom-id")

    def test_current_task_id_none_when_not_working(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        instances = self.orch.list_agent_instances()
        self.assertIsNone(instances[0]["current_task_id"])

    def test_age_seconds_is_numeric_or_none(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        instances = self.orch.list_agent_instances()
        age = instances[0]["age_seconds"]
        self.assertTrue(age is None or isinstance(age, (int, float)))


# ---------------------------------------------------------------------------
# 4. Offline agent snapshot preservation
# ---------------------------------------------------------------------------

class OfflineAgentSnapshotTests(unittest.TestCase):
    """Offline agents must still have all required fields."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_offline_agent_has_all_required_fields(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        # Make agent stale
        instances_data = self.orch._read_json(self.orch.agent_instances_path)
        for key in instances_data:
            instances_data[key]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch._write_json(self.orch.agent_instances_path, instances_data)

        instances = self.orch.list_agent_instances()
        self.assertGreaterEqual(len(instances), 1)
        entry = instances[0]
        for field in REQUIRED_FIELDS:
            self.assertIn(field, entry, f"offline agent missing field: {field}")

    def test_offline_agent_status_is_offline(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        instances_data = self.orch._read_json(self.orch.agent_instances_path)
        for key in instances_data:
            instances_data[key]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch._write_json(self.orch.agent_instances_path, instances_data)

        instances = self.orch.list_agent_instances()
        self.assertEqual(instances[0]["status"], "offline")

    def test_mixed_active_offline_all_have_fields(self) -> None:
        _setup_agent(self.orch, self.root, "claude_code", "cc-1")
        _setup_agent(self.orch, self.root, "gemini", "g-1")
        # Make only claude_code stale
        instances_data = self.orch._read_json(self.orch.agent_instances_path)
        for key in instances_data:
            if "claude_code" in key:
                instances_data[key]["last_seen"] = "2020-01-01T00:00:00+00:00"
        self.orch._write_json(self.orch.agent_instances_path, instances_data)

        instances = self.orch.list_agent_instances()
        self.assertGreaterEqual(len(instances), 2)
        for entry in instances:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, entry,
                              f"agent {entry.get('agent_name')} missing field: {field}")


# ---------------------------------------------------------------------------
# 5. Empty state snapshot
# ---------------------------------------------------------------------------

class EmptyStateSnapshotTests(unittest.TestCase):
    """No agents registered should return empty list."""

    def test_empty_instances_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            instances = orch.list_agent_instances()
            self.assertEqual(instances, [])
            self.assertIsInstance(instances, list)


if __name__ == "__main__":
    unittest.main()
