from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, *, auto_validate: bool) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "qa": "codex", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "auto_validate_reports_on_submit": auto_validate,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _mk_orch(root: Path, *, auto_validate: bool) -> tuple[Orchestrator, Policy]:
    policy = _make_policy(root / "policy.json", auto_validate=auto_validate)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch, policy


class SubmitReportAutoCycleTests(unittest.TestCase):
    def _connect_codex(self, orch: Orchestrator) -> None:
        root = str(orch.root)
        result = orch.connect_to_leader(
            agent="codex",
            source="codex",
            metadata={
                "client": "codex-cli",
                "model": "gpt-5-codex",
                "cwd": root,
                "project_root": root,
                "permissions_mode": "default",
                "sandbox_mode": "workspace-write",
                "session_id": "codex-test-session",
                "connection_id": "codex-test-conn",
                "instance_id": "codex#default",
                "server_version": "1.0",
                "verification_source": "codex",
                "role": "manager",
            },
        )
        self.assertTrue(result["connected"])

    def _seed_claimed_task(self, orch: Orchestrator) -> dict:
        self._connect_codex(orch)
        task = orch.create_task(
            title="QA report auto-cycle",
            workstream="qa",
            owner="codex",
            acceptance_criteria=["done"],
        )
        claimed = orch.claim_next_task(owner="codex", instance_id="codex#default")
        self.assertIsNotNone(claimed)
        return task

    def _run_submit_via_mcp(self, orch: Orchestrator, policy: Policy) -> dict:
        import orchestrator_mcp_server as mcp

        old_orch, old_policy = mcp.ORCH, mcp.POLICY
        try:
            mcp.ORCH = orch
            mcp.POLICY = policy
            response = mcp.handle_tool_call(
                "req-submit",
                {
                    "name": "orchestrator_submit_report",
                    "arguments": {
                        "task_id": orch.list_tasks(status="in_progress", owner="codex")[0]["id"],
                        "agent": "codex",
                        "commit_sha": "abc123",
                        "status": "done",
                        "test_summary": {"command": "pytest -q", "passed": 1, "failed": 0},
                        "notes": "auto-cycle test",
                    },
                },
            )
            return json.loads(response["result"]["content"][0]["text"])
        finally:
            mcp.ORCH = old_orch
            mcp.POLICY = old_policy

    def test_submit_report_auto_manager_cycle_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch, policy = _mk_orch(Path(tmp), auto_validate=True)
            task = self._seed_claimed_task(orch)
            payload = self._run_submit_via_mcp(orch, policy)

            self.assertIn("auto_manager_cycle", payload)
            self.assertTrue(payload["auto_manager_cycle"]["enabled"])
            updated = next(t for t in orch.list_tasks() if t["id"] == task["id"])
            self.assertEqual("done", updated["status"])

    def test_submit_report_auto_manager_cycle_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch, policy = _mk_orch(Path(tmp), auto_validate=False)
            task = self._seed_claimed_task(orch)
            payload = self._run_submit_via_mcp(orch, policy)

            self.assertNotIn("auto_manager_cycle", payload)
            updated = next(t for t in orch.list_tasks() if t["id"] == task["id"])
            self.assertEqual("reported", updated["status"])


if __name__ == "__main__":
    unittest.main()
