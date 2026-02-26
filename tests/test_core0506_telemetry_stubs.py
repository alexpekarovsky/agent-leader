"""CORE-05/06 dispatch telemetry and noop diagnostic stubs.

Covers:
- TASK-d57b84aa: Telemetry correlation fixture pack (command->ack->result/noop)
- TASK-b00aa039: Dispatch targeting semantics matrix (6+ scenarios)
- TASK-ce6fa5ef: Blocker escalation threshold examples
- TASK-e0f2ca4c: Timeout no-op diagnostic payload examples
- TASK-667e48c3: CORE milestone completion gate checklist
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
        "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
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


def _connect(orch: Orchestrator, root: Path, agent: str, **overrides: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent, **overrides), source=agent)


# ── TASK-d57b84aa: Telemetry correlation fixture pack ────────────────


# Fixture: consistent correlation across dispatch lifecycle events.
CORRELATION_FIXTURE_COMMAND = {
    "type": "dispatch.command",
    "correlation_id": "CMD-fixture01",
    "command_type": "claim_override",
    "agent": "claude_code",
    "task_id": "TASK-fixture01",
    "source": "codex",
}

CORRELATION_FIXTURE_ACK = {
    "type": "dispatch.ack",
    "correlation_id": "CMD-fixture01",
    "agent": "claude_code",
    "instance_id": "cc#worker-01",
    "task_id": "TASK-fixture01",
    "ack_type": "claim_override_consumed",
}

CORRELATION_FIXTURE_NOOP = {
    "type": "dispatch.noop",
    "correlation_id": "CMD-fixture01",
    "reason": "ack_timeout",
    "agent": "claude_code",
    "task_id": "TASK-fixture01",
    "elapsed_seconds": 45.0,
}

ALL_CORRELATION_FIXTURES = [
    CORRELATION_FIXTURE_COMMAND,
    CORRELATION_FIXTURE_ACK,
    CORRELATION_FIXTURE_NOOP,
]


class TelemetryCorrelationFixtureTests(unittest.TestCase):
    """Tests for correlation consistency across dispatch lifecycle."""

    def test_all_fixtures_share_correlation_id(self) -> None:
        """All lifecycle events should share the same correlation_id."""
        ids = {f["correlation_id"] for f in ALL_CORRELATION_FIXTURES}
        self.assertEqual(1, len(ids))

    def test_command_has_command_type(self) -> None:
        self.assertIn("command_type", CORRELATION_FIXTURE_COMMAND)

    def test_ack_has_instance_id(self) -> None:
        self.assertIn("instance_id", CORRELATION_FIXTURE_ACK)

    def test_noop_has_reason_and_elapsed(self) -> None:
        self.assertIn("reason", CORRELATION_FIXTURE_NOOP)
        self.assertIn("elapsed_seconds", CORRELATION_FIXTURE_NOOP)

    def test_live_correlation_chain(self) -> None:
        """Live: command -> ack should share correlation_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Corr test", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            events_before = list(orch.bus.iter_events())
            commands = [e for e in events_before if e["type"] == "dispatch.command"]
            cmd_corr = commands[-1]["payload"]["correlation_id"]

            orch.claim_next_task("claude_code")
            events_after = list(orch.bus.iter_events())
            acks = [e for e in events_after if e["type"] == "dispatch.ack"]
            self.assertGreaterEqual(len(acks), 1)
            self.assertEqual(cmd_corr, acks[-1]["payload"]["correlation_id"])

    def test_fixtures_json_serializable(self) -> None:
        for f in ALL_CORRELATION_FIXTURES:
            self.assertIsInstance(json.loads(json.dumps(f)), dict)


# ── TASK-b00aa039: Dispatch targeting semantics matrix ───────────────


# Matrix: at least 6 targeting scenarios with expected outcomes.
TARGETING_MATRIX = [
    {
        "scenario": "agent_family_single_instance",
        "target": "claude_code",
        "target_type": "agent_family",
        "instances_available": 1,
        "expected_outcome": "claim_consumed",
    },
    {
        "scenario": "agent_family_multi_instance",
        "target": "claude_code",
        "target_type": "agent_family",
        "instances_available": 3,
        "expected_outcome": "any_instance_claims",
    },
    {
        "scenario": "agent_family_no_instance",
        "target": "claude_code",
        "target_type": "agent_family",
        "instances_available": 0,
        "expected_outcome": "noop_no_available_worker",
    },
    {
        "scenario": "agent_family_all_stale",
        "target": "claude_code",
        "target_type": "agent_family",
        "instances_available": 0,
        "expected_outcome": "noop_stale_override",
    },
    {
        "scenario": "wrong_agent_family",
        "target": "gemini",
        "target_type": "agent_family",
        "instances_available": 1,
        "expected_outcome": "override_not_visible",
    },
    {
        "scenario": "manager_self_target",
        "target": "codex",
        "target_type": "agent_family",
        "instances_available": 1,
        "expected_outcome": "rejected_manager_target",
    },
]


class DispatchTargetingMatrixTests(unittest.TestCase):
    """Tests validating the dispatch targeting semantics matrix."""

    def test_matrix_has_at_least_6_scenarios(self) -> None:
        self.assertGreaterEqual(len(TARGETING_MATRIX), 6)

    def test_all_scenarios_have_required_fields(self) -> None:
        for scenario in TARGETING_MATRIX:
            for field in ("scenario", "target", "target_type", "expected_outcome"):
                self.assertIn(field, scenario, f"Missing {field} in {scenario['scenario']}")

    def test_single_instance_claim_consumed(self) -> None:
        """Agent with single instance should consume override."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Single", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)

    def test_multi_instance_any_claims(self) -> None:
        """Agent with multiple instances: any instance can claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code", instance_id="cc#w1")
            orch.heartbeat("claude_code", {
                **_full_metadata(root, "claude_code"),
                "instance_id": "cc#w2",
                "session_id": "sess-w2",
                "connection_id": "conn-w2",
            })
            task = orch.create_task("Multi", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")
            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)

    def test_wrong_agent_cannot_see_override(self) -> None:
        """Override for claude_code is not visible to gemini."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            _connect(orch, root, "gemini")
            task = orch.create_task("Wrong agent", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            overrides = orch._read_json(orch.claim_overrides_path)
            self.assertNotIn("gemini", overrides)

    def test_stale_override_produces_noop(self) -> None:
        """Stale override should produce noop diagnostic."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Stale", "backend", ["done"], owner="claude_code")
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            overrides = orch._read_json(orch.claim_overrides_path)
            overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.claim_overrides_path, overrides)

            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)
            self.assertEqual(1, result["emitted_count"])

    def test_matrix_json_serializable(self) -> None:
        serialized = json.dumps(TARGETING_MATRIX)
        self.assertIsInstance(json.loads(serialized), list)


# ── TASK-ce6fa5ef: Blocker escalation threshold examples ─────────────


# Examples: when noop diagnostics stay informational vs escalate to blocker.
ESCALATION_THRESHOLDS = [
    {
        "noop_count": 1,
        "action": "informational",
        "note": "First no-op: log diagnostic, no blocker",
    },
    {
        "noop_count": 3,
        "action": "informational",
        "note": "Third no-op: still informational, increase monitoring",
    },
    {
        "noop_count": 5,
        "action": "escalate_to_blocker",
        "note": "Fifth repeated no-op: create blocker for manager attention",
    },
    {
        "noop_count": 10,
        "action": "escalate_to_blocker",
        "note": "Tenth no-op: high severity blocker, possible system issue",
        "severity": "high",
    },
]


class BlockerEscalationThresholdTests(unittest.TestCase):
    """Tests documenting informational vs blocker escalation thresholds."""

    def test_threshold_examples_defined(self) -> None:
        self.assertGreaterEqual(len(ESCALATION_THRESHOLDS), 3)

    def test_informational_before_escalation(self) -> None:
        """Low noop counts should be informational."""
        low_counts = [t for t in ESCALATION_THRESHOLDS if t["noop_count"] <= 3]
        for t in low_counts:
            self.assertEqual("informational", t["action"])

    def test_escalation_after_threshold(self) -> None:
        """High noop counts should escalate to blocker."""
        high_counts = [t for t in ESCALATION_THRESHOLDS if t["noop_count"] >= 5]
        for t in high_counts:
            self.assertEqual("escalate_to_blocker", t["action"])

    def test_all_entries_have_required_fields(self) -> None:
        for entry in ESCALATION_THRESHOLDS:
            self.assertIn("noop_count", entry)
            self.assertIn("action", entry)
            self.assertIn("note", entry)

    def test_thresholds_json_serializable(self) -> None:
        serialized = json.dumps(ESCALATION_THRESHOLDS)
        self.assertIsInstance(json.loads(serialized), list)


# ── TASK-e0f2ca4c: Timeout no-op payload examples ───────────────────


TIMEOUT_NOOP_EXAMPLES = [
    {
        "type": "dispatch.noop",
        "correlation_id": "CMD-op001",
        "reason": "ack_timeout",
        "task_id": "TASK-op001",
        "target_agent": "claude_code",
        "elapsed_seconds": 62.5,
        "dispatch_timeout_seconds": 60,
        "source": "codex",
        "timestamp": "2025-01-15T10:30:00+00:00",
    },
    {
        "type": "dispatch.noop",
        "correlation_id": "CMD-op002",
        "reason": "result_timeout",
        "task_id": "TASK-op002",
        "target_agent": "gemini",
        "elapsed_seconds": 305.0,
        "dispatch_timeout_seconds": 300,
        "source": "codex",
        "timestamp": "2025-01-15T11:00:00+00:00",
    },
    {
        "type": "dispatch.noop",
        "correlation_id": "CMD-op003",
        "reason": "no_available_worker",
        "task_id": "TASK-op003",
        "target_agent": "claude_code",
        "elapsed_seconds": 180.0,
        "source": "codex",
        "timestamp": "2025-01-15T12:00:00+00:00",
    },
]


class TimeoutNoopPayloadExampleTests(unittest.TestCase):
    """Tests for operator-facing timeout noop diagnostic payload examples."""

    def test_examples_defined(self) -> None:
        self.assertGreaterEqual(len(TIMEOUT_NOOP_EXAMPLES), 3)

    def test_all_have_required_fields(self) -> None:
        for ex in TIMEOUT_NOOP_EXAMPLES:
            for field in ("type", "correlation_id", "reason", "task_id", "target_agent", "elapsed_seconds"):
                self.assertIn(field, ex, f"Missing: {field}")

    def test_all_type_dispatch_noop(self) -> None:
        for ex in TIMEOUT_NOOP_EXAMPLES:
            self.assertEqual("dispatch.noop", ex["type"])

    def test_correlation_ids_unique(self) -> None:
        ids = [ex["correlation_id"] for ex in TIMEOUT_NOOP_EXAMPLES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_elapsed_seconds_numeric(self) -> None:
        for ex in TIMEOUT_NOOP_EXAMPLES:
            self.assertIsInstance(ex["elapsed_seconds"], (int, float))

    def test_examples_json_serializable(self) -> None:
        for ex in TIMEOUT_NOOP_EXAMPLES:
            serialized = json.dumps(ex)
            self.assertIsInstance(json.loads(serialized), dict)


# ── TASK-667e48c3: CORE milestone completion gate checklist ──────────


CORE_COMPLETION_GATES = {
    "CORE-02": {
        "title": "Instance-aware status payload",
        "code_gates": [
            "agent_instances field in status response",
            "active_agent_identities field in status response",
            "instance_id derivation logic",
        ],
        "test_gates": [
            "Schema validation tests",
            "Null handling tests",
            "Forward compatibility tests",
            "Mixed active/offline tests",
            "Post-restart visibility tests",
        ],
        "doc_gates": ["Instance row field documentation"],
    },
    "CORE-03": {
        "title": "Lease issuance on task claim",
        "code_gates": [
            "_issue_task_lease_unlocked implementation",
            "Lease fields in task state",
            "renew_task_lease method",
        ],
        "test_gates": [
            "Lease issuance schema tests",
            "Override path invariant tests",
            "Renewal reason code tests",
            "Response compatibility tests",
        ],
        "doc_gates": ["Lease field schema documentation"],
    },
    "CORE-04": {
        "title": "Expired lease recovery",
        "code_gates": [
            "recover_expired_task_leases implementation",
            "Requeue vs block decision logic",
            "Blocker creation for no-eligible-worker",
        ],
        "test_gates": [
            "No eligible worker recovery tests",
            "Same-family replacement tests",
            "Event correlation tests",
            "Lease clearing verification",
        ],
        "doc_gates": ["Recovery scenario documentation"],
    },
    "CORE-05": {
        "title": "Dispatch telemetry correlation",
        "code_gates": [
            "dispatch.command event emission",
            "dispatch.ack event on claim",
            "Correlation ID propagation",
        ],
        "test_gates": [
            "Correlation fixture pack",
            "Targeting semantics matrix",
            "Event ordering tests",
        ],
        "doc_gates": ["Telemetry payload schema"],
    },
    "CORE-06": {
        "title": "Manager no-op diagnostics",
        "code_gates": [
            "emit_stale_claim_override_noops implementation",
            "dispatch.noop event emission",
            "Timeout detection logic",
        ],
        "test_gates": [
            "Noop emission tests",
            "Blocker escalation threshold stubs",
            "Operator payload examples",
        ],
        "doc_gates": ["Noop reason code taxonomy"],
    },
}


class CoreCompletionGateChecklistTests(unittest.TestCase):
    """Tests for CORE milestone completion gate coverage."""

    def test_all_core_tasks_have_gates(self) -> None:
        """CORE-02 through CORE-06 should all have gate definitions."""
        for core_id in ("CORE-02", "CORE-03", "CORE-04", "CORE-05", "CORE-06"):
            self.assertIn(core_id, CORE_COMPLETION_GATES, f"Missing: {core_id}")

    def test_each_gate_has_code_test_doc(self) -> None:
        """Each CORE gate should have code, test, and doc gates."""
        for core_id, gates in CORE_COMPLETION_GATES.items():
            self.assertIn("code_gates", gates, f"{core_id} missing code_gates")
            self.assertIn("test_gates", gates, f"{core_id} missing test_gates")
            self.assertIn("doc_gates", gates, f"{core_id} missing doc_gates")

    def test_each_gate_has_title(self) -> None:
        for core_id, gates in CORE_COMPLETION_GATES.items():
            self.assertIn("title", gates, f"{core_id} missing title")

    def test_code_gates_non_empty(self) -> None:
        for core_id, gates in CORE_COMPLETION_GATES.items():
            self.assertGreater(len(gates["code_gates"]), 0, f"{core_id} empty code_gates")

    def test_test_gates_non_empty(self) -> None:
        for core_id, gates in CORE_COMPLETION_GATES.items():
            self.assertGreater(len(gates["test_gates"]), 0, f"{core_id} empty test_gates")

    def test_checklist_json_serializable(self) -> None:
        serialized = json.dumps(CORE_COMPLETION_GATES)
        self.assertIsInstance(json.loads(serialized), dict)


if __name__ == "__main__":
    unittest.main()
