"""Tests for active_agent_identities in status output.

Validates that list_agents() produces the correct identity entries
that the MCP status handler uses to build active_agent_identities.
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
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _meta(root: Path, client: str, model: str, **extra) -> dict:
    base = {
        "role": "team_member",
        "client": client,
        "model": model,
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": "test-session",
        "connection_id": "test-connection",
        "server_version": "0.1.0",
        "verification_source": "test",
    }
    base.update(extra)
    return base


class StatusAgentIdentitiesTests(unittest.TestCase):
    """Test active_agent_identities built from list_agents(active_only=True)."""

    def _make_orch(self, root: Path) -> Orchestrator:
        policy = _make_policy(root / "policy.json")
        orch = Orchestrator(root=root, policy=policy)
        orch.bootstrap()
        return orch

    def _build_identities(self, agents: list) -> list:
        """Mirror MCP status handler logic for active_agent_identities."""
        return [
            {
                "agent": agent.get("agent"),
                "instance_id": agent.get("instance_id"),
                "status": agent.get("status"),
                "last_seen": agent.get("last_seen"),
            }
            for agent in agents
        ]

    # ── empty state ──────────────────────────────────────────────────

    def test_no_agents_returns_empty_identities(self) -> None:
        """With no registered agents, active_agent_identities should be empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            self.assertEqual([], identities)

    # ── single agent ─────────────────────────────────────────────────

    def test_single_agent_has_instance_id(self) -> None:
        """A single registered agent should appear with its instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                _meta(root, "claude-code", "claude-opus", instance_id="claude_code#worker-01"),
            )
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            self.assertEqual(1, len(identities))
            self.assertEqual("claude_code", identities[0]["agent"])
            self.assertEqual("claude_code#worker-01", identities[0]["instance_id"])
            self.assertEqual("active", identities[0]["status"])
            self.assertIsNotNone(identities[0]["last_seen"])

    def test_single_agent_session_id_fallback(self) -> None:
        """Agent registered with session_id but no instance_id uses session_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "gemini",
                _meta(root, "gemini-cli", "gemini-2.5", session_id="sess-gm-1"),
            )
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            self.assertEqual(1, len(identities))
            self.assertEqual("sess-gm-1", identities[0]["instance_id"])

    # ── multiple agents ──────────────────────────────────────────────

    def test_multiple_agents_each_have_instance_id(self) -> None:
        """Multiple registered agents should each have distinct instance_ids."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                _meta(root, "claude-code", "claude-opus", instance_id="claude_code#cc1"),
            )
            orch.register_agent(
                "gemini",
                _meta(root, "gemini-cli", "gemini-2.5", instance_id="gemini#gm1"),
            )
            orch.register_agent(
                "codex",
                _meta(root, "codex-cli", "o4-mini", instance_id="codex#cx1"),
            )
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            self.assertEqual(3, len(identities))
            ids = {i["instance_id"] for i in identities}
            self.assertEqual({"claude_code#cc1", "gemini#gm1", "codex#cx1"}, ids)

    def test_all_identity_fields_present(self) -> None:
        """Each identity entry must have agent, instance_id, status, last_seen."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                _meta(root, "claude-code", "claude-opus", instance_id="claude_code#test"),
            )
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            required_keys = {"agent", "instance_id", "status", "last_seen"}
            for identity in identities:
                self.assertEqual(required_keys, set(identity.keys()))

    # ── active_only filtering ────────────────────────────────────────

    def test_active_only_excludes_stale_agents(self) -> None:
        """Agents with stale heartbeats should not appear in active_only=True."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            # Register agent then make it stale by manipulating last_seen
            orch.register_agent(
                "gemini",
                _meta(root, "gemini-cli", "gemini-2.5", instance_id="gemini#stale"),
            )
            # Manually set last_seen to a very old time
            agents_data = orch._read_json(orch.agents_path)
            if "gemini" in agents_data:
                agents_data["gemini"]["last_seen"] = "2020-01-01T00:00:00+00:00"
                orch._write_json(orch.agents_path, agents_data)

            agents_active = orch.list_agents(active_only=True)
            identities = self._build_identities(agents_active)
            self.assertEqual(0, len(identities))

            # But all-agents should still include it
            agents_all = orch.list_agents(active_only=False)
            self.assertTrue(any(a.get("agent") == "gemini" for a in agents_all))

    # ── heartbeat updates identity ───────────────────────────────────

    def test_heartbeat_updates_last_seen_in_identity(self) -> None:
        """After heartbeat, the agent's last_seen should be recent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                _meta(root, "claude-code", "claude-opus", instance_id="claude_code#hb"),
            )
            orch.heartbeat("claude_code")
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            self.assertEqual(1, len(identities))
            self.assertIsNotNone(identities[0]["last_seen"])

    def test_heartbeat_with_new_instance_id_reflected(self) -> None:
        """Heartbeat updating instance_id should be reflected in identity."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                _meta(root, "claude-code", "claude-opus", instance_id="claude_code#old"),
            )
            orch.heartbeat("claude_code", metadata={"instance_id": "claude_code#new"})
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            self.assertEqual(1, len(identities))
            self.assertEqual("claude_code#new", identities[0]["instance_id"])

    # ── default instance_id ──────────────────────────────────────────

    def test_default_instance_id_when_no_ids_provided(self) -> None:
        """Agent with no explicit instance_id uses session_id from metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            # _meta provides session_id="test-session" by default, so fallback is session_id
            orch.register_agent(
                "codex",
                _meta(root, "codex-cli", "o4-mini"),
            )
            agents = orch.list_agents(active_only=True)
            identities = self._build_identities(agents)
            self.assertEqual(1, len(identities))
            self.assertEqual("test-session", identities[0]["instance_id"])

    # ── backward compatibility ───────────────────────────────────────

    def test_active_agents_list_matches_identities(self) -> None:
        """active_agents (name-only list) should match active_agent_identities agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                _meta(root, "claude-code", "claude-opus", instance_id="claude_code#a"),
            )
            orch.register_agent(
                "gemini",
                _meta(root, "gemini-cli", "gemini-2.5", instance_id="gemini#b"),
            )
            agents = orch.list_agents(active_only=True)
            # Mirror both MCP status fields
            active_agents = [agent["agent"] for agent in agents]
            identities = self._build_identities(agents)
            identity_agents = [i["agent"] for i in identities]
            self.assertEqual(sorted(active_agents), sorted(identity_agents))


if __name__ == "__main__":
    unittest.main()
