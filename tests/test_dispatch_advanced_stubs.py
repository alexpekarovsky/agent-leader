"""Advanced dispatch telemetry tests: timeout budgets, targeting, noop fixtures.

Covers:
- TASK-5c69a1be: Dispatch telemetry timeout budget semantics
- TASK-076943e7: Manager no-op diagnostic on execute timeout
- TASK-94a1d4c1: Dispatch command targeting (agent vs instance)
- TASK-811e9168: Noop diagnostic fixture examples
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, **trigger_overrides: int) -> Policy:
    triggers = {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300}
    triggers.update(trigger_overrides)
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": triggers,
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, **trigger_overrides: int) -> Orchestrator:
    policy = _make_policy(root / "policy.json", **trigger_overrides)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str, **overrides: str) -> dict:
    meta = {
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
    meta.update(overrides)
    return meta


def _connect_agent(orch: Orchestrator, root: Path, agent: str, **overrides: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent, **overrides), source=agent)


# ── TASK-5c69a1be: Timeout budget field semantics ────────────────────


# Timeout budget field definitions for dispatch telemetry.
# These document expected fields when dispatch commands carry deadline info.
TIMEOUT_BUDGET_FIELDS = {
    "dispatch_deadline": "ISO timestamp by which the command must be dispatched to a worker",
    "ack_deadline": "ISO timestamp by which the worker must acknowledge receipt",
    "result_deadline": "ISO timestamp by which the worker must submit results",
}

# Noop timeout reasons linked to budget fields.
NOOP_TIMEOUT_REASONS = {
    "ack_timeout": "Worker did not acknowledge within ack_deadline",
    "result_timeout": "Worker did not submit results within result_deadline",
    "no_available_worker": "No eligible worker found before dispatch_deadline",
}


class TimeoutBudgetSemanticsTests(unittest.TestCase):
    """Tests documenting timeout budget field expectations."""

    def test_budget_fields_defined(self) -> None:
        """All timeout budget fields should have descriptions."""
        for field, desc in TIMEOUT_BUDGET_FIELDS.items():
            self.assertIsInstance(field, str)
            self.assertIsInstance(desc, str)
            self.assertTrue(field.endswith("_deadline"), f"{field} should end with _deadline")

    def test_noop_reasons_map_to_budget_fields(self) -> None:
        """Each noop timeout reason should reference a relevant budget concept."""
        for reason, desc in NOOP_TIMEOUT_REASONS.items():
            combined = reason.lower() + " " + desc.lower()
            has_budget_ref = any(
                kw in combined for kw in ("timeout", "deadline", "available", "worker")
            )
            self.assertTrue(has_budget_ref, f"Reason '{reason}' lacks budget field reference")

    def test_dispatch_command_event_has_correlation_id(self) -> None:
        """dispatch.command events should include correlation_id for budget tracking."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Budget test", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            events = list(orch.bus.iter_events())
            dispatch = [e for e in events if e["type"] == "dispatch.command"]
            self.assertGreaterEqual(len(dispatch), 1)
            self.assertIn("correlation_id", dispatch[-1]["payload"])

    def test_dispatch_command_includes_task_id(self) -> None:
        """dispatch.command should reference the target task_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Task ref test", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            events = list(orch.bus.iter_events())
            dispatch = [e for e in events if e["type"] == "dispatch.command"]
            self.assertEqual(task["id"], dispatch[-1]["payload"]["task_id"])


# ── TASK-076943e7: Manager no-op diagnostic on execute timeout ───────


class ManagerNoopDiagnosticTests(unittest.TestCase):
    """Tests for manager-emitted noop diagnostics on stale overrides."""

    def test_stale_override_produces_noop(self) -> None:
        """A stale claim override should emit a dispatch.noop event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Noop test", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            # Backdate override
            overrides = orch._read_json(orch.claim_overrides_path)
            overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.claim_overrides_path, overrides)

            orch.bus.events_path.write_text("", encoding="utf-8")
            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)
            self.assertEqual(1, result["emitted_count"])

            events = list(orch.bus.iter_events())
            noops = [e for e in events if e["type"] == "dispatch.noop"]
            self.assertEqual(1, len(noops))

    def test_noop_event_contains_expected_fields(self) -> None:
        """dispatch.noop event should have correlation_id, agent, reason."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Noop fields", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            overrides = orch._read_json(orch.claim_overrides_path)
            correlation_id = overrides["claude_code"]["correlation_id"]
            overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.claim_overrides_path, overrides)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)

            events = list(orch.bus.iter_events())
            noops = [e for e in events if e["type"] == "dispatch.noop"]
            self.assertEqual(1, len(noops))
            payload = noops[0]["payload"]
            self.assertEqual("claude_code", payload["agent"])
            self.assertEqual(correlation_id, payload["correlation_id"])
            self.assertIn("reason", payload)

    def test_noop_not_emitted_for_recent_override(self) -> None:
        """Recent override should not produce a noop."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Fresh override", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=3600)
            self.assertEqual(0, result["emitted_count"])

    def test_noop_requires_leader_source(self) -> None:
        """Non-leader source should be rejected for noop emission."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            with self.assertRaises(ValueError):
                orch.emit_stale_claim_override_noops(source="claude_code", timeout_seconds=5)


# ── TASK-94a1d4c1: Command targeting (agent vs instance) ────────────


class DispatchCommandTargetingTests(unittest.TestCase):
    """Tests for dispatch command targeting: agent-family vs instance."""

    def test_claim_override_targets_agent_family(self) -> None:
        """set_claim_override targets an agent name, not specific instance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")
            task = orch.create_task(
                title="Agent target", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            events = list(orch.bus.iter_events())
            dispatch = [e for e in events if e["type"] == "dispatch.command"]
            self.assertGreaterEqual(len(dispatch), 1)
            # Target is agent name, not instance
            self.assertEqual("claude_code", dispatch[-1]["payload"]["agent"])

    def test_claim_ack_includes_instance_id(self) -> None:
        """dispatch.ack from claim should include the specific instance_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")
            task = orch.create_task(
                title="Ack instance", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            # Clear events and claim (which consumes override)
            orch.bus.events_path.write_text("", encoding="utf-8")
            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)

            events = list(orch.bus.iter_events())
            acks = [e for e in events if e["type"] == "dispatch.ack"]
            self.assertGreaterEqual(len(acks), 1)
            self.assertIn("instance_id", acks[0]["payload"])

    def test_multiple_instances_same_agent_any_can_claim(self) -> None:
        """Any instance of an agent family can consume a claim override."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code", instance_id="cc#w1")
            # Register second instance
            orch.heartbeat("claude_code", {
                **_full_metadata(root, "claude_code"),
                "instance_id": "cc#w2",
                "session_id": "sess-w2",
                "connection_id": "conn-w2",
            })

            task = orch.create_task(
                title="Multi instance", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            # Either instance can claim
            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual(task["id"], claimed["id"])

    def test_override_cannot_target_wrong_agent(self) -> None:
        """Claim override for agent A should not be consumable by agent B."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")
            task = orch.create_task(
                title="Wrong target", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            # gemini should not see claude_code's override
            overrides = orch._read_json(orch.claim_overrides_path)
            self.assertNotIn("gemini", overrides)
            self.assertIn("claude_code", overrides)


# ── TASK-811e9168: Noop diagnostic fixture examples ──────────────────


# Example noop diagnostic payloads for operator documentation.
NOOP_FIXTURE_TIMEOUT = {
    "type": "dispatch.noop",
    "correlation_id": "CMD-example01",
    "reason": "ack_timeout",
    "task_id": "TASK-example01",
    "target_agent": "claude_code",
    "elapsed_seconds": 45.2,
    "dispatch_timeout_seconds": 30,
    "source": "codex",
}

NOOP_FIXTURE_NO_ACTIVE_INSTANCE = {
    "type": "dispatch.noop",
    "correlation_id": "CMD-example02",
    "reason": "no_active_instance",
    "task_id": "TASK-example02",
    "target_agent": "gemini",
    "elapsed_seconds": 120.0,
    "source": "codex",
}

NOOP_FIXTURE_DUPLICATE_CLAIM_RISK = {
    "type": "dispatch.noop",
    "correlation_id": "CMD-example03",
    "reason": "duplicate_claim_risk",
    "task_id": "TASK-example03",
    "target_agent": "claude_code",
    "elapsed_seconds": 5.0,
    "source": "codex",
    "note": "Task already in_progress by same agent",
}

NOOP_FIXTURE_STALE_OVERRIDE = {
    "type": "dispatch.noop",
    "correlation_id": "CMD-example04",
    "reason": "stale_override",
    "task_id": "TASK-example04",
    "target_agent": "claude_code",
    "elapsed_seconds": 300.0,
    "dispatch_timeout_seconds": 60,
    "source": "codex",
}

ALL_NOOP_FIXTURES = [
    NOOP_FIXTURE_TIMEOUT,
    NOOP_FIXTURE_NO_ACTIVE_INSTANCE,
    NOOP_FIXTURE_DUPLICATE_CLAIM_RISK,
    NOOP_FIXTURE_STALE_OVERRIDE,
]


class NoopDiagnosticFixtureTests(unittest.TestCase):
    """Tests validating noop diagnostic fixture examples."""

    def test_at_least_four_fixtures_defined(self) -> None:
        """At least 4 noop fixture examples should be defined."""
        self.assertGreaterEqual(len(ALL_NOOP_FIXTURES), 4)

    def test_all_fixtures_have_correlation_id(self) -> None:
        """Each fixture should include a correlation_id."""
        for fixture in ALL_NOOP_FIXTURES:
            self.assertIn("correlation_id", fixture)
            self.assertTrue(fixture["correlation_id"].startswith("CMD-"))

    def test_all_fixtures_have_reason_code(self) -> None:
        """Each fixture should include a reason code."""
        for fixture in ALL_NOOP_FIXTURES:
            self.assertIn("reason", fixture)
            self.assertIsInstance(fixture["reason"], str)
            self.assertGreater(len(fixture["reason"]), 0)

    def test_all_fixtures_have_type_dispatch_noop(self) -> None:
        """Each fixture should have type=dispatch.noop."""
        for fixture in ALL_NOOP_FIXTURES:
            self.assertEqual("dispatch.noop", fixture["type"])

    def test_all_fixtures_have_task_and_agent(self) -> None:
        """Each fixture should reference a task_id and target_agent."""
        for fixture in ALL_NOOP_FIXTURES:
            self.assertIn("task_id", fixture)
            self.assertIn("target_agent", fixture)

    def test_all_fixtures_have_elapsed_seconds(self) -> None:
        """Each fixture should have numeric elapsed_seconds."""
        for fixture in ALL_NOOP_FIXTURES:
            self.assertIn("elapsed_seconds", fixture)
            self.assertIsInstance(fixture["elapsed_seconds"], (int, float))

    def test_reason_codes_are_unique(self) -> None:
        """Each fixture should have a distinct reason code."""
        reasons = [f["reason"] for f in ALL_NOOP_FIXTURES]
        self.assertEqual(len(reasons), len(set(reasons)))

    def test_fixtures_are_json_serializable(self) -> None:
        """All fixtures should be JSON-serializable."""
        for fixture in ALL_NOOP_FIXTURES:
            serialized = json.dumps(fixture)
            deserialized = json.loads(serialized)
            self.assertEqual(fixture["correlation_id"], deserialized["correlation_id"])

    def test_live_noop_matches_fixture_structure(self) -> None:
        """A real noop emission should have similar fields to fixtures."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Live noop", workstream="backend",
                owner="claude_code", acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            overrides = orch._read_json(orch.claim_overrides_path)
            overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.claim_overrides_path, overrides)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)

            events = list(orch.bus.iter_events())
            noops = [e for e in events if e["type"] == "dispatch.noop"]
            self.assertEqual(1, len(noops))
            live_payload = noops[0]["payload"]

            # Verify structural similarity to fixture
            self.assertIn("correlation_id", live_payload)
            self.assertIn("agent", live_payload)
            self.assertIn("reason", live_payload)


if __name__ == "__main__":
    unittest.main()
