"""Tests for instance_id fallback derivation precedence.

Validates the priority order: explicit instance_id > session_id > connection_id > default.
Covers register_agent, heartbeat, and connect_to_leader paths.
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


def _team_metadata(root: Path, client: str, model: str, role: str, sid: str, cid: str) -> dict:
    return {
        "role": role,
        "client": client,
        "model": model,
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": sid,
        "connection_id": cid,
        "server_version": "0.1.0",
        "verification_source": "test",
    }


class InstanceIdPrecedenceTests(unittest.TestCase):
    """Test instance_id fallback derivation: explicit > session_id > connection_id > default."""

    def _make_orch(self, root: Path) -> Orchestrator:
        policy = _make_policy(root / "policy.json")
        orch = Orchestrator(root=root, policy=policy)
        orch.bootstrap()
        return orch

    # ── register_agent ──────────────────────────────────────────────────

    def test_register_explicit_instance_id_takes_precedence(self) -> None:
        """Explicit instance_id should override session_id and connection_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            entry = orch.register_agent(
                "claude_code",
                {
                    "client": "claude-code",
                    "model": "claude-opus",
                    "cwd": str(root),
                    "session_id": "sess-123",
                    "connection_id": "cid-456",
                    "instance_id": "claude_code#worker-05",
                },
            )
            self.assertEqual("claude_code#worker-05", entry["metadata"]["instance_id"])

    def test_register_session_id_fallback(self) -> None:
        """session_id is used when instance_id is not provided."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            entry = orch.register_agent(
                "gemini",
                {
                    "client": "gemini-cli",
                    "model": "gemini-2.5",
                    "cwd": str(root),
                    "session_id": "sess-abc",
                    "connection_id": "cid-def",
                },
            )
            self.assertEqual("sess-abc", entry["metadata"]["instance_id"])

    def test_register_connection_id_fallback(self) -> None:
        """connection_id is used when neither instance_id nor session_id is provided."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            entry = orch.register_agent(
                "gemini",
                {
                    "client": "gemini-cli",
                    "model": "gemini-2.5",
                    "cwd": str(root),
                    "connection_id": "cid-xyz",
                },
            )
            self.assertEqual("cid-xyz", entry["metadata"]["instance_id"])

    def test_register_default_fallback(self) -> None:
        """Default format agent#default is used when no identifiers provided."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            entry = orch.register_agent(
                "gemini",
                {
                    "client": "gemini-cli",
                    "model": "gemini-2.5",
                    "cwd": str(root),
                },
            )
            self.assertEqual("gemini#default", entry["metadata"]["instance_id"])

    def test_register_empty_instance_id_uses_fallback(self) -> None:
        """Empty string instance_id should fall through to session_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            entry = orch.register_agent(
                "claude_code",
                {
                    "client": "claude-code",
                    "model": "claude-opus",
                    "cwd": str(root),
                    "instance_id": "",
                    "session_id": "sess-fallback",
                },
            )
            self.assertEqual("sess-fallback", entry["metadata"]["instance_id"])

    def test_register_whitespace_instance_id_uses_fallback(self) -> None:
        """Whitespace-only instance_id should fall through to session_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            entry = orch.register_agent(
                "claude_code",
                {
                    "client": "claude-code",
                    "model": "claude-opus",
                    "cwd": str(root),
                    "instance_id": "   ",
                    "session_id": "sess-ws",
                },
            )
            self.assertEqual("sess-ws", entry["metadata"]["instance_id"])

    # ── heartbeat ───────────────────────────────────────────────────────

    def test_heartbeat_preserves_existing_instance_id_without_metadata(self) -> None:
        """Heartbeat without metadata should preserve previously set instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            # Register with explicit instance_id
            orch.register_agent(
                "claude_code",
                {
                    **_team_metadata(root, "claude-code", "claude-opus", "team_member", "sid-1", "cid-1"),
                    "instance_id": "claude_code#worker-01",
                },
            )
            # Heartbeat without metadata
            entry = orch.heartbeat("claude_code")
            self.assertEqual("claude_code#worker-01", entry["metadata"]["instance_id"])

    def test_heartbeat_explicit_instance_id_override(self) -> None:
        """Heartbeat with explicit instance_id should override previous value."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                {
                    **_team_metadata(root, "claude-code", "claude-opus", "team_member", "sid-1", "cid-1"),
                    "instance_id": "claude_code#worker-01",
                },
            )
            # Heartbeat with new instance_id
            entry = orch.heartbeat(
                "claude_code",
                metadata={"instance_id": "claude_code#worker-99"},
            )
            self.assertEqual("claude_code#worker-99", entry["metadata"]["instance_id"])

    def test_heartbeat_session_id_does_not_override_existing_instance_id(self) -> None:
        """Heartbeat with session_id but no instance_id should keep existing instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                {
                    **_team_metadata(root, "claude-code", "claude-opus", "team_member", "sid-1", "cid-1"),
                    "instance_id": "claude_code#worker-01",
                },
            )
            # Heartbeat with new session_id but no instance_id
            entry = orch.heartbeat(
                "claude_code",
                metadata={"session_id": "new-session"},
            )
            # The merged metadata has instance_id from existing + session_id from new
            # Since instance_id exists in merged, it takes precedence over session_id
            iid = entry["metadata"]["instance_id"]
            self.assertEqual("claude_code#worker-01", iid)

    # ── connect_to_leader ───────────────────────────────────────────────

    def test_connect_explicit_instance_id_in_response(self) -> None:
        """connect_to_leader with explicit instance_id should reflect in identity."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            result = orch.connect_to_leader(
                agent="claude_code",
                metadata={
                    **_team_metadata(root, "claude-code", "claude-opus", "team_member", "sid-cc", "cid-cc"),
                    "instance_id": "claude_code#worker-03",
                },
                source="claude_code",
            )
            self.assertEqual("claude_code#worker-03", result["identity"]["instance_id"])

    def test_connect_session_id_fallback_in_response(self) -> None:
        """connect_to_leader without instance_id falls back to session_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            result = orch.connect_to_leader(
                agent="gemini",
                metadata=_team_metadata(root, "gemini-cli", "gemini-2.5", "team_member", "sid-gm", "cid-gm"),
                source="gemini",
            )
            self.assertEqual("sid-gm", result["identity"]["instance_id"])

    def test_connect_default_fallback_in_response(self) -> None:
        """connect_to_leader with empty session/connection IDs uses default."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            result = orch.connect_to_leader(
                agent="gemini",
                metadata={
                    "role": "team_member",
                    "client": "gemini-cli",
                    "model": "gemini-2.5",
                    "cwd": str(root),
                    "project_root": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "workspace-write",
                    "server_version": "0.1.0",
                    "verification_source": "test",
                },
                source="gemini",
            )
            self.assertEqual("gemini#default", result["identity"]["instance_id"])

    # ── instance recording ──────────────────────────────────────────────

    def test_instance_recorded_after_register(self) -> None:
        """register_agent should create an instance record."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.register_agent(
                "claude_code",
                {
                    **_team_metadata(root, "claude-code", "claude-opus", "team_member", "sid-1", "cid-1"),
                    "instance_id": "claude_code#worker-01",
                },
            )
            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i.get("agent_name") == "claude_code"]
            self.assertEqual(1, len(cc))
            self.assertEqual("claude_code#worker-01", cc[0]["instance_id"])

    def test_instance_recorded_after_heartbeat(self) -> None:
        """heartbeat should update/create an instance record."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = self._make_orch(root)
            orch.heartbeat(
                "gemini",
                metadata={
                    **_team_metadata(root, "gemini-cli", "gemini-2.5", "team_member", "sid-g", "cid-g"),
                    "instance_id": "gemini#worker-01",
                },
            )
            instances = orch.list_agent_instances(active_only=False)
            gm = [i for i in instances if i.get("agent_name") == "gemini"]
            self.assertEqual(1, len(gm))
            self.assertEqual("gemini#worker-01", gm[0]["instance_id"])


if __name__ == "__main__":
    unittest.main()
