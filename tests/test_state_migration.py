"""Tests for versioned state schema migration.

Covers migration from legacy (v0 / no schema_version) to v1 for
tasks.json, agents.json, and events.jsonl.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.migration import (
    CURRENT_SCHEMA_VERSION,
    detect_schema_version,
    migrate_state,
)


class TestDetectSchemaVersion(unittest.TestCase):
    def test_fresh_state_dir_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(detect_schema_version(Path(td)), 0)

    def test_returns_version_from_meta(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            meta = Path(td) / "schema_meta.json"
            meta.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
            self.assertEqual(detect_schema_version(Path(td)), 1)


class TestMigrateTasksV0ToV1(unittest.TestCase):
    """Legacy tasks.json (bare list, no schema_version) → v1 records."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmp.name) / "state"
        self.bus_dir = Path(self._tmp.name) / "bus"
        self.state_dir.mkdir()
        self.bus_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_tasks(self, tasks: list) -> None:
        (self.state_dir / "tasks.json").write_text(
            json.dumps(tasks, indent=2), encoding="utf-8"
        )

    def _read_tasks(self) -> list:
        return json.loads((self.state_dir / "tasks.json").read_text(encoding="utf-8"))

    def test_legacy_tasks_get_schema_version(self) -> None:
        self._write_tasks([
            {"id": "TASK-aaa", "title": "test task", "status": "assigned"},
        ])
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("tasks.json", report["migrated"])
        tasks = self._read_tasks()
        self.assertIsInstance(tasks, list)  # still a list, not a wrapper
        self.assertEqual(tasks[0]["schema_version"], 1)

    def test_legacy_tasks_get_default_fields(self) -> None:
        self._write_tasks([{"id": "TASK-bbb", "title": "bare task"}])
        migrate_state(self.state_dir, self.bus_dir)
        task = self._read_tasks()[0]
        self.assertIsNone(task["team_id"])
        self.assertIsNone(task["parent_task_id"])
        self.assertEqual(task["tags"], [])
        self.assertIn("risk", task["delivery_profile"])

    def test_already_migrated_tasks_skipped(self) -> None:
        self._write_tasks([
            {"id": "TASK-ccc", "schema_version": 1, "title": "already done"},
        ])
        # Write schema_meta so detect_schema_version returns 1
        (self.state_dir / "schema_meta.json").write_text(
            json.dumps({"schema_version": 1}), encoding="utf-8"
        )
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("tasks.json", report["skipped"])
        self.assertEqual(report["migrated"], [])

    def test_empty_tasks_file(self) -> None:
        self._write_tasks([])
        report = migrate_state(self.state_dir, self.bus_dir)
        # Empty list → no records changed → skipped
        self.assertIn("tasks.json", report["skipped"])

    def test_missing_tasks_file(self) -> None:
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("tasks.json", report["skipped"])

    def test_existing_fields_not_overwritten(self) -> None:
        self._write_tasks([{
            "id": "TASK-ddd",
            "team_id": "team-alpha",
            "tags": ["important"],
            "delivery_profile": {"risk": "high", "test_plan": "full", "doc_impact": "roadmap"},
        }])
        migrate_state(self.state_dir, self.bus_dir)
        task = self._read_tasks()[0]
        self.assertEqual(task["team_id"], "team-alpha")
        self.assertEqual(task["tags"], ["important"])
        self.assertEqual(task["delivery_profile"]["risk"], "high")


class TestMigrateAgentsV0ToV1(unittest.TestCase):
    """Legacy agents.json (bare dict, no schema_version) → v1 records."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmp.name) / "state"
        self.bus_dir = Path(self._tmp.name) / "bus"
        self.state_dir.mkdir()
        self.bus_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_agents(self, agents: dict) -> None:
        (self.state_dir / "agents.json").write_text(
            json.dumps(agents, indent=2), encoding="utf-8"
        )

    def _read_agents(self) -> dict:
        return json.loads((self.state_dir / "agents.json").read_text(encoding="utf-8"))

    def test_legacy_agents_get_schema_version(self) -> None:
        self._write_agents({
            "claude_code": {"agent": "claude_code", "status": "active"},
            "gemini": {"agent": "gemini", "status": "active"},
        })
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("agents.json", report["migrated"])
        agents = self._read_agents()
        self.assertIsInstance(agents, dict)  # still a plain dict
        self.assertEqual(agents["claude_code"]["schema_version"], 1)
        self.assertEqual(agents["gemini"]["schema_version"], 1)

    def test_empty_agents_file(self) -> None:
        self._write_agents({})
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("agents.json", report["skipped"])


class TestMigrateEventsV0ToV1(unittest.TestCase):
    """Legacy events.jsonl (no schema_version per line) → v1 lines."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmp.name) / "state"
        self.bus_dir = Path(self._tmp.name) / "bus"
        self.state_dir.mkdir()
        self.bus_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_events(self, events: list) -> None:
        lines = [json.dumps(e) for e in events]
        (self.bus_dir / "events.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def _read_events(self) -> list:
        text = (self.bus_dir / "events.jsonl").read_text(encoding="utf-8")
        return [json.loads(l) for l in text.splitlines() if l.strip()]

    def test_legacy_events_get_schema_version(self) -> None:
        self._write_events([
            {"event_id": "EVT-aaa", "type": "agent.heartbeat", "source": "codex"},
            {"event_id": "EVT-bbb", "type": "task.created", "source": "orchestrator"},
        ])
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("events.jsonl", report["migrated"])
        events = self._read_events()
        self.assertEqual(events[0]["schema_version"], 1)
        self.assertEqual(events[1]["schema_version"], 1)

    def test_already_versioned_events_skipped(self) -> None:
        self._write_events([
            {"event_id": "EVT-ccc", "schema_version": 1, "type": "test"},
        ])
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("events.jsonl", report["skipped"])

    def test_missing_events_file(self) -> None:
        report = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("events.jsonl", report["skipped"])

    def test_blank_lines_preserved(self) -> None:
        content = json.dumps({"event_id": "EVT-ddd", "type": "test"}) + "\n\n"
        (self.bus_dir / "events.jsonl").write_text(content, encoding="utf-8")
        migrate_state(self.state_dir, self.bus_dir)
        text = (self.bus_dir / "events.jsonl").read_text(encoding="utf-8")
        # Original blank line should still be there (as empty line between content)
        self.assertIn("\n\n", text)


class TestSchemaMetaPersistence(unittest.TestCase):
    """schema_meta.json is written after successful migration."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmp.name) / "state"
        self.bus_dir = Path(self._tmp.name) / "bus"
        self.state_dir.mkdir()
        self.bus_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_meta_written_after_migration(self) -> None:
        (self.state_dir / "tasks.json").write_text("[]\n", encoding="utf-8")
        (self.state_dir / "agents.json").write_text("{}\n", encoding="utf-8")
        migrate_state(self.state_dir, self.bus_dir)
        meta_path = self.state_dir / "schema_meta.json"
        self.assertTrue(meta_path.exists())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["schema_version"], CURRENT_SCHEMA_VERSION)
        self.assertIn("migrated_at", meta)

    def test_idempotent_migration(self) -> None:
        (self.state_dir / "tasks.json").write_text(
            json.dumps([{"id": "TASK-x", "title": "t"}]), encoding="utf-8"
        )
        (self.state_dir / "agents.json").write_text("{}\n", encoding="utf-8")

        r1 = migrate_state(self.state_dir, self.bus_dir)
        self.assertIn("tasks.json", r1["migrated"])

        r2 = migrate_state(self.state_dir, self.bus_dir)
        self.assertEqual(r2["migrated"], [])
        self.assertIn("tasks.json", r2["skipped"])


class TestDryRun(unittest.TestCase):
    """dry_run=True reports changes without writing."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._tmp.name) / "state"
        self.bus_dir = Path(self._tmp.name) / "bus"
        self.state_dir.mkdir()
        self.bus_dir.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dry_run_does_not_modify_files(self) -> None:
        original = [{"id": "TASK-dry", "title": "unchanged"}]
        (self.state_dir / "tasks.json").write_text(
            json.dumps(original), encoding="utf-8"
        )
        (self.state_dir / "agents.json").write_text("{}\n", encoding="utf-8")
        report = migrate_state(self.state_dir, self.bus_dir, dry_run=True)
        self.assertIn("tasks.json", report["migrated"])
        self.assertTrue(report["dry_run"])

        # File should be unchanged
        data = json.loads(
            (self.state_dir / "tasks.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("schema_version", data[0])

        # No schema_meta.json written
        self.assertFalse((self.state_dir / "schema_meta.json").exists())


class TestBootstrapIntegration(unittest.TestCase):
    """Verify migration runs during Orchestrator.bootstrap()."""

    def test_bootstrap_stamps_schema_version(self) -> None:
        from orchestrator.engine import Orchestrator
        from orchestrator.policy import Policy

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = {
                "name": "test-policy",
                "roles": {"manager": "codex"},
                "routing": {"backend": "claude_code", "default": "codex"},
                "decisions": {"architecture": {"mode": "consensus", "members": ["codex"]}},
                "triggers": {"heartbeat_timeout_minutes": 10},
            }
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            policy = Policy.load(policy_path)
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            meta_path = root / "state" / "schema_meta.json"
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["schema_version"], CURRENT_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
