"""CORE-02 status regression tests.

Covers:
- TASK-60047d22: MCP status active_agent_identities + agent_instances coherence
- TASK-0ac7db06: Mixed valid/malformed agent_instances row serialization
- TASK-8f31f055: Post-restart three-worker visibility fixture
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


def _connect(orch: Orchestrator, root: Path, agent: str, **overrides: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent, **overrides), source=agent)


def _build_status_payload(orch: Orchestrator) -> dict:
    """Replicate the MCP handler status payload construction."""
    tasks = orch.list_tasks()
    bugs = orch.list_bugs()
    agents = orch.list_agents(active_only=True)
    instances = orch.list_agent_instances(active_only=False)

    by_status: dict = {}
    for task in tasks:
        by_status[task["status"]] = by_status.get(task["status"], 0) + 1

    return {
        "task_count": len(tasks),
        "task_status_counts": by_status,
        "bug_count": len(bugs),
        "active_agents": [a["agent"] for a in agents],
        "active_agent_identities": [
            {
                "agent": a.get("agent"),
                "instance_id": a.get("instance_id"),
                "status": a.get("status"),
                "last_seen": a.get("last_seen"),
            }
            for a in agents
        ],
        "agent_instances": [
            {
                "agent_name": item.get("agent_name"),
                "instance_id": item.get("instance_id"),
                "role": item.get("role"),
                "status": item.get("status"),
                "project_root": item.get("project_root"),
                "current_task_id": item.get("current_task_id"),
                "last_seen": item.get("last_seen"),
            }
            for item in instances
        ],
    }


# ── TASK-60047d22: active_agent_identities + agent_instances coherence ──


class StatusCoherenceTests(unittest.TestCase):
    """active_agent_identities and agent_instances should be coherent."""

    def test_active_identity_agents_subset_of_instances(self) -> None:
        """Every agent in active_agent_identities must appear in agent_instances."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            _connect(orch, root, "gemini")

            payload = _build_status_payload(orch)
            identity_agents = {i["agent"] for i in payload["active_agent_identities"]}
            instance_agents = {i["agent_name"] for i in payload["agent_instances"]}
            self.assertTrue(identity_agents.issubset(instance_agents))

    def test_active_agents_list_matches_identity_agents(self) -> None:
        """active_agents top-level list should match active_agent_identities."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            payload = _build_status_payload(orch)
            self.assertEqual(
                set(payload["active_agents"]),
                {i["agent"] for i in payload["active_agent_identities"]},
            )

    def test_legacy_top_level_keys_preserved(self) -> None:
        """Legacy keys (task_count, bug_count, active_agents) must be present."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            payload = _build_status_payload(orch)

            for key in ("task_count", "bug_count", "active_agents", "task_status_counts"):
                self.assertIn(key, payload, f"Missing legacy key: {key}")

    def test_both_new_fields_present(self) -> None:
        """active_agent_identities and agent_instances must both be present."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            payload = _build_status_payload(orch)
            self.assertIn("active_agent_identities", payload)
            self.assertIn("agent_instances", payload)

    def test_stale_agent_in_instances_not_in_identities(self) -> None:
        """Stale agent should be in agent_instances but not active_agent_identities."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            _connect(orch, root, "gemini")

            agents = orch._read_json(orch.agents_path)
            agents["gemini"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            payload = _build_status_payload(orch)
            identity_agents = {i["agent"] for i in payload["active_agent_identities"]}
            instance_agents = {i["agent_name"] for i in payload["agent_instances"]}

            self.assertNotIn("gemini", identity_agents)
            self.assertIn("gemini", instance_agents)


# ── TASK-0ac7db06: Mixed valid/malformed rows serialization ──────────


class MixedRowSerializationTests(unittest.TestCase):
    """Status remains stable with mixed valid/malformed instance rows."""

    def test_malformed_metadata_empty_dict_does_not_break(self) -> None:
        """Instance with metadata={} should still list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                raw[key]["metadata"] = {}
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            self.assertGreaterEqual(len(instances), 1)

    def test_missing_agent_field_in_instance(self) -> None:
        """Instance row missing 'agent' field should still be processed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                raw[key].pop("agent", None)
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            self.assertGreaterEqual(len(instances), 1)

    def test_mixed_valid_and_empty_metadata_rows(self) -> None:
        """Mix of valid and empty-metadata rows should be serializable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            _connect(orch, root, "gemini")

            raw = orch._read_json(orch.agent_instances_path)
            keys = list(raw.keys())
            if keys:
                raw[keys[0]]["metadata"] = {}
            orch._write_json(orch.agent_instances_path, raw)

            payload = _build_status_payload(orch)
            serialized = json.dumps(payload)
            self.assertIsInstance(json.loads(serialized), dict)

    def test_extra_non_dict_instance_entry_skipped(self) -> None:
        """Non-dict entries in agent_instances should be skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            raw = orch._read_json(orch.agent_instances_path)
            raw["bad_entry"] = "not a dict"
            raw["bad_entry_2"] = 42
            orch._write_json(orch.agent_instances_path, raw)

            instances = orch.list_agent_instances(active_only=False)
            # Valid entries should still appear
            cc = [i for i in instances if i.get("agent_name") == "claude_code"]
            self.assertGreaterEqual(len(cc), 1)


# ── TASK-8f31f055: Post-restart three-worker visibility fixture ──────


class PostRestartVisibilityTests(unittest.TestCase):
    """Fixture: Codex + 3 Claude sessions + Gemini post-restart."""

    def test_five_agent_instances_visible_after_setup(self) -> None:
        """All 5 instances (codex, 3x claude, gemini) should appear."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Codex as manager
            orch.connect_to_leader(
                agent="codex",
                metadata={**_full_metadata(root, "codex"), "role": "manager", "instance_id": "codex#mgr"},
                source="codex",
            )
            # 3 Claude sessions
            for i in range(1, 4):
                orch.heartbeat("claude_code", {
                    **_full_metadata(root, "claude_code"),
                    "instance_id": f"cc#worker-{i:02d}",
                    "session_id": f"sess-cc-{i}",
                    "connection_id": f"conn-cc-{i}",
                })
            # Gemini
            _connect(orch, root, "gemini", instance_id="gem#w1")

            instances = orch.list_agent_instances(active_only=False)
            instance_ids = {i["instance_id"] for i in instances}

            self.assertIn("cc#worker-01", instance_ids)
            self.assertIn("cc#worker-02", instance_ids)
            self.assertIn("cc#worker-03", instance_ids)
            self.assertIn("gem#w1", instance_ids)

    def test_restart_preserves_instances(self) -> None:
        """After re-bootstrap, all instances should be preserved."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.connect_to_leader(
                agent="codex",
                metadata={**_full_metadata(root, "codex"), "role": "manager"},
                source="codex",
            )
            for i in range(1, 4):
                orch.heartbeat("claude_code", {
                    **_full_metadata(root, "claude_code"),
                    "instance_id": f"cc#w{i}",
                    "session_id": f"sess-{i}",
                    "connection_id": f"conn-{i}",
                })
            _connect(orch, root, "gemini")

            before = len(orch.list_agent_instances(active_only=False))
            orch.bootstrap()  # re-bootstrap
            after = len(orch.list_agent_instances(active_only=False))
            self.assertEqual(before, after)

    def test_mixed_active_offline_after_stale(self) -> None:
        """After making one claude instance stale, others stay active."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(1, 4):
                orch.heartbeat("claude_code", {
                    **_full_metadata(root, "claude_code"),
                    "instance_id": f"cc#w{i}",
                    "session_id": f"sess-{i}",
                    "connection_id": f"conn-{i}",
                })

            # Make cc#w1 stale
            raw = orch._read_json(orch.agent_instances_path)
            for key in raw:
                if raw[key].get("instance_id") == "cc#w1":
                    raw[key]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agent_instances_path, raw)

            all_inst = orch.list_agent_instances(active_only=False)
            cc = [i for i in all_inst if i.get("agent_name") == "claude_code"]
            statuses = {i["instance_id"]: i["status"] for i in cc}
            self.assertEqual("offline", statuses.get("cc#w1"))

    def test_agent_family_duplicates_represented(self) -> None:
        """Multiple claude_code instances should all appear."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(1, 4):
                orch.heartbeat("claude_code", {
                    **_full_metadata(root, "claude_code"),
                    "instance_id": f"cc#w{i}",
                    "session_id": f"sess-{i}",
                    "connection_id": f"conn-{i}",
                })

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertEqual(3, len(cc))
            ids = {i["instance_id"] for i in cc}
            self.assertEqual({"cc#w1", "cc#w2", "cc#w3"}, ids)

    def test_payload_json_serializable_with_all_instances(self) -> None:
        """Full status payload with all instances should be JSON-safe."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.connect_to_leader(
                agent="codex",
                metadata={**_full_metadata(root, "codex"), "role": "manager"},
                source="codex",
            )
            for i in range(1, 4):
                orch.heartbeat("claude_code", {
                    **_full_metadata(root, "claude_code"),
                    "instance_id": f"cc#w{i}",
                    "session_id": f"sess-{i}",
                    "connection_id": f"conn-{i}",
                })
            _connect(orch, root, "gemini")

            payload = _build_status_payload(orch)
            serialized = json.dumps(payload)
            self.assertIsInstance(json.loads(serialized), dict)


if __name__ == "__main__":
    unittest.main()
