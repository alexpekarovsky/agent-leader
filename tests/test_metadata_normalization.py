"""Tests for _normalize_agent_metadata and _current_agent_instance_id_unlocked.

Covers instance_id derivation priority (explicit > session_id > connection_id > default),
metadata merge with existing values, and _current_agent_instance_id_unlocked fallback paths.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    data = {
        "name": "test-policy",
        "manager": "codex",
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "architecture_mode": "solo",
        "triggers": {},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


class NormalizeExplicitInstanceIdTests(unittest.TestCase):
    """When instance_id is explicitly provided, it should be preserved."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_explicit_instance_id_preserved(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code", {"instance_id": "my-instance-42"}
        )
        self.assertEqual(result["instance_id"], "my-instance-42")

    def test_explicit_instance_id_over_session_id(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code",
            {"instance_id": "explicit-id", "session_id": "session-99"},
        )
        self.assertEqual(result["instance_id"], "explicit-id")

    def test_explicit_instance_id_over_connection_id(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code",
            {"instance_id": "explicit-id", "connection_id": "conn-77"},
        )
        self.assertEqual(result["instance_id"], "explicit-id")


class NormalizeSessionIdFallbackTests(unittest.TestCase):
    """When no instance_id, session_id should be used."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_session_id_fallback(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code", {"session_id": "sess-abc"}
        )
        self.assertEqual(result["instance_id"], "sess-abc")

    def test_session_id_over_connection_id(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code",
            {"session_id": "sess-abc", "connection_id": "conn-xyz"},
        )
        self.assertEqual(result["instance_id"], "sess-abc")


class NormalizeConnectionIdFallbackTests(unittest.TestCase):
    """When no instance_id or session_id, connection_id should be used."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_connection_id_fallback(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code", {"connection_id": "conn-xyz"}
        )
        self.assertEqual(result["instance_id"], "conn-xyz")


class NormalizeDefaultFallbackTests(unittest.TestCase):
    """When no IDs at all, should fall back to agent#default."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_default_fallback_no_metadata(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {})
        self.assertEqual(result["instance_id"], "claude_code#default")

    def test_default_fallback_none_metadata(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", None)
        self.assertEqual(result["instance_id"], "claude_code#default")

    def test_default_fallback_empty_strings(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "gemini", {"instance_id": "", "session_id": "", "connection_id": ""}
        )
        self.assertEqual(result["instance_id"], "gemini#default")

    def test_default_fallback_whitespace_only(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "codex", {"instance_id": "  ", "session_id": "  "}
        )
        self.assertEqual(result["instance_id"], "codex#default")


class NormalizeMergeTests(unittest.TestCase):
    """Metadata merge with existing values."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_merge_new_over_existing(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code",
            {"model": "opus-4.6"},
            existing={"model": "sonnet-4.6", "client": "vscode"},
        )
        self.assertEqual(result["model"], "opus-4.6")
        self.assertEqual(result["client"], "vscode")

    def test_merge_preserves_existing_not_overwritten(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code",
            {"session_id": "s1"},
            existing={"client": "cli", "cwd": "/home"},
        )
        self.assertEqual(result["client"], "cli")
        self.assertEqual(result["cwd"], "/home")
        self.assertEqual(result["instance_id"], "s1")

    def test_merge_none_existing(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code", {"session_id": "s1"}, existing=None
        )
        self.assertEqual(result["instance_id"], "s1")

    def test_merge_none_metadata_uses_existing(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code", None, existing={"instance_id": "from-existing"}
        )
        self.assertEqual(result["instance_id"], "from-existing")

    def test_merge_existing_instance_id_overridden_by_new(self) -> None:
        result = self.orch._normalize_agent_metadata(
            "claude_code",
            {"instance_id": "new-id"},
            existing={"instance_id": "old-id"},
        )
        self.assertEqual(result["instance_id"], "new-id")


class CurrentAgentInstanceIdTests(unittest.TestCase):
    """Tests for _current_agent_instance_id_unlocked."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_agent_not_found_returns_default(self) -> None:
        result = self.orch._current_agent_instance_id_unlocked("unknown_agent")
        self.assertEqual(result, "unknown_agent#default")

    def test_agent_with_session_id_in_metadata(self) -> None:
        # Register agent with metadata containing session_id
        self.orch.register_agent("claude_code", metadata={"session_id": "sess-42"})
        result = self.orch._current_agent_instance_id_unlocked("claude_code")
        self.assertEqual(result, "sess-42")

    def test_agent_with_explicit_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-99"})
        result = self.orch._current_agent_instance_id_unlocked("claude_code")
        self.assertEqual(result, "inst-99")

    def test_agent_with_no_metadata_returns_default(self) -> None:
        self.orch.register_agent("claude_code")
        result = self.orch._current_agent_instance_id_unlocked("claude_code")
        self.assertEqual(result, "claude_code#default")

    def test_agent_with_empty_metadata_returns_default(self) -> None:
        self.orch.register_agent("claude_code", metadata={})
        result = self.orch._current_agent_instance_id_unlocked("claude_code")
        self.assertEqual(result, "claude_code#default")

    def test_agent_with_connection_id_only(self) -> None:
        self.orch.register_agent("gemini", metadata={"connection_id": "conn-88"})
        result = self.orch._current_agent_instance_id_unlocked("gemini")
        self.assertEqual(result, "conn-88")

    def test_agents_file_missing_returns_default(self) -> None:
        self.orch.agents_path.unlink(missing_ok=True)
        result = self.orch._current_agent_instance_id_unlocked("claude_code")
        self.assertEqual(result, "claude_code#default")


if __name__ == "__main__":
    unittest.main()
