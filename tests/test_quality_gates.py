"""Tests for quality gate framework: gate implementations, runner, and policy enforcement.

Validates gate outcomes for test_completeness, arch_check, and anti_pattern gates
under fail/warn policies. Covers the full run_quality_gates runner with various
policy configurations and edge cases.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.quality_gates import (
    GATE_REGISTRY,
    GateResult,
    QualityGateOutcome,
    run_quality_gates,
    _gate_test_completeness,
    _gate_arch_check,
    _gate_anti_pattern,
)
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _good_report(**overrides):
    """Return a report that should pass all gates."""
    base = {
        "task_id": "TASK-test",
        "agent": "test-agent",
        "commit_sha": "abc123def456",
        "status": "done",
        "test_summary": {"command": "pytest tests/", "passed": 5, "failed": 0},
        "artifacts": ["orchestrator/quality_gates.py"],
        "notes": "Implemented quality gate framework with full test coverage.",
    }
    base.update(overrides)
    return base


def _task():
    return {"id": "TASK-test", "title": "Test task", "workstream": "qa"}


def _balanced_gates():
    """Balanced policy: test_completeness=fail, arch_check=warn, anti_pattern=fail."""
    return {
        "enabled": True,
        "gates": {
            "test_completeness": {"policy": "fail", "min_passed": 1},
            "arch_check": {"policy": "warn", "forbidden_patterns": []},
            "anti_pattern": {"policy": "fail"},
        },
    }


def _strict_gates():
    """Strict-qa policy: all gates set to fail."""
    return {
        "enabled": True,
        "gates": {
            "test_completeness": {"policy": "fail", "min_passed": 1},
            "arch_check": {"policy": "fail", "forbidden_patterns": []},
            "anti_pattern": {"policy": "fail"},
        },
    }


def _prototype_gates():
    """Prototype-fast policy: gates disabled."""
    return {
        "enabled": False,
        "gates": {
            "test_completeness": {"policy": "warn", "min_passed": 1},
            "arch_check": {"policy": "warn", "forbidden_patterns": []},
            "anti_pattern": {"policy": "warn"},
        },
    }


# ===========================================================================
# Unit tests: individual gate implementations
# ===========================================================================


class TestGateTestCompleteness(unittest.TestCase):
    """Tests for the test_completeness gate."""

    def test_passes_with_tests_run(self):
        report = _good_report()
        result = _gate_test_completeness(report, _task(), {"policy": "fail", "min_passed": 1})
        self.assertTrue(result.passed)
        self.assertEqual(result.gate, "test_completeness")
        self.assertEqual(result.policy, "fail")
        self.assertEqual(result.message, "ok")

    def test_fails_when_no_command(self):
        report = _good_report(test_summary={"command": "", "passed": 5, "failed": 0})
        result = _gate_test_completeness(report, _task(), {"policy": "fail", "min_passed": 1})
        self.assertFalse(result.passed)
        self.assertIn("No test command", result.message)

    def test_fails_when_command_missing(self):
        report = _good_report(test_summary={"passed": 5, "failed": 0})
        result = _gate_test_completeness(report, _task(), {"policy": "fail", "min_passed": 1})
        self.assertFalse(result.passed)
        self.assertIn("No test command", result.message)

    def test_fails_when_too_few_passed(self):
        report = _good_report(test_summary={"command": "pytest", "passed": 0, "failed": 0})
        result = _gate_test_completeness(report, _task(), {"policy": "fail", "min_passed": 1})
        self.assertFalse(result.passed)
        self.assertIn("0 tests passed", result.message)

    def test_respects_min_passed_threshold(self):
        report = _good_report(test_summary={"command": "pytest", "passed": 2, "failed": 0})
        result = _gate_test_completeness(report, _task(), {"policy": "fail", "min_passed": 3})
        self.assertFalse(result.passed)
        self.assertIn("2 tests passed", result.message)
        self.assertIn("minimum: 3", result.message)

    def test_warn_policy_preserved(self):
        report = _good_report(test_summary={"command": "", "passed": 0, "failed": 0})
        result = _gate_test_completeness(report, _task(), {"policy": "warn", "min_passed": 1})
        self.assertFalse(result.passed)
        self.assertEqual(result.policy, "warn")

    def test_missing_test_summary(self):
        report = _good_report()
        report.pop("test_summary")
        result = _gate_test_completeness(report, _task(), {"policy": "fail", "min_passed": 1})
        self.assertFalse(result.passed)

    def test_none_test_summary(self):
        report = _good_report(test_summary=None)
        result = _gate_test_completeness(report, _task(), {"policy": "fail", "min_passed": 1})
        self.assertFalse(result.passed)


class TestGateArchCheck(unittest.TestCase):
    """Tests for the arch_check gate."""

    def test_passes_with_no_forbidden_patterns(self):
        report = _good_report()
        result = _gate_arch_check(report, _task(), {"policy": "warn", "forbidden_patterns": []})
        self.assertTrue(result.passed)
        self.assertEqual(result.message, "ok")

    def test_fails_when_forbidden_pattern_in_artifacts(self):
        report = _good_report(artifacts=["src/god_object.py"])
        result = _gate_arch_check(
            report, _task(), {"policy": "fail", "forbidden_patterns": ["god_object"]}
        )
        self.assertFalse(result.passed)
        self.assertIn("god_object", result.message)

    def test_fails_when_forbidden_pattern_in_notes(self):
        report = _good_report(notes="Refactored the singleton module for efficiency")
        result = _gate_arch_check(
            report, _task(), {"policy": "warn", "forbidden_patterns": ["singleton"]}
        )
        self.assertFalse(result.passed)
        self.assertIn("singleton", result.message)

    def test_case_insensitive_match(self):
        report = _good_report(notes="Added GlobalState handler")
        result = _gate_arch_check(
            report, _task(), {"policy": "fail", "forbidden_patterns": ["globalstate"]}
        )
        self.assertFalse(result.passed)

    def test_multiple_forbidden_patterns(self):
        report = _good_report(artifacts=["god_object.py"], notes="uses singleton pattern")
        result = _gate_arch_check(
            report, _task(), {"policy": "fail", "forbidden_patterns": ["god_object", "singleton", "circular_dep"]}
        )
        self.assertFalse(result.passed)
        self.assertIn("god_object", result.message)
        self.assertIn("singleton", result.message)
        # circular_dep should NOT be in the message since it's not present
        self.assertNotIn("circular_dep", result.message)

    def test_handles_non_list_forbidden_patterns(self):
        report = _good_report()
        result = _gate_arch_check(report, _task(), {"policy": "warn", "forbidden_patterns": "not_a_list"})
        self.assertTrue(result.passed)

    def test_handles_non_list_artifacts(self):
        report = _good_report(artifacts="not_a_list")
        result = _gate_arch_check(
            report, _task(), {"policy": "warn", "forbidden_patterns": ["something"]}
        )
        # Should not crash — artifacts coerced to empty list
        self.assertIsInstance(result, GateResult)


class TestGateAntiPattern(unittest.TestCase):
    """Tests for the anti_pattern gate."""

    def test_passes_with_good_report(self):
        report = _good_report()
        result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
        self.assertTrue(result.passed)
        self.assertEqual(result.message, "ok")

    def test_fails_on_placeholder_commit_sha(self):
        for sha in ("", "none", "n/a", "placeholder", "unknown"):
            with self.subTest(sha=sha):
                report = _good_report(commit_sha=sha)
                result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
                self.assertFalse(result.passed)
                self.assertIn("commit_sha", result.message)

    def test_fails_on_suspicious_test_command(self):
        for cmd in ("", "none", "n/a", "echo ok", "true"):
            with self.subTest(cmd=cmd):
                report = _good_report(test_summary={"command": cmd, "passed": 5, "failed": 0})
                result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
                self.assertFalse(result.passed)
                self.assertIn("suspicious test command", result.message)

    def test_fails_on_short_notes(self):
        report = _good_report(notes="ok")
        result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
        self.assertFalse(result.passed)
        self.assertIn("too short", result.message)

    def test_empty_notes_not_flagged(self):
        """Empty notes are allowed (different from very short notes)."""
        report = _good_report(notes="")
        result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
        # Empty notes (len=0) should NOT trigger the "too short" check
        # Only notes between 1-4 chars are flagged
        self.assertTrue(result.passed or "too short" not in result.message)

    def test_fails_on_done_with_failed_tests(self):
        report = _good_report(
            status="done",
            test_summary={"command": "pytest", "passed": 5, "failed": 3},
        )
        result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
        self.assertFalse(result.passed)
        self.assertIn("3 tests failed", result.message)

    def test_needs_review_status_with_failures_not_flagged(self):
        """status=needs_review with failed tests should NOT trigger the done+failed anti-pattern."""
        report = _good_report(
            status="needs_review",
            test_summary={"command": "pytest", "passed": 5, "failed": 2},
        )
        result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
        # The done+failed check only triggers when status=="done"
        self.assertNotIn("tests failed", result.message if not result.passed else "ok")

    def test_multiple_anti_patterns_combined(self):
        report = _good_report(
            commit_sha="placeholder",
            test_summary={"command": "echo ok", "passed": 5, "failed": 0},
            notes="hi",
        )
        result = _gate_anti_pattern(report, _task(), {"policy": "fail"})
        self.assertFalse(result.passed)
        # Should catch all three issues
        self.assertIn("commit_sha", result.message)
        self.assertIn("suspicious test command", result.message)
        self.assertIn("too short", result.message)

    def test_warn_policy_preserved(self):
        report = _good_report(commit_sha="placeholder")
        result = _gate_anti_pattern(report, _task(), {"policy": "warn"})
        self.assertFalse(result.passed)
        self.assertEqual(result.policy, "warn")


# ===========================================================================
# Integration tests: run_quality_gates runner
# ===========================================================================


class TestRunQualityGatesRunner(unittest.TestCase):
    """Tests for the run_quality_gates orchestration function."""

    def test_all_pass_balanced(self):
        outcome = run_quality_gates(_good_report(), _task(), _balanced_gates())
        self.assertTrue(outcome.all_passed)
        self.assertEqual(len(outcome.blocking), 0)
        self.assertEqual(len(outcome.warnings), 0)
        self.assertEqual(outcome.summary(), "all gates passed")

    def test_all_pass_strict(self):
        outcome = run_quality_gates(_good_report(), _task(), _strict_gates())
        self.assertTrue(outcome.all_passed)
        self.assertEqual(len(outcome.results), 3)

    def test_disabled_gates_always_pass(self):
        outcome = run_quality_gates(_good_report(commit_sha="placeholder"), _task(), _prototype_gates())
        self.assertTrue(outcome.all_passed)
        self.assertEqual(len(outcome.results), 0)

    def test_fail_policy_blocks(self):
        """A failing gate with policy=fail should block the outcome."""
        report = _good_report(commit_sha="placeholder")
        outcome = run_quality_gates(report, _task(), _balanced_gates())
        self.assertFalse(outcome.all_passed)
        self.assertTrue(len(outcome.blocking) > 0)
        blocked_gates = [r.gate for r in outcome.blocking]
        self.assertIn("anti_pattern", blocked_gates)

    def test_warn_policy_does_not_block(self):
        """A failing gate with policy=warn should NOT block the outcome."""
        gates = _balanced_gates()
        gates["gates"]["arch_check"]["forbidden_patterns"] = ["quality_gates"]
        report = _good_report()  # artifacts contain "quality_gates.py"
        outcome = run_quality_gates(report, _task(), gates)
        self.assertTrue(outcome.all_passed)
        self.assertEqual(len(outcome.warnings), 1)
        self.assertEqual(outcome.warnings[0].gate, "arch_check")

    def test_strict_arch_check_blocks(self):
        """In strict-qa, arch_check=fail should block."""
        gates = _strict_gates()
        gates["gates"]["arch_check"]["forbidden_patterns"] = ["quality_gates"]
        report = _good_report()
        outcome = run_quality_gates(report, _task(), gates)
        self.assertFalse(outcome.all_passed)
        blocked_gates = [r.gate for r in outcome.blocking]
        self.assertIn("arch_check", blocked_gates)

    def test_multiple_gates_fail(self):
        """Multiple gates can fail simultaneously."""
        report = _good_report(
            commit_sha="placeholder",
            test_summary={"command": "", "passed": 0, "failed": 0},
        )
        outcome = run_quality_gates(report, _task(), _strict_gates())
        self.assertFalse(outcome.all_passed)
        # test_completeness (no command) + anti_pattern (placeholder sha + suspicious command)
        self.assertTrue(len(outcome.blocking) >= 2)

    def test_summary_format_blocking(self):
        report = _good_report(commit_sha="placeholder")
        outcome = run_quality_gates(report, _task(), _balanced_gates())
        summary = outcome.summary()
        self.assertIn("BLOCKED", summary)
        self.assertIn("anti_pattern", summary)

    def test_summary_format_warnings(self):
        gates = _balanced_gates()
        gates["gates"]["arch_check"]["forbidden_patterns"] = ["quality_gates"]
        outcome = run_quality_gates(_good_report(), _task(), gates)
        summary = outcome.summary()
        self.assertIn("WARN", summary)
        self.assertIn("arch_check", summary)

    def test_empty_config(self):
        outcome = run_quality_gates(_good_report(), _task(), {})
        self.assertTrue(outcome.all_passed)

    def test_non_dict_config(self):
        outcome = run_quality_gates(_good_report(), _task(), "invalid")
        self.assertTrue(outcome.all_passed)

    def test_unknown_gate_skipped(self):
        gates = {
            "enabled": True,
            "gates": {
                "unknown_gate_xyz": {"policy": "fail"},
                "test_completeness": {"policy": "fail", "min_passed": 1},
            },
        }
        outcome = run_quality_gates(_good_report(), _task(), gates)
        # unknown gate should be silently skipped; test_completeness should run
        gate_names = [r.gate for r in outcome.results]
        self.assertNotIn("unknown_gate_xyz", gate_names)
        self.assertIn("test_completeness", gate_names)

    def test_non_dict_gate_config_skipped(self):
        gates = {
            "enabled": True,
            "gates": {
                "test_completeness": "invalid",
                "anti_pattern": {"policy": "fail"},
            },
        }
        outcome = run_quality_gates(_good_report(), _task(), gates)
        gate_names = [r.gate for r in outcome.results]
        self.assertNotIn("test_completeness", gate_names)
        self.assertIn("anti_pattern", gate_names)


# ===========================================================================
# Integration test: quality gates in engine validation loop
# ===========================================================================


def _make_policy_with_gates(path: Path, gates_config: dict) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "quality_gates": gates_config,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _setup_orch_with_task(root: Path, gates_config: dict):
    """Create an orchestrator with a task ready for quality gate validation."""
    policy = _make_policy_with_gates(root / "policy.json", gates_config)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()

    owner = "claude_code"
    orch.register_agent(owner, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": "test-session",
        "connection_id": "test-connection",
        "server_version": "0.1.0",
        "verification_source": "test",
    })

    task = orch.create_task(
        title="Test quality gate validation",
        workstream="backend",
        acceptance_criteria=["tests pass"],
        owner=owner,
    )
    orch.claim_next_task(owner)
    return orch, task["id"], owner


class TestQualityGatesInEngine(unittest.TestCase):
    """Tests that quality gates integrate correctly in the engine validation flow."""

    def test_run_quality_gates_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy_with_gates(root / "policy.json", _balanced_gates())
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            task = {"id": "TASK-test", "title": "t"}
            report = _good_report()
            outcome = orch.run_quality_gates(task, report)
            self.assertTrue(outcome.all_passed)

    def test_validate_with_quality_gate_outcome_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch, task_id, owner = _setup_orch_with_task(root, _balanced_gates())

            report = {
                "task_id": task_id,
                "agent": owner,
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
                "artifacts": ["test.py"],
                "notes": "All tests passing",
            }
            orch.ingest_report(report)

            # Run gates and validate
            task = next(t for t in orch.list_tasks() if t["id"] == task_id)
            stored_report = orch.bus.read_report(task_id) or {}
            outcome = orch.run_quality_gates(task, stored_report)
            self.assertTrue(outcome.all_passed)

            result = orch.validate_task(
                task_id=task_id,
                passed=True,
                notes="Validated with quality gates",
                source="codex",
                quality_gate_outcome=outcome,
            )

            # Check quality_gate snapshot was stored
            self.assertIn("quality_gate", result)
            self.assertTrue(result["quality_gate"]["all_passed"])

    def test_validate_with_quality_gate_outcome_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch, task_id, owner = _setup_orch_with_task(root, _balanced_gates())

            report = {
                "task_id": task_id,
                "agent": owner,
                "commit_sha": "placeholder",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
                "artifacts": [],
                "notes": "Placeholder report",
            }
            orch.ingest_report(report)

            task = next(t for t in orch.list_tasks() if t["id"] == task_id)
            stored_report = orch.bus.read_report(task_id) or {}
            outcome = orch.run_quality_gates(task, stored_report)
            self.assertFalse(outcome.all_passed)

            result = orch.validate_task(
                task_id=task_id,
                passed=False,
                notes=f"Quality gate blocked: {outcome.summary()}",
                source="codex",
                quality_gate_outcome=outcome,
            )

            self.assertIn("quality_gate", result)
            self.assertFalse(result["quality_gate"]["all_passed"])
            self.assertIn("BLOCKED", result["quality_gate"]["summary"])

    def test_validate_without_quality_gate_outcome(self):
        """Validation without quality gates should still work (quality_gate=None)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch, task_id, owner = _setup_orch_with_task(root, _balanced_gates())

            report = {
                "task_id": task_id,
                "agent": owner,
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
                "artifacts": ["test.py"],
                "notes": "All tests passing",
            }
            orch.ingest_report(report)

            result = orch.validate_task(
                task_id=task_id,
                passed=True,
                notes="Validated without gates",
                source="codex",
            )

            # quality_gate should be None in the snapshot
            task = next(t for t in orch.list_tasks() if t["id"] == task_id)
            self.assertIsNone(task["validation_gate"].get("quality_gate"))


class TestGateRegistry(unittest.TestCase):
    """Tests for the gate registry."""

    def test_registry_contains_all_gates(self):
        self.assertIn("test_completeness", GATE_REGISTRY)
        self.assertIn("arch_check", GATE_REGISTRY)
        self.assertIn("anti_pattern", GATE_REGISTRY)

    def test_registry_functions_callable(self):
        for name, fn in GATE_REGISTRY.items():
            self.assertTrue(callable(fn), f"Gate {name} is not callable")


class TestQualityGateOutcome(unittest.TestCase):
    """Tests for QualityGateOutcome dataclass."""

    def test_summary_all_passed(self):
        outcome = QualityGateOutcome(all_passed=True)
        self.assertEqual(outcome.summary(), "all gates passed")

    def test_summary_with_blocking(self):
        outcome = QualityGateOutcome(
            all_passed=False,
            blocking=[GateResult("test_completeness", False, "fail", "no tests")],
        )
        self.assertIn("BLOCKED[test_completeness]", outcome.summary())

    def test_summary_with_warnings(self):
        outcome = QualityGateOutcome(
            all_passed=True,
            warnings=[GateResult("arch_check", False, "warn", "found singleton")],
        )
        self.assertIn("WARN[arch_check]", outcome.summary())

    def test_summary_mixed(self):
        outcome = QualityGateOutcome(
            all_passed=False,
            blocking=[GateResult("anti_pattern", False, "fail", "placeholder sha")],
            warnings=[GateResult("arch_check", False, "warn", "found singleton")],
        )
        summary = outcome.summary()
        self.assertIn("BLOCKED", summary)
        self.assertIn("WARN", summary)


if __name__ == "__main__":
    unittest.main()
