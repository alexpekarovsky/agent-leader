"""Tests for iterative self-review loop scaffold.

Covers config parsing, round transitions, early-exit logic, max-round
enforcement, outcome serialisation, and engine integration.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.self_review import (
    SelfReviewConfig,
    SelfReviewLoop,
    SelfReviewOutcome,
    SelfReviewRound,
    create_self_review_loop,
)
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestSelfReviewConfig(unittest.TestCase):
    """Tests for SelfReviewConfig construction and defaults."""

    def test_defaults(self):
        cfg = SelfReviewConfig()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.max_rounds, 2)
        self.assertEqual(cfg.min_rounds, 1)

    def test_from_policy_enabled(self):
        triggers = {"self_review": {"enabled": True, "max_rounds": 3, "min_rounds": 2}}
        cfg = SelfReviewConfig.from_policy(triggers)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.max_rounds, 3)
        self.assertEqual(cfg.min_rounds, 2)

    def test_from_policy_disabled(self):
        triggers = {"self_review": {"enabled": False}}
        cfg = SelfReviewConfig.from_policy(triggers)
        self.assertFalse(cfg.enabled)

    def test_from_policy_missing_section(self):
        cfg = SelfReviewConfig.from_policy({})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.max_rounds, 2)

    def test_from_policy_non_dict(self):
        cfg = SelfReviewConfig.from_policy({"self_review": "invalid"})
        self.assertFalse(cfg.enabled)

    def test_min_rounds_clamped_to_1(self):
        triggers = {"self_review": {"enabled": True, "min_rounds": 0}}
        cfg = SelfReviewConfig.from_policy(triggers)
        self.assertEqual(cfg.min_rounds, 1)

    def test_max_rounds_clamped_to_1(self):
        triggers = {"self_review": {"enabled": True, "max_rounds": 0}}
        cfg = SelfReviewConfig.from_policy(triggers)
        self.assertEqual(cfg.max_rounds, 1)

    def test_to_dict(self):
        cfg = SelfReviewConfig(enabled=True, max_rounds=3, min_rounds=2)
        d = cfg.to_dict()
        self.assertEqual(d, {"enabled": True, "max_rounds": 3, "min_rounds": 2})


# ---------------------------------------------------------------------------
# Round tests
# ---------------------------------------------------------------------------


class TestSelfReviewRound(unittest.TestCase):
    """Tests for individual round construction and validation."""

    def test_valid_needs_revision(self):
        rnd = SelfReviewRound(round_number=1, verdict="needs_revision", findings=["bug A"])
        self.assertEqual(rnd.verdict, "needs_revision")
        self.assertEqual(rnd.round_number, 1)
        self.assertEqual(rnd.findings, ["bug A"])

    def test_valid_ready(self):
        rnd = SelfReviewRound(round_number=2, verdict="ready")
        self.assertEqual(rnd.verdict, "ready")

    def test_invalid_verdict(self):
        with self.assertRaises(ValueError):
            SelfReviewRound(round_number=1, verdict="maybe")

    def test_to_dict(self):
        rnd = SelfReviewRound(
            round_number=1,
            verdict="needs_revision",
            findings=["issue X"],
            revised_files=["a.py"],
        )
        d = rnd.to_dict()
        self.assertEqual(d["round_number"], 1)
        self.assertEqual(d["verdict"], "needs_revision")
        self.assertEqual(d["findings"], ["issue X"])
        self.assertEqual(d["revised_files"], ["a.py"])
        self.assertIn("timestamp", d)

    def test_auto_timestamp(self):
        rnd = SelfReviewRound(round_number=1, verdict="ready")
        self.assertTrue(len(rnd.timestamp) > 0)


# ---------------------------------------------------------------------------
# Loop transition tests
# ---------------------------------------------------------------------------


class TestSelfReviewLoop(unittest.TestCase):
    """Tests for the SelfReviewLoop controller and round transitions."""

    def _cfg(self, **kwargs):
        defaults = {"enabled": True, "max_rounds": 3, "min_rounds": 1}
        defaults.update(kwargs)
        return SelfReviewConfig(**defaults)

    # -- basic transitions ---------------------------------------------------

    def test_single_round_ready(self):
        """Worker says 'ready' on first round → loop passes."""
        loop = SelfReviewLoop(self._cfg())
        self.assertFalse(loop.is_complete())
        loop.record_round(verdict="ready")
        self.assertTrue(loop.is_complete())
        self.assertEqual(loop.outcome().status, "passed")
        self.assertEqual(loop.outcome().total_rounds, 1)

    def test_needs_revision_then_ready(self):
        """Round 1: needs_revision, Round 2: ready → passes."""
        loop = SelfReviewLoop(self._cfg())
        loop.record_round(verdict="needs_revision", findings=["missing edge case"])
        self.assertFalse(loop.is_complete())
        loop.record_round(verdict="ready")
        self.assertTrue(loop.is_complete())
        self.assertEqual(loop.outcome().status, "passed")
        self.assertEqual(loop.outcome().total_rounds, 2)

    def test_max_rounds_reached(self):
        """All rounds say needs_revision → max_rounds_reached."""
        loop = SelfReviewLoop(self._cfg(max_rounds=2))
        loop.record_round(verdict="needs_revision")
        self.assertFalse(loop.is_complete())
        loop.record_round(verdict="needs_revision")
        self.assertTrue(loop.is_complete())
        self.assertEqual(loop.outcome().status, "max_rounds_reached")

    def test_cannot_record_after_complete(self):
        """Recording after loop is complete raises RuntimeError."""
        loop = SelfReviewLoop(self._cfg())
        loop.record_round(verdict="ready")
        with self.assertRaises(RuntimeError):
            loop.record_round(verdict="ready")

    # -- min_rounds enforcement -----------------------------------------------

    def test_min_rounds_prevents_early_exit(self):
        """With min_rounds=2, first 'ready' does NOT complete the loop."""
        loop = SelfReviewLoop(self._cfg(min_rounds=2))
        loop.record_round(verdict="ready")
        # min_rounds not yet met → loop continues
        self.assertFalse(loop.is_complete())
        loop.record_round(verdict="ready")
        # now min_rounds met → passes
        self.assertTrue(loop.is_complete())
        self.assertEqual(loop.outcome().status, "passed")

    def test_min_rounds_with_revision_then_ready(self):
        """min_rounds=2: revision + ready → passes (2 rounds done)."""
        loop = SelfReviewLoop(self._cfg(min_rounds=2))
        loop.record_round(verdict="needs_revision", findings=["style issue"])
        self.assertFalse(loop.is_complete())
        loop.record_round(verdict="ready")
        self.assertTrue(loop.is_complete())
        self.assertEqual(loop.outcome().status, "passed")
        self.assertEqual(loop.outcome().total_rounds, 2)

    # -- state queries -------------------------------------------------------

    def test_rounds_remaining(self):
        loop = SelfReviewLoop(self._cfg(max_rounds=3))
        self.assertEqual(loop.rounds_remaining(), 3)
        loop.record_round(verdict="needs_revision")
        self.assertEqual(loop.rounds_remaining(), 2)
        loop.record_round(verdict="needs_revision")
        self.assertEqual(loop.rounds_remaining(), 1)

    def test_can_exit_early(self):
        loop = SelfReviewLoop(self._cfg(min_rounds=2))
        self.assertFalse(loop.can_exit_early())
        loop.record_round(verdict="needs_revision")
        self.assertFalse(loop.can_exit_early())
        loop.record_round(verdict="needs_revision")
        self.assertTrue(loop.can_exit_early())

    def test_current_round(self):
        loop = SelfReviewLoop(self._cfg())
        self.assertEqual(loop.outcome().current_round, 1)
        loop.record_round(verdict="needs_revision")
        self.assertEqual(loop.outcome().current_round, 2)

    # -- round metadata ------------------------------------------------------

    def test_findings_and_revised_files_recorded(self):
        loop = SelfReviewLoop(self._cfg())
        rnd = loop.record_round(
            verdict="needs_revision",
            findings=["missing validation"],
            revised_files=["src/handler.py"],
        )
        self.assertEqual(rnd.findings, ["missing validation"])
        self.assertEqual(rnd.revised_files, ["src/handler.py"])
        self.assertEqual(loop.outcome().rounds[0].findings, ["missing validation"])

    # -- outcome serialisation -----------------------------------------------

    def test_outcome_to_dict_passed(self):
        loop = SelfReviewLoop(self._cfg())
        loop.record_round(verdict="ready")
        d = loop.outcome().to_dict()
        self.assertEqual(d["status"], "passed")
        self.assertEqual(d["total_rounds"], 1)
        self.assertIn("passed after 1 round", d["summary"])
        self.assertEqual(len(d["rounds"]), 1)
        self.assertEqual(d["rounds"][0]["verdict"], "ready")

    def test_outcome_to_dict_max_rounds(self):
        loop = SelfReviewLoop(self._cfg(max_rounds=2))
        loop.record_round(verdict="needs_revision")
        loop.record_round(verdict="needs_revision")
        d = loop.outcome().to_dict()
        self.assertEqual(d["status"], "max_rounds_reached")
        self.assertIn("exhausted", d["summary"])

    def test_outcome_to_dict_pending(self):
        loop = SelfReviewLoop(self._cfg(max_rounds=3))
        loop.record_round(verdict="needs_revision")
        d = loop.outcome().to_dict()
        self.assertEqual(d["status"], "pending")
        self.assertIn("pending", d["summary"])
        self.assertIn("2/3", d["summary"])

    # -- full lifecycle: 3 rounds, pass on 3rd --------------------------------

    def test_three_round_lifecycle(self):
        loop = SelfReviewLoop(self._cfg(max_rounds=3, min_rounds=1))
        loop.record_round(verdict="needs_revision", findings=["issue 1"])
        self.assertFalse(loop.is_complete())
        loop.record_round(verdict="needs_revision", findings=["issue 2"])
        self.assertFalse(loop.is_complete())
        loop.record_round(verdict="ready")
        self.assertTrue(loop.is_complete())
        self.assertEqual(loop.outcome().status, "passed")
        self.assertEqual(loop.outcome().total_rounds, 3)


# ---------------------------------------------------------------------------
# Factory function tests
# ---------------------------------------------------------------------------


class TestCreateSelfReviewLoop(unittest.TestCase):
    """Tests for the create_self_review_loop convenience function."""

    def test_returns_loop_when_enabled(self):
        triggers = {"self_review": {"enabled": True, "max_rounds": 2}}
        loop = create_self_review_loop(triggers)
        self.assertIsNotNone(loop)
        self.assertIsInstance(loop, SelfReviewLoop)

    def test_returns_none_when_disabled(self):
        triggers = {"self_review": {"enabled": False}}
        self.assertIsNone(create_self_review_loop(triggers))

    def test_returns_none_when_missing(self):
        self.assertIsNone(create_self_review_loop({}))


# ---------------------------------------------------------------------------
# Engine integration tests
# ---------------------------------------------------------------------------


def _make_policy_with_self_review(path: Path, self_review_config: dict) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus"}},
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "self_review": self_review_config,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


class TestSelfReviewInEngine(unittest.TestCase):
    """Tests that self-review config is accessible from the engine."""

    def test_self_review_config_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy_with_self_review(
                root / "policy.json",
                {"enabled": True, "max_rounds": 3, "min_rounds": 2},
            )
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            cfg = orch.self_review_config()
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.max_rounds, 3)
            self.assertEqual(cfg.min_rounds, 2)

    def test_self_review_config_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy_with_self_review(
                root / "policy.json",
                {"enabled": False},
            )
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            cfg = orch.self_review_config()
            self.assertFalse(cfg.enabled)

    def test_self_review_metadata_in_report(self):
        """When a report includes self_review dict, it's stored on the task."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy_with_self_review(
                root / "policy.json",
                {"enabled": True, "max_rounds": 2},
            )
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            owner = "claude_code"
            orch.register_agent(owner, {
                "client": "test",
                "model": "test",
                "cwd": str(root),
                "project_root": str(root),
                "permissions_mode": "default",
                "sandbox_mode": "workspace-write",
                "session_id": "test-session",
                "connection_id": "test-conn",
                "server_version": "0.1.0",
                "verification_source": "test",
            })

            task = orch.create_task(
                title="Test self-review report",
                workstream="backend",
                acceptance_criteria=["tests pass"],
                owner=owner,
            )
            orch.claim_next_task(owner)

            self_review_data = {
                "status": "passed",
                "total_rounds": 2,
                "rounds": [
                    {"round_number": 1, "verdict": "needs_revision", "findings": ["missing edge case"]},
                    {"round_number": 2, "verdict": "ready", "findings": []},
                ],
            }

            report = {
                "task_id": task["id"],
                "agent": owner,
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
                "notes": "Implementation with self-review",
                "self_review": self_review_data,
            }
            orch.ingest_report(report)

            # Verify self_review stored on task
            tasks = orch.list_tasks()
            updated_task = next(t for t in tasks if t["id"] == task["id"])
            self.assertIn("self_review", updated_task)
            self.assertEqual(updated_task["self_review"]["status"], "passed")
            self.assertEqual(updated_task["self_review"]["total_rounds"], 2)
            self.assertIn("self_review_updated_at", updated_task)

    def test_report_without_self_review_no_field(self):
        """Reports without self_review dict should not add the field."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy_with_self_review(
                root / "policy.json",
                {"enabled": True, "max_rounds": 2},
            )
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            owner = "claude_code"
            orch.register_agent(owner, {
                "client": "test",
                "model": "test",
                "cwd": str(root),
                "project_root": str(root),
                "permissions_mode": "default",
                "sandbox_mode": "workspace-write",
                "session_id": "test-session",
                "connection_id": "test-conn",
                "server_version": "0.1.0",
                "verification_source": "test",
            })

            task = orch.create_task(
                title="Test no self-review",
                workstream="backend",
                acceptance_criteria=["tests pass"],
                owner=owner,
            )
            orch.claim_next_task(owner)

            report = {
                "task_id": task["id"],
                "agent": owner,
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
                "notes": "No self-review metadata",
            }
            orch.ingest_report(report)

            tasks = orch.list_tasks()
            updated_task = next(t for t in tasks if t["id"] == task["id"])
            self.assertNotIn("self_review", updated_task)


if __name__ == "__main__":
    unittest.main()
