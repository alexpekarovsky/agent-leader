"""Tests for audit log reading and filtering via bus.read_audit.

Validates limit, tool_name filter, status filter, combined filters,
empty results, and edge cases.
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


def _write_audit_entry(orch: Orchestrator, tool: str, status: str = "ok", **extra) -> dict:
    """Write an audit entry to the bus."""
    record = {"tool": tool, "status": status, "category": "mcp_tool_call"}
    record.update(extra)
    return orch.bus.append_audit(record)


class ReadAuditBasicTests(unittest.TestCase):
    """Basic read_audit tests."""

    def test_empty_audit_returns_empty(self) -> None:
        """read_audit on fresh state should return empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            logs = list(orch.bus.read_audit())
            self.assertEqual([], logs)

    def test_reads_written_entries(self) -> None:
        """Entries written via append_audit should be readable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "orchestrator_bootstrap")
            _write_audit_entry(orch, "orchestrator_claim_next_task")

            logs = list(orch.bus.read_audit())
            self.assertEqual(2, len(logs))

    def test_entry_has_tool_field(self) -> None:
        """Each audit entry should have a 'tool' field."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "orchestrator_heartbeat")

            logs = list(orch.bus.read_audit())
            self.assertEqual("orchestrator_heartbeat", logs[0]["tool"])

    def test_entry_has_timestamp(self) -> None:
        """append_audit should add a timestamp to entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "orchestrator_status")

            logs = list(orch.bus.read_audit())
            self.assertIn("timestamp", logs[0])

    def test_returns_list(self) -> None:
        """read_audit should return a list (or iterable convertible to list)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.bus.read_audit()
            self.assertIsInstance(list(result), list)


class ReadAuditFilterTests(unittest.TestCase):
    """Tests for read_audit filtering."""

    def test_filter_by_tool_name(self) -> None:
        """tool_name filter should return only matching entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "orchestrator_bootstrap")
            _write_audit_entry(orch, "orchestrator_claim_next_task")
            _write_audit_entry(orch, "orchestrator_bootstrap")

            logs = list(orch.bus.read_audit(tool_name="orchestrator_bootstrap"))
            self.assertEqual(2, len(logs))
            for entry in logs:
                self.assertEqual("orchestrator_bootstrap", entry["tool"])

    def test_filter_by_tool_name_no_match(self) -> None:
        """tool_name filter with no matching entries should return empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "orchestrator_bootstrap")

            logs = list(orch.bus.read_audit(tool_name="orchestrator_nonexistent"))
            self.assertEqual([], logs)

    def test_filter_by_status(self) -> None:
        """status filter should return only matching entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "orchestrator_claim_next_task", status="ok")
            _write_audit_entry(orch, "orchestrator_claim_next_task", status="error")
            _write_audit_entry(orch, "orchestrator_heartbeat", status="ok")

            ok_logs = list(orch.bus.read_audit(status="ok"))
            self.assertEqual(2, len(ok_logs))
            for entry in ok_logs:
                self.assertEqual("ok", entry["status"])

    def test_filter_by_status_error(self) -> None:
        """status='error' should return only error entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "tool_a", status="ok")
            _write_audit_entry(orch, "tool_b", status="error")

            error_logs = list(orch.bus.read_audit(status="error"))
            self.assertEqual(1, len(error_logs))
            self.assertEqual("error", error_logs[0]["status"])

    def test_combined_tool_and_status_filter(self) -> None:
        """Both tool_name and status filters should apply together."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            _write_audit_entry(orch, "tool_a", status="ok")
            _write_audit_entry(orch, "tool_a", status="error")
            _write_audit_entry(orch, "tool_b", status="ok")
            _write_audit_entry(orch, "tool_b", status="error")

            logs = list(orch.bus.read_audit(tool_name="tool_a", status="error"))
            self.assertEqual(1, len(logs))
            self.assertEqual("tool_a", logs[0]["tool"])
            self.assertEqual("error", logs[0]["status"])

    def test_no_filter_returns_all(self) -> None:
        """Without filters, all entries should be returned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(5):
                _write_audit_entry(orch, f"tool_{i}")

            logs = list(orch.bus.read_audit())
            self.assertEqual(5, len(logs))


class ReadAuditLimitTests(unittest.TestCase):
    """Tests for read_audit limit parameter."""

    def test_limit_caps_results(self) -> None:
        """limit parameter should cap the number of returned entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(10):
                _write_audit_entry(orch, f"tool_{i}")

            logs = list(orch.bus.read_audit(limit=3))
            self.assertEqual(3, len(logs))

    def test_limit_returns_latest(self) -> None:
        """limit should return the most recent entries (tail behavior via deque)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(10):
                _write_audit_entry(orch, f"tool_{i}")

            logs = list(orch.bus.read_audit(limit=2))
            # Deque keeps the last N entries
            tools = [entry["tool"] for entry in logs]
            self.assertIn("tool_8", tools)
            self.assertIn("tool_9", tools)

    def test_limit_with_filter(self) -> None:
        """limit should apply after filtering."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(10):
                _write_audit_entry(orch, "target_tool")
            _write_audit_entry(orch, "other_tool")

            logs = list(orch.bus.read_audit(tool_name="target_tool", limit=3))
            self.assertEqual(3, len(logs))
            for entry in logs:
                self.assertEqual("target_tool", entry["tool"])

    def test_default_limit_is_100(self) -> None:
        """Default limit should be 100."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(150):
                _write_audit_entry(orch, f"tool_{i}")

            logs = list(orch.bus.read_audit())
            self.assertEqual(100, len(logs))

    def test_limit_larger_than_entries(self) -> None:
        """When limit > entries, should return all entries."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            for i in range(3):
                _write_audit_entry(orch, f"tool_{i}")

            logs = list(orch.bus.read_audit(limit=100))
            self.assertEqual(3, len(logs))


if __name__ == "__main__":
    unittest.main()
