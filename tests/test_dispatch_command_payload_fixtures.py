"""CORE-05 dispatch command payload schema fixtures.

Provides canonical dispatch command payload fixtures for two targeting modes:

1. **Agent-family target** — Dispatches to any available instance of an agent
   family (e.g. "claude_code"). The orchestrator picks the best instance.
   Fields: agent (required), instance_id (absent or None)

2. **Instance-specific target** — Dispatches to a specific instance of an
   agent (e.g. "sess-claude_code-abc"). The orchestrator must route to exactly
   that instance or noop if unavailable.
   Fields: agent (required), instance_id (required, non-empty)

Both variants share: correlation_id, command_type, task_id, timeout_seconds.

These fixtures map directly to set_claim_override (engine.py line 366) which
generates dispatch.command events with correlation_id CMD-{hex}.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Fixture Definitions
# ---------------------------------------------------------------------------

# Agent-family target: dispatches to any instance of "claude_code"
COMMAND_AGENT_TARGET = {
    "type": "dispatch.command",
    "correlation_id": "CMD-fam1234567",
    "command_type": "claim_override",
    "agent": "claude_code",
    "instance_id": None,
    "task_id": "TASK-fam-001",
    "timeout_seconds": 60,
    "source": "codex",
    "timestamp": "2026-02-26T12:00:00+00:00",
}

# Instance-specific target: dispatches to exactly "sess-claude_code-abc"
COMMAND_INSTANCE_TARGET = {
    "type": "dispatch.command",
    "correlation_id": "CMD-inst987654",
    "command_type": "claim_override",
    "agent": "claude_code",
    "instance_id": "sess-claude_code-abc",
    "task_id": "TASK-inst-002",
    "timeout_seconds": 30,
    "source": "codex",
    "timestamp": "2026-02-26T12:00:00+00:00",
}

# Additional variant: gemini agent family target
COMMAND_GEMINI_AGENT_TARGET = {
    "type": "dispatch.command",
    "correlation_id": "CMD-gem4567890",
    "command_type": "claim_override",
    "agent": "gemini",
    "instance_id": None,
    "task_id": "TASK-gem-003",
    "timeout_seconds": 60,
    "source": "codex",
    "timestamp": "2026-02-26T12:00:00+00:00",
}

# Additional variant: instance-specific gemini target
COMMAND_GEMINI_INSTANCE_TARGET = {
    "type": "dispatch.command",
    "correlation_id": "CMD-gemi123456",
    "command_type": "claim_override",
    "agent": "gemini",
    "instance_id": "gem-v2-inst",
    "task_id": "TASK-gem-004",
    "timeout_seconds": 45,
    "source": "codex",
    "timestamp": "2026-02-26T12:00:00+00:00",
}

REQUIRED_COMMAND_FIELDS = {
    "type", "correlation_id", "command_type", "agent", "task_id", "source",
}

ALL_COMMAND_FIXTURES = {
    "agent_target": COMMAND_AGENT_TARGET,
    "instance_target": COMMAND_INSTANCE_TARGET,
    "gemini_agent_target": COMMAND_GEMINI_AGENT_TARGET,
    "gemini_instance_target": COMMAND_GEMINI_INSTANCE_TARGET,
}

AGENT_TARGET_FIXTURES = {
    "agent_target": COMMAND_AGENT_TARGET,
    "gemini_agent_target": COMMAND_GEMINI_AGENT_TARGET,
}

INSTANCE_TARGET_FIXTURES = {
    "instance_target": COMMAND_INSTANCE_TARGET,
    "gemini_instance_target": COMMAND_GEMINI_INSTANCE_TARGET,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str) -> dict:
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_agent(orch: Orchestrator, root: Path, agent: str) -> None:
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))


# ---------------------------------------------------------------------------
# 1. Fixture schema completeness
# ---------------------------------------------------------------------------

class CommandFixtureSchemaTests(unittest.TestCase):
    """All command fixtures must have required fields."""

    def test_all_fixtures_have_required_fields(self) -> None:
        for name, fixture in ALL_COMMAND_FIXTURES.items():
            for field in REQUIRED_COMMAND_FIELDS:
                self.assertIn(field, fixture, f"fixture '{name}' missing '{field}'")

    def test_all_fixtures_have_type_dispatch_command(self) -> None:
        for name, fixture in ALL_COMMAND_FIXTURES.items():
            self.assertEqual(fixture["type"], "dispatch.command",
                             f"fixture '{name}' wrong type")

    def test_all_fixtures_have_command_type_claim_override(self) -> None:
        for name, fixture in ALL_COMMAND_FIXTURES.items():
            self.assertEqual(fixture["command_type"], "claim_override",
                             f"fixture '{name}' wrong command_type")

    def test_correlation_id_starts_with_cmd(self) -> None:
        for name, fixture in ALL_COMMAND_FIXTURES.items():
            self.assertTrue(fixture["correlation_id"].startswith("CMD-"),
                            f"fixture '{name}' correlation_id format")

    def test_all_fixtures_have_timeout_seconds(self) -> None:
        for name, fixture in ALL_COMMAND_FIXTURES.items():
            self.assertIn("timeout_seconds", fixture,
                          f"fixture '{name}' missing timeout_seconds")
            self.assertIsInstance(fixture["timeout_seconds"], (int, float))
            self.assertGreater(fixture["timeout_seconds"], 0)

    def test_all_fixtures_have_timestamp(self) -> None:
        from datetime import datetime
        for name, fixture in ALL_COMMAND_FIXTURES.items():
            self.assertIn("timestamp", fixture)
            try:
                datetime.fromisoformat(fixture["timestamp"])
            except ValueError:
                self.fail(f"fixture '{name}' invalid timestamp")


# ---------------------------------------------------------------------------
# 2. Agent-family target variant
# ---------------------------------------------------------------------------

class AgentTargetVariantTests(unittest.TestCase):
    """Agent-family targets have instance_id absent or None."""

    def test_agent_target_instance_id_is_none(self) -> None:
        for name, fixture in AGENT_TARGET_FIXTURES.items():
            self.assertIsNone(fixture.get("instance_id"),
                              f"agent-target fixture '{name}' should have None instance_id")

    def test_agent_target_has_agent_name(self) -> None:
        for name, fixture in AGENT_TARGET_FIXTURES.items():
            self.assertIsInstance(fixture["agent"], str)
            self.assertTrue(len(fixture["agent"]) > 0)

    def test_agent_targets_have_distinct_correlation_ids(self) -> None:
        cids = [f["correlation_id"] for f in AGENT_TARGET_FIXTURES.values()]
        self.assertEqual(len(cids), len(set(cids)))

    def test_agent_targets_have_distinct_task_ids(self) -> None:
        tids = [f["task_id"] for f in AGENT_TARGET_FIXTURES.values()]
        self.assertEqual(len(tids), len(set(tids)))


# ---------------------------------------------------------------------------
# 3. Instance-specific target variant
# ---------------------------------------------------------------------------

class InstanceTargetVariantTests(unittest.TestCase):
    """Instance-specific targets have non-empty instance_id."""

    def test_instance_target_has_nonempty_instance_id(self) -> None:
        for name, fixture in INSTANCE_TARGET_FIXTURES.items():
            self.assertIsNotNone(fixture["instance_id"],
                                 f"instance-target fixture '{name}' should have instance_id")
            self.assertTrue(len(fixture["instance_id"]) > 0)

    def test_instance_target_has_agent_name(self) -> None:
        for name, fixture in INSTANCE_TARGET_FIXTURES.items():
            self.assertIsInstance(fixture["agent"], str)
            self.assertTrue(len(fixture["agent"]) > 0)

    def test_instance_targets_have_distinct_correlation_ids(self) -> None:
        cids = [f["correlation_id"] for f in INSTANCE_TARGET_FIXTURES.values()]
        self.assertEqual(len(cids), len(set(cids)))

    def test_instance_id_differs_from_agent_name(self) -> None:
        """Instance ID should not be identical to the bare agent name."""
        for name, fixture in INSTANCE_TARGET_FIXTURES.items():
            self.assertNotEqual(fixture["instance_id"], fixture["agent"],
                                f"fixture '{name}' instance_id should differ from agent")


# ---------------------------------------------------------------------------
# 4. Variant distinction
# ---------------------------------------------------------------------------

class VariantDistinctionTests(unittest.TestCase):
    """Agent-target and instance-target variants should be distinguishable."""

    def test_can_distinguish_by_instance_id_presence(self) -> None:
        for name, fixture in AGENT_TARGET_FIXTURES.items():
            self.assertTrue(
                fixture.get("instance_id") is None,
                f"agent-target '{name}' should be None",
            )
        for name, fixture in INSTANCE_TARGET_FIXTURES.items():
            self.assertTrue(
                fixture.get("instance_id") is not None and len(fixture["instance_id"]) > 0,
                f"instance-target '{name}' should have value",
            )

    def test_all_fixtures_have_unique_correlation_ids(self) -> None:
        cids = [f["correlation_id"] for f in ALL_COMMAND_FIXTURES.values()]
        self.assertEqual(len(cids), len(set(cids)))

    def test_all_fixtures_have_unique_task_ids(self) -> None:
        tids = [f["task_id"] for f in ALL_COMMAND_FIXTURES.values()]
        self.assertEqual(len(tids), len(set(tids)))

    def test_source_is_always_manager(self) -> None:
        for name, fixture in ALL_COMMAND_FIXTURES.items():
            self.assertEqual(fixture["source"], "codex",
                             f"fixture '{name}' source should be manager")


# ---------------------------------------------------------------------------
# 5. Live command event matches fixture schema
# ---------------------------------------------------------------------------

class LiveCommandEventSchemaTests(unittest.TestCase):
    """Live dispatch.command events from set_claim_override match fixture schema."""

    def test_live_command_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Live schema test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            events = list(orch.bus.iter_events())
            cmd = next(e for e in events if e.get("type") == "dispatch.command")
            for field in ("correlation_id", "command_type", "agent", "task_id"):
                self.assertIn(field, cmd["payload"], f"live event missing payload.{field}")

    def test_live_command_correlation_id_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Live corr format",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.bus.events_path.write_text("", encoding="utf-8")

            result = orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            self.assertTrue(result["correlation_id"].startswith("CMD-"))

    def test_live_command_task_id_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Live task match",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            events = list(orch.bus.iter_events())
            cmd = next(e for e in events if e.get("type") == "dispatch.command")
            self.assertEqual(cmd["payload"]["task_id"], task["id"])

    def test_live_command_source_is_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Live source check",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            events = list(orch.bus.iter_events())
            cmd = next(e for e in events if e.get("type") == "dispatch.command")
            self.assertEqual(cmd["source"], "codex")


if __name__ == "__main__":
    unittest.main()
