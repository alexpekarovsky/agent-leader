"""Tests for manager_cycle orchestration logic.

Since _manager_cycle() lives in orchestrator_mcp_server.py and uses the global
ORCH singleton, we test the same orchestration flow through the engine API.
This covers: report validation, retry queue processing, stale reconnection,
lease recovery, and stale task reassignment — the same steps _manager_cycle performs.
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


def _connect_agent(orch: Orchestrator, root: Path, agent: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent), source=agent)


def _create_claim_report(orch: Orchestrator, agent: str, commit: str = "abc123") -> dict:
    """Create task, claim, and submit report — returning the task."""
    task = orch.create_task(
        title="Cycle test task",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["done"],
    )
    orch.claim_next_task(agent)
    orch.ingest_report({
        "task_id": task["id"],
        "agent": agent,
        "commit_sha": commit,
        "status": "done",
        "test_summary": {"command": "python3 -m unittest -v", "passed": 10, "failed": 0},
    })
    return task


class ManagerCycleReportValidationTests(unittest.TestCase):
    """Tests for report validation within manager cycle."""

    def test_valid_report_gets_accepted(self) -> None:
        """A report with done status, 0 failures, commit, and command should pass."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_claim_report(orch, "claude_code")

            # Verify task is in reported state
            tasks = orch.list_tasks()
            reported = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("reported", reported["status"])

            # Manager validates
            orch.validate_task(
                task_id=task["id"],
                passed=True,
                notes="Accepted",
                source="codex",
            )
            updated = next(t for t in orch.list_tasks() if t["id"] == task["id"])
            self.assertEqual("done", updated["status"])

    def test_missing_report_file_fails_validation(self) -> None:
        """Task in reported state without report file should fail validation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = _create_claim_report(orch, "claude_code")

            # Remove the report file
            report_path = orch.bus.reports_dir / f"{task['id']}.json"
            report_path.unlink()

            # Manager rejects
            orch.validate_task(
                task_id=task["id"],
                passed=False,
                notes="Missing report file",
                source="codex",
            )
            updated = next(t for t in orch.list_tasks() if t["id"] == task["id"])
            self.assertEqual("bug_open", updated["status"])

    def test_report_with_failures_rejected(self) -> None:
        """Report with failed tests should be rejected by manager."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Failing tests",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["all pass"],
            )
            orch.claim_next_task("claude_code")
            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "def456",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 8, "failed": 2},
            })

            # Manager rejects due to failures
            report = json.loads(
                (orch.bus.reports_dir / f"{task['id']}.json").read_text(encoding="utf-8")
            )
            summary = report.get("test_summary", {})
            failed = int(summary.get("failed", 1))
            self.assertGreater(failed, 0)

            orch.validate_task(
                task_id=task["id"],
                passed=False,
                notes=f"Failed tests: {failed}",
                source="codex",
            )
            updated = next(t for t in orch.list_tasks() if t["id"] == task["id"])
            self.assertEqual("bug_open", updated["status"])

    def test_blocked_report_rejected(self) -> None:
        """Report with status=blocked should not pass validation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Blocked report",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.claim_next_task("claude_code")
            orch.ingest_report({
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "ghi789",
                "status": "blocked",
                "test_summary": {"command": "pytest", "passed": 0, "failed": 0},
            })

            report = json.loads(
                (orch.bus.reports_dir / f"{task['id']}.json").read_text(encoding="utf-8")
            )
            self.assertEqual("blocked", report["status"])


class ManagerCycleRetryQueueTests(unittest.TestCase):
    """Tests for report retry queue processing in cycle."""

    def test_retry_queue_processes_pending_reports(self) -> None:
        """Retry queue should process pending reports and submit them."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Retry me",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.claim_next_task("claude_code")

            report = {
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "retry123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
            }
            orch.enqueue_report_retry(report=report, error="temporary failure")

            result = orch.process_report_retry_queue(
                max_attempts=3,
                base_backoff_seconds=0,
                max_backoff_seconds=1,
                limit=10,
            )

            self.assertGreaterEqual(result["submitted"], 1)
            # Task should now be reported
            updated = next(t for t in orch.list_tasks() if t["id"] == task["id"])
            self.assertEqual("reported", updated["status"])

    def test_retry_queue_empty_returns_zero(self) -> None:
        """Empty retry queue should return 0 processed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.process_report_retry_queue(
                max_attempts=3,
                base_backoff_seconds=0,
                max_backoff_seconds=1,
                limit=10,
            )

            self.assertEqual(0, result["submitted"])


class ManagerCycleStaleAgentTests(unittest.TestCase):
    """Tests for stale agent handling in cycle."""

    def test_stale_agent_tasks_reassigned(self) -> None:
        """Tasks owned by stale agents should be reassigned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")
            task = orch.create_task(
                title="Stale owner task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.claim_next_task("claude_code")

            # Make claude_code stale
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)
            # Keep gemini fresh
            orch.heartbeat("gemini", _full_metadata(root, "gemini"))

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex",
                stale_after_seconds=600,
                include_blocked=True,
            )

            self.assertGreaterEqual(result["reassigned_count"], 1)

    def test_no_stale_agents_no_reassignment(self) -> None:
        """When all agents are active, no reassignment should happen."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            orch.create_task(
                title="Active owner",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.claim_next_task("claude_code")

            result = orch.reassign_stale_tasks_to_active_workers(
                source="codex",
                stale_after_seconds=600,
                include_blocked=True,
            )

            self.assertEqual(0, result["reassigned_count"])


class ManagerCycleLeaseRecoveryTests(unittest.TestCase):
    """Tests for lease recovery in cycle."""

    def test_expired_leases_recovered_in_cycle(self) -> None:
        """Manager cycle should recover expired leases."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Lease expire",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")

            # Expire the lease
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == task["id"] and t.get("lease"):
                    t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])


class ManagerCycleNoopDiagnosticsTests(unittest.TestCase):
    """Tests for claim override noop diagnostics in cycle."""

    def test_stale_overrides_emit_noops(self) -> None:
        """Stale claim overrides should produce noop diagnostics."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Noop target",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.set_claim_override(agent="claude_code", task_id=task["id"], source="codex")

            # Backdate the override
            overrides = orch._read_json(orch.claim_overrides_path)
            overrides["claude_code"]["created_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.claim_overrides_path, overrides)

            result = orch.emit_stale_claim_override_noops(source="codex", timeout_seconds=5)

            self.assertEqual(1, result["emitted_count"])

    def test_no_overrides_no_noops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.emit_stale_claim_override_noops(source="codex")

            self.assertEqual(0, result["emitted_count"])


class ManagerCycleFullFlowTests(unittest.TestCase):
    """End-to-end test simulating a complete manager cycle."""

    def test_full_cycle_processes_all_steps(self) -> None:
        """Simulate a full manager cycle: create tasks, report, validate, recover."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            _connect_agent(orch, root, "gemini")

            # Create and complete a task
            task1 = _create_claim_report(orch, "claude_code", "commit1")

            # Step 1: Process retry queue (should be empty)
            retry = orch.process_report_retry_queue(
                max_attempts=3, base_backoff_seconds=0, max_backoff_seconds=1, limit=10
            )
            self.assertEqual(0, retry["submitted"])

            # Step 2: Validate reported tasks
            reported_tasks = [t for t in orch.list_tasks() if t["status"] == "reported"]
            self.assertEqual(1, len(reported_tasks))
            orch.validate_task(
                task_id=task1["id"],
                passed=True,
                notes="Accepted in cycle",
                source="codex",
            )

            # Step 3: Reassign stale tasks (none stale)
            reassign = orch.reassign_stale_tasks_to_active_workers(
                source="codex", stale_after_seconds=600, include_blocked=True
            )
            self.assertEqual(0, reassign["reassigned_count"])

            # Step 4: Noop diagnostics (none)
            noops = orch.emit_stale_claim_override_noops(source="codex")
            self.assertEqual(0, noops["emitted_count"])

            # Step 5: Lease recovery (none)
            leases = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(0, leases["recovered_count"])

            # Verify final state
            final_tasks = orch.list_tasks()
            done = [t for t in final_tasks if t["status"] == "done"]
            self.assertEqual(1, len(done))

    def test_remaining_by_owner_uses_fresh_snapshot(self) -> None:
        """After validate_task mutations, re-reading tasks must reflect updated state.

        Regression test for stale-snapshot bug: the initial list_tasks() call
        at the start of the cycle should NOT be used for the remaining_by_owner
        summary — a fresh read after all mutations is required.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            # Create two tasks, report one
            task1 = _create_claim_report(orch, "claude_code", "commit1")
            task2 = orch.create_task(
                title="Still pending",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            # Snapshot before mutations (like manager_cycle's initial read)
            stale_tasks = orch.list_tasks()
            reported_in_stale = [t for t in stale_tasks if t["status"] == "reported"]
            self.assertEqual(1, len(reported_in_stale))

            # Mutate: validate the reported task → status becomes "done"
            orch.validate_task(
                task_id=task1["id"],
                passed=True,
                notes="Accepted",
                source="codex",
            )

            # The stale snapshot still shows "reported"
            stale_reported = next(t for t in stale_tasks if t["id"] == task1["id"])
            self.assertEqual("reported", stale_reported["status"])

            # Fresh read (what the fix does) must show "done"
            fresh_tasks = orch.list_tasks()
            fresh_t1 = next(t for t in fresh_tasks if t["id"] == task1["id"])
            self.assertEqual("done", fresh_t1["status"])

            # Build remaining_by_owner from fresh snapshot
            pending_statuses = {"assigned", "in_progress", "reported", "bug_open", "blocked"}
            by_owner: dict = {}
            for task in fresh_tasks:
                owner = task.get("owner", "unknown")
                bucket = by_owner.setdefault(owner, {"pending": 0, "done": 0})
                if task.get("status") in pending_statuses:
                    bucket["pending"] += 1
                if task.get("status") == "done":
                    bucket["done"] += 1

            # task1 is done, task2 is assigned → 1 pending, 1 done
            self.assertEqual(1, by_owner["claude_code"]["done"])
            self.assertEqual(1, by_owner["claude_code"]["pending"])

    def test_cycle_publishes_task_contracts_event(self) -> None:
        """Manager cycle should publish task contract digest event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            orch.create_task("Pending task", "backend", ["done"], owner="claude_code")

            # Clear events and publish contracts like manager_cycle does
            orch.bus.events_path.write_text("", encoding="utf-8")
            pending = [t for t in orch.list_tasks() if t["status"] in {"assigned", "in_progress", "reported", "bug_open", "blocked"}]
            contracts = [
                {"task_id": t["id"], "owner": t.get("owner"), "title": t.get("title"), "status": t.get("status")}
                for t in pending
            ]
            orch.publish_event(
                event_type="manager.task_contracts",
                source="codex",
                payload={"contracts": contracts},
            )

            events = list(orch.bus.iter_events())
            contract_events = [e for e in events if e.get("type") == "manager.task_contracts"]
            self.assertEqual(1, len(contract_events))
            self.assertGreaterEqual(len(contract_events[0]["payload"]["contracts"]), 1)


class ManagerCycleNonBlockingConnectTests(unittest.TestCase):
    """Tests for non-blocking connect_team_members in manager cycle."""

    def test_non_blocking_connect_returns_immediately(self) -> None:
        """blocking=False should return triggered_non_blocking without polling."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            result = orch.connect_team_members(
                source="codex",
                team_members=["claude_code"],
                timeout_seconds=30,
                blocking=False,
            )

            self.assertEqual("triggered_non_blocking", result["status"])
            self.assertEqual(["claude_code"], result["requested"])
            self.assertEqual([], result["connected"])
            self.assertEqual(["claude_code"], result["missing"])
            self.assertEqual(0, result["elapsed_seconds"])

    def test_non_blocking_connect_emits_event(self) -> None:
        """Non-blocking mode should still emit the connect event for workers."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            # Clear events
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.connect_team_members(
                source="codex",
                team_members=["claude_code"],
                timeout_seconds=10,
                blocking=False,
            )

            events = list(orch.bus.iter_events())
            connect_events = [e for e in events if e.get("type") == "manager.connect_team_members"]
            self.assertEqual(1, len(connect_events))
            self.assertIn("claude_code", connect_events[0]["payload"]["team_members"])

    def test_non_blocking_does_not_emit_result_event(self) -> None:
        """Non-blocking mode should NOT emit a result event (no poll happened)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")

            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.connect_team_members(
                source="codex",
                team_members=["claude_code"],
                timeout_seconds=10,
                blocking=False,
            )

            events = list(orch.bus.iter_events())
            result_events = [e for e in events if e.get("type") == "manager.connect_team_members.result"]
            self.assertEqual(0, len(result_events))

    def test_blocking_connect_still_polls(self) -> None:
        """blocking=True (default) should still poll and return connected agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect_agent(orch, root, "claude_code")
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.connect_team_members(
                source="codex",
                team_members=["claude_code"],
                timeout_seconds=5,
                blocking=True,
            )

            self.assertEqual("connected", result["status"])
            self.assertIn("claude_code", result["connected"])


if __name__ == "__main__":
    unittest.main()
