"""Consolidated tests for audit logging, decision recording, and learnings."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bus import EventBus
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ── helpers ──────────────────────────────────────────────────────────

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


def _team_meta(root: Path, agent: str) -> dict:
    return {
        "role": "team_member", "client": f"{agent}-cli", "model": agent,
        "cwd": str(root), "project_root": str(root),
        "permissions_mode": "default", "sandbox_mode": "workspace-write",
        "session_id": f"sid-{agent}", "connection_id": f"cid-{agent}",
        "server_version": "0.1.0", "verification_source": "test",
    }


class _BusMixin:
    """Provides a fresh EventBus per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bus = EventBus(root=self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ── audit: append ────────────────────────────────────────────────────

class TestAppendAudit(_BusMixin, unittest.TestCase):

    def test_returns_entry_with_timestamp(self) -> None:
        entry = self.bus.append_audit({"tool": "t", "status": "ok"})
        self.assertIn("timestamp", entry)
        self.assertEqual("t", entry["tool"])

    def test_preserves_existing_timestamp(self) -> None:
        ts = "2026-01-01T00:00:00+00:00"
        entry = self.bus.append_audit({"tool": "x", "status": "ok", "timestamp": ts})
        self.assertEqual(ts, entry["timestamp"])

    def test_persists_to_file(self) -> None:
        self.bus.append_audit({"tool": "persist", "status": "ok"})
        self.assertTrue(self.bus.audit_path.exists())
        self.assertIn("persist", self.bus.audit_path.read_text(encoding="utf-8"))

    def test_multiple_entries_append(self) -> None:
        for i in range(5):
            self.bus.append_audit({"tool": f"t{i}", "status": "ok"})
        lines = [l for l in self.bus.audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(5, len(lines))


# ── audit: read basics ──────────────────────────────────────────────

class TestReadAudit(_BusMixin, unittest.TestCase):

    def test_empty_returns_empty(self) -> None:
        self.assertEqual([], list(self.bus.read_audit()))

    def test_empty_file_returns_empty(self) -> None:
        self.bus.audit_path.write_text("", encoding="utf-8")
        self.assertEqual([], list(self.bus.read_audit()))

    def test_reads_appended_entries(self) -> None:
        self.bus.append_audit({"tool": "a", "status": "ok"})
        self.bus.append_audit({"tool": "b", "status": "ok"})
        result = list(self.bus.read_audit())
        self.assertEqual(2, len(result))

    def test_preserves_entry_fields(self) -> None:
        self.bus.append_audit({"tool": "m", "status": "ok", "args": {"x": 1}})
        r = list(self.bus.read_audit())[0]
        self.assertEqual("m", r["tool"])
        self.assertEqual(1, r["args"]["x"])

    def test_skips_malformed_lines(self) -> None:
        self.bus.append_audit({"tool": "good", "status": "ok"})
        with self.bus.audit_path.open("a", encoding="utf-8") as fh:
            fh.write("not json\n")
        self.bus.append_audit({"tool": "also_good", "status": "ok"})
        result = list(self.bus.read_audit())
        self.assertEqual(2, len(result))

    def test_skips_blank_lines(self) -> None:
        self.bus.append_audit({"tool": "t", "status": "ok"})
        with self.bus.audit_path.open("a", encoding="utf-8") as fh:
            fh.write("\n\n\n")
        self.bus.append_audit({"tool": "t2", "status": "ok"})
        self.assertEqual(2, len(list(self.bus.read_audit())))

    def test_entry_without_tool_field_readable(self) -> None:
        self.bus.append_audit({"status": "ok", "data": "no tool"})
        result = list(self.bus.read_audit())
        self.assertEqual(1, len(result))
        self.assertEqual("no tool", result[0]["data"])


# ── audit: filters ───────────────────────────────────────────────────

class TestAuditFilters(_BusMixin, unittest.TestCase):

    def setUp(self) -> None:
        super().setUp()
        self.bus.append_audit({"tool": "claim_task", "status": "ok"})
        self.bus.append_audit({"tool": "submit_report", "status": "ok"})
        self.bus.append_audit({"tool": "claim_task", "status": "error"})
        self.bus.append_audit({"tool": "poll_events", "status": "ok"})
        self.bus.append_audit({"tool": "submit_report", "status": "error"})

    def test_filter_by_tool_name(self) -> None:
        result = list(self.bus.read_audit(tool_name="claim_task"))
        self.assertEqual(2, len(result))
        self.assertTrue(all(r["tool"] == "claim_task" for r in result))

    def test_filter_by_status(self) -> None:
        result = list(self.bus.read_audit(status="error"))
        self.assertEqual(2, len(result))
        self.assertTrue(all(r["status"] == "error" for r in result))

    def test_combined_filter(self) -> None:
        result = list(self.bus.read_audit(tool_name="claim_task", status="error"))
        self.assertEqual(1, len(result))
        self.assertEqual("claim_task", result[0]["tool"])

    def test_tool_filter_no_match(self) -> None:
        self.assertEqual([], list(self.bus.read_audit(tool_name="nonexistent")))

    def test_combined_filter_no_match(self) -> None:
        self.assertEqual([], list(self.bus.read_audit(tool_name="poll_events", status="error")))

    def test_no_filter_returns_all(self) -> None:
        self.assertEqual(5, len(list(self.bus.read_audit())))

    def test_tool_filter_excludes_entries_without_tool(self) -> None:
        self.bus.append_audit({"status": "ok", "data": "no tool"})
        result = list(self.bus.read_audit(tool_name="claim_task"))
        self.assertTrue(all("tool" in r for r in result))


# ── audit: limit ─────────────────────────────────────────────────────

class TestAuditLimit(_BusMixin, unittest.TestCase):

    def setUp(self) -> None:
        super().setUp()
        for i in range(20):
            self.bus.append_audit({"tool": "bulk", "status": "ok", "n": i})

    def test_limit_caps_results(self) -> None:
        self.assertEqual(5, len(list(self.bus.read_audit(limit=5))))

    def test_limit_returns_most_recent(self) -> None:
        result = list(self.bus.read_audit(limit=3))
        self.assertEqual([17, 18, 19], [r["n"] for r in result])

    def test_limit_larger_than_total(self) -> None:
        self.assertEqual(20, len(list(self.bus.read_audit(limit=100))))

    def test_limit_with_filter(self) -> None:
        for i in range(10):
            self.bus.append_audit({"tool": "special", "status": "ok", "n": 100 + i})
        result = list(self.bus.read_audit(tool_name="special", limit=3))
        self.assertEqual(3, len(result))
        self.assertTrue(all(r["tool"] == "special" for r in result))

    def test_default_limit_is_100(self) -> None:
        # Add more entries to exceed default limit
        for i in range(130):
            self.bus.append_audit({"tool": f"extra_{i}", "status": "ok"})
        # 20 from setUp + 130 = 150 total; default limit should cap at 100
        self.assertEqual(100, len(list(self.bus.read_audit())))


# ── decisions ────────────────────────────────────────────────────────

class TestDecisions(unittest.TestCase):

    def test_record_decision_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            decisions_file = root / "decisions" / "decisions.jsonl"
            self.assertFalse(decisions_file.exists())

            d1 = orch.orchestrator_record_decision(
                topic="DB", choice="PostgreSQL",
                rationale="ACID", agent="codex", references=["link1"],
            )
            self.assertTrue(decisions_file.exists())
            self.assertIn("DEC-", d1["id"])

            d2 = orch.orchestrator_record_decision(
                topic="Framework", choice="React",
                rationale="Components", agent="gemini",
            )
            lines = decisions_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))

            loaded1 = json.loads(lines[0])
            self.assertEqual(d1["id"], loaded1["id"])
            self.assertEqual("PostgreSQL", loaded1["choice"])
            self.assertEqual(["link1"], loaded1["references"])

            loaded2 = json.loads(lines[1])
            self.assertEqual(d2["id"], loaded2["id"])
            self.assertEqual([], loaded2["references"])

    def test_connect_to_leader_loads_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.orchestrator_record_decision(
                topic="Auth", choice="OAuth2",
                rationale="Standard", agent="claude_code", references=["rfc6749"],
            )
            orch.orchestrator_record_decision(
                topic="CI", choice="GitHub Actions",
                rationale="Integrated", agent="codex",
            )

            result = orch.connect_to_leader(
                agent="gemini", metadata=_team_meta(root, "gemini"), source="gemini",
            )
            self.assertTrue(result["connected"])
            decisions = result["identity"]["decisions"]
            self.assertEqual(2, len(decisions))
            self.assertEqual("OAuth2", decisions[0]["choice"])
            self.assertEqual("GitHub Actions", decisions[1]["choice"])


# ── learnings ────────────────────────────────────────────────────────

class TestLearnings(unittest.TestCase):

    def test_record_learning_with_and_without_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            agent = "gemini"
            orch.connect_to_leader(
                agent=agent, metadata=_team_meta(root, agent), source=agent,
            )

            orch.orchestrator_record_learning(
                agent=agent,
                learning="Persistent state management.",
                context="While implementing decision logging.",
            )
            history = (root / "state" / "agents" / agent / "history.md")
            self.assertTrue(history.exists())
            content = history.read_text(encoding="utf-8")
            self.assertIn("### Learning by gemini at", content)
            self.assertIn("**Learning:** Persistent state management.", content)
            self.assertIn("**Context:** While implementing decision logging.", content)

            # Second learning without context
            orch.orchestrator_record_learning(
                agent=agent, learning="Atomic writes matter.",
            )
            content = history.read_text(encoding="utf-8")
            self.assertIn("**Learning:** Atomic writes matter.", content)

    def test_connect_to_leader_loads_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            agent = "claude_code"
            orch.connect_to_leader(
                agent=agent, metadata=_team_meta(root, agent), source=agent,
            )
            orch.orchestrator_record_learning(
                agent=agent, learning="Tricky test case.",
                context="Writing MCP tool tests.",
            )
            orch.orchestrator_record_learning(
                agent=agent, learning="Optimized slow query.",
            )

            result = orch.connect_to_leader(
                agent=agent, metadata=_team_meta(root, agent), source=agent,
            )
            hist = result["identity"]["history"]
            self.assertIn("**Learning:** Tricky test case.", hist)
            self.assertIn("**Context:** Writing MCP tool tests.", hist)
            self.assertIn("**Learning:** Optimized slow query.", hist)


if __name__ == "__main__":
    unittest.main()
