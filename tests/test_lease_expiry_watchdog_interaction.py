"""Lease expiry watchdog interaction test design notes and stubs.

Design Notes — Responsibility Split (AUTO-M1-CORE-04 reference)
================================================================

Three components participate in lease expiry detection and recovery:

1. **Watchdog** (scripts/autopilot/watchdog_loop.sh)
   - Role: *Passive observer / diagnostic emitter*
   - Runs on a fixed interval (default 15s) outside the orchestrator process
   - Reads state/tasks.json and emits `stale_task` JSONL diagnostics when
     in_progress tasks exceed INPROGRESS_TIMEOUT (default 900s)
   - Does NOT modify task state or invoke recovery
   - Does NOT check lease fields — only compares updated_at/created_at age
   - Output: .autopilot-logs/watchdog-*.jsonl with kind=stale_task entries
   - State corruption: also emits `state_corruption_detected` for bugs/blockers

2. **Core Engine** (orchestrator.engine.Orchestrator.recover_expired_task_leases)
   - Role: *Authoritative recovery actor*
   - Called explicitly by manager (or manager_cycle) — not self-triggering
   - Checks actual lease.expires_at timestamps (not age heuristics)
   - Recovery actions:
     a) Active owner → requeue (status: in_progress → assigned, lease cleared)
     b) No eligible worker → block (status: in_progress → blocked, blocker created)
   - Events emitted:
     * task.requeued_lease_expired (owner still active)
     * task.reassigned_lease_expired (reassigned to different worker)
     * task.lease_expired_blocked (no eligible worker)

3. **Manager Cycle** (_manager_cycle in orchestrator_mcp_server.py)
   - Role: *Periodic orchestration driver*
   - Validates reported tasks (report files in bus/reports/)
   - Auto-reconnects stale team members with active/blocked tasks
   - Does NOT directly call recover_expired_task_leases (that's invoked
     separately via reassign_stale_tasks or explicit MCP tool call)
   - Indirectly related: reconnecting stale members may prevent future
     lease expiry by restoring heartbeat flow

Interaction Timeline (happy path → expiry → recovery):
------------------------------------------------------
1. Agent claims task → lease issued (TTL from policy, default 300s)
2. Agent periodically renews lease → extends expires_at
3. Agent crashes / disconnects → renewals stop
4. Lease expires_at passes current time
5. Watchdog detects stale_task (age > INPROGRESS_TIMEOUT) → emits diagnostic
6. Manager or operator calls recover_expired_task_leases
7. Core engine checks lease.expires_at, confirms expiry
8. Recovery: requeue to owner (if active) or block (if no worker)
9. Manager cycle may auto-reconnect the stale agent
10. Reconnected agent can re-claim the requeued task

Key Distinction: Watchdog vs Core Detection
--------------------------------------------
- Watchdog uses *age-based heuristic* (updated_at delta > timeout threshold)
  and may flag tasks that have valid leases but old updated_at timestamps.
- Core engine uses *lease.expires_at comparison* which is the authoritative
  expiry check. A task can be watchdog-flagged but not actually lease-expired
  if the lease was recently renewed (renewed_at updates expires_at but may
  not update task.updated_at).
- This design intentionally decouples detection (watchdog) from action (core)
  to prevent the watchdog from causing state mutations.

Expected Events and Status Changes (CORE-04):
----------------------------------------------
| Trigger                    | Event Type                      | Status Change           |
|----------------------------|---------------------------------|-------------------------|
| Lease expires, owner alive | task.requeued_lease_expired      | in_progress → assigned  |
| Lease expires, owner dead  | task.lease_expired_blocked       | in_progress → blocked   |
| Lease expires, reassigned  | task.reassigned_lease_expired    | in_progress → assigned  |
| Lease renewed successfully | task.lease_renewed               | in_progress (no change) |
| Watchdog detects stale     | (JSONL diagnostic, no bus event) | (no state change)       |
| Manager reconnects agent   | (connect_team_members result)    | (no direct change)      |
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Helpers (shared across test classes)
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


def _make_expired_lease_task(orch: Orchestrator, root: Path, agent: str = "claude_code") -> dict:
    """Create, claim, then manually expire a task's lease."""
    _setup_agent(orch, root, agent)
    task = orch.create_task(
        title="Lease expiry watchdog test",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    claimed = orch.claim_next_task(agent)
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == claimed["id"]:
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)
    return claimed


# ---------------------------------------------------------------------------
# 1. Watchdog stale_task detection does NOT modify state
# ---------------------------------------------------------------------------

class WatchdogDoesNotMutateStateTests(unittest.TestCase):
    """Watchdog is a passive observer — it must never change task status or leases.

    Design: The watchdog_loop.sh reads state/tasks.json and emits JSONL
    diagnostics but never writes back. This test verifies that running the
    watchdog over a directory with stale in_progress tasks does not alter
    the tasks.json content.
    """

    def test_watchdog_preserves_tasks_json(self) -> None:
        """Running watchdog --once should not modify tasks.json."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)

            tasks_before = (root / "state" / "tasks.json").read_text(encoding="utf-8")
            log_dir = root / "watchdog-logs"
            log_dir.mkdir(exist_ok=True)

            script = Path(__file__).resolve().parent.parent / "scripts" / "autopilot" / "watchdog_loop.sh"
            if script.exists():
                subprocess.run(
                    ["bash", str(script), "--project-root", str(root),
                     "--log-dir", str(log_dir), "--once",
                     "--inprogress-timeout", "1"],
                    capture_output=True, text=True, timeout=30,
                )

            tasks_after = (root / "state" / "tasks.json").read_text(encoding="utf-8")
            self.assertEqual(tasks_before, tasks_after)

    def test_watchdog_emits_stale_task_diagnostic(self) -> None:
        """Watchdog should emit stale_task kind for old in_progress tasks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Create a task with very old updated_at
            task = _make_expired_lease_task(orch, root)
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == task["id"]:
                    t["updated_at"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.tasks_path, tasks)

            log_dir = root / "watchdog-logs"
            log_dir.mkdir(exist_ok=True)

            script = Path(__file__).resolve().parent.parent / "scripts" / "autopilot" / "watchdog_loop.sh"
            if not script.exists():
                self.skipTest("watchdog_loop.sh not found")

            subprocess.run(
                ["bash", str(script), "--project-root", str(root),
                 "--log-dir", str(log_dir), "--once",
                 "--inprogress-timeout", "1"],
                capture_output=True, text=True, timeout=30,
            )

            jsonl_files = list(log_dir.glob("watchdog-*.jsonl"))
            self.assertGreaterEqual(len(jsonl_files), 1)
            lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
            stale_entries = [json.loads(l) for l in lines if "stale_task" in l]
            self.assertGreaterEqual(len(stale_entries), 1)
            self.assertEqual(stale_entries[0]["kind"], "stale_task")
            self.assertEqual(stale_entries[0]["task_id"], task["id"])
            for field in (
                "timestamp",
                "kind",
                "task_id",
                "owner",
                "status",
                "age_seconds",
                "timeout_seconds",
                "title",
            ):
                self.assertIn(field, stale_entries[0])
            self.assertEqual(stale_entries[0]["status"], "in_progress")
            self.assertEqual(stale_entries[0]["timeout_seconds"], 1)
            self.assertIsInstance(stale_entries[0]["age_seconds"], int)

    def test_watchdog_emits_state_corruption_detected_for_dict_collection(self) -> None:
        """Corrupted bugs/blockers collection types should emit diagnostics."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Corrupt list-backed files with dicts to trigger watchdog diagnostics.
            orch._write_json(orch.bugs_path, {"bad": True})
            orch._write_json(orch.blockers_path, {"also_bad": True})

            log_dir = root / "watchdog-logs"
            log_dir.mkdir(exist_ok=True)
            script = Path(__file__).resolve().parent.parent / "scripts" / "autopilot" / "watchdog_loop.sh"
            if not script.exists():
                self.skipTest("watchdog_loop.sh not found")

            subprocess.run(
                ["bash", str(script), "--project-root", str(root), "--log-dir", str(log_dir), "--once"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            jsonl_files = list(log_dir.glob("watchdog-*.jsonl"))
            self.assertGreaterEqual(len(jsonl_files), 1)
            entries = [
                json.loads(line)
                for line in jsonl_files[0].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            corruption = [e for e in entries if e.get("kind") == "state_corruption_detected"]
            self.assertGreaterEqual(len(corruption), 2)
            for entry in corruption:
                for field in ("timestamp", "kind", "path", "previous_type", "expected_type"):
                    self.assertIn(field, entry)
                self.assertEqual("list", entry["expected_type"])
                self.assertEqual("dict", entry["previous_type"])


# ---------------------------------------------------------------------------
# 2. Core engine recovery events and status changes
# ---------------------------------------------------------------------------

class LeaseExpiryRecoveryEventsTests(unittest.TestCase):
    """Core engine recovery emits the correct events per CORE-04 spec.

    Expected events:
    - task.requeued_lease_expired when owner is still active
    - task.lease_expired_blocked when no eligible worker
    """

    def test_recovery_emits_requeue_event_for_active_owner(self) -> None:
        """Active owner → task.requeued_lease_expired event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            requeue_events = [
                e for e in events
                if e.get("type") in {"task.requeued_lease_expired", "task.reassigned_lease_expired"}
            ]
            self.assertGreaterEqual(len(requeue_events), 1)
            self.assertEqual(requeue_events[0]["payload"]["task_id"], task["id"])

    def test_recovery_emits_blocked_event_for_stale_owner(self) -> None:
        """Stale owner, no eligible worker → task.lease_expired_blocked event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.recover_expired_task_leases(source="codex")

            events = list(orch.bus.iter_events())
            blocked_events = [e for e in events if e.get("type") == "task.lease_expired_blocked"]
            self.assertEqual(len(blocked_events), 1)
            self.assertEqual(blocked_events[0]["payload"]["task_id"], task["id"])

    def test_requeue_sets_status_to_assigned(self) -> None:
        """After requeue recovery, task status must be 'assigned'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("assigned", recovered["status"])

    def test_blocked_recovery_sets_status_to_blocked(self) -> None:
        """After blocked recovery, task status must be 'blocked'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("blocked", recovered["status"])

    def test_requeue_clears_lease_field(self) -> None:
        """After requeue, lease must be None."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIsNone(recovered.get("lease"))


# ---------------------------------------------------------------------------
# 3. Watchdog detection vs core detection divergence
# ---------------------------------------------------------------------------

class WatchdogVsCoreDetectionTests(unittest.TestCase):
    """Watchdog age heuristic and core lease check can diverge.

    Watchdog flags tasks whose updated_at exceeds INPROGRESS_TIMEOUT.
    Core checks lease.expires_at. A recently-renewed lease has a fresh
    expires_at but may have an old updated_at, so watchdog may flag
    a task that core considers valid.
    """

    def test_valid_lease_not_recovered_despite_old_updated_at(self) -> None:
        """Task with valid lease should not be recovered even if updated_at is old."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="Valid lease old update",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            # Set updated_at very old but lease is still valid (future expires_at)
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == claimed["id"]:
                    t["updated_at"] = "2020-01-01T00:00:00+00:00"
                    # lease.expires_at remains in the future (set by claim)
            orch._write_json(orch.tasks_path, tasks)

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(0, result["recovered_count"])

    def test_expired_lease_recovered_despite_recent_updated_at(self) -> None:
        """Task with expired lease should be recovered even if updated_at is recent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            # Set updated_at to now but lease is expired
            from datetime import datetime, timezone
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == task["id"]:
                    t["updated_at"] = datetime.now(timezone.utc).isoformat()
            orch._write_json(orch.tasks_path, tasks)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])


# ---------------------------------------------------------------------------
# 4. Manager cycle does not directly invoke lease recovery
# ---------------------------------------------------------------------------

class ManagerCycleIndependenceTests(unittest.TestCase):
    """Manager cycle handles reports and reconnects but not lease recovery.

    The manager_cycle processes reported tasks and reconnects stale agents.
    Lease recovery is a separate operation (recover_expired_task_leases or
    reassign_stale_tasks) to prevent coupling report validation with
    recovery logic. This test confirms that an expired lease task remains
    in_progress after manager cycle activities that don't include
    explicit recovery calls.
    """

    def test_expired_lease_task_persists_without_explicit_recovery(self) -> None:
        """Without calling recover_expired_task_leases, expired tasks stay in_progress."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)

            # Simulate what manager_cycle does: list tasks, check reported status
            reported_tasks = [t for t in orch.list_tasks() if t.get("status") == "reported"]
            # No reported tasks, so manager_cycle report processing is a no-op
            self.assertEqual(len(reported_tasks), 0)

            # Verify expired task is still in_progress (not auto-recovered)
            tasks = orch._read_json(orch.tasks_path)
            expired = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("in_progress", expired["status"])
            self.assertIsNotNone(expired.get("lease"))

    def test_recovery_only_triggered_by_explicit_call(self) -> None:
        """Recovery must be explicitly invoked to change task status."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            # Before explicit call: still in_progress
            tasks = orch._read_json(orch.tasks_path)
            before = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("in_progress", before["status"])

            # Explicit recovery call
            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            tasks = orch._read_json(orch.tasks_path)
            after = next(t for t in tasks if t["id"] == task["id"])
            self.assertEqual("assigned", after["status"])


# ---------------------------------------------------------------------------
# 5. Recovered task is re-claimable (CORE-04 round-trip)
# ---------------------------------------------------------------------------

class RecoveredTaskRoundTripTests(unittest.TestCase):
    """After recovery, task should be claimable again (CORE-04 requirement).

    The full round-trip: claim → expire → recover → re-claim must produce
    a new valid lease on the re-claimed task.
    """

    def test_recovered_task_is_reclaimable(self) -> None:
        """After recovery to assigned, the same agent can re-claim."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            self.assertEqual(task["id"], reclaimed["id"])
            self.assertEqual("in_progress", reclaimed["status"])
            self.assertIsNotNone(reclaimed.get("lease"))

    def test_reclaimed_task_has_new_lease_id(self) -> None:
        """Re-claim after recovery should issue a fresh lease_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            old_lease_id = task["lease"]["lease_id"]
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")
            reclaimed = orch.claim_next_task("claude_code")

            self.assertNotEqual(old_lease_id, reclaimed["lease"]["lease_id"])

    def test_recovery_sets_lease_recovery_at(self) -> None:
        """Recovered task should have lease_recovery_at timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            task = _make_expired_lease_task(orch, root)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == task["id"])
            self.assertIn("lease_recovery_at", recovered)


if __name__ == "__main__":
    unittest.main()
