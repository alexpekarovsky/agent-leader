from __future__ import annotations

import json
import multiprocessing
import os
import stat
import subprocess
import tempfile
import time
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


def _team_metadata(root: Path, client: str, model: str, role: str, sid: str, cid: str) -> dict:
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


def _worker_complete_tasks(root_str: str, policy_path_str: str, agent: str) -> None:
    root = Path(root_str)
    policy = Policy.load(Path(policy_path_str))
    orch = Orchestrator(root=root, policy=policy)
    result = orch.connect_to_leader(
        agent=agent,
        metadata=_team_metadata(
            root=root,
            client=f"{agent}-cli",
            model=agent,
            role="team_member",
            sid=f"{agent}-sid",
            cid=f"{agent}-cid",
        ),
        source=agent,
    )
    auto_claimed = result.get("auto_claimed_task")
    if isinstance(auto_claimed, dict) and auto_claimed.get("id"):
        orch.ingest_report(
            {
                "task_id": auto_claimed["id"],
                "agent": agent,
                "commit_sha": "deadbeef",
                "status": "done",
                "test_summary": {"command": "pytest -q", "passed": 1, "failed": 0},
            }
        )

    while True:
        # Simulate normal long-poll heartbeat loop before claiming.
        orch.poll_events(agent=agent, timeout_ms=10)
        task = orch.claim_next_task(owner=agent)
        if not task:
            break
        orch.ingest_report(
            {
                "task_id": task["id"],
                "agent": agent,
                "commit_sha": "deadbeef",
                "status": "done",
                "test_summary": {"command": "pytest -q", "passed": 1, "failed": 0},
            }
        )


def _manager_validate_until_done(root_str: str, policy_path_str: str, expected_done: int, timeout_s: float = 15.0) -> None:
    root = Path(root_str)
    policy = Policy.load(Path(policy_path_str))
    orch = Orchestrator(root=root, policy=policy)
    start = time.time()
    while time.time() - start < timeout_s:
        tasks = orch.list_tasks()
        for task in tasks:
            if task.get("status") == "reported":
                orch.validate_task(task_id=task["id"], passed=True, notes="ok", source="codex")
        done_count = sum(1 for task in orch.list_tasks() if task.get("status") == "done")
        if done_count >= expected_done:
            return
        time.sleep(0.02)
    raise TimeoutError(f"manager validation timeout; expected done={expected_done}")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_sleeping_cli_stub(bin_dir: Path, name: str, sleep_seconds: int = 5) -> None:
    _write_executable(bin_dir / name, f"#!/usr/bin/env bash\nsleep {sleep_seconds}\n")


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

    def test_iter_events_from_returns_offsets_from_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(Path(tmp) / "bus")
            for i in range(40):
                bus.emit("evt", {"idx": i}, source="tester")

            items = list(bus.iter_events_from(start=30))
            self.assertEqual(10, len(items))
            self.assertEqual(30, items[0][0])
            self.assertEqual(39, items[-1][0])
            self.assertEqual(30, items[0][1]["payload"]["idx"])
            self.assertEqual(39, items[-1][1]["payload"]["idx"])

    def test_read_audit_limit_returns_tail_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus(Path(tmp) / "bus")
            for i in range(120):
                bus.append_audit({"tool": "orchestrator_poll_events", "status": "ok", "n": i})

            rows = list(bus.read_audit(limit=7))
            self.assertEqual(7, len(rows))
            self.assertEqual(113, rows[0]["n"])
            self.assertEqual(119, rows[-1]["n"])


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

    def test_cross_project_agent_cannot_claim_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with tempfile.TemporaryDirectory() as outside:
                root = Path(tmp)
                policy = _make_policy(root / "policy.json")
                orch = Orchestrator(root=root, policy=policy)
                orch.bootstrap()
                orch.create_task(
                    title="Cross-project guard",
                    workstream="frontend",
                    acceptance_criteria=["guarded"],
                    owner="gemini",
                )
                # Register heartbeat metadata from a different project root.
                orch.connect_to_leader(
                    agent="gemini",
                    metadata={
                        "role": "team_member",
                        "client": "gemini-cli",
                        "model": "gemini",
                        "cwd": outside,
                        "project_root": outside,
                        "permissions_mode": "default",
                        "sandbox_mode": "workspace-write",
                        "session_id": "sid-outside",
                        "connection_id": "cid-outside",
                        "server_version": "0.1.0",
                        "verification_source": "test",
                    },
                    source="gemini",
                )
                with self.assertRaises(ValueError):
                    orch.claim_next_task(owner="gemini")

    def test_same_project_agent_can_resume_claim_after_stale_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_team_metadata(
                    root=root,
                    client="claude-code",
                    model="claude-opus-4-6",
                    role="team_member",
                    sid="sid-stale",
                    cid="cid-stale",
                ),
                source="claude_code",
            )
            orch.create_task(
                title="Resume after stale",
                workstream="backend",
                acceptance_criteria=["guarded"],
                owner="claude_code",
            )
            # Force stale timestamp to emulate long outage.
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2000-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            claimed = orch.claim_next_task(owner="claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])


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

    def test_register_agent_derives_instance_id_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            entry = orch.register_agent(
                "gemini",
                {
                    "client": "gemini-cli",
                    "model": "gemini-2.5",
                    "cwd": str(root),
                    "session_id": "sess-x",
                },
            )
            self.assertEqual("sess-x", entry.get("metadata", {}).get("instance_id"))

    def test_connect_to_leader_preserves_explicit_instance_id_and_identity_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            result = orch.connect_to_leader(
                agent="claude_code",
                metadata={
                    **_team_metadata(root, "claude-code", "claude-opus", "team_member", "sid-cc", "cid-cc"),
                    "instance_id": "claude_code#worker-02",
                },
                source="claude_code",
            )
            self.assertTrue(result.get("connected"))
            self.assertEqual("claude_code#worker-02", result.get("identity", {}).get("instance_id"))
            agents = orch.list_agents(active_only=False)
            claude = next(item for item in agents if item.get("agent") == "claude_code")
            self.assertEqual("claude_code#worker-02", claude.get("instance_id"))


class WorkflowReliabilityTests(unittest.TestCase):
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
                    metadata=_team_metadata(root, "codex-cli", "gpt-5", "manager", "s0", "c0"),
                    source="codex",
                )
                self.assertTrue(leader.get("connected"))
                self.assertIsNone(leader.get("auto_claimed_task"))

                # Team members connect with full identity metadata.
                cc = orch.connect_to_leader(
                    agent="claude_code",
                    metadata=_team_metadata(root, "claude-code", "claude-opus-4-6", "team_member", "s1", "c1"),
                    source="claude_code",
                )
                gm = orch.connect_to_leader(
                    agent="gemini",
                    metadata=_team_metadata(root, "gemini-cli", "gemini-cli", "team_member", "s2", "c2"),
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
                    metadata=_team_metadata(root, "claude-code", "claude-opus-4-6", "team_member", "s3", "c3"),
                    source="claude_code",
                )
                gm_claim = orch.connect_to_leader(
                    agent="gemini",
                    metadata=_team_metadata(root, "gemini-cli", "gemini-cli", "team_member", "s4", "c4"),
                    source="gemini",
                )
                self.assertEqual(t1["id"], (cc_claim.get("auto_claimed_task") or {}).get("id"))
                self.assertEqual(t2["id"], (gm_claim.get("auto_claimed_task") or {}).get("id"))

    def test_multi_process_manager_and_two_workers_complete_all_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_path = root / "policy.json"
            policy = _make_policy(policy_path)
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.connect_to_leader(
                agent="codex",
                metadata=_team_metadata(root, "codex-cli", "gpt-5", "manager", "m-sid", "m-cid"),
                source="codex",
            )
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_team_metadata(root, "claude-code", "claude-opus-4-6", "team_member", "c-sid", "c-cid"),
                source="claude_code",
            )
            orch.connect_to_leader(
                agent="gemini",
                metadata=_team_metadata(root, "gemini-cli", "gemini-cli", "team_member", "g-sid", "g-cid"),
                source="gemini",
            )
            orch.connect_team_members(
                source="codex",
                team_members=["claude_code", "gemini"],
                timeout_seconds=2,
                poll_interval_seconds=1,
            )

            total_tasks = 24
            for idx in range(total_tasks):
                owner = "claude_code" if idx % 2 == 0 else "gemini"
                orch.create_task(
                    title=f"stress-{idx}",
                    workstream="backend" if owner == "claude_code" else "frontend",
                    acceptance_criteria=["done"],
                    owner=owner,
                )

            manager = multiprocessing.Process(
                target=_manager_validate_until_done,
                args=(str(root), str(policy_path), total_tasks, 20.0),
            )
            cc_worker = multiprocessing.Process(
                target=_worker_complete_tasks,
                args=(str(root), str(policy_path), "claude_code"),
            )
            gm_worker = multiprocessing.Process(
                target=_worker_complete_tasks,
                args=(str(root), str(policy_path), "gemini"),
            )
            manager.start()
            cc_worker.start()
            gm_worker.start()
            manager.join(25)
            cc_worker.join(25)
            gm_worker.join(25)

            self.assertFalse(manager.is_alive(), "manager process did not finish")
            self.assertFalse(cc_worker.is_alive(), "claude_code worker did not finish")
            self.assertFalse(gm_worker.is_alive(), "gemini worker did not finish")
            self.assertEqual(0, manager.exitcode)
            self.assertEqual(0, cc_worker.exitcode)
            self.assertEqual(0, gm_worker.exitcode)

            final_tasks = orch.list_tasks()
            done_count = sum(1 for task in final_tasks if task.get("status") == "done")
            self.assertEqual(total_tasks, done_count)
            self.assertFalse(
                any(task.get("status") in {"assigned", "in_progress", "reported"} for task in final_tasks),
                "all tasks should reach done",
            )

    def test_report_retry_queue_recovers_after_initial_submission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_team_metadata(root, "claude-code", "claude-opus-4-6", "team_member", "sid-1", "cid-1"),
                source="claude_code",
            )
            task = orch.create_task(
                title="Retry queue task",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
            )
            # Claim the task so report ownership/status is valid once retry runs.
            orch.claim_next_task(owner="claude_code")

            report = {
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest -q", "passed": 1, "failed": 0},
            }
            queued = orch.enqueue_report_retry(report=report, error="temporary transport failure")
            self.assertEqual("pending", queued["status"])

            result = orch.process_report_retry_queue(
                max_attempts=3,
                base_backoff_seconds=1,
                max_backoff_seconds=2,
                limit=5,
            )
            self.assertGreaterEqual(len(result["processed"]), 1)
            self.assertGreaterEqual(result["submitted"], 1)
            task_after = next(t for t in orch.list_tasks() if t["id"] == task["id"])
            self.assertEqual("reported", task_after["status"])


class AutopilotTimeoutBehaviorTests(unittest.TestCase):
    def test_run_cli_prompt_timeout_writes_marker_and_returns_124(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _make_sleeping_cli_stub(bin_dir, "codex", sleep_seconds=5)
            prompt_file = tmp_path / "prompt.txt"
            out_file = tmp_path / "out.log"
            prompt_file.write_text("test prompt\n", encoding="utf-8")

            cmd = (
                f"source '{repo_root / 'scripts/autopilot/common.sh'}' && "
                f"run_cli_prompt codex '{tmp_path}' '{prompt_file}' '{out_file}' 1"
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            start = time.time()
            proc = subprocess.run(
                ["bash", "-lc", cmd],
                cwd=repo_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            elapsed = time.time() - start

            self.assertEqual(124, proc.returncode)
            self.assertLess(elapsed, 4.0)
            self.assertTrue(out_file.exists())
            self.assertIn("[AUTOPILOT] CLI timeout after 1s for codex", out_file.read_text(encoding="utf-8"))

    def test_manager_loop_timeout_creates_log_file_with_marker(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            logs_dir = tmp_path / "logs"
            bin_dir.mkdir()
            logs_dir.mkdir()
            _make_sleeping_cli_stub(bin_dir, "codex", sleep_seconds=5)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            proc = subprocess.run(
                [
                    "bash",
                    "scripts/autopilot/manager_loop.sh",
                    "--once",
                    "--project-root",
                    str(repo_root),
                    "--log-dir",
                    str(logs_dir),
                    "--cli-timeout",
                    "1",
                ],
                cwd=repo_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )

            self.assertEqual(0, proc.returncode)
            self.assertIn("manager cycle timed out after 1s", proc.stderr)
            logs = list(logs_dir.glob("manager-codex-*.log"))
            self.assertEqual(1, len(logs))
            self.assertIn("[AUTOPILOT] CLI timeout after 1s for codex", logs[0].read_text(encoding="utf-8"))

    def test_worker_loop_timeout_creates_log_file_with_marker(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            logs_dir = tmp_path / "logs"
            bin_dir.mkdir()
            logs_dir.mkdir()
            _make_sleeping_cli_stub(bin_dir, "claude", sleep_seconds=5)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            proc = subprocess.run(
                [
                    "bash",
                    "scripts/autopilot/worker_loop.sh",
                    "--once",
                    "--cli",
                    "claude",
                    "--agent",
                    "claude_code",
                    "--project-root",
                    str(repo_root),
                    "--log-dir",
                    str(logs_dir),
                    "--cli-timeout",
                    "1",
                ],
                cwd=repo_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )

            self.assertEqual(0, proc.returncode)
            self.assertIn("worker cycle timed out agent=claude_code after 1s", proc.stderr)
            logs = list(logs_dir.glob("worker-claude_code-claude-*.log"))
            self.assertEqual(1, len(logs))
            self.assertIn("[AUTOPILOT] CLI timeout after 1s for claude", logs[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
