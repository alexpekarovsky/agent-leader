"""Tests for auto_resolve_stale_blockers policy.

Validates that meta/watchdog and project-mismatch blockers are auto-resolved
when stale, while user-input-required blockers are never auto-resolved.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def _register_and_claim(orch: Orchestrator, owner: str, title: str) -> str:
    """Create task, register agent, claim. Returns task_id."""
    task = orch.create_task(title=title, workstream="backend", acceptance_criteria=["done"], owner=owner)
    task_id = task["id"]
    orch.register_agent(owner, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": "test-session",
        "connection_id": "test-connection",
        "server_version": "0.1.0",
        "verification_source": "test",
    })
    orch.claim_next_task(owner)
    return task_id


def _inject_blocker(orch: Orchestrator, task_id: str, agent: str,
                    question: str, age_seconds: int,
                    severity: str = "medium",
                    options: list | None = None) -> str:
    """Raise a blocker and backdate its created_at timestamp."""
    blocker = orch.raise_blocker(
        task_id=task_id,
        agent=agent,
        question=question,
        options=options or [],
        severity=severity,
    )
    # Backdate created_at to simulate age.
    blockers = json.loads(orch.blockers_path.read_text(encoding="utf-8"))
    for blk in blockers:
        if blk["id"] == blocker["id"]:
            old_time = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
            blk["created_at"] = old_time.isoformat()
    orch.blockers_path.write_text(json.dumps(blockers), encoding="utf-8")
    return blocker["id"]


class MetaBlockerDetectionTests(unittest.TestCase):
    """Tests for _is_meta_blocker classification."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.orch = _make_orch(Path(self.tmp))

    def test_watchdog_blocker_is_meta(self) -> None:
        blocker = {"question": "Watchdog marked this task stale (age 5000s > timeout 180s)"}
        self.assertTrue(self.orch._is_meta_blocker(blocker))

    def test_project_mismatch_is_meta(self) -> None:
        blocker = {"question": "Wrong project scope: targets /other/project, not /this/project"}
        self.assertTrue(self.orch._is_meta_blocker(blocker))

    def test_cannot_work_outside_project_is_meta(self) -> None:
        blocker = {"question": "Cannot work on tasks outside my project. Task targets /other."}
        self.assertTrue(self.orch._is_meta_blocker(blocker))

    def test_stale_task_is_meta(self) -> None:
        blocker = {"question": "This task is stale and has not been worked on"}
        self.assertTrue(self.orch._is_meta_blocker(blocker))

    def test_user_decision_is_not_meta(self) -> None:
        blocker = {"question": "Should I use approach A or approach B for the auth module?"}
        self.assertFalse(self.orch._is_meta_blocker(blocker))

    def test_missing_docs_decision_is_not_meta(self) -> None:
        blocker = {"question": "docs/foo.md does not exist. Should I create it or skip?"}
        self.assertFalse(self.orch._is_meta_blocker(blocker))

    def test_empty_question_is_not_meta(self) -> None:
        blocker = {"question": ""}
        self.assertFalse(self.orch._is_meta_blocker(blocker))


class AutoResolveStaleBlockersTests(unittest.TestCase):
    """Tests for auto_resolve_stale_blockers."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.orch = _make_orch(Path(self.tmp))
        self.agent = "claude_code"

    def test_stale_watchdog_blocker_auto_resolved(self) -> None:
        task_id = _register_and_claim(self.orch, self.agent, "task-1")
        blk_id = _inject_blocker(
            self.orch, task_id, self.agent,
            question="Watchdog marked this task stale (age 5000s > timeout 180s)",
            age_seconds=7200,
        )

        result = self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        self.assertEqual(result["resolved_count"], 1)
        self.assertEqual(result["resolved"][0]["blocker_id"], blk_id)
        self.assertEqual(result["resolved"][0]["reason_code"], "stale_watchdog_blocker")

        # Blocker should be resolved now.
        blockers = self.orch.list_blockers(status="open")
        self.assertEqual(len(blockers), 0)

    def test_stale_project_mismatch_blocker_auto_resolved(self) -> None:
        task_id = _register_and_claim(self.orch, self.agent, "task-2")
        blk_id = _inject_blocker(
            self.orch, task_id, self.agent,
            question="Wrong project scope: targets /other/project, not /this/project. Cannot work on tasks outside my project.",
            age_seconds=7200,
            severity="high",
        )

        result = self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        self.assertEqual(result["resolved_count"], 1)
        self.assertEqual(result["resolved"][0]["reason_code"], "project_mismatch_blocker")

    def test_actionable_blocker_never_auto_resolved(self) -> None:
        task_id = _register_and_claim(self.orch, self.agent, "task-3")
        _inject_blocker(
            self.orch, task_id, self.agent,
            question="Should I use OAuth or JWT for authentication?",
            age_seconds=7200,
            options=["OAuth", "JWT"],
        )

        result = self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        self.assertEqual(result["resolved_count"], 0)
        self.assertEqual(result["skipped_actionable"], 1)

        # Blocker remains open.
        open_blockers = self.orch.list_blockers(status="open")
        self.assertEqual(len(open_blockers), 1)

    def test_young_meta_blocker_not_resolved(self) -> None:
        task_id = _register_and_claim(self.orch, self.agent, "task-4")
        _inject_blocker(
            self.orch, task_id, self.agent,
            question="Watchdog marked this task stale (age 200s > timeout 180s)",
            age_seconds=600,  # Only 10 minutes old.
        )

        result = self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        self.assertEqual(result["resolved_count"], 0)
        self.assertEqual(result["skipped_young"], 1)

    def test_mixed_blockers_only_eligible_resolved(self) -> None:
        """With a mix of meta-stale, meta-young, and actionable blockers,
        only the stale meta blocker is resolved."""
        t1 = _register_and_claim(self.orch, self.agent, "task-a")
        t2 = _register_and_claim(self.orch, self.agent, "task-b")
        t3 = _register_and_claim(self.orch, self.agent, "task-c")

        # Stale watchdog → should be resolved.
        blk_stale = _inject_blocker(
            self.orch, t1, self.agent,
            question="Watchdog marked this task stale",
            age_seconds=7200,
        )
        # Young watchdog → should be skipped.
        _inject_blocker(
            self.orch, t2, self.agent,
            question="Watchdog marked this task stale",
            age_seconds=300,
        )
        # Actionable → should be skipped.
        _inject_blocker(
            self.orch, t3, self.agent,
            question="Which database should I use?",
            age_seconds=7200,
        )

        result = self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        self.assertEqual(result["resolved_count"], 1)
        self.assertEqual(result["resolved"][0]["blocker_id"], blk_stale)
        self.assertEqual(result["skipped_actionable"], 1)
        self.assertEqual(result["skipped_young"], 1)

    def test_auto_resolve_emits_audit_event(self) -> None:
        task_id = _register_and_claim(self.orch, self.agent, "task-5")
        _inject_blocker(
            self.orch, task_id, self.agent,
            question="Watchdog marked this task stale",
            age_seconds=7200,
        )

        self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        # Check bus events for the audit trail.
        events = list(self.orch.bus.iter_events())
        auto_resolved_events = [
            e for e in events if e.get("type") == "blocker.auto_resolved"
        ]
        self.assertEqual(len(auto_resolved_events), 1)
        payload = auto_resolved_events[0].get("payload", {})
        self.assertIn("reason_code", payload)
        self.assertIn("age_seconds", payload)
        self.assertIn("threshold_seconds", payload)

    def test_resolved_blocker_has_resolution_text(self) -> None:
        task_id = _register_and_claim(self.orch, self.agent, "task-6")
        blk_id = _inject_blocker(
            self.orch, task_id, self.agent,
            question="Watchdog marked this task stale (age 9000s)",
            age_seconds=7200,
        )

        self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        resolved = [b for b in self.orch.list_blockers(status="resolved") if b["id"] == blk_id]
        self.assertEqual(len(resolved), 1)
        self.assertIn("auto_policy", resolved[0]["resolution"])
        self.assertIn("stale_watchdog_blocker", resolved[0]["resolution"])
        self.assertEqual(resolved[0]["resolved_by"], "auto_policy")

    def test_limit_caps_resolutions(self) -> None:
        """The limit parameter caps how many blockers are resolved per call."""
        task_ids = []
        for i in range(5):
            tid = _register_and_claim(self.orch, self.agent, f"task-lim-{i}")
            task_ids.append(tid)

        for tid in task_ids:
            _inject_blocker(
                self.orch, tid, self.agent,
                question="Watchdog marked this task stale",
                age_seconds=7200,
            )

        result = self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600, limit=2,
        )

        self.assertEqual(result["resolved_count"], 2)
        # 3 remain open.
        open_blockers = self.orch.list_blockers(status="open")
        self.assertEqual(len(open_blockers), 3)

    def test_task_unblocked_after_auto_resolve(self) -> None:
        """Auto-resolving a blocker should unblock the associated task."""
        task_id = _register_and_claim(self.orch, self.agent, "task-unblock")
        _inject_blocker(
            self.orch, task_id, self.agent,
            question="Watchdog marked this task stale",
            age_seconds=7200,
        )

        # Task should be blocked.
        tasks = self.orch.list_tasks()
        task = next(t for t in tasks if t["id"] == task_id)
        self.assertEqual(task["status"], "blocked")

        self.orch.auto_resolve_stale_blockers(
            source="auto_policy", stale_after_seconds=3600,
        )

        # Task should no longer be blocked.
        tasks = self.orch.list_tasks()
        task = next(t for t in tasks if t["id"] == task_id)
        self.assertIn(task["status"], ("in_progress", "assigned"))


if __name__ == "__main__":
    unittest.main()
