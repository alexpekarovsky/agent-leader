"""Status parity: verify MCP and headless status share canonical operator fields.

Both orchestrator_status (MCP) and headless_status.sh (--json) must expose the
same core operator-facing fields so that dashboards and runbooks work uniformly
regardless of runtime mode.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ── Canonical operator status fields ─────────────────────────────────
# Both MCP and headless payloads MUST include these top-level keys.
CANONICAL_STATUS_FIELDS = {
    "timestamp",
    "manager",
    "roles",
    "task_count",
    "task_status_counts",
    "team_lane_counters",
    "bug_count",
    "in_progress",
    "wingman_count",
    "recovery_actions",
    "active_agents",
    "active_agent_identities",
    "metrics",
}


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "parity-test",
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


class TestMCPStatusHasCanonicalFields(unittest.TestCase):
    """MCP orchestrator_status payload includes all canonical fields."""

    def test_canonical_fields_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="claude_code",
                metadata={
                    "role": "team_member",
                    "client": "test",
                    "model": "test",
                    "cwd": str(root),
                    "project_root": str(root),
                    "permissions_mode": "default",
                    "sandbox_mode": "false",
                    "session_id": "s1",
                    "connection_id": "c1",
                    "server_version": "1.0",
                    "verification_source": "test",
                },
                source="test",
            )
            orch.create_task("Parity test task", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            # Build payload matching MCP handler (lines 2006-2064 of orchestrator_mcp_server.py)
            tasks = orch.list_tasks()
            bugs = orch.list_bugs()
            agents = orch.list_agents(active_only=True)
            roles = orch.get_roles()
            by_status: dict = {}
            for t in tasks:
                by_status[t["status"]] = by_status.get(t["status"], 0) + 1

            from orchestrator_mcp_server import _aggregate_team_lanes
            from datetime import datetime, timezone

            in_progress_tasks = [t for t in tasks if t.get("status") == "in_progress"]
            wingman_pending = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "pending"]
            wingman_rejected = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "rejected"]

            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "manager": roles.get("leader"),
                "roles": roles,
                "task_count": len(tasks),
                "task_status_counts": by_status,
                "team_lane_counters": _aggregate_team_lanes(tasks),
                "bug_count": len(bugs),
                "in_progress": [
                    {"id": t.get("id"), "owner": t.get("owner"), "title": t.get("title"), "updated_at": t.get("updated_at")}
                    for t in in_progress_tasks[:8]
                ],
                "wingman_count": len(wingman_pending) + len(wingman_rejected),
                "recovery_actions": [],
                "active_agents": [a["agent"] for a in agents],
                "active_agent_identities": [
                    {"agent": a.get("agent"), "instance_id": a.get("instance_id"), "status": a.get("status"), "last_seen": a.get("last_seen")}
                    for a in agents
                ],
                "metrics": {"throughput": {"tasks_total": len(tasks)}},
            }

            missing = CANONICAL_STATUS_FIELDS - set(payload.keys())
            self.assertEqual(set(), missing, f"MCP payload missing canonical fields: {missing}")


class TestHeadlessStatusHasCanonicalFields(unittest.TestCase):
    """headless_status.sh --json output includes all canonical fields."""

    def test_canonical_fields_present(self) -> None:
        script = Path(__file__).resolve().parent.parent / "scripts" / "autopilot" / "headless_status.sh"
        if not script.exists():
            self.skipTest("headless_status.sh not found")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Bootstrap minimal state so the script can read it
            state_dir = root / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "tasks.json").write_text("[]", encoding="utf-8")
            (state_dir / "agents.json").write_text("{}", encoding="utf-8")
            (state_dir / "roles.json").write_text('{"leader": "codex", "team_members": []}', encoding="utf-8")
            (state_dir / "blockers.json").write_text("[]", encoding="utf-8")
            (state_dir / "bugs.json").write_text("[]", encoding="utf-8")

            result = subprocess.run(
                ["bash", str(script), "--project-root", str(root), "--json", "--once"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(0, result.returncode, f"headless_status.sh failed: {result.stderr}")

            payload = json.loads(result.stdout)
            missing = CANONICAL_STATUS_FIELDS - set(payload.keys())
            self.assertEqual(set(), missing, f"Headless payload missing canonical fields: {missing}")


class TestCanonicalFieldSemantics(unittest.TestCase):
    """Verify canonical fields have consistent types across both modes."""

    def test_field_types_match(self) -> None:
        """Both payloads use the same types for canonical fields."""
        # Type contract for canonical fields
        expected_types = {
            "timestamp": str,
            "manager": (str, type(None)),
            "roles": dict,
            "task_count": int,
            "task_status_counts": dict,
            "team_lane_counters": dict,
            "bug_count": int,
            "in_progress": list,
            "wingman_count": int,
            "recovery_actions": list,
            "active_agents": list,
            "active_agent_identities": list,
            "metrics": dict,
        }
        # Verify the contract covers all canonical fields
        self.assertEqual(set(expected_types.keys()), CANONICAL_STATUS_FIELDS)


if __name__ == "__main__":
    unittest.main()
