"""Tests for per-team lane counter aggregation in status output."""

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
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


class TestAggregateTeamLanes(unittest.TestCase):
    """Unit tests for _aggregate_team_lanes helper."""

    def _aggregate(self, tasks: list) -> dict:
        # Import the helper from the server module.
        from orchestrator_mcp_server import _aggregate_team_lanes
        return _aggregate_team_lanes(tasks)

    def test_empty_tasks(self) -> None:
        self.assertEqual({}, self._aggregate([]))

    def test_tasks_without_team_id_excluded(self) -> None:
        tasks = [
            {"status": "in_progress", "team_id": None},
            {"status": "done"},
        ]
        self.assertEqual({}, self._aggregate(tasks))

    def test_single_team_counts(self) -> None:
        tasks = [
            {"status": "in_progress", "team_id": "team-a"},
            {"status": "reported", "team_id": "team-a"},
            {"status": "blocked", "team_id": "team-a"},
            {"status": "done", "team_id": "team-a"},
            {"status": "done", "team_id": "team-a"},
        ]
        result = self._aggregate(tasks)
        self.assertEqual({"team-a"}, set(result.keys()))
        self.assertEqual(5, result["team-a"]["total"])
        self.assertEqual(1, result["team-a"]["in_progress"])
        self.assertEqual(1, result["team-a"]["reported"])
        self.assertEqual(1, result["team-a"]["blocked"])
        self.assertEqual(2, result["team-a"]["done"])

    def test_multiple_teams(self) -> None:
        tasks = [
            {"status": "in_progress", "team_id": "team-a"},
            {"status": "done", "team_id": "team-b"},
            {"status": "done", "team_id": "team-b"},
            {"status": "blocked", "team_id": "team-c"},
        ]
        result = self._aggregate(tasks)
        self.assertEqual({"team-a", "team-b", "team-c"}, set(result.keys()))
        self.assertEqual(1, result["team-a"]["total"])
        self.assertEqual(2, result["team-b"]["total"])
        self.assertEqual(2, result["team-b"]["done"])
        self.assertEqual(1, result["team-c"]["blocked"])

    def test_missing_status_defaults_to_unknown(self) -> None:
        tasks = [{"team_id": "team-x"}]
        result = self._aggregate(tasks)
        self.assertEqual(1, result["team-x"]["total"])
        self.assertEqual(1, result["team-x"].get("unknown", 0))


class TestTeamLaneCountersIntegration(unittest.TestCase):
    """Integration tests for team lane counters in status output."""

    def test_team_lanes_in_status_payload(self) -> None:
        """team_lane_counters should appear in orchestrator_status payload."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="claude_code",
                metadata={"client": "test", "model": "test", "cwd": str(root),
                          "project_root": str(root), "permissions_mode": "default",
                          "sandbox_mode": "false", "session_id": "s1",
                          "connection_id": "c1", "server_version": "1.0",
                          "verification_source": "test"},
                source="claude_code",
            )
            orch.create_task("T1", "backend", ["done"], owner="claude_code", team_id="team-core")
            orch.create_task("T2", "backend", ["done"], owner="claude_code", team_id="team-core")
            orch.create_task("T3", "frontend", ["done"], owner="gemini", team_id="team-ui")
            # Claim T1 to move it to in_progress
            orch.claim_next_task("claude_code", team_id="team-core")

            tasks = orch.list_tasks()
            from orchestrator_mcp_server import _aggregate_team_lanes
            lanes = _aggregate_team_lanes(tasks)

            self.assertIn("team-core", lanes)
            self.assertIn("team-ui", lanes)
            self.assertEqual(2, lanes["team-core"]["total"])
            self.assertEqual(1, lanes["team-core"].get("in_progress", 0))
            self.assertEqual(1, lanes["team-core"].get("assigned", 0))
            self.assertEqual(1, lanes["team-ui"]["total"])

    def test_team_lanes_json_serializable(self) -> None:
        tasks = [
            {"status": "done", "team_id": "team-a"},
            {"status": "in_progress", "team_id": "team-a"},
        ]
        from orchestrator_mcp_server import _aggregate_team_lanes
        lanes = _aggregate_team_lanes(tasks)
        serialized = json.dumps(lanes)
        deserialized = json.loads(serialized)
        self.assertEqual(lanes, deserialized)


if __name__ == "__main__":
    unittest.main()
