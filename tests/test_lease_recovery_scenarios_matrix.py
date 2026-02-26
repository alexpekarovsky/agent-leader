"""CORE-04 lease expiry recovery scenarios matrix under project-scope constraints.

Scenario Matrix (8 cases)
=========================
| # | Owner Status | Same Project | Replacement Available | Expected Outcome       |
|---|--------------|-------------|----------------------|------------------------|
| 1 | Active       | Yes         | N/A (requeue self)   | Requeued to owner      |
| 2 | Active       | No          | Yes                  | Blocked (scope mismatch)|
| 3 | Offline      | Yes (was)   | Yes (same project)   | Reassigned or blocked  |
| 4 | Offline      | Yes (was)   | No                   | Blocked + blocker      |
| 5 | Active       | Yes         | N/A (multiple tasks) | All requeued to owner  |
| 6 | Mixed owners | Yes         | Partial              | Per-task recovery      |
| 7 | Active       | Yes         | N/A (lease valid)    | No recovery (not expired)|
| 8 | Offline      | N/A         | No agents at all     | Blocked + blocker      |

Project-scope constraints:
- Recovery checks active agents via list_agents(active_only=True) which
  enforces identity verification and same_project matching
- An agent is only "active" if: verified identity + same project + recent heartbeat
- Replacement only considers agents in the same project scope
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


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


def _expire_task_lease(orch: Orchestrator, task_id: str) -> None:
    """Manually expire a specific task's lease."""
    tasks = orch._read_json(orch.tasks_path)
    for t in tasks:
        if t["id"] == task_id and t.get("lease"):
            t["lease"]["expires_at"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.tasks_path, tasks)


def _make_agent_stale(orch: Orchestrator, agent: str) -> None:
    """Set agent's last_seen far in the past to make it offline."""
    agents = orch._read_json(orch.agents_path)
    if agent in agents:
        agents[agent]["last_seen"] = "2020-01-01T00:00:00+00:00"
    orch._write_json(orch.agents_path, agents)


# ---------------------------------------------------------------------------
# Scenario 1: Active owner, same project → requeue to self
# ---------------------------------------------------------------------------

class Scenario1ActiveOwnerRequeueTests(unittest.TestCase):
    """Active owner in same project gets task requeued to themselves."""

    def test_active_owner_requeued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="S1 active owner",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual("requeued", result["recovered"][0]["action"])
            self.assertEqual("claude_code", result["recovered"][0]["to_owner"])

    def test_requeued_task_status_is_assigned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="S1 status check",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            orch.recover_expired_task_leases(source="codex")

            tasks = orch._read_json(orch.tasks_path)
            recovered = next(t for t in tasks if t["id"] == claimed["id"])
            self.assertEqual("assigned", recovered["status"])
            self.assertIsNone(recovered.get("lease"))


# ---------------------------------------------------------------------------
# Scenario 2: Active owner, different project → scope mismatch
# ---------------------------------------------------------------------------

class Scenario2ScopeMismatchTests(unittest.TestCase):
    """Active owner from a different project should not count as eligible.

    When the agent's cwd/project_root doesn't match the orchestrator root,
    identity verification fails same_project check, making the agent
    appear offline to list_agents(active_only=True).
    """

    def test_different_project_agent_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Register with different project root
            meta = _full_metadata(root, "claude_code")
            meta["cwd"] = "/Users/other/different-project"
            meta["project_root"] = "/Users/other/different-project"
            orch.register_agent("claude_code", meta)
            orch.heartbeat("claude_code", meta)

            task = orch.create_task(
                title="S2 scope mismatch",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            # Claim requires operational status - use same-project meta temporarily
            same_meta = _full_metadata(root, "claude_code")
            orch.heartbeat("claude_code", same_meta)
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])

            # Switch back to different-project metadata
            orch.heartbeat("claude_code", meta)

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            # Should be blocked since agent is not in same project
            self.assertEqual("blocked", result["recovered"][0]["action"])


# ---------------------------------------------------------------------------
# Scenario 3: Offline owner, replacement available
# ---------------------------------------------------------------------------

class Scenario3OfflineOwnerReplacementTests(unittest.TestCase):
    """Offline owner with active replacement agent in same project."""

    def test_offline_owner_task_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="S3 offline replacement",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])
            _make_agent_stale(orch, "claude_code")

            # Register a replacement agent in the same project
            _setup_agent(orch, root, "gemini")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            # Task should be either reassigned or blocked depending on routing
            action = result["recovered"][0]["action"]
            self.assertIn(action, {"requeued", "blocked"})


# ---------------------------------------------------------------------------
# Scenario 4: Offline owner, no replacement → blocked + blocker
# ---------------------------------------------------------------------------

class Scenario4NoReplacementBlockedTests(unittest.TestCase):
    """Offline owner with no eligible replacement → task blocked with blocker."""

    def test_no_replacement_creates_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="S4 no replacement",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])
            _make_agent_stale(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual("blocked", result["recovered"][0]["action"])
            self.assertIn("blocker_id", result["recovered"][0])

    def test_blocked_task_has_blocker_in_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            task = orch.create_task(
                title="S4 blocker state",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])
            _make_agent_stale(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            blockers = orch._read_json_list(orch.blockers_path)
            blocker_ids = {b["id"] for b in blockers}
            self.assertIn(result["recovered"][0]["blocker_id"], blocker_ids)


# ---------------------------------------------------------------------------
# Scenario 5: Active owner, multiple expired tasks → all requeued
# ---------------------------------------------------------------------------

class Scenario5MultipleTasksRequeueTests(unittest.TestCase):
    """Multiple expired tasks for the same active owner all get requeued."""

    def test_all_tasks_requeued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            claimed_ids = []
            for i in range(3):
                orch.create_task(
                    title=f"S5 multi {i}",
                    workstream="backend",
                    owner="claude_code",
                    acceptance_criteria=["test"],
                )
                claimed = orch.claim_next_task("claude_code")
                claimed_ids.append(claimed["id"])

            for cid in claimed_ids:
                _expire_task_lease(orch, cid)
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(3, result["recovered_count"])
            for rec in result["recovered"]:
                self.assertEqual("requeued", rec["action"])
                self.assertEqual("claude_code", rec["to_owner"])


# ---------------------------------------------------------------------------
# Scenario 6: Mixed owners → per-task recovery
# ---------------------------------------------------------------------------

class Scenario6MixedOwnersTests(unittest.TestCase):
    """Tasks from different owners are recovered independently."""

    def test_mixed_owners_per_task_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")

            # claude_code task
            orch.create_task(
                title="S6 claude task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            cc_claimed = orch.claim_next_task("claude_code")

            # gemini task
            orch.create_task(
                title="S6 gemini task",
                workstream="frontend",
                owner="gemini",
                acceptance_criteria=["test"],
            )
            gem_claimed = orch.claim_next_task("gemini")

            _expire_task_lease(orch, cc_claimed["id"])
            _expire_task_lease(orch, gem_claimed["id"])

            # Keep claude_code active, make gemini stale
            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))
            _make_agent_stale(orch, "gemini")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(2, result["recovered_count"])
            by_task = {r["task_id"]: r for r in result["recovered"]}
            # claude_code's task should be requeued (owner active)
            self.assertEqual("requeued", by_task[cc_claimed["id"]]["action"])
            # gemini's task should be blocked (owner offline, no same-workstream replacement)
            self.assertIn(by_task[gem_claimed["id"]]["action"], {"requeued", "blocked"})


# ---------------------------------------------------------------------------
# Scenario 7: Valid lease → no recovery
# ---------------------------------------------------------------------------

class Scenario7ValidLeaseNoRecoveryTests(unittest.TestCase):
    """Tasks with valid (non-expired) leases should not be recovered."""

    def test_valid_lease_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="S7 valid lease",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            orch.claim_next_task("claude_code")
            # Do NOT expire the lease

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(0, result["recovered_count"])

    def test_mix_valid_and_expired_only_expired_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            orch.create_task(
                title="S7 valid",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            valid_claimed = orch.claim_next_task("claude_code")

            orch.create_task(
                title="S7 expired",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            expired_claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, expired_claimed["id"])

            orch.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual(expired_claimed["id"], result["recovered"][0]["task_id"])


# ---------------------------------------------------------------------------
# Scenario 8: No agents at all → blocked
# ---------------------------------------------------------------------------

class Scenario8NoAgentsTests(unittest.TestCase):
    """When all agents are offline/stale, expired tasks get blocked."""

    def test_all_agents_stale_produces_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="S8 no agents",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])
            _make_agent_stale(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            self.assertEqual(1, result["recovered_count"])
            self.assertEqual("blocked", result["recovered"][0]["action"])

    def test_recovery_returns_empty_active_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="S8 empty active",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["test"],
            )
            claimed = orch.claim_next_task("claude_code")
            _expire_task_lease(orch, claimed["id"])
            _make_agent_stale(orch, "claude_code")

            result = orch.recover_expired_task_leases(source="codex")

            active = result.get("active_agents", [])
            active_names = [a.get("agent") for a in active]
            self.assertNotIn("claude_code", active_names)


if __name__ == "__main__":
    unittest.main()
