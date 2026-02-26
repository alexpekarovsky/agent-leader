"""Tests for Policy methods and Bus report/command I/O.

Validates Policy.manager, task_owner_for, architecture_mode, voters,
and Bus write_command, write_report, read_report.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bus import EventBus
from orchestrator.policy import Policy


def _make_policy_raw(**overrides) -> dict:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    raw.update(overrides)
    return raw


def _write_and_load(root: Path, raw: dict) -> Policy:
    path = root / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


class PolicyManagerTests(unittest.TestCase):
    """Tests for Policy.manager."""

    def test_returns_configured_manager(self) -> None:
        """manager() should return the manager from roles."""
        with tempfile.TemporaryDirectory() as tmp:
            policy = _write_and_load(Path(tmp), _make_policy_raw())
            self.assertEqual("codex", policy.manager())

    def test_custom_manager(self) -> None:
        """manager() should return a custom manager when configured."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(roles={"manager": "claude_code"})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual("claude_code", policy.manager())

    def test_missing_manager_defaults_to_codex(self) -> None:
        """manager() should default to 'codex' when not in roles."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(roles={})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual("codex", policy.manager())


class PolicyTaskOwnerForTests(unittest.TestCase):
    """Tests for Policy.task_owner_for."""

    def test_returns_routed_owner(self) -> None:
        """task_owner_for should return the agent for the workstream."""
        with tempfile.TemporaryDirectory() as tmp:
            policy = _write_and_load(Path(tmp), _make_policy_raw())
            self.assertEqual("claude_code", policy.task_owner_for("backend"))

    def test_frontend_routing(self) -> None:
        """task_owner_for('frontend') should return the frontend agent."""
        with tempfile.TemporaryDirectory() as tmp:
            policy = _write_and_load(Path(tmp), _make_policy_raw())
            self.assertEqual("gemini", policy.task_owner_for("frontend"))

    def test_unknown_workstream_uses_default(self) -> None:
        """Unknown workstream should fall back to the default route."""
        with tempfile.TemporaryDirectory() as tmp:
            policy = _write_and_load(Path(tmp), _make_policy_raw())
            self.assertEqual("codex", policy.task_owner_for("unknown_workstream"))

    def test_no_default_falls_back_to_manager(self) -> None:
        """When no default route exists, should fall back to manager."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(routing={"backend": "claude_code"})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual("codex", policy.task_owner_for("devops"))

    def test_empty_routing_uses_manager(self) -> None:
        """Empty routing should fall back to manager for any workstream."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(routing={})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual("codex", policy.task_owner_for("backend"))


class PolicyArchitectureModeTests(unittest.TestCase):
    """Tests for Policy.architecture_mode."""

    def test_returns_configured_mode(self) -> None:
        """architecture_mode should return the mode from decisions."""
        with tempfile.TemporaryDirectory() as tmp:
            policy = _write_and_load(Path(tmp), _make_policy_raw())
            self.assertEqual("consensus", policy.architecture_mode())

    def test_custom_mode(self) -> None:
        """architecture_mode should return a custom mode."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(decisions={"architecture": {"mode": "leader_decides", "members": []}})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual("leader_decides", policy.architecture_mode())

    def test_missing_mode_defaults_to_consensus(self) -> None:
        """Missing mode should default to 'consensus'."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(decisions={})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual("consensus", policy.architecture_mode())


class PolicyVotersTests(unittest.TestCase):
    """Tests for Policy.voters."""

    def test_returns_configured_voters(self) -> None:
        """voters() should return the members from decisions."""
        with tempfile.TemporaryDirectory() as tmp:
            policy = _write_and_load(Path(tmp), _make_policy_raw())
            voters = policy.voters()
            self.assertEqual(["codex", "claude_code", "gemini"], voters)

    def test_custom_voters(self) -> None:
        """voters() should return custom members list."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(decisions={"architecture": {"mode": "consensus", "members": ["a", "b"]}})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual(["a", "b"], policy.voters())

    def test_empty_members_defaults_to_trio(self) -> None:
        """Empty members should default to codex/claude_code/gemini."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(decisions={"architecture": {"mode": "consensus", "members": []}})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual(["codex", "claude_code", "gemini"], policy.voters())

    def test_missing_decisions_defaults_to_trio(self) -> None:
        """Missing decisions should default to the trio."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = _make_policy_raw(decisions={})
            policy = _write_and_load(Path(tmp), raw)
            self.assertEqual(["codex", "claude_code", "gemini"], policy.voters())


class BusWriteCommandTests(unittest.TestCase):
    """Tests for Bus.write_command."""

    def test_writes_command_file(self) -> None:
        """write_command should create a JSON file in commands dir."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            command = {"action": "claim", "agent": "claude_code"}

            path = bus.write_command("TASK-001", command)

            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("claim", data["action"])

    def test_command_file_named_by_task_id(self) -> None:
        """Command file should be named {task_id}.json."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            path = bus.write_command("TASK-xyz", {"action": "test"})

            self.assertEqual("TASK-xyz.json", path.name)

    def test_command_returns_path(self) -> None:
        """write_command should return the Path to the written file."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            result = bus.write_command("TASK-001", {"a": 1})

            self.assertIsInstance(result, Path)

    def test_overwrites_existing_command(self) -> None:
        """Writing a command for the same task_id should overwrite."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            bus.write_command("TASK-ow", {"version": 1})
            bus.write_command("TASK-ow", {"version": 2})

            path = bus.commands_dir / "TASK-ow.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(2, data["version"])


class BusWriteReportTests(unittest.TestCase):
    """Tests for Bus.write_report."""

    def test_writes_report_file(self) -> None:
        """write_report should create a JSON file in reports dir."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            report = {"task_id": "TASK-001", "status": "done", "agent": "cc"}

            path = bus.write_report("TASK-001", report)

            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("done", data["status"])

    def test_report_file_named_by_task_id(self) -> None:
        """Report file should be named {task_id}.json."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            path = bus.write_report("TASK-rpt", {"status": "done"})

            self.assertEqual("TASK-rpt.json", path.name)

    def test_report_in_reports_dir(self) -> None:
        """Report file should be in the reports directory."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            path = bus.write_report("TASK-dir", {"status": "done"})

            self.assertEqual(bus.reports_dir, path.parent)


class BusReadReportTests(unittest.TestCase):
    """Tests for Bus.read_report."""

    def test_reads_written_report(self) -> None:
        """read_report should return the data written by write_report."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            report = {"task_id": "TASK-rd", "status": "done", "agent": "cc"}

            bus.write_report("TASK-rd", report)
            result = bus.read_report("TASK-rd")

            self.assertIsNotNone(result)
            self.assertEqual("done", result["status"])
            self.assertEqual("cc", result["agent"])

    def test_missing_report_returns_none(self) -> None:
        """read_report for non-existent task should return None."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            result = bus.read_report("TASK-nonexistent")

            self.assertIsNone(result)

    def test_read_returns_dict(self) -> None:
        """read_report should return a dict."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))
            bus.write_report("TASK-type", {"status": "done"})

            result = bus.read_report("TASK-type")

            self.assertIsInstance(result, dict)

    def test_write_then_overwrite_then_read(self) -> None:
        """read_report should return the latest version after overwrite."""
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(root=Path(tmp))

            bus.write_report("TASK-ver", {"version": 1})
            bus.write_report("TASK-ver", {"version": 2})
            result = bus.read_report("TASK-ver")

            self.assertEqual(2, result["version"])


if __name__ == "__main__":
    unittest.main()
