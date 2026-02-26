"""Unit tests for audit log: append_audit and read_audit.

Tests cover reading entries, filtering by tool_name, filtering by status,
limit parameter, empty/no-match cases, and combined filters.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.bus import EventBus


def _make_bus(root: Path) -> EventBus:
    return EventBus(root=root)


class AppendAuditTests(unittest.TestCase):
    """Tests for append_audit."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bus = _make_bus(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_returns_entry_with_timestamp(self) -> None:
        entry = self.bus.append_audit({"tool": "test_tool", "status": "ok"})
        self.assertIn("timestamp", entry)
        self.assertEqual(entry["tool"], "test_tool")

    def test_append_preserves_existing_timestamp(self) -> None:
        entry = self.bus.append_audit({
            "tool": "x", "status": "ok", "timestamp": "2026-01-01T00:00:00+00:00",
        })
        self.assertEqual(entry["timestamp"], "2026-01-01T00:00:00+00:00")

    def test_append_persists_to_file(self) -> None:
        self.bus.append_audit({"tool": "persist_tool", "status": "ok"})
        self.assertTrue(self.bus.audit_path.exists())
        content = self.bus.audit_path.read_text(encoding="utf-8")
        self.assertIn("persist_tool", content)

    def test_append_multiple_entries(self) -> None:
        for i in range(5):
            self.bus.append_audit({"tool": f"tool_{i}", "status": "ok"})
        lines = [l for l in self.bus.audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 5)


class ReadAuditBasicTests(unittest.TestCase):
    """Tests for read_audit — basic reading."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bus = _make_bus(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_empty_returns_empty(self) -> None:
        """Reading when no audit file exists returns empty list."""
        result = list(self.bus.read_audit())
        self.assertEqual(result, [])

    def test_read_returns_appended_entries(self) -> None:
        self.bus.append_audit({"tool": "a", "status": "ok", "data": 1})
        self.bus.append_audit({"tool": "b", "status": "ok", "data": 2})
        result = list(self.bus.read_audit())
        self.assertEqual(len(result), 2)
        tools = [r["tool"] for r in result]
        self.assertIn("a", tools)
        self.assertIn("b", tools)

    def test_read_preserves_entry_fields(self) -> None:
        self.bus.append_audit({"tool": "my_tool", "status": "ok", "args": {"x": 1}})
        result = list(self.bus.read_audit())
        self.assertEqual(result[0]["tool"], "my_tool")
        self.assertEqual(result[0]["args"]["x"], 1)

    def test_read_skips_malformed_lines(self) -> None:
        """Malformed JSON lines should be silently skipped."""
        self.bus.append_audit({"tool": "good", "status": "ok"})
        # Manually write a bad line
        with self.bus.audit_path.open("a", encoding="utf-8") as fh:
            fh.write("this is not json\n")
        self.bus.append_audit({"tool": "also_good", "status": "ok"})
        result = list(self.bus.read_audit())
        self.assertEqual(len(result), 2)
        tools = [r["tool"] for r in result]
        self.assertIn("good", tools)
        self.assertIn("also_good", tools)


class ReadAuditFilterTests(unittest.TestCase):
    """Tests for read_audit — filtering by tool_name and status."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bus = _make_bus(self.root)
        # Seed audit entries
        self.bus.append_audit({"tool": "claim_task", "status": "ok", "n": 1})
        self.bus.append_audit({"tool": "submit_report", "status": "ok", "n": 2})
        self.bus.append_audit({"tool": "claim_task", "status": "error", "n": 3})
        self.bus.append_audit({"tool": "poll_events", "status": "ok", "n": 4})
        self.bus.append_audit({"tool": "submit_report", "status": "error", "n": 5})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_filter_by_tool_name(self) -> None:
        result = list(self.bus.read_audit(tool_name="claim_task"))
        self.assertEqual(len(result), 2)
        for r in result:
            self.assertEqual(r["tool"], "claim_task")

    def test_filter_by_status(self) -> None:
        result = list(self.bus.read_audit(status="error"))
        self.assertEqual(len(result), 2)
        for r in result:
            self.assertEqual(r["status"], "error")

    def test_filter_by_tool_and_status(self) -> None:
        result = list(self.bus.read_audit(tool_name="claim_task", status="error"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool"], "claim_task")
        self.assertEqual(result[0]["status"], "error")

    def test_filter_no_match_returns_empty(self) -> None:
        result = list(self.bus.read_audit(tool_name="nonexistent_tool"))
        self.assertEqual(result, [])

    def test_filter_status_no_match(self) -> None:
        result = list(self.bus.read_audit(status="timeout"))
        self.assertEqual(result, [])

    def test_combined_filter_no_match(self) -> None:
        result = list(self.bus.read_audit(tool_name="poll_events", status="error"))
        self.assertEqual(result, [])

    def test_no_filters_returns_all(self) -> None:
        result = list(self.bus.read_audit())
        self.assertEqual(len(result), 5)


class ReadAuditLimitTests(unittest.TestCase):
    """Tests for read_audit — limit parameter."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bus = _make_bus(self.root)
        for i in range(20):
            self.bus.append_audit({"tool": "bulk", "status": "ok", "n": i})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_limit_caps_results(self) -> None:
        result = list(self.bus.read_audit(limit=5))
        self.assertEqual(len(result), 5)

    def test_limit_returns_most_recent(self) -> None:
        """With limit, should return the most recent N entries (deque tail behavior)."""
        result = list(self.bus.read_audit(limit=3))
        self.assertEqual(len(result), 3)
        # The deque keeps the last N entries
        ns = [r["n"] for r in result]
        self.assertEqual(ns, [17, 18, 19])

    def test_limit_larger_than_total(self) -> None:
        result = list(self.bus.read_audit(limit=100))
        self.assertEqual(len(result), 20)

    def test_limit_with_filter(self) -> None:
        """Limit should apply after filtering."""
        # Add some entries with different tool
        for i in range(10):
            self.bus.append_audit({"tool": "special", "status": "ok", "n": 100 + i})
        result = list(self.bus.read_audit(tool_name="special", limit=3))
        self.assertEqual(len(result), 3)
        for r in result:
            self.assertEqual(r["tool"], "special")

    def test_default_limit_is_100(self) -> None:
        """Default limit should be 100."""
        # We have 20 entries, all should be returned with default limit
        result = list(self.bus.read_audit())
        self.assertEqual(len(result), 20)


class ReadAuditEdgeCaseTests(unittest.TestCase):
    """Edge cases for audit log."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bus = _make_bus(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_file_returns_empty(self) -> None:
        """An existing but empty audit file should return empty list."""
        self.bus.audit_path.write_text("", encoding="utf-8")
        result = list(self.bus.read_audit())
        self.assertEqual(result, [])

    def test_blank_lines_skipped(self) -> None:
        self.bus.append_audit({"tool": "t", "status": "ok"})
        with self.bus.audit_path.open("a", encoding="utf-8") as fh:
            fh.write("\n\n\n")
        self.bus.append_audit({"tool": "t2", "status": "ok"})
        result = list(self.bus.read_audit())
        self.assertEqual(len(result), 2)

    def test_entry_without_tool_field(self) -> None:
        """Entries without 'tool' field should still be readable."""
        self.bus.append_audit({"status": "ok", "data": "no tool"})
        result = list(self.bus.read_audit())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["data"], "no tool")

    def test_entry_without_tool_excluded_by_tool_filter(self) -> None:
        """Filtering by tool_name should exclude entries without tool field."""
        self.bus.append_audit({"status": "ok", "data": "no tool"})
        self.bus.append_audit({"tool": "my_tool", "status": "ok"})
        result = list(self.bus.read_audit(tool_name="my_tool"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tool"], "my_tool")


if __name__ == "__main__":
    unittest.main()
