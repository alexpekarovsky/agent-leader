"""Tests for get_roles, manager_agent, and set_role.

Validates role retrieval, leader identification, and role assignment
with permission checks.
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


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


class ManagerAgentTests(unittest.TestCase):
    """Tests for manager_agent."""

    def test_default_leader_from_policy(self) -> None:
        """manager_agent should return the policy default when no role override."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self.assertEqual("codex", orch.manager_agent())

    def test_leader_from_roles_file(self) -> None:
        """manager_agent should return the leader from roles.json when set."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Set a different leader via set_role
            orch.set_role("claude_code", "leader", source="codex")
            self.assertEqual("claude_code", orch.manager_agent())

    def test_empty_roles_falls_back_to_policy(self) -> None:
        """manager_agent should fall back to policy when roles.json is empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Write empty roles
            orch._write_json(orch.roles_path, {})
            self.assertEqual("codex", orch.manager_agent())

    def test_whitespace_leader_falls_back(self) -> None:
        """manager_agent with whitespace-only leader should fall back to policy."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch._write_json(orch.roles_path, {"leader": "   "})
            self.assertEqual("codex", orch.manager_agent())


class GetRolesTests(unittest.TestCase):
    """Tests for get_roles."""

    def test_default_roles(self) -> None:
        """get_roles should return leader from policy when no overrides."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            roles = orch.get_roles()
            self.assertEqual("codex", roles["leader"])
            self.assertEqual("codex#default", roles["leader_instance_id"])
            self.assertEqual("codex", roles["default_leader"])
            self.assertIsInstance(roles["team_members"], list)

    def test_roles_structure(self) -> None:
        """get_roles should return leader, team_members, and default_leader."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            roles = orch.get_roles()
            self.assertIn("leader", roles)
            self.assertIn("leader_instance_id", roles)
            self.assertIn("team_members", roles)
            self.assertIn("default_leader", roles)

    def test_team_members_excludes_leader(self) -> None:
        """team_members should not include the current leader."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.set_role("claude_code", "team_member", source="codex")
            orch.set_role("gemini", "team_member", source="codex")
            roles = orch.get_roles()
            self.assertNotIn(roles["leader"], roles["team_members"])

    def test_team_members_sorted(self) -> None:
        """team_members should be sorted alphabetically."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.set_role("gemini", "team_member", source="codex")
            orch.set_role("claude_code", "team_member", source="codex")
            roles = orch.get_roles()
            self.assertEqual(sorted(roles["team_members"]), roles["team_members"])

    def test_empty_roles_file(self) -> None:
        """get_roles with empty roles.json should fall back to policy defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch._write_json(orch.roles_path, {})
            roles = orch.get_roles()
            self.assertEqual("codex", roles["leader"])
            self.assertEqual("codex#default", roles["leader_instance_id"])
            self.assertEqual([], roles["team_members"])

    def test_roles_file_without_leader_instance_id_migrates_on_read(self) -> None:
        """Backward compatibility: roles without leader_instance_id should derive leader#default."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch._write_json(orch.roles_path, {"leader": "claude_code", "team_members": ["gemini"]})
            roles = orch.get_roles()
            self.assertEqual("claude_code", roles["leader"])
            self.assertEqual("claude_code#default", roles["leader_instance_id"])
            self.assertEqual(["gemini"], roles["team_members"])


class SetRoleTests(unittest.TestCase):
    """Tests for set_role."""

    def test_set_team_member(self) -> None:
        """set_role should add a team member."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            result = orch.set_role("claude_code", "team_member", source="codex")
            self.assertIn("claude_code", result["team_members"])

    def test_set_new_leader(self) -> None:
        """set_role with leader role should change the leader."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            result = orch.set_role("claude_code", "leader", source="codex")
            self.assertEqual("claude_code", result["leader"])
            self.assertEqual("claude_code#default", result["leader_instance_id"])

    def test_leader_removed_from_team_members(self) -> None:
        """Promoting a team member to leader should remove them from team_members."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.set_role("claude_code", "team_member", source="codex")
            result = orch.set_role("claude_code", "leader", source="codex")
            self.assertNotIn("claude_code", result["team_members"])

    def test_non_leader_source_rejected(self) -> None:
        """set_role from a non-leader source should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            with self.assertRaises(ValueError) as ctx:
                orch.set_role("gemini", "team_member", source="claude_code")
            self.assertIn("leader_mismatch", str(ctx.exception))

    def test_default_manager_can_recover_leadership_when_current_leader_not_operational(self) -> None:
        """Default manager can reclaim leadership if the configured leader is stale/off-project."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Move leadership away from codex first.
            orch.set_role("claude_code", "leader", source="codex")
            # Register leader identity from another project to force non-operational status.
            orch.register_agent(
                "claude_code",
                metadata={
                    "client": "claude-code",
                    "model": "claude-opus-4-6",
                    "cwd": "/tmp/outside-project",
                    "project_root": "/tmp/outside-project",
                    "permissions_mode": "default",
                    "sandbox_mode": "none",
                    "session_id": "foreign-session",
                    "connection_id": "foreign-conn",
                    "server_version": "1.0.0",
                    "verification_source": "test",
                    "role": "team_member",
                    "status": "idle",
                },
            )
            # codex is no longer the current leader, but should be allowed to recover.
            result = orch.set_role("codex", "leader", source="codex")
            self.assertEqual("codex", result["leader"])

    def test_demote_leader_to_team_member_rejected(self) -> None:
        """Current leader cannot be assigned as team_member."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            with self.assertRaises(ValueError) as ctx:
                orch.set_role("codex", "team_member", source="codex")
            self.assertIn("current leader", str(ctx.exception))

    def test_invalid_role_rejected(self) -> None:
        """set_role with invalid role name should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            with self.assertRaises(ValueError) as ctx:
                orch.set_role("claude_code", "admin", source="codex")
            self.assertIn("role must be", str(ctx.exception))

    def test_empty_agent_rejected(self) -> None:
        """set_role with empty agent should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            with self.assertRaises(ValueError):
                orch.set_role("", "team_member", source="codex")

    def test_set_role_reflects_in_get_roles(self) -> None:
        """Changes via set_role should be visible in get_roles."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.set_role("claude_code", "team_member", source="codex")
            orch.set_role("gemini", "team_member", source="codex")

            roles = orch.get_roles()
            self.assertEqual("codex", roles["leader"])
            self.assertIn("claude_code", roles["team_members"])
            self.assertIn("gemini", roles["team_members"])

    def test_set_role_reflects_in_manager_agent(self) -> None:
        """Leadership change via set_role should be visible in manager_agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self.assertEqual("codex", orch.manager_agent())
            orch.set_role("claude_code", "leader", source="codex")
            self.assertEqual("claude_code", orch.manager_agent())


class PolicyBundlePresetTests(unittest.TestCase):
    def test_bundle_files_exist_and_load(self) -> None:
        config = Path(__file__).resolve().parents[1] / "config"
        for name in ("policy.strict-qa.json", "policy.prototype-fast.json", "policy.balanced.json"):
            path = config / name
            self.assertTrue(path.exists(), f"missing bundle: {name}")
            policy = Policy.load(path)
            self.assertTrue(policy.name)
            self.assertIn("default", policy.routing)


if __name__ == "__main__":
    unittest.main()
