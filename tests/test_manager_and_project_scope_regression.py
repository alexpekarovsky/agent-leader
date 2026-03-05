"""Regression coverage for manager-role mismatch and project-scope fallback."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, *, allow_cross_project: bool = False) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "allow_cross_project_agents": allow_cross_project,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, *, allow_cross_project: bool = False) -> Orchestrator:
    policy = _make_policy(root / "policy.json", allow_cross_project=allow_cross_project)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


class ManagerAndProjectScopeRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_manager_self_connect_as_team_member_is_rejected(self) -> None:
        orch = _make_orch(self.root)
        result = orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex-cli",
                "model": "gpt-5-codex",
                "cwd": str(self.root),
                "project_root": str(self.root),
                "session_id": "leader-session",
                "connection_id": "leader-conn",
                "instance_id": "codex#default",
                "verification_source": "codex",
                "role": "team_member",
            },
        )
        self.assertFalse(result["connected"])
        self.assertEqual("manager_role_mismatch", result["reason"])

    def test_project_scope_mismatch_is_rejected_without_cross_project_flag(self) -> None:
        orch = _make_orch(self.root, allow_cross_project=False)
        outside = self.root.parent
        result = orch.connect_to_leader(
            agent="claude_code",
            source="claude_code",
            metadata={
                "client": "claude_code",
                "model": "claude-opus",
                "cwd": str(outside),
                "project_root": str(outside),
                "permissions_mode": "default",
                "sandbox_mode": False,
                "session_id": "claude-session",
                "connection_id": "claude-conn",
                "instance_id": "claude_code#default",
                "server_version": "1.0",
                "verification_source": "claude_code",
                "role": "team_member",
            },
        )
        self.assertFalse(result["connected"])
        self.assertEqual("project_mismatch", result["reason"])

    def test_project_scope_mismatch_allowed_with_cross_project_flag(self) -> None:
        orch = _make_orch(self.root, allow_cross_project=True)
        outside = self.root.parent
        result = orch.connect_to_leader(
            agent="claude_code",
            source="claude_code",
            metadata={
                "client": "claude_code",
                "model": "claude-opus",
                "cwd": str(outside),
                "project_root": str(outside),
                "permissions_mode": "default",
                "sandbox_mode": False,
                "session_id": "claude-session",
                "connection_id": "claude-conn",
                "instance_id": "claude_code#default",
                "server_version": "1.0",
                "verification_source": "claude_code",
                "role": "team_member",
            },
        )
        self.assertTrue(result["connected"])
        self.assertEqual("verified_identity_cross_project", result["reason"])


if __name__ == "__main__":
    unittest.main()
