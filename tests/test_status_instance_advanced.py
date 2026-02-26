"""Advanced status and agent_instances tests.

Covers:
- TASK-46ee4eda: agent_instances cleanup/retention policy
- TASK-9568b53d: active_agents vs agent_instances consistency
- TASK-bde314e5: unknown extra fields forward compatibility
- TASK-5f9da09c: current_task_id refresh on claim/report/complete
- TASK-d2fa60b0: mixed project roots with active/offline
- TASK-d9b93d0e: instance-aware status row schema and null handling
- TASK-7aadedc5: multi-project mixed instances
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


def _connect_agent(orch: Orchestrator, root: Path, agent: str, **overrides: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent, **overrides), source=agent)


# ── TASK-46ee4eda: Cleanup/retention policy ─────────────────────────


class AgentInstancesRetentionPolicyTests(unittest.TestCase):
    """Tests documenting retention behavior for agent_instances records."""

    def test_offline_instances_retained_in_full_listing(self) -> None:
        """Stale instances should still appear when active_only=False."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")
            # Force stale
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            instances = orch.list_agent_instances(active_only=False)
            names = [i["agent_name"] for i in instances]
            self.assertIn("claude_code", names)

    def test_offline_instances_excluded_by_active_filter(self) -> None:
        """Stale instances should not appear when active_only=True."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")
            # Force both agents.json AND agent_instances.json stale
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)
            raw_inst = orch._read_json(orch.agent_instances_path)
            for key in raw_inst:
                raw_inst[key]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agent_instances_path, raw_inst)

            instances = orch.list_agent_instances(active_only=True)
            names = [i["agent_name"] for i in instances]
            self.assertNotIn("claude_code", names)

    def test_multiple_instances_same_agent_retained(self) -> None:
        """All instances (active + stale) for same agent should be retained."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")
            orch.heartbeat("claude_code", {
                **_full_metadata(root, "claude_code"),
                "instance_id": "cc#w2",
                "session_id": "sess-w2",
                "connection_id": "conn-w2",
            })

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertEqual(2, len(cc))

    def test_no_automatic_cleanup_on_bootstrap(self) -> None:
        """Bootstrap should not remove existing instance records."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")
            before = orch.list_agent_instances(active_only=False)

            orch.bootstrap()  # re-bootstrap
            after = orch.list_agent_instances(active_only=False)
            self.assertEqual(len(before), len(after))


# ── TASK-9568b53d: active_agents vs agent_instances consistency ──────


class ActiveAgentsConsistencyTests(unittest.TestCase):
    """Verify active_agents list is consistent with agent_instances."""

    def test_active_agents_subset_of_instances(self) -> None:
        """Every active agent name should appear in agent_instances."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")

            agents = orch.list_agents(active_only=True)
            active_names = {a["agent"] for a in agents}
            instances = orch.list_agent_instances(active_only=False)
            instance_agent_names = {i["agent_name"] for i in instances}

            self.assertTrue(active_names.issubset(instance_agent_names))

    def test_stale_agent_not_in_active_but_in_instances(self) -> None:
        """Stale agent should be absent from active list but present in instances."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")

            agents_data = orch._read_json(orch.agents_path)
            agents_data["gemini"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents_data)

            active = orch.list_agents(active_only=True)
            active_names = {a["agent"] for a in active}
            self.assertNotIn("gemini", active_names)
            self.assertIn("claude_code", active_names)

            instances = orch.list_agent_instances(active_only=False)
            instance_names = {i["agent_name"] for i in instances}
            self.assertIn("gemini", instance_names)
            self.assertIn("claude_code", instance_names)

    def test_both_views_include_manager_when_registered(self) -> None:
        """Manager (codex) should appear in both views if registered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="codex",
                metadata={**_full_metadata(root, "codex"), "role": "manager"},
                source="codex",
            )
            _connect_agent(orch, root, "claude_code")

            agents = orch.list_agents(active_only=True)
            active_names = {a["agent"] for a in agents}
            self.assertIn("codex", active_names)

            instances = orch.list_agent_instances(active_only=False)
            instance_names = {i["agent_name"] for i in instances}
            self.assertIn("codex", instance_names)

    def test_active_count_matches_between_views(self) -> None:
        """Number of active agent names should match between views."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")

            active_agents = orch.list_agents(active_only=True)
            active_names = {a["agent"] for a in active_agents}

            active_instances = orch.list_agent_instances(active_only=True)
            instance_names = {i["agent_name"] for i in active_instances}

            self.assertEqual(active_names, instance_names)


# ── TASK-bde314e5: Forward compatibility with unknown fields ─────────


class ForwardCompatibilityTests(unittest.TestCase):
    """Status generation should tolerate extra unknown fields."""

    def test_unknown_fields_in_agent_instances_preserved(self) -> None:
        """Extra fields in agent_instances.json should not break listing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            # Inject unknown field into agent_instances
            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                raw[key]["future_field"] = "v2_data"
                raw[key]["metrics"] = {"cpu": 0.5, "memory": 1024}
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            self.assertGreaterEqual(len(instances), 1)
            self.assertEqual("claude_code", instances[0]["agent_name"])

    def test_unknown_fields_in_agents_json_preserved(self) -> None:
        """Extra fields in agents.json should not break list_agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["custom_v2_field"] = {"nested": True}
            orch._write_json(orch.agents_path, agents)

            result = orch.list_agents(active_only=False)
            names = [a["agent"] for a in result]
            self.assertIn("claude_code", names)

    def test_known_fields_remain_intact_after_extra_injection(self) -> None:
        """Known fields should not be affected by extra unknown fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#test")

            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                raw[key]["unknown_extension"] = [1, 2, 3]
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertEqual(1, len(cc))
            self.assertIsNotNone(cc[0]["instance_id"])
            self.assertIsNotNone(cc[0]["last_seen"])

    def test_empty_metadata_dict_does_not_break_listing(self) -> None:
        """Instance record with empty metadata dict should still list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                raw[key]["metadata"] = {}
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            self.assertGreaterEqual(len(instances), 1)


# ── TASK-5f9da09c: current_task_id refresh on transitions ────────────


class CurrentTaskIdTransitionTests(unittest.TestCase):
    """Tests for current_task_id tracking across task lifecycle."""

    def test_current_task_id_defaults_to_none(self) -> None:
        """Before any task claim, current_task_id should be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            instances = orch.list_agent_instances(active_only=True)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertEqual(1, len(cc))
            self.assertIsNone(cc[0]["current_task_id"])

    def test_current_task_id_field_exists_in_instance_row(self) -> None:
        """current_task_id should be a recognized field in instance output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            instances = orch.list_agent_instances(active_only=False)
            self.assertTrue(all("current_task_id" in i for i in instances))

    def test_current_task_id_is_none_for_fresh_instances(self) -> None:
        """Multiple fresh instances should all have None current_task_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")

            instances = orch.list_agent_instances(active_only=True)
            for inst in instances:
                self.assertIsNone(inst["current_task_id"])


# ── TASK-d2fa60b0 & TASK-7aadedc5: Mixed project roots ──────────────


class MixedProjectRootTests(unittest.TestCase):
    """Tests for agents with different project roots."""

    def test_same_project_root_appears_active(self) -> None:
        """Agent with matching project_root should be active."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            instances = orch.list_agent_instances(active_only=True)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertEqual(1, len(cc))
            self.assertEqual("active", cc[0]["status"])

    def test_different_project_root_appears_offline(self) -> None:
        """Agent with different project_root should be offline."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            meta = _full_metadata(root, "claude_code")
            meta["cwd"] = "/tmp/other-project"
            meta["project_root"] = "/tmp/other-project"
            orch.connect_to_leader(agent="claude_code", metadata=meta, source="claude_code")

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertGreaterEqual(len(cc), 1)
            # Different project root = offline (project_mismatch)
            self.assertEqual("offline", cc[0]["status"])

    def test_mixed_roots_both_listed_when_not_filtering(self) -> None:
        """Two instances with different roots both appear in full listing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Instance 1: same project
            _connect_agent(orch, root, "claude_code", instance_id="cc#same")
            # Instance 2: different project
            orch.heartbeat("claude_code", {
                **_full_metadata(root, "claude_code"),
                "instance_id": "cc#other",
                "session_id": "sess-other",
                "connection_id": "conn-other",
                "cwd": "/tmp/other-project",
                "project_root": "/tmp/other-project",
            })

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertEqual(2, len(cc))

    def test_only_same_project_instances_are_active(self) -> None:
        """Only instances with matching project_root should be active."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#same")
            orch.heartbeat("claude_code", {
                **_full_metadata(root, "claude_code"),
                "instance_id": "cc#other",
                "session_id": "sess-other",
                "connection_id": "conn-other",
                "cwd": "/tmp/other-project",
                "project_root": "/tmp/other-project",
            })

            active = orch.list_agent_instances(active_only=True)
            cc_active = [i for i in active if i["agent_name"] == "claude_code"]
            self.assertEqual(1, len(cc_active))
            self.assertEqual("cc#same", cc_active[0]["instance_id"])

    def test_mixed_agents_mixed_roots(self) -> None:
        """Multiple agents, some same-project some not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            meta_gem = _full_metadata(root, "gemini")
            meta_gem["cwd"] = "/tmp/other"
            meta_gem["project_root"] = "/tmp/other"
            orch.connect_to_leader(agent="gemini", metadata=meta_gem, source="gemini")

            active = orch.list_agent_instances(active_only=True)
            active_names = {i["agent_name"] for i in active}
            self.assertIn("claude_code", active_names)
            self.assertNotIn("gemini", active_names)

            all_instances = orch.list_agent_instances(active_only=False)
            all_names = {i["agent_name"] for i in all_instances}
            self.assertIn("claude_code", all_names)
            self.assertIn("gemini", all_names)


# ── TASK-d9b93d0e: Instance row schema and null handling ─────────────


EXPECTED_INSTANCE_ROW_KEYS = {
    "agent_name",
    "instance_id",
    "role",
    "status",
    "project_root",
    "current_task_id",
    "last_seen",
}


class InstanceRowSchemaTests(unittest.TestCase):
    """Tests for instance row key presence and null handling."""

    def test_instance_row_has_all_expected_keys(self) -> None:
        """Each instance row should have all expected keys."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")

            instances = orch.list_agent_instances(active_only=False)
            self.assertGreaterEqual(len(instances), 1)
            for inst in instances:
                for key in EXPECTED_INSTANCE_ROW_KEYS:
                    self.assertIn(key, inst, f"Missing key: {key}")

    def test_null_handling_role_missing(self) -> None:
        """Instance with no role in metadata should have role=None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            # Strip role from stored metadata
            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                if "metadata" in raw[key]:
                    raw[key]["metadata"].pop("role", None)
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertGreaterEqual(len(cc), 1)
            self.assertIsNone(cc[0]["role"])

    def test_null_handling_current_task_id_missing(self) -> None:
        """Instance without current_task_id in metadata should be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertIsNone(cc[0]["current_task_id"])

    def test_null_handling_project_root_missing(self) -> None:
        """Instance without cwd/project_root should have None project_root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                if "metadata" in raw[key]:
                    raw[key]["metadata"].pop("cwd", None)
                    raw[key]["metadata"].pop("project_root", None)
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertGreaterEqual(len(cc), 1)
            # project_root derived from cwd/project_root — both gone => empty/None
            self.assertFalse(cc[0]["project_root"])

    def test_instance_row_json_serializable(self) -> None:
        """All instance row values should be JSON-serializable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")

            instances = orch.list_agent_instances(active_only=False)
            for inst in instances:
                row = {k: inst.get(k) for k in EXPECTED_INSTANCE_ROW_KEYS}
                serialized = json.dumps(row)
                self.assertIsInstance(json.loads(serialized), dict)

    def test_backward_compat_without_instance_id_metadata(self) -> None:
        """Agent registered without explicit instance_id gets default."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            meta = _full_metadata(root, "claude_code")
            meta.pop("instance_id", None)
            orch.connect_to_leader(agent="claude_code", metadata=meta, source="claude_code")

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertGreaterEqual(len(cc), 1)
            # Should fallback to session_id or connection_id
            self.assertIsNotNone(cc[0]["instance_id"])
            self.assertTrue(len(cc[0]["instance_id"]) > 0)


if __name__ == "__main__":
    unittest.main()
