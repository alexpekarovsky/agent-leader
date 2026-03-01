"""
Tests for connect workflow hardening.

- V0.2: Polish one-shot connect workflow end-to-end (TASK-796f3f32)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, manager: str = "codex") -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": manager},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, manager: str = "codex") -> Orchestrator:
    policy = _make_policy(root / "policy.json", manager=manager)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _register_agent(orch: Orchestrator, agent: str, is_stale: bool = False) -> None:
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": False,
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })
    if is_stale:
        agents = orch._read_json(orch.agents_path)
        agents[agent]["last_seen"] = "2000-01-01T00:00:00+00:00"
        orch._write_json(orch.agents_path, agents)


class ConnectTeamMembersHardening(unittest.TestCase):
    """Tests for connect_team_members hardening."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_connect_team_members_timeout(self) -> None:
        """Test that connect_team_members times out if a worker doesn't connect."""
        _register_agent(self.orch, "claude_code")
        # Note: gemini is NOT registered
        self.orch.connect_to_leader(
            agent="claude_code",
            source="claude_code",
            metadata={
                "client": "claude_code", "model": "claude_code",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "cc-sid-new", "connection_id": "cc-cid-new",
                "server_version": "1.0", "verification_source": "claude_code",
                "role": "team_member",
            },
        )
        result = self.orch.connect_team_members(
            source="codex",
            team_members=["claude_code", "gemini"],
            timeout_seconds=2,
            poll_interval_seconds=1,
        )
        self.assertEqual(result["status"], "timeout")
        self.assertIn("claude_code", result["connected"])
        self.assertIn("gemini", result["missing"])

    def test_connect_team_members_with_stale_heartbeat(self) -> None:
        """Test connect_team_members with a stale worker."""
        _register_agent(self.orch, "claude_code")
        _register_agent(self.orch, "gemini", is_stale=True)
        self.orch.connect_to_leader(agent="claude_code", source="claude_code", metadata={
            "client": "claude_code", "model": "claude_code",
            "cwd": str(self.root), "project_root": str(self.root),
            "permissions_mode": "default", "sandbox_mode": False,
            "session_id": "cc-sid-new", "connection_id": "cc-cid-new",
            "server_version": "1.0", "verification_source": "claude_code",
            "role": "team_member",
        })

        # gemini has a stale heartbeat, but let's see if it can connect
        self.orch.connect_to_leader(agent="gemini", source="gemini", metadata={
            "client": "gemini", "model": "gemini",
            "cwd": str(self.root), "project_root": str(self.root),
            "permissions_mode": "default", "sandbox_mode": False,
            "session_id": "gemini-sid-new", "connection_id": "gemini-cid-new",
            "server_version": "1.0", "verification_source": "gemini",
            "role": "team_member",
        })

        result = self.orch.connect_team_members(
            source="codex",
            team_members=["claude_code", "gemini"],
            timeout_seconds=3,
            poll_interval_seconds=1,
        )
        self.assertEqual(result["status"], "connected")
        self.assertEqual(sorted(result["connected"]), sorted(["claude_code", "gemini"]))
        self.assertEqual(result["missing"], [])


class ConnectToLeaderHardening(unittest.TestCase):
    """Tests for connect_to_leader hardening."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_connect_to_leader_with_stale_heartbeat(self) -> None:
        """Test that a worker with a stale heartbeat can reconnect."""
        _register_agent(self.orch, "claude_code", is_stale=True)
        result = self.orch.connect_to_leader(
            agent="claude_code",
            source="claude_code",
            metadata={
                "client": "claude_code", "model": "claude_code",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "cc-sid-new", "connection_id": "cc-cid-new",
                "server_version": "1.0", "verification_source": "claude_code",
                "role": "team_member",
            },
        )
        self.assertTrue(result["connected"])
        self.assertTrue(result["verified"])

    def test_connect_to_leader_missing_metadata(self) -> None:
        """Test that connect_to_leader fails with missing metadata."""
        result = self.orch.connect_to_leader(
            agent="gemini",
            source="gemini",
            metadata={
                "role": "team_member",
            },
        )
        self.assertFalse(result["connected"])
        self.assertIn("missing_identity_fields", result["reason"])

    def test_leader_handoff_connect(self) -> None:
        """Test that after a leader handoff, the old leader can connect as a team member."""
        _register_agent(self.orch, "codex")
        _register_agent(self.orch, "claude_code")

        # claude_code becomes the new leader
        self.orch.set_role("claude_code", "leader", source="codex")

        # codex, the old leader, connects as a team member
        result = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex", "model": "codex",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "codex-sid-new", "connection_id": "codex-cid-new",
                "server_version": "1.0", "verification_source": "codex",
                "role": "team_member",
            },
        )
        self.assertTrue(result["connected"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["manager"], "claude_code")

if __name__ == "__main__":
    unittest.main()
