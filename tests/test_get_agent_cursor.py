"""Tests for get_agent_cursor.

Validates cursor retrieval, initialization, and advancement
through event polling.
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


def _register_agent(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"cid-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    })


class GetAgentCursorTests(unittest.TestCase):
    """Tests for get_agent_cursor."""

    def test_unknown_agent_returns_zero(self) -> None:
        """Cursor for an unknown agent should default to 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            cursor = orch.get_agent_cursor("nonexistent")
            self.assertEqual(0, cursor)

    def test_returns_int(self) -> None:
        """Cursor should always be an integer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            cursor = orch.get_agent_cursor("claude_code")
            self.assertIsInstance(cursor, int)

    def test_cursor_advances_after_poll(self) -> None:
        """After polling events with auto_advance, cursor should advance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            # Emit an event so there's something to poll
            orch.publish_event("test.ping", "orchestrator", {"hello": True})

            before = orch.get_agent_cursor("claude_code")
            orch.poll_events("claude_code", timeout_ms=0)
            after = orch.get_agent_cursor("claude_code")

            self.assertGreater(after, before)

    def test_cursor_unchanged_without_auto_advance(self) -> None:
        """Polling with auto_advance=False should not change the cursor."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("test.noadvance", "orchestrator", {"v": 1})

            before = orch.get_agent_cursor("claude_code")
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=False)
            after = orch.get_agent_cursor("claude_code")

            self.assertEqual(before, after)

    def test_different_agents_have_independent_cursors(self) -> None:
        """Each agent should maintain its own cursor position."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            _register_agent(orch, "gemini")

            orch.publish_event("test.multi", "orchestrator", {"v": 1})

            # Only claude_code polls
            orch.poll_events("claude_code", timeout_ms=0)

            cc_cursor = orch.get_agent_cursor("claude_code")
            gem_cursor = orch.get_agent_cursor("gemini")

            self.assertGreater(cc_cursor, gem_cursor)

    def test_cursor_persists_across_reads(self) -> None:
        """Cursor should be persisted and consistent across multiple reads."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.publish_event("test.persist", "orchestrator", {"v": 1})
            orch.poll_events("claude_code", timeout_ms=0)

            cursor1 = orch.get_agent_cursor("claude_code")
            cursor2 = orch.get_agent_cursor("claude_code")

            self.assertEqual(cursor1, cursor2)

    def test_corrupted_cursors_file_recovers(self) -> None:
        """If cursors file is not a dict, get_agent_cursor should recover gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Write corrupted data
            orch.cursors_path.write_text("null", encoding="utf-8")

            cursor = orch.get_agent_cursor("claude_code")
            self.assertEqual(0, cursor)


if __name__ == "__main__":
    unittest.main()
