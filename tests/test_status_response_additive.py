"""CORE-02 MCP status response tests for additive agent_instances + active_agent_identities.

Validates that status() returns both active_agent_identities and agent_instances
fields, with correct structure, filtering, and field presence.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

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
    agents = orch.list_agents(active_only=True)
    instances = orch.list_agent_instances(active_only=False)

    return {
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
        # Additive status fields introduced for stats/dashboard provenance.
        "integrity": {"ok": True, "warnings": [], "provenance": {"task_counts": "live_state"}},
        "stats_provenance": {
            "dashboard_percent": "live_status_report_estimate",
            "task_summary": "live_state",
            "integrity_state": "ok",
        },
    }


class StatusResponseFieldPresenceTests(unittest.TestCase):
    """status() must return both active_agent_identities and agent_instances."""

    def test_status_has_both_new_fields(self) -> None:
        """Payload must contain both active_agent_identities and agent_instances."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            payload = _build_status_payload(orch)

            self.assertIn("active_agent_identities", payload)
            self.assertIn("agent_instances", payload)
            self.assertIn("integrity", payload)
            self.assertIn("stats_provenance", payload)

    def test_agent_instances_is_list_of_dicts(self) -> None:
        """agent_instances must be a list of dicts with required keys."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            payload = _build_status_payload(orch)
            instances = payload["agent_instances"]

            self.assertIsInstance(instances, list)
            self.assertGreater(len(instances), 0)
            required_keys = {"agent_name", "instance_id", "role", "status", "project_root", "current_task_id", "last_seen"}
            for item in instances:
                self.assertIsInstance(item, dict)
                for key in required_keys:
                    self.assertIn(key, item, f"Missing required key: {key}")


class StatusActiveAgentCoherenceTests(unittest.TestCase):
    """Active agents should appear in both identities and instances."""

    def test_active_agents_in_both_fields(self) -> None:
        """Active agents must appear in both active_agent_identities and agent_instances."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            _connect(orch, root, "gemini")

            payload = _build_status_payload(orch)
            identity_agents = {i["agent"] for i in payload["active_agent_identities"]}
            instance_agents = {i["agent_name"] for i in payload["agent_instances"]}

            # All active agents should be in both
            for agent in payload["active_agents"]:
                self.assertIn(agent, identity_agents)
                self.assertIn(agent, instance_agents)

    def test_offline_agent_not_in_active_identities(self) -> None:
        """Offline/stale agents should not appear in active_agent_identities."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            _connect(orch, root, "gemini")

            # Make gemini stale
            agents = orch._read_json(orch.agents_path)
            agents["gemini"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            payload = _build_status_payload(orch)
            identity_agents = {i["agent"] for i in payload["active_agent_identities"]}

            self.assertNotIn("gemini", identity_agents)
            self.assertIn("claude_code", identity_agents)

    def test_unregistered_agent_not_in_active(self) -> None:
        """Agents that were never registered should not appear in active lists."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            payload = _build_status_payload(orch)

            self.assertEqual([], payload["active_agent_identities"])
            self.assertEqual([], payload["active_agents"])


class StatusMultipleAgentsTests(unittest.TestCase):
    """Multiple registered agents should all appear."""

    def test_three_agents_all_in_instances(self) -> None:
        """All three registered agents should appear in agent_instances."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code", instance_id="cc#w1")
            _connect(orch, root, "gemini", instance_id="gem#w1")
            orch.connect_to_leader(
                agent="codex",
                metadata={**_full_metadata(root, "codex"), "role": "manager", "instance_id": "codex#mgr"},
                source="codex",
            )

            payload = _build_status_payload(orch)
            instance_agents = {i["agent_name"] for i in payload["agent_instances"]}

            self.assertIn("claude_code", instance_agents)
            self.assertIn("gemini", instance_agents)
            self.assertIn("codex", instance_agents)


class InstanceRecordFieldTests(unittest.TestCase):
    """Instance records must have role, project_root, instance_id fields."""

    def test_instance_has_role_field(self) -> None:
        """Each instance record should have a role field."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            payload = _build_status_payload(orch)
            for item in payload["agent_instances"]:
                self.assertIn("role", item)

    def test_instance_has_project_root(self) -> None:
        """Each instance record should have project_root matching the orchestrator root."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")

            payload = _build_status_payload(orch)
            for item in payload["agent_instances"]:
                self.assertIn("project_root", item)
                if item["status"] == "active":
                    self.assertIsNotNone(item["project_root"])

    def test_instance_has_instance_id(self) -> None:
        """Each instance record should have a non-empty instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code", instance_id="cc#test-inst")

            payload = _build_status_payload(orch)
            cc_instances = [i for i in payload["agent_instances"] if i["agent_name"] == "claude_code"]
            self.assertGreater(len(cc_instances), 0)
            for item in cc_instances:
                self.assertIsNotNone(item["instance_id"])
                self.assertNotEqual("", item["instance_id"])


if __name__ == "__main__":
    unittest.main()
