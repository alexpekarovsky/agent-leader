"""Unit tests for report retry queue: enqueue_report_retry and process_report_retry_queue.

Tests cover enqueue deduplication, retry attempt counting, exponential
backoff timing, max attempt failure, successful retry processing,
and event emissions.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

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


def _register_and_setup(orch: Orchestrator, agent: str) -> None:
    """Register agent with standard metadata."""
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": False,
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })


def _sample_report(task_id: str, agent: str = "claude_code") -> dict:
    return {
        "task_id": task_id,
        "agent": agent,
        "commit_sha": "abc123",
        "status": "done",
        "test_summary": {"command": "python3 -m unittest", "passed": 1, "failed": 0},
    }


class EnqueueReportRetryTests(unittest.TestCase):
    """Tests for enqueue_report_retry."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_and_setup(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_enqueue_creates_entry(self) -> None:
        """Enqueue should create a new pending entry."""
        report = _sample_report("TASK-001")
        entry = self.orch.enqueue_report_retry(report, error="connection timeout")

        self.assertTrue(entry["id"].startswith("RPTQ-"))
        self.assertEqual(entry["status"], "pending")
        self.assertEqual(entry["attempts"], 0)
        self.assertEqual(entry["last_error"], "connection timeout")
        self.assertEqual(entry["report"]["task_id"], "TASK-001")

    def test_enqueue_persists_to_file(self) -> None:
        """Enqueued entry should be persisted to the retry queue file."""
        report = _sample_report("TASK-002")
        self.orch.enqueue_report_retry(report, error="timeout")

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["report"]["task_id"], "TASK-002")

    def test_enqueue_deduplication(self) -> None:
        """Enqueue same task_id+agent should update existing entry, not create duplicate."""
        report = _sample_report("TASK-003")
        self.orch.enqueue_report_retry(report, error="error 1")
        self.orch.enqueue_report_retry(report, error="error 2")

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        pending = [e for e in queue if e["status"] == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["last_error"], "error 2")

    def test_enqueue_different_tasks_not_deduped(self) -> None:
        """Different task_ids should create separate entries."""
        self.orch.enqueue_report_retry(_sample_report("TASK-A"), error="err")
        self.orch.enqueue_report_retry(_sample_report("TASK-B"), error="err")

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        pending = [e for e in queue if e["status"] == "pending"]
        self.assertEqual(len(pending), 2)

    def test_enqueue_different_agents_not_deduped(self) -> None:
        """Same task_id but different agents should create separate entries."""
        _register_and_setup(self.orch, "gemini")
        self.orch.enqueue_report_retry(_sample_report("TASK-X", agent="claude_code"), error="err")
        self.orch.enqueue_report_retry(_sample_report("TASK-X", agent="gemini"), error="err")

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        pending = [e for e in queue if e["status"] == "pending"]
        self.assertEqual(len(pending), 2)

    def test_enqueue_emits_event(self) -> None:
        """Enqueue should emit a report.retry_queued event."""
        report = _sample_report("TASK-004")
        self.orch.enqueue_report_retry(report, error="err")

        all_events = list(self.orch.bus.iter_events())
        retry_events = [e for e in all_events if e["type"] == "report.retry_queued"]
        self.assertGreater(len(retry_events), 0)
        self.assertEqual(retry_events[-1]["payload"]["task_id"], "TASK-004")

    def test_enqueue_entry_has_timestamps(self) -> None:
        """Entry should have created_at, updated_at, and next_retry_at."""
        entry = self.orch.enqueue_report_retry(_sample_report("TASK-005"), error="err")
        self.assertIn("created_at", entry)
        self.assertIn("updated_at", entry)
        self.assertIn("next_retry_at", entry)


class ProcessRetryQueueSuccessTests(unittest.TestCase):
    """Tests for process_report_retry_queue — successful retry path."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_and_setup(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_successful_retry_submits_report(self) -> None:
        """When ingest_report succeeds, entry moves to submitted."""
        task = self.orch.create_task(
            title="Retry task",
            workstream="backend",
            acceptance_criteria=["A"],
        )
        self.orch.claim_next_task(owner="claude_code")

        report = _sample_report(task["id"])
        self.orch.enqueue_report_retry(report, error="transient error")

        result = self.orch.process_report_retry_queue()
        self.assertEqual(len(result["processed"]), 1)
        self.assertEqual(result["processed"][0]["status"], "submitted")

    def test_successful_retry_updates_queue_status(self) -> None:
        """After successful retry, queue entry status is 'submitted'."""
        task = self.orch.create_task(
            title="Retry status task",
            workstream="backend",
            acceptance_criteria=["A"],
        )
        self.orch.claim_next_task(owner="claude_code")

        report = _sample_report(task["id"])
        self.orch.enqueue_report_retry(report, error="err")
        self.orch.process_report_retry_queue()

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        self.assertEqual(queue[0]["status"], "submitted")

    def test_successful_retry_emits_submitted_event(self) -> None:
        """Successful retry should emit report.retry_submitted event."""
        task = self.orch.create_task(
            title="Retry event task",
            workstream="backend",
            acceptance_criteria=["A"],
        )
        self.orch.claim_next_task(owner="claude_code")

        report = _sample_report(task["id"])
        self.orch.enqueue_report_retry(report, error="err")
        self.orch.process_report_retry_queue()

        all_events = list(self.orch.bus.iter_events())
        submitted_events = [e for e in all_events if e["type"] == "report.retry_submitted"]
        self.assertGreater(len(submitted_events), 0)

    def test_empty_queue_returns_zeros(self) -> None:
        """Processing an empty queue should return zero counts."""
        result = self.orch.process_report_retry_queue()
        self.assertEqual(len(result["processed"]), 0)
        self.assertEqual(result["pending"], 0)


class ProcessRetryQueueFailureTests(unittest.TestCase):
    """Tests for process_report_retry_queue — failure and backoff paths."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_and_setup(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_failed_retry_increments_attempts(self) -> None:
        """When ingest_report fails, attempt count increments."""
        # Enqueue a report for a non-existent task (will fail)
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="initial error")

        result = self.orch.process_report_retry_queue()
        self.assertEqual(len(result["processed"]), 1)
        self.assertEqual(result["processed"][0]["attempts"], 1)
        self.assertEqual(result["processed"][0]["status"], "retrying")

    def test_failed_retry_sets_backoff(self) -> None:
        """Failed retry should set next_retry_at in the future."""
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="err")

        self.orch.process_report_retry_queue(base_backoff_seconds=10)

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        entry = queue[0]
        self.assertIn("next_retry_at", entry)
        next_retry = datetime.fromisoformat(entry["next_retry_at"])
        self.assertGreater(next_retry, datetime.now(timezone.utc))

    def test_exponential_backoff_increases(self) -> None:
        """Each failed attempt should increase backoff exponentially."""
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="err")

        # Process twice (first attempt uses next_retry_at=now, so it runs)
        self.orch.process_report_retry_queue(base_backoff_seconds=10)

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        first_retry = datetime.fromisoformat(queue[0]["next_retry_at"])

        # Force the next_retry_at to now so it runs again
        queue[0]["next_retry_at"] = datetime.now(timezone.utc).isoformat()
        self.orch.report_retry_queue_path.write_text(json.dumps(queue), encoding="utf-8")

        self.orch.process_report_retry_queue(base_backoff_seconds=10)

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        second_retry = datetime.fromisoformat(queue[0]["next_retry_at"])

        # Second backoff should be farther in the future than first
        self.assertGreater(second_retry, first_retry)

    def test_max_attempts_marks_failed(self) -> None:
        """Reaching max_attempts should mark entry as failed."""
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="err")

        # Set attempts to max_attempts - 1 so next attempt is terminal
        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        queue[0]["attempts"] = 2
        self.orch.report_retry_queue_path.write_text(json.dumps(queue), encoding="utf-8")

        result = self.orch.process_report_retry_queue(max_attempts=3)
        self.assertEqual(result["processed"][0]["status"], "failed")
        self.assertEqual(result["failed"], 1)

    def test_max_attempts_emits_failed_event(self) -> None:
        """Terminal failure should emit report.retry_failed event."""
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="err")

        # Set to terminal
        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        queue[0]["attempts"] = 0
        self.orch.report_retry_queue_path.write_text(json.dumps(queue), encoding="utf-8")

        self.orch.process_report_retry_queue(max_attempts=1)

        all_events = list(self.orch.bus.iter_events())
        failed_events = [e for e in all_events if e["type"] == "report.retry_failed"]
        self.assertGreater(len(failed_events), 0)

    def test_non_terminal_failure_emits_retrying_event(self) -> None:
        """Non-terminal failure should emit report.retry_retrying event."""
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="err")

        self.orch.process_report_retry_queue(max_attempts=5)

        all_events = list(self.orch.bus.iter_events())
        retrying_events = [e for e in all_events if e["type"] == "report.retry_retrying"]
        self.assertGreater(len(retrying_events), 0)

    def test_backoff_capped_at_max(self) -> None:
        """Backoff should not exceed max_backoff_seconds."""
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="err")

        # Set high attempt count to force large backoff
        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        queue[0]["attempts"] = 18  # 2^18 * 15 = huge, should be capped
        self.orch.report_retry_queue_path.write_text(json.dumps(queue), encoding="utf-8")

        self.orch.process_report_retry_queue(
            max_attempts=25, base_backoff_seconds=15, max_backoff_seconds=300,
        )

        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        next_retry = datetime.fromisoformat(queue[0]["next_retry_at"])
        now = datetime.now(timezone.utc)
        # Should be at most ~300 seconds in the future (plus small margin)
        self.assertLess((next_retry - now).total_seconds(), 310)

    def test_future_retry_not_processed(self) -> None:
        """Entries with next_retry_at in the future should not be processed."""
        report = _sample_report("TASK-nonexistent")
        self.orch.enqueue_report_retry(report, error="err")

        # Set next_retry_at to the future
        queue = json.loads(self.orch.report_retry_queue_path.read_text(encoding="utf-8"))
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        queue[0]["next_retry_at"] = future
        self.orch.report_retry_queue_path.write_text(json.dumps(queue), encoding="utf-8")

        result = self.orch.process_report_retry_queue()
        self.assertEqual(len(result["processed"]), 0)
        self.assertEqual(result["pending"], 1)

    def test_limit_caps_processing(self) -> None:
        """Only process up to 'limit' entries per call."""
        for i in range(5):
            self.orch.enqueue_report_retry(
                _sample_report(f"TASK-lim-{i}"), error="err"
            )

        result = self.orch.process_report_retry_queue(limit=2)
        self.assertLessEqual(len(result["processed"]), 2)


class RetryQueueSummaryTests(unittest.TestCase):
    """Tests for return value summary counts."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)
        _register_and_setup(self.orch, "claude_code")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_summary_counts_after_mixed_results(self) -> None:
        """Summary should reflect pending, submitted, and failed counts."""
        # Create a valid task for one entry
        task = self.orch.create_task(
            title="Summary task", workstream="backend", acceptance_criteria=["A"],
        )
        self.orch.claim_next_task(owner="claude_code")

        # One that will succeed
        self.orch.enqueue_report_retry(_sample_report(task["id"]), error="err")
        # One that will fail (non-existent task)
        self.orch.enqueue_report_retry(_sample_report("TASK-bogus"), error="err")

        result = self.orch.process_report_retry_queue()
        self.assertEqual(result["submitted"], 1)
        # The bogus one is still pending (retrying, not terminal)
        self.assertEqual(len(result["processed"]), 2)


if __name__ == "__main__":
    unittest.main()
