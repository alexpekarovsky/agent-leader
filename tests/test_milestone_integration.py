"""Core milestone integration test (CORE-02..06 flow).

Walks through each CORE milestone in sequence:
  CORE-02: Register agents, verify status shows them with identities
  CORE-03: Create task, claim it (lease issued), renew lease
  CORE-04: Expire lease, recover it, verify requeue
  CORE-05: Publish targeted events, verify audience filtering
  CORE-06: Verify recovery events have diagnostic info
  Full lifecycle: create -> claim -> renew -> report -> validate -> done
  Multi-agent: claude_code and gemini both work on tasks concurrently
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


def _register(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.register_agent(agent, metadata={
        "client": "test", "model": "test", "cwd": str(orch.root),
        "project_root": str(orch.root), "permissions_mode": "default",
        "sandbox_mode": "workspace-write", "session_id": session_id,
        "connection_id": f"conn-{agent}", "server_version": "0.1.0",
        "verification_source": "test",
    })


def _heartbeat(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.heartbeat(agent, metadata={
        "client": "test", "model": "test", "cwd": str(orch.root),
        "project_root": str(orch.root), "permissions_mode": "default",
        "sandbox_mode": "workspace-write", "session_id": session_id,
        "connection_id": f"conn-{agent}", "server_version": "0.1.0",
        "verification_source": "test",
    })


def _expire_lease(orch: Orchestrator, task_id: str) -> None:
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == task_id and isinstance(t.get("lease"), dict):
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)


class MilestoneIntegrationCORE02Tests(unittest.TestCase):
    """CORE-02: Register agents, verify status shows them with identities."""

    def test_register_agents_appear_in_list(self) -> None:
        """After registering, agents appear in list_agents with identities."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-cc")
            _register(orch, "gemini", session_id="sess-gm")
            _register(orch, "codex", session_id="sess-cx")

            agents = orch.list_agents(active_only=True)
            agent_names = {a["agent"] for a in agents}
            self.assertIn("claude_code", agent_names)
            self.assertIn("gemini", agent_names)
            self.assertIn("codex", agent_names)

    def test_registered_agents_have_identity_fields(self) -> None:
        """Registered agents should have verified identity with session_id."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-cc")

            agents = orch.list_agents(active_only=True)
            cc = next(a for a in agents if a["agent"] == "claude_code")
            self.assertTrue(cc.get("verified"))
            self.assertTrue(cc.get("same_project"))
            self.assertEqual("sess-cc", cc.get("instance_id"))


class MilestoneIntegrationCORE03Tests(unittest.TestCase):
    """CORE-03: Create task, claim it (lease issued), renew lease."""

    def test_create_claim_lease_issued(self) -> None:
        """Creating and claiming a task should issue a lease."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = orch.create_task(
                title="CORE-03 task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])
            lease = claimed["lease"]
            self.assertIsNotNone(lease)
            self.assertIn("lease_id", lease)
            self.assertIn("expires_at", lease)

    def test_renew_lease(self) -> None:
        """Renewing a lease should update renewed_at and expires_at."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            task = orch.create_task(
                title="Renewable task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            lease_id = claimed["lease"]["lease_id"]
            original_expires = claimed["lease"]["expires_at"]

            result = orch.renew_task_lease(
                task_id=claimed["id"],
                agent="claude_code",
                lease_id=lease_id,
            )

            self.assertIn("lease", result)
            self.assertIsNotNone(result["lease"]["renewed_at"])


class MilestoneIntegrationCORE04Tests(unittest.TestCase):
    """CORE-04: Expire lease, recover it, verify requeue."""

    def test_expire_and_recover_lease(self) -> None:
        """Expiring a lease and running recovery should requeue the task."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            task = orch.create_task(
                title="CORE-04 expire task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_lease(orch, claimed["id"])
            _heartbeat(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            tasks = orch.list_tasks()
            recovered = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("assigned", recovered["status"])
            self.assertIsNone(recovered.get("lease"))


class MilestoneIntegrationCORE05Tests(unittest.TestCase):
    """CORE-05: Publish targeted events, verify audience filtering."""

    def test_targeted_event_audience_filtering(self) -> None:
        """Events with audience targeting are properly filtered per agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _register(orch, "gemini")
            _register(orch, "codex")

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.core05",
                source="codex",
                payload={"msg": "targeted"},
                audience=["claude_code"],
            )

            # claude_code sees it
            cc_result = orch.poll_events(agent="claude_code", cursor=0, limit=100, auto_advance=False)
            cc_hits = [e for e in cc_result["events"] if e.get("type") == "test.core05"]
            self.assertGreaterEqual(len(cc_hits), 1)

            # gemini does not
            gm_result = orch.poll_events(agent="gemini", cursor=0, limit=100, auto_advance=False)
            gm_hits = [e for e in gm_result["events"] if e.get("type") == "test.core05"]
            self.assertEqual(0, len(gm_hits))


class MilestoneIntegrationCORE06Tests(unittest.TestCase):
    """CORE-06: Verify recovery events have diagnostic info."""

    def test_recovery_events_have_diagnostics(self) -> None:
        """Recovery events should contain task_id, owner, reason."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")
            task = orch.create_task(
                title="CORE-06 diagnostic task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_lease(orch, claimed["id"])

            orch.bus.events_path.write_text("", encoding="utf-8")
            _heartbeat(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            detail = result["recovered"][0]
            self.assertEqual(claimed["id"], detail["task_id"])
            self.assertEqual("claude_code", detail["owner"])
            self.assertEqual("lease_expired", detail["reason"])

            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in {
                    "task.requeued_lease_expired",
                    "task.reassigned_lease_expired",
                    "task.lease_expired_blocked",
                }
            ]
            self.assertGreaterEqual(len(recovery_events), 1)
            payload = recovery_events[0]["payload"]
            self.assertEqual(claimed["id"], payload["task_id"])


class FullLifecycleTests(unittest.TestCase):
    """Full lifecycle: create -> claim -> renew -> report -> validate -> done."""

    def test_full_task_lifecycle(self) -> None:
        """Walk a task through the entire lifecycle from creation to done."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")

            # Create
            task = orch.create_task(
                title="Lifecycle task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["tests pass"],
            )
            task_id = task["id"]
            self.assertEqual("assigned", task["status"])

            # Claim
            claimed = orch.claim_next_task("claude_code")
            self.assertEqual(task_id, claimed["id"])
            self.assertEqual("in_progress", claimed["status"])
            lease_id = claimed["lease"]["lease_id"]

            # Renew
            renewal = orch.renew_task_lease(
                task_id=task_id,
                agent="claude_code",
                lease_id=lease_id,
            )
            self.assertIn("lease", renewal)

            # Report
            report = orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
                "notes": "All tests pass",
            })
            tasks = orch.list_tasks()
            reported = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("reported", reported["status"])

            # Validate
            result = orch.validate_task(
                task_id=task_id,
                passed=True,
                notes="Looks good",
                source="codex",
            )
            tasks = orch.list_tasks()
            done = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("done", done["status"])

    def test_lifecycle_with_failed_validation_and_bug_fix(self) -> None:
        """Task that fails validation, gets bug_open, then re-submitted and validated."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _heartbeat(orch, "claude_code")

            task = orch.create_task(
                title="Bug cycle task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["tests pass"],
            )
            task_id = task["id"]

            # Claim and report
            claimed = orch.claim_next_task("claude_code")
            orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "bad123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 3, "failed": 2},
                "notes": "Some tests failing",
            })

            # Validation fails - opens bug
            result = orch.validate_task(
                task_id=task_id,
                passed=False,
                notes="2 tests failing",
                source="codex",
            )
            tasks = orch.list_tasks()
            bug_task = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("bug_open", bug_task["status"])

            # Bug fix: reclaim, report, validate
            reclaimed = orch.claim_next_task("claude_code")
            self.assertEqual(task_id, reclaimed["id"])
            orch.ingest_report({
                "task_id": task_id,
                "agent": "claude_code",
                "commit_sha": "fix456",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 5, "failed": 0},
                "notes": "All fixed",
            })
            orch.validate_task(
                task_id=task_id,
                passed=True,
                notes="All good now",
                source="codex",
            )
            tasks = orch.list_tasks()
            done = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("done", done["status"])


class MultiAgentConcurrentTests(unittest.TestCase):
    """Multi-agent: claude_code and gemini both work on tasks concurrently."""

    def test_multi_agent_concurrent_tasks(self) -> None:
        """claude_code and gemini each claim and complete different tasks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code", session_id="sess-cc")
            _register(orch, "gemini", session_id="sess-gm")
            _heartbeat(orch, "claude_code", session_id="sess-cc")
            _heartbeat(orch, "gemini", session_id="sess-gm")

            # Create tasks for each agent
            be_task = orch.create_task(
                title="Backend work",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            fe_task = orch.create_task(
                title="Frontend work",
                workstream="frontend",
                owner="gemini",
                acceptance_criteria=["done"],
            )

            # Both claim
            cc_claimed = orch.claim_next_task("claude_code")
            gm_claimed = orch.claim_next_task("gemini")

            self.assertIsNotNone(cc_claimed)
            self.assertIsNotNone(gm_claimed)
            self.assertEqual(be_task["id"], cc_claimed["id"])
            self.assertEqual(fe_task["id"], gm_claimed["id"])

            # Both report
            orch.ingest_report({
                "task_id": be_task["id"],
                "agent": "claude_code",
                "commit_sha": "cc-sha",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 3, "failed": 0},
            })
            orch.ingest_report({
                "task_id": fe_task["id"],
                "agent": "gemini",
                "commit_sha": "gm-sha",
                "status": "done",
                "test_summary": {"command": "npm test", "passed": 5, "failed": 0},
            })

            # Both validate
            orch.validate_task(task_id=be_task["id"], passed=True, notes="ok", source="codex")
            orch.validate_task(task_id=fe_task["id"], passed=True, notes="ok", source="codex")

            tasks = orch.list_tasks()
            statuses = {t["id"]: t["status"] for t in tasks}
            self.assertEqual("done", statuses[be_task["id"]])
            self.assertEqual("done", statuses[fe_task["id"]])

    def test_multi_agent_event_isolation(self) -> None:
        """Events targeted to one agent should not leak to the other."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register(orch, "claude_code")
            _register(orch, "gemini")

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.isolation",
                source="codex",
                payload={"secret": "for claude"},
                audience=["claude_code"],
            )

            gm_result = orch.poll_events(agent="gemini", cursor=0, limit=100, auto_advance=False)
            gm_isolation = [e for e in gm_result["events"] if e.get("type") == "test.isolation"]
            self.assertEqual(0, len(gm_isolation))


class SequentialMilestoneFlowTests(unittest.TestCase):
    """Walk through each CORE milestone in sequence within one test."""

    def test_sequential_core02_through_core06(self) -> None:
        """Sequential walk: CORE-02 -> CORE-03 -> CORE-04 -> CORE-05 -> CORE-06."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # === CORE-02: Register agents ===
            _register(orch, "claude_code", session_id="sess-cc")
            _register(orch, "gemini", session_id="sess-gm")
            _register(orch, "codex", session_id="sess-cx")
            _heartbeat(orch, "claude_code", session_id="sess-cc")
            _heartbeat(orch, "gemini", session_id="sess-gm")
            _heartbeat(orch, "codex", session_id="sess-cx")

            agents = orch.list_agents(active_only=True)
            self.assertEqual(3, len(agents))
            for a in agents:
                self.assertTrue(a.get("verified"), f"Agent {a['agent']} should be verified")

            # === CORE-03: Create, claim, lease, renew ===
            task = orch.create_task(
                title="Sequential test task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            task_id = task["id"]
            claimed = orch.claim_next_task("claude_code")
            self.assertEqual("in_progress", claimed["status"])
            lease = claimed["lease"]
            self.assertIsNotNone(lease)

            renewal = orch.renew_task_lease(
                task_id=task_id,
                agent="claude_code",
                lease_id=lease["lease_id"],
            )
            self.assertIn("lease", renewal)

            # === CORE-04: Expire, recover ===
            _expire_lease(orch, task_id)
            _heartbeat(orch, "claude_code", session_id="sess-cc")

            recover_result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(1, recover_result["recovered_count"])

            tasks = orch.list_tasks()
            recovered = next(t for t in tasks if t["id"] == task_id)
            self.assertEqual("assigned", recovered["status"])

            # === CORE-05: Targeted event ===
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.milestone",
                source="codex",
                payload={"step": "core-05"},
                audience=["claude_code"],
            )

            cc_poll = orch.poll_events(agent="claude_code", cursor=0, limit=100, auto_advance=False)
            cc_hits = [e for e in cc_poll["events"] if e.get("type") == "test.milestone"]
            self.assertGreaterEqual(len(cc_hits), 1)

            gm_poll = orch.poll_events(agent="gemini", cursor=0, limit=100, auto_advance=False)
            gm_hits = [e for e in gm_poll["events"] if e.get("type") == "test.milestone"]
            self.assertEqual(0, len(gm_hits))

            # === CORE-06: Recovery diagnostic verification ===
            # Re-claim and expire again for diagnostic check
            _heartbeat(orch, "claude_code", session_id="sess-cc")
            reclaimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(reclaimed)
            _expire_lease(orch, task_id)

            orch.bus.events_path.write_text("", encoding="utf-8")
            _heartbeat(orch, "claude_code", session_id="sess-cc")

            diag_result = orch.recover_expired_task_leases(source="codex")
            self.assertEqual(1, diag_result["recovered_count"])
            detail = diag_result["recovered"][0]
            self.assertEqual(task_id, detail["task_id"])
            self.assertEqual("lease_expired", detail["reason"])

            events = list(orch.bus.iter_events())
            recovery_events = [
                e for e in events
                if e.get("type") in {
                    "task.requeued_lease_expired",
                    "task.reassigned_lease_expired",
                }
            ]
            self.assertGreaterEqual(len(recovery_events), 1)


if __name__ == "__main__":
    unittest.main()
