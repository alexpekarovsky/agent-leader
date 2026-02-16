from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.bus import EventBus
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


class EventBusReliabilityTests(unittest.TestCase):
    def test_iter_events_skips_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bus"
            bus = EventBus(root)
            bus.emit("ok.event", {"x": 1}, source="tester")
            with bus.events_path.open("a", encoding="utf-8") as fh:
                fh.write("{this is malformed json\n")
                fh.write("\n")
            bus.emit("ok.event2", {"x": 2}, source="tester")

            events = list(bus.iter_events())
            self.assertEqual(2, len(events))
            self.assertEqual("ok.event", events[0]["type"])
            self.assertEqual("ok.event2", events[1]["type"])


class ListAgentsSideEffectTests(unittest.TestCase):
    def test_list_agents_default_does_not_emit_stale_notice_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            # Reset emitted bootstrap event so this test checks list_agents side effects only.
            orch.bus.events_path.write_text("", encoding="utf-8")

            orch.register_agent(
                "gemini",
                {
                    "client": "gemini-cli",
                    "model": "gemini-2.5-pro",
                    "cwd": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "default",
                    "session_id": "sess-1",
                    "connection_id": "conn-1",
                    "server_version": "0.1.0",
                    "verification_source": "test",
                },
            )
            # Force offline without invoking stale notice emission.
            agents = orch._read_json(orch.agents_path)
            agents["gemini"]["last_seen"] = "2000-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)
            orch.bus.events_path.write_text("", encoding="utf-8")

            listed = orch.list_agents(active_only=False)
            self.assertTrue(any(a.get("agent") == "gemini" for a in listed))
            self.assertEqual([], list(orch.bus.iter_events()))


class TaskStatusGuardTests(unittest.TestCase):
    def test_non_manager_cannot_set_done_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = orch.create_task(
                title="Guarded completion",
                workstream="backend",
                acceptance_criteria=["Use submit_report"],
            )

            with self.assertRaises(ValueError):
                orch.set_task_status(task_id=task["id"], status="done", source="claude_code")

    def test_manager_can_set_done_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = orch.create_task(
                title="Manager override",
                workstream="backend",
                acceptance_criteria=["Manager can override"],
            )

            updated = orch.set_task_status(task_id=task["id"], status="done", source="codex")
            self.assertEqual("done", updated.get("status"))

    def test_non_owner_non_leader_cannot_change_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = orch.create_task(
                title="Status auth",
                workstream="backend",
                acceptance_criteria=["owner/leader only"],
                owner="claude_code",
            )
            with self.assertRaises(ValueError):
                orch.set_task_status(task_id=task["id"], status="blocked", source="gemini")


class ConnectBehaviorTests(unittest.TestCase):
    def test_manager_connect_does_not_auto_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.create_task(
                title="Manager should not auto-claim",
                workstream="default",
                acceptance_criteria=["Remain assigned"],
                owner="codex",
            )

            result = orch.connect_to_leader(
                agent="codex",
                metadata={
                    "role": "manager",
                    "client": "codex-cli",
                    "model": "gpt-5",
                    "cwd": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "workspace-write",
                    "session_id": "manager-test",
                    "connection_id": "manager-conn-test",
                    "server_version": "0.1.0",
                    "verification_source": "test",
                },
                source="codex",
            )

            self.assertTrue(result.get("connected"))
            self.assertIsNone(result.get("auto_claimed_task"))
            assigned = orch.list_tasks_for_owner("codex")
            self.assertEqual("assigned", assigned[0].get("status"))

    def test_manager_connect_as_team_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            result = orch.connect_to_leader(
                agent="codex",
                metadata={
                    "role": "team_member",
                    "client": "codex-cli",
                    "model": "gpt-5",
                    "cwd": str(root),
                    "project_root": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "workspace-write",
                    "session_id": "manager-bad-role",
                    "connection_id": "manager-bad-role-conn",
                    "server_version": "0.1.0",
                    "verification_source": "test",
                },
                source="codex",
            )

            self.assertFalse(result.get("connected"))
            self.assertEqual("manager_role_mismatch", result.get("reason"))

    def test_connect_rejects_cwd_outside_project_even_if_project_root_claims_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as outside:
                root = Path(tmp)
                policy = _make_policy(root / "policy.json")
                orch = Orchestrator(root=root, policy=policy)
                orch.bootstrap()

                result = orch.connect_to_leader(
                    agent="gemini",
                    metadata={
                        "role": "team_member",
                        "client": "gemini-cli",
                        "model": "gemini-cli",
                        "cwd": outside,
                        "project_root": str(root),
                        "permissions_mode": "default",
                        "sandbox_mode": "workspace-write",
                        "session_id": "outside-cwd",
                        "connection_id": "outside-cwd-conn",
                        "server_version": "0.1.0",
                        "verification_source": "test",
                    },
                    source="gemini",
                )

                self.assertFalse(result.get("connected"))
                self.assertFalse(bool(result.get("identity", {}).get("same_project")))
                self.assertEqual("project_mismatch", result.get("reason"))

    def test_connect_team_members_rejects_non_leader_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.set_role(agent="claude_code", role="leader", source="codex")

            with self.assertRaises(ValueError):
                orch.connect_team_members(source="codex", team_members=["gemini"], timeout_seconds=1)

    def test_connect_to_leader_requires_explicit_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            result = orch.connect_to_leader(
                agent="gemini",
                metadata={
                    "role": "team_member",
                    "model": "gemini-cli",
                    "permissions_mode": "default",
                    "sandbox_mode": "workspace-write",
                    "session_id": "sess",
                    "connection_id": "conn",
                },
                source="gemini",
            )

            self.assertFalse(result.get("connected"))
            self.assertFalse(result.get("verified"))
            self.assertIn("missing_identity_fields", str(result.get("reason")))


class RoleAuthorizationTests(unittest.TestCase):
    def test_set_role_rejects_non_leader_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            with self.assertRaises(ValueError):
                orch.set_role(agent="gemini", role="leader", source="gemini")

    def test_new_leader_can_manage_roles_after_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            orch.set_role(agent="claude_code", role="leader", source="codex")
            roles = orch.set_role(agent="codex", role="team_member", source="claude_code")
            self.assertEqual("claude_code", roles.get("leader"))
            self.assertIn("codex", roles.get("team_members", []))

    def test_set_claim_override_rejects_non_leader_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = orch.create_task(
                title="Override auth",
                workstream="backend",
                acceptance_criteria=["auth"],
                owner="claude_code",
            )
            with self.assertRaises(ValueError):
                orch.set_claim_override(agent="claude_code", task_id=task["id"], source="gemini")

    def test_validate_task_rejects_non_leader_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            task = orch.create_task(
                title="Validate auth",
                workstream="backend",
                acceptance_criteria=["auth"],
                owner="claude_code",
            )
            with self.assertRaises(ValueError):
                orch.validate_task(task_id=task["id"], passed=True, notes="x", source="claude_code")


class PresenceRefreshTests(unittest.TestCase):
    def test_refresh_agent_presence_preserves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.register_agent(
                "gemini",
                {
                    "client": "gemini-cli",
                    "model": "gemini-cli",
                    "cwd": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "default",
                    "session_id": "sess",
                    "connection_id": "conn",
                    "server_version": "0.1.0",
                    "verification_source": "test",
                },
            )

            before = orch._read_json(orch.agents_path)["gemini"]["metadata"]
            orch._refresh_agent_presence("gemini")
            after = orch._read_json(orch.agents_path)["gemini"]["metadata"]
            self.assertEqual(before, after)


class WorkflowReliabilityTests(unittest.TestCase):
    def _team_metadata(self, root: Path, client: str, model: str, role: str, sid: str, cid: str) -> dict:
        return {
            "role": role,
            "client": client,
            "model": model,
            "cwd": str(root),
            "project_root": str(root),
            "permissions_mode": "default",
            "sandbox_mode": "workspace-write",
            "session_id": sid,
            "connection_id": cid,
            "server_version": "0.1.0",
            "verification_source": "test",
        }

    def test_core_flow_reliable_across_five_runs(self) -> None:
        for _ in range(5):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                policy = _make_policy(root / "policy.json")
                orch = Orchestrator(root=root, policy=policy)
                orch.bootstrap()

                # Leader connects with verified manager identity.
                leader = orch.connect_to_leader(
                    agent="codex",
                    metadata=self._team_metadata(root, "codex-cli", "gpt-5", "manager", "s0", "c0"),
                    source="codex",
                )
                self.assertTrue(leader.get("connected"))
                self.assertIsNone(leader.get("auto_claimed_task"))

                # Team members connect with full identity metadata.
                cc = orch.connect_to_leader(
                    agent="claude_code",
                    metadata=self._team_metadata(root, "claude-code", "claude-opus-4-6", "team_member", "s1", "c1"),
                    source="claude_code",
                )
                gm = orch.connect_to_leader(
                    agent="gemini",
                    metadata=self._team_metadata(root, "gemini-cli", "gemini-cli", "team_member", "s2", "c2"),
                    source="gemini",
                )
                handshake = orch.connect_team_members(
                    source="codex",
                    team_members=["claude_code", "gemini"],
                    timeout_seconds=3,
                    poll_interval_seconds=1,
                )

                self.assertTrue(cc.get("connected"))
                self.assertTrue(gm.get("connected"))
                self.assertEqual("connected", handshake["status"])

                # Assigned tasks are auto-claimed on reconnect for team members.
                t1 = orch.create_task("BE task", "backend", ["done"], owner="claude_code")
                t2 = orch.create_task("FE task", "frontend", ["done"], owner="gemini")
                cc_claim = orch.connect_to_leader(
                    agent="claude_code",
                    metadata=self._team_metadata(root, "claude-code", "claude-opus-4-6", "team_member", "s3", "c3"),
                    source="claude_code",
                )
                gm_claim = orch.connect_to_leader(
                    agent="gemini",
                    metadata=self._team_metadata(root, "gemini-cli", "gemini-cli", "team_member", "s4", "c4"),
                    source="gemini",
                )
                self.assertEqual(t1["id"], (cc_claim.get("auto_claimed_task") or {}).get("id"))
                self.assertEqual(t2["id"], (gm_claim.get("auto_claimed_task") or {}).get("id"))


if __name__ == "__main__":
    unittest.main()
