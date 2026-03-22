"""Consolidated task lifecycle tests.

Covers: create, claim, heartbeat, report, validate, dedupe, requeue,
auto-cycle, task-count guard, multi-project tags, and event ordering.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ── shared helpers ──────────────────────────────────────────────────────

def _make_policy(path: Path, **trigger_overrides) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini",
                     "qa": "codex", "default": "codex"},
        "decisions": {"architecture": {
            "mode": "consensus",
            "members": ["codex", "claude_code", "gemini"],
        }},
        "triggers": {"heartbeat_timeout_minutes": 10, **trigger_overrides},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, **trigger_overrides) -> Orchestrator:
    policy = _make_policy(root / "policy.json", **trigger_overrides)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _reg(orch: Orchestrator, agent: str, **extra) -> None:
    meta = {
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}", "connection_id": f"cid-{agent}",
        "server_version": "1.0", "verification_source": "test",
        **extra,
    }
    orch.register_agent(agent, meta)


def _report(orch: Orchestrator, task_id: str, agent: str = "claude_code",
            sha: str = "abc123", passed: int = 1, failed: int = 0) -> dict:
    return orch.ingest_report({
        "task_id": task_id, "agent": agent, "commit_sha": sha,
        "status": "done",
        "test_summary": {"command": "pytest", "passed": passed, "failed": failed},
    })


def _get(orch: Orchestrator, task_id: str) -> dict:
    return next(t for t in orch.list_tasks() if t["id"] == task_id)


def _inject_dup(orch: Orchestrator, title: str, workstream: str,
                owner: str) -> str:
    tid = f"TASK-{uuid.uuid4().hex[:8]}"
    tasks = orch._read_json(orch.tasks_path)
    tasks.append({
        "id": tid, "title": title, "workstream": workstream,
        "owner": owner, "status": "assigned",
        "created_at": orch._now(), "updated_at": orch._now(),
    })
    orch._write_json(orch.tasks_path, tasks)
    return tid


def _make_agent_stale(orch: Orchestrator, agent: str,
                      age: timedelta = timedelta(hours=1)) -> None:
    agents = orch._read_json(orch.agents_path)
    agents[agent]["last_seen"] = (
        datetime.now(timezone.utc) - age
    ).isoformat()
    orch._write_json(orch.agents_path, agents)


class _OrchestratorMixin:
    """Common setUp / tearDown for most test classes."""

    def _init_orch(self, **trigger_overrides) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root, **trigger_overrides)
        _reg(self.orch, "claude_code")

    def _cleanup(self) -> None:
        self._tmp.cleanup()


# ── core lifecycle ──────────────────────────────────────────────────────

class TestLifecycle(unittest.TestCase, _OrchestratorMixin):
    def setUp(self) -> None:
        self._init_orch()

    def tearDown(self) -> None:
        self._cleanup()

    def test_happy_path(self) -> None:
        task = self.orch.create_task(
            title="Lifecycle", workstream="backend",
            acceptance_criteria=["A", "B"], description="test")
        tid = task["id"]
        self.assertEqual(task["status"], "assigned")

        claimed = self.orch.claim_next_task(owner="claude_code")
        self.assertEqual(claimed["id"], tid)
        self.assertEqual(_get(self.orch, tid)["status"], "in_progress")

        hb = self.orch.heartbeat(agent="claude_code")
        self.assertEqual(hb["status"], "active")

        _report(self.orch, tid)
        self.assertEqual(_get(self.orch, tid)["status"], "reported")

        self.orch.validate_task(task_id=tid, passed=True,
                                notes="OK", source="codex")
        self.assertEqual(_get(self.orch, tid)["status"], "done")

    def test_validation_failure_opens_bug(self) -> None:
        task = self.orch.create_task(
            title="Fail-val", workstream="backend",
            acceptance_criteria=["Must pass"])
        tid = task["id"]
        self.orch.claim_next_task(owner="claude_code")
        _report(self.orch, tid, failed=1, passed=0)

        result = self.orch.validate_task(
            task_id=tid, passed=False, notes="Nope", source="codex")
        self.assertIn("bug_id", result)
        self.assertEqual(_get(self.orch, tid)["status"], "bug_open")

        bugs = self.orch.list_bugs()
        bug = next(b for b in bugs if b.get("source_task") == tid)
        self.assertEqual("open", bug["status"])

    def test_blocked_then_resolved(self) -> None:
        task = self.orch.create_task(
            title="Blocker", workstream="backend",
            acceptance_criteria=["done"], owner="claude_code")
        tid = task["id"]
        self.orch.claim_next_task("claude_code")

        blocker = self.orch.raise_blocker(tid, "claude_code", "Need spec")
        self.assertEqual(_get(self.orch, tid)["status"], "blocked")

        self.orch.heartbeat("claude_code", metadata={
            "client": "c", "model": "m", "cwd": str(self.root),
            "project_root": str(self.root), "permissions_mode": "default",
            "sandbox_mode": "workspace-write", "session_id": "s",
            "connection_id": "c", "server_version": "1.0",
            "verification_source": "test",
        })
        self.orch.resolve_blocker(blocker["id"], "Done", "codex")
        self.assertIn(_get(self.orch, tid)["status"],
                      ("in_progress", "assigned"))

    def test_claim_none_when_empty(self) -> None:
        self.assertIsNone(self.orch.claim_next_task(owner="claude_code"))

    def test_double_claim_returns_none(self) -> None:
        self.orch.create_task(title="One", workstream="backend",
                              acceptance_criteria=["done"])
        self.assertIsNotNone(self.orch.claim_next_task(owner="claude_code"))
        self.assertIsNone(self.orch.claim_next_task(owner="claude_code"))

    def test_report_wrong_agent_rejected(self) -> None:
        _reg(self.orch, "gemini")
        task = self.orch.create_task(
            title="Owner-check", workstream="backend",
            acceptance_criteria=["done"])
        self.orch.claim_next_task(owner="claude_code")
        with self.assertRaises(ValueError) as ctx:
            _report(self.orch, task["id"], agent="gemini")
        self.assertIn("does not match", str(ctx.exception))

    def test_validate_non_leader_rejected(self) -> None:
        task = self.orch.create_task(
            title="Leader-check", workstream="backend",
            acceptance_criteria=["done"])
        self.orch.claim_next_task(owner="claude_code")
        _report(self.orch, task["id"])
        with self.assertRaises(ValueError) as ctx:
            self.orch.validate_task(task_id=task["id"], passed=True,
                                    notes="x", source="claude_code")
        self.assertIn("leader_mismatch", str(ctx.exception))

    def test_report_missing_fields_rejected(self) -> None:
        task = self.orch.create_task(
            title="Missing", workstream="backend",
            acceptance_criteria=["A"])
        self.orch.claim_next_task(owner="claude_code")
        with self.assertRaises(ValueError) as ctx:
            self.orch.ingest_report({
                "task_id": task["id"], "agent": "claude_code"})
        self.assertIn("Missing report fields", str(ctx.exception))

    def test_multiple_tasks_sequential(self) -> None:
        ids = []
        for i in range(3):
            t = self.orch.create_task(
                title=f"Seq-{i}", workstream="backend",
                acceptance_criteria=["done"], owner="claude_code")
            ids.append(t["id"])
            self.orch.claim_next_task("claude_code")
            _report(self.orch, t["id"], sha=f"sha-{i}")
            self.orch.validate_task(t["id"], passed=True,
                                    notes="OK", source="codex")
        done = [t for t in self.orch.list_tasks() if t["status"] == "done"]
        self.assertGreaterEqual(len(done), 3)

    def test_updated_at_advances(self) -> None:
        task = self.orch.create_task(
            title="Timestamps", workstream="backend",
            acceptance_criteria=["A"])
        tid = task["id"]
        t0 = task["updated_at"]

        self.orch.claim_next_task(owner="claude_code")
        t1 = _get(self.orch, tid)["updated_at"]
        self.assertGreaterEqual(t1, t0)

        _report(self.orch, tid)
        t2 = _get(self.orch, tid)["updated_at"]
        self.assertGreaterEqual(t2, t1)

        self.orch.validate_task(tid, passed=True, notes="OK", source="codex")
        t3 = _get(self.orch, tid)["updated_at"]
        self.assertGreaterEqual(t3, t2)


# ── events ──────────────────────────────────────────────────────────────

class TestLifecycleEvents(unittest.TestCase, _OrchestratorMixin):
    def setUp(self) -> None:
        self._init_orch()

    def tearDown(self) -> None:
        self._cleanup()

    def _event_types(self):
        return [e["type"] for e in self.orch.bus.iter_events()]

    def test_events_order(self) -> None:
        task = self.orch.create_task(
            title="Events", workstream="backend",
            acceptance_criteria=["done"])
        tid = task["id"]
        self.orch.claim_next_task(owner="claude_code")
        self.orch.heartbeat(agent="claude_code")
        _report(self.orch, tid)
        self.orch.validate_task(tid, passed=True, notes="OK", source="codex")

        types = self._event_types()
        self.assertIn("task.assigned", types)
        self.assertIn("task.reported", types)
        self.assertIn("validation.passed", types)
        ai = next(i for i, t in enumerate(types) if t == "task.assigned")
        ri = next(i for i, t in enumerate(types) if t == "task.reported")
        pi = next(i for i, t in enumerate(types) if t == "validation.passed")
        self.assertLess(ai, ri)
        self.assertLess(ri, pi)

    def test_heartbeat_event(self) -> None:
        self.orch.heartbeat(agent="claude_code")
        hb = [e for e in self.orch.bus.iter_events()
              if e["type"] == "agent.heartbeat"]
        self.assertTrue(hb)
        self.assertEqual(hb[-1]["payload"]["agent"], "claude_code")

    def test_validation_failed_event(self) -> None:
        task = self.orch.create_task(
            title="FailEvt", workstream="backend",
            acceptance_criteria=["done"])
        self.orch.claim_next_task(owner="claude_code")
        _report(self.orch, task["id"], failed=1, passed=0)
        self.orch.validate_task(task["id"], passed=False,
                                notes="Bad", source="codex")
        fail = [e for e in self.orch.bus.iter_events()
                if e["type"] == "validation.failed"]
        self.assertTrue(fail)
        self.assertEqual(fail[-1]["payload"]["task_id"], task["id"])


# ── deduplication ───────────────────────────────────────────────────────

class TestDedupe(unittest.TestCase):
    def test_no_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            orch.create_task(title="A", workstream="backend",
                             owner="claude_code", acceptance_criteria=["x"])
            orch.create_task(title="B", workstream="backend",
                             owner="claude_code", acceptance_criteria=["x"])
            r = orch.dedupe_open_tasks(source="codex")
            self.assertEqual(0, r["deduped_count"])

    def test_duplicates_keeps_oldest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            t1 = orch.create_task(title="Same", workstream="backend",
                                  owner="claude_code",
                                  acceptance_criteria=["x"])
            dup = _inject_dup(orch, "Same", "backend", "claude_code")
            r = orch.dedupe_open_tasks(source="codex")
            self.assertEqual(1, r["deduped_count"])
            self.assertEqual("assigned", _get(orch, t1["id"])["status"])
            d = _get(orch, dup)
            self.assertEqual("duplicate_closed", d["status"])
            self.assertEqual(t1["id"], d["duplicate_of"])

    def test_diff_workstream_or_owner_not_dup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            orch.create_task(title="X", workstream="backend",
                             owner="claude_code", acceptance_criteria=["x"])
            orch.create_task(title="X", workstream="frontend",
                             owner="gemini", acceptance_criteria=["x"])
            self.assertEqual(0,
                             orch.dedupe_open_tasks(source="codex")["deduped_count"])

    def test_closed_tasks_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            t1 = orch.create_task(title="Same", workstream="backend",
                                  owner="claude_code",
                                  acceptance_criteria=["x"])
            tasks = orch._read_json(orch.tasks_path)
            for t in tasks:
                if t["id"] == t1["id"]:
                    t["status"] = "done"
            orch._write_json(orch.tasks_path, tasks)
            orch.create_task(title="Same", workstream="backend",
                             owner="claude_code", acceptance_criteria=["x"])
            self.assertEqual(0,
                             orch.dedupe_open_tasks(source="codex")["deduped_count"])

    def test_multiple_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            t1 = orch.create_task(title="Dup", workstream="backend",
                                  owner="claude_code",
                                  acceptance_criteria=["x"])
            d2 = _inject_dup(orch, "Dup", "backend", "claude_code")
            d3 = _inject_dup(orch, "Dup", "backend", "claude_code")
            r = orch.dedupe_open_tasks(source="codex")
            self.assertEqual(2, r["deduped_count"])
            st = {t["id"]: t["status"] for t in orch.list_tasks()}
            self.assertEqual("assigned", st[t1["id"]])
            self.assertEqual("duplicate_closed", st[d2])
            self.assertEqual("duplicate_closed", st[d3])


# ── requeue stale ───────────────────────────────────────────────────────

class TestRequeueStale(unittest.TestCase, _OrchestratorMixin):
    def setUp(self) -> None:
        self._init_orch()

    def tearDown(self) -> None:
        self._cleanup()

    def test_fresh_not_requeued(self) -> None:
        self.orch.create_task(title="Fresh", workstream="backend",
                              owner="claude_code", acceptance_criteria=["x"])
        self.orch.claim_next_task("claude_code")
        self.assertEqual(
            [], self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=1800))

    def test_stale_task_requeued_with_reason(self) -> None:
        task = self.orch.create_task(
            title="Stale", workstream="backend",
            owner="claude_code", acceptance_criteria=["x"])
        self.orch.claim_next_task("claude_code")
        _make_agent_stale(self.orch, "claude_code")

        rq = self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=60)
        self.assertEqual(1, len(rq))
        self.assertEqual(task["id"], rq[0]["task_id"])
        self.assertIn("stale", rq[0]["reason"])
        self.assertEqual("assigned",
                         _get(self.orch, task["id"])["status"])

    def test_assigned_not_requeued(self) -> None:
        self.orch.create_task(title="Asgn", workstream="backend",
                              owner="claude_code", acceptance_criteria=["x"])
        _make_agent_stale(self.orch, "claude_code")
        self.assertEqual(
            [], self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=60))

    def test_multiple_stale(self) -> None:
        t1 = self.orch.create_task(title="S1", workstream="backend",
                                   owner="claude_code",
                                   acceptance_criteria=["x"])
        t2 = self.orch.create_task(title="S2", workstream="backend",
                                   owner="claude_code",
                                   acceptance_criteria=["x"])
        self.orch.claim_next_task("claude_code")
        self.orch.claim_next_task("claude_code")
        _make_agent_stale(self.orch, "claude_code")

        rq = self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=60)
        self.assertEqual(2, len(rq))
        self.assertEqual({t1["id"], t2["id"]},
                         {r["task_id"] for r in rq})

    def test_threshold_respected(self) -> None:
        self.orch.create_task(title="Recent", workstream="backend",
                              owner="claude_code", acceptance_criteria=["x"])
        self.orch.claim_next_task("claude_code")
        _make_agent_stale(self.orch, "claude_code",
                          age=timedelta(seconds=30))
        self.assertEqual(
            [], self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=60))


# ── submit-report auto-cycle ───────────────────────────────────────────

class TestAutoManagerCycle(unittest.TestCase):
    def _mk(self, tmp, *, auto_validate: bool):
        root = Path(tmp)
        orch = _make_orch(root,
                          auto_validate_reports_on_submit=auto_validate)
        policy = Policy.load(root / "policy.json")
        root_s = str(root)
        orch.connect_to_leader(agent="codex", source="codex", metadata={
            "client": "codex-cli", "model": "gpt-5-codex",
            "cwd": root_s, "project_root": root_s,
            "permissions_mode": "default",
            "sandbox_mode": "workspace-write",
            "session_id": "s", "connection_id": "c",
            "instance_id": "codex#default",
            "server_version": "1.0", "verification_source": "codex",
            "role": "manager",
        })
        task = orch.create_task(
            title="AC", workstream="qa", owner="codex",
            acceptance_criteria=["done"])
        orch.claim_next_task(owner="codex", instance_id="codex#default")
        return orch, policy, task

    def _submit(self, orch, policy, **overrides):
        import orchestrator_mcp_server as mcp
        old_o, old_p = mcp.ORCH, mcp.POLICY
        try:
            mcp.ORCH, mcp.POLICY = orch, policy
            args = {
                "task_id": orch.list_tasks(
                    status="in_progress", owner="codex")[0]["id"],
                "agent": "codex", "commit_sha": "abc",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1,
                                 "failed": 0},
                "notes": "auto", **overrides,
            }
            resp = mcp.handle_tool_call("r", {
                "name": "orchestrator_submit_report",
                "arguments": args})
            return json.loads(resp["result"]["content"][0]["text"])
        finally:
            mcp.ORCH, mcp.POLICY = old_o, old_p

    def test_auto_cycle_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch, pol, task = self._mk(tmp, auto_validate=True)
            pay = self._submit(orch, pol)
            self.assertTrue(pay["auto_manager_cycle"]["enabled"])
            self.assertEqual("done", _get(orch, task["id"])["status"])

    def test_auto_cycle_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch, pol, task = self._mk(tmp, auto_validate=False)
            pay = self._submit(orch, pol)
            self.assertNotIn("auto_manager_cycle", pay)
            self.assertEqual("reported", _get(orch, task["id"])["status"])

    def test_auto_cycle_approved_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch, pol, task = self._mk(tmp, auto_validate=True)
            pay = self._submit(orch, pol,
                               status="needs_review",
                               review_gate={"required": True,
                                            "status": "approved",
                                            "reviewer_agent": "ccm"})
            self.assertTrue(pay["auto_manager_cycle"]["processed_reports"]
                            [0]["passed"])
            self.assertEqual("done", _get(orch, task["id"])["status"])

    def test_auto_cycle_defers_pending_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch, pol, task = self._mk(tmp, auto_validate=True)
            pay = self._submit(orch, pol,
                               status="needs_review",
                               review_gate={"required": True,
                                            "status": "pending",
                                            "reviewer_agent": "ccm"})
            self.assertEqual([], pay["auto_manager_cycle"]["processed_reports"])
            self.assertEqual(1, len(
                pay["auto_manager_cycle"]["deferred_reports"]))
            self.assertEqual("reported", _get(orch, task["id"])["status"])

    def test_auto_cycle_rejects_rejected_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch, pol, task = self._mk(tmp, auto_validate=True)
            pay = self._submit(orch, pol,
                               status="needs_review",
                               review_gate={"required": True,
                                            "status": "rejected",
                                            "reviewer_agent": "ccm"})
            self.assertFalse(pay["auto_manager_cycle"]["processed_reports"]
                             [0]["passed"])
            self.assertIn(_get(orch, task["id"])["status"],
                          {"bug_open", "in_progress"})


# ── task count guard ───────────────────────────────────────────────────

class TestTaskCountGuard(unittest.TestCase, _OrchestratorMixin):
    def setUp(self) -> None:
        self._init_orch()
        self._prev = os.environ.pop(
            "ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK", None)

    def tearDown(self) -> None:
        if self._prev is not None:
            os.environ["ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK"] = self._prev
        else:
            os.environ.pop("ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK", None)
        self._cleanup()

    def test_rejects_shrink(self) -> None:
        t1 = self.orch.create_task("t1", "backend", ["a"])
        self.orch.create_task("t2", "backend", ["b"])
        with self.assertRaises(RuntimeError) as ctx:
            self.orch._write_tasks_json([t1])
        self.assertIn("refusing_tasks_json_shrink", str(ctx.exception))
        self.assertEqual(2, len(self.orch.list_tasks()))

    def test_allows_shrink_with_override(self) -> None:
        t1 = self.orch.create_task("t1", "backend", ["a"])
        self.orch.create_task("t2", "backend", ["b"])
        os.environ["ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK"] = "1"
        self.orch._write_tasks_json([t1])
        self.assertEqual(1, len(self.orch.list_tasks()))


# ── multi-project tags ─────────────────────────────────────────────────

class TestMultiProjectTags(unittest.TestCase):
    def test_project_and_workstream_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            task = orch.create_task(
                title="Endpoint", workstream="backend",
                acceptance_criteria=["done"],
                tags=["api", "Project:my-api", "api"],
                project_name="my-api", project_root="/tmp/my-api")
            tags = set(task.get("tags", []))
            self.assertIn("api", tags)
            self.assertIn("project:my-api", tags)
            self.assertIn("workstream:backend", tags)
            self.assertEqual("/tmp/my-api", task["project_root"])

    def test_filter_by_project_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            orch.create_task(title="A", workstream="backend",
                             acceptance_criteria=["done"],
                             owner="claude_code",
                             project_name="proj-a",
                             project_root="/tmp/proj-a",
                             tags=["service", "priority:p1"])
            orch.create_task(title="B", workstream="frontend",
                             acceptance_criteria=["done"],
                             owner="gemini",
                             project_name="proj-b",
                             project_root="/tmp/proj-b",
                             tags=["ui"])
            filt = orch.list_tasks(project_name="proj-a", tags=["service"])
            self.assertEqual(1, len(filt))
            self.assertEqual("A", filt[0]["title"])

    def test_team_id_scopes_list_and_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _reg(orch, "claude_code")
            t1 = orch.create_task(title="Team A", workstream="backend",
                                  acceptance_criteria=["done"],
                                  owner="claude_code", team_id="team-a")
            orch.create_task(title="Team B", workstream="backend",
                             acceptance_criteria=["done"],
                             owner="claude_code", team_id="team-b")
            listed = orch.list_tasks(team_id="team-a")
            self.assertEqual(1, len(listed))
            claimed = orch.claim_next_task(owner="claude_code",
                                           team_id="team-a")
            self.assertEqual(t1["id"], claimed["id"])

    def test_claim_scoped_to_agent_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            orch = _make_orch(state,
                              allow_cross_project_agents=True)
            proj_a = Path(tmp) / "proj-a"
            proj_b = Path(tmp) / "proj-b"
            proj_a.mkdir()
            proj_b.mkdir()
            agent_meta = {
                "client": "claude_code", "model": "claude_code",
                "cwd": str(proj_b), "project_root": str(proj_b),
                "project_name": proj_b.name,
                "permissions_mode": "default", "sandbox_mode": "none",
                "session_id": "s", "connection_id": "c",
                "server_version": "1.0", "verification_source": "test",
                "instance_id": "claude_code#worker", "role": "team_member",
            }
            orch.register_agent("claude_code", agent_meta)
            orch.heartbeat("claude_code", metadata=agent_meta)
            orch.create_task(title="TA", workstream="backend",
                             acceptance_criteria=["done"],
                             owner="claude_code",
                             project_root=str(proj_a),
                             project_name=proj_a.name)
            tb = orch.create_task(title="TB", workstream="backend",
                                  acceptance_criteria=["done"],
                                  owner="claude_code",
                                  project_root=str(proj_b),
                                  project_name=proj_b.name)
            claimed = orch.claim_next_task(owner="claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual(tb["id"], claimed["id"])


class DeliveryProfileTests(unittest.TestCase):
    def test_default_delivery_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "p.json"))
            orch.bootstrap()
            task = orch.create_task(title="Lean", workstream="backend",
                                    acceptance_criteria=["done"], owner="claude_code")
            self.assertEqual({"risk": "medium", "test_plan": "targeted", "doc_impact": "none"},
                             task.get("delivery_profile"))

    def test_explicit_delivery_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "p.json"))
            orch.bootstrap()
            task = orch.create_task(title="Lean explicit", workstream="backend",
                                    acceptance_criteria=["done"], owner="claude_code",
                                    risk="high", test_plan="smoke", doc_impact="runbook")
            self.assertEqual({"risk": "high", "test_plan": "smoke", "doc_impact": "runbook"},
                             task.get("delivery_profile"))

    def test_invalid_delivery_profile_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "p.json"))
            orch.bootstrap()
            with self.assertRaises(ValueError):
                orch.create_task(title="Bad", workstream="backend",
                                 acceptance_criteria=["done"], owner="claude_code",
                                 risk="extreme")


if __name__ == "__main__":
    unittest.main()
