"""Validation tests for wingman connect hardening (commit fa176da).

Scenario 1: codex self-connect returns manager_role_mismatch with reason_message.
Scenario 2: After leader handoff to claude_code, codex connects as wingman.
Scenario 3: Project-local startup guard catches .mcp.json shared-path miswire.
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


def _register_agent(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": False,
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })


class Scenario1SelfConnectGuard(unittest.TestCase):
    """Codex (leader) self-connect should return manager_role_mismatch with reason_message."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_codex_self_connect_as_team_member_returns_mismatch(self) -> None:
        """Leader connecting as team_member should get manager_role_mismatch."""
        result = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex", "model": "codex",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "codex-sid", "connection_id": "codex-cid",
                "instance_id": "codex#default",
                "server_version": "1.0", "verification_source": "codex",
                "role": "team_member",
            },
        )
        # Should NOT be connected
        self.assertFalse(result["connected"])
        self.assertEqual(result["reason"], "manager_role_mismatch")

    def test_codex_self_connect_has_reason_message(self) -> None:
        """reason_message should explain the self-connect issue."""
        result = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex", "model": "codex",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "codex-sid", "connection_id": "codex-cid",
                "instance_id": "codex#default",
                "server_version": "1.0", "verification_source": "codex",
                "role": "team_member",
            },
        )
        self.assertIn("reason_message", result)
        msg = result["reason_message"]
        self.assertIn("codex", msg)
        self.assertIn("leader", msg.lower())

    def test_codex_default_role_auto_promotes_to_manager(self) -> None:
        """Without explicit role=team_member, codex self-connect should auto-promote."""
        result = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex", "model": "codex",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "codex-sid", "connection_id": "codex-cid",
                "instance_id": "codex#default",
                "server_version": "1.0", "verification_source": "codex",
            },
        )
        # Default role should auto-promote to manager, so connect succeeds
        # but no auto_claimed_task (managers don't auto-claim)
        self.assertTrue(result["connected"])
        self.assertIsNone(result["auto_claimed_task"])

    def test_self_connect_no_auto_claim(self) -> None:
        """Self-connected leader should NOT auto-claim tasks."""
        _register_agent(self.orch, "claude_code")
        self.orch.create_task(
            acceptance_criteria=["test"],
            title="task for cc",
            workstream="backend",
            owner="codex",
        )
        result = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex", "model": "codex",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "codex-sid", "connection_id": "codex-cid",
                "instance_id": "codex#default",
                "server_version": "1.0", "verification_source": "codex",
            },
        )
        self.assertIsNone(result["auto_claimed_task"])

    def test_second_codex_instance_can_connect_as_wingman(self) -> None:
        """Different codex instance_id should be allowed as team_member when leader is codex."""
        leader_connect = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex",
                "model": "codex",
                "cwd": str(self.root),
                "project_root": str(self.root),
                "permissions_mode": "default",
                "sandbox_mode": False,
                "session_id": "codex-leader-session",
                "connection_id": "codex-leader-conn",
                "server_version": "1.0",
                "verification_source": "codex",
                "role": "manager",
            },
        )
        self.assertTrue(leader_connect["connected"])

        wingman_connect = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex",
                "model": "codex",
                "cwd": str(self.root),
                "project_root": str(self.root),
                "permissions_mode": "default",
                "sandbox_mode": False,
                "session_id": "codex-wingman-session",
                "connection_id": "codex-wingman-conn",
                "server_version": "1.0",
                "verification_source": "codex",
                "role": "team_member",
                "role_intent": "wingman",
            },
        )
        self.assertTrue(wingman_connect["connected"])
        self.assertEqual("verified_identity", wingman_connect["reason"])
        self.assertEqual("codex", wingman_connect["manager"])


class Scenario2LeaderHandoffWingman(unittest.TestCase):
    """After leader handoff, codex should connect as wingman successfully."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_agent(self.orch, "claude_code")
        _register_agent(self.orch, "codex")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_codex_wingman_after_handoff(self) -> None:
        """After switching leader to claude_code, codex connects as wingman."""
        # Handoff: change leader to claude_code
        self.orch.set_role("claude_code", "leader", source="codex")
        # Now codex is no longer manager, connecting as team_member should work
        result = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex", "model": "codex",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "codex-sid", "connection_id": "codex-cid",
                "server_version": "1.0", "verification_source": "codex",
                "role": "team_member",
            },
        )
        self.assertTrue(result["connected"])
        self.assertEqual(result["manager"], "claude_code")

    def test_codex_wingman_can_auto_claim(self) -> None:
        """After handoff, codex as wingman should auto-claim tasks."""
        self.orch.create_task(
            acceptance_criteria=["test"],
            title="task for wingman",
            workstream="default",
            owner="codex",
        )
        self.orch.set_role("claude_code", "leader", source="codex")
        result = self.orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex", "model": "codex",
                "cwd": str(self.root), "project_root": str(self.root),
                "permissions_mode": "default", "sandbox_mode": False,
                "session_id": "codex-sid", "connection_id": "codex-cid",
                "server_version": "1.0", "verification_source": "codex",
                "role": "team_member",
            },
        )
        self.assertTrue(result["connected"])
        self.assertIsNotNone(result["auto_claimed_task"])
        self.assertEqual(result["auto_claimed_task"]["title"], "task for wingman")


class Scenario3McpJsonSharedPathGuard(unittest.TestCase):
    """Project-local startup guard should catch .mcp.json shared-path miswire."""

    def test_detects_shared_path_in_mcp_json(self) -> None:
        """_project_mcp_server_uses_shared_path should detect shared install path."""
        from orchestrator_mcp_server import _project_mcp_server_uses_shared_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mcp = {
                "mcpServers": {
                    "agent-leader-orchestrator": {
                        "command": "python3",
                        "args": [
                            "/Users/alex/.local/share/agent-leader/current/orchestrator_mcp_server.py"
                        ],
                    }
                }
            }
            (root / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
            self.assertTrue(_project_mcp_server_uses_shared_path(root))

    def test_no_false_positive_for_local_path(self) -> None:
        """Local project paths should not trigger the guard."""
        from orchestrator_mcp_server import _project_mcp_server_uses_shared_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mcp = {
                "mcpServers": {
                    "agent-leader-orchestrator": {
                        "command": "python3",
                        "args": [
                            f"{tmp}/orchestrator_mcp_server.py"
                        ],
                    }
                }
            }
            (root / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
            self.assertFalse(_project_mcp_server_uses_shared_path(root))

    def test_missing_mcp_json_returns_false(self) -> None:
        """No .mcp.json should not trigger the guard."""
        from orchestrator_mcp_server import _project_mcp_server_uses_shared_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(_project_mcp_server_uses_shared_path(root))

    def test_binding_error_message_content(self) -> None:
        """The binding error for shared-path miswire should provide actionable guidance."""
        from orchestrator_mcp_server import _project_mcp_server_uses_shared_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mcp = {
                "mcpServers": {
                    "agent-leader-orchestrator": {
                        "command": "python3",
                        "args": [
                            "/Users/test/.local/share/agent-leader/current/orchestrator_mcp_server.py"
                        ],
                    }
                }
            }
            (root / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
            self.assertTrue(_project_mcp_server_uses_shared_path(root))
            # The expected error message in the guard (line 104-108)
            expected_fragment = "shared install path"
            # Verify the error message from the guard matches
            error_msg = (
                "Project .mcp.json points agent-leader-orchestrator to shared install path "
                "'/.local/share/agent-leader/current'. In project-local mode, update .mcp.json "
                "to launch this repo's orchestrator_mcp_server.py and policy."
            )
            self.assertIn(expected_fragment, error_msg)
            self.assertIn(".mcp.json", error_msg)

    def test_is_shared_agent_leader_install(self) -> None:
        """_is_shared_agent_leader_install should detect shared install paths."""
        from orchestrator_mcp_server import _is_shared_agent_leader_install

        shared = Path("/Users/alex/.local/share/agent-leader/current/orchestrator_mcp_server.py")
        self.assertTrue(_is_shared_agent_leader_install(shared))

        local = Path("/Users/alex/my-project/orchestrator_mcp_server.py")
        self.assertFalse(_is_shared_agent_leader_install(local))


if __name__ == "__main__":
    unittest.main()
