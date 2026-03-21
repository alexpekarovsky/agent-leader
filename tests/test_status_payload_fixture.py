"""Status payload example fixture for dashboard consumers.

Generates and validates example status payloads with active, offline,
and mixed instance states. These fixtures document the expected schema
for the orchestrator_status response.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

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


def _full_metadata(root: Path, agent: str, instance_id: str = "", project_name: Optional[str] = None) -> dict:
    meta = {
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
    if instance_id:
        meta["instance_id"] = instance_id
    if project_name:
        meta["project_name"] = project_name
    return meta


# ── Example fixture: expected status payload shape ──────────────────
EXPECTED_STATUS_KEYS = {
    "task_count",
    "task_status_counts",
    "team_lane_counters",
    "bug_count",
    "recovery_actions",
    "active_agents",
    "active_agent_identities",
    "agent_instances",
    "integrity",
    "stats_provenance",
    "live_status_text",
    "metrics",
    "cross_project_summary",
}

EXPECTED_METRICS_KEYS = {"throughput", "timings_seconds", "reliability", "usage", "code_output", "efficiency"}
EXPECTED_USAGE_KEYS = {
    "unique_agents_seen",
    "unique_agents_all_time",
    "tool_call_counts_recent",
    "daily_budget_calls",
    "daily_budget_by_process",
}

EXPECTED_AGENT_IDENTITY_KEYS = {"agent", "instance_id", "status", "last_seen"}

EXPECTED_INSTANCE_KEYS = {
    "agent_name",
    "instance_id",
    "role",
    "status",
    "project_root",
    "current_task_id",
    "last_seen",
}

EXPECTED_INTEGRITY_KEYS = {"ok", "warnings", "provenance"}
EXPECTED_STATS_PROVENANCE_KEYS = {"dashboard_percent", "task_summary", "integrity_state"}


class StatusPayloadShapeTests(unittest.TestCase):
    """Validate the shape of status payload fields."""

    def _build_status_payload(self, orch: Orchestrator) -> dict:
        """Build a status payload matching the MCP handler schema."""
        tasks = orch.list_tasks()
        bugs = orch.list_bugs()
        agents = orch.list_agents(active_only=True)
        instances = orch.list_agent_instances(active_only=False)
        roles = orch.get_roles()

        by_status: dict = {}
        for task in tasks:
            by_status[task["status"]] = by_status.get(task["status"], 0) + 1

        from orchestrator_mcp_server import _aggregate_team_lanes, _status_metrics, _status_integrity_and_provenance, _runtime_source_consistency, _server_binding_health, _live_status_report
        from datetime import datetime, timezone

        integrity = _status_integrity_and_provenance(
            current_task_count=len(tasks),
            current_done_count=int(by_status.get("done", 0)),
        )
        rsc = _runtime_source_consistency()
        binding = _server_binding_health()
        if not rsc["ok"]:
            integrity["warnings"] = integrity.get("warnings", []) + rsc["warnings"]
            integrity["ok"] = False
        if not binding["ok"]:
            integrity["warnings"] = integrity.get("warnings", []) + binding["warnings"]
            integrity["ok"] = False
        
        from orchestrator_mcp_server import _aggregate_by_project_root
        agent_instances = orch.list_agent_instances(active_only=False)
        cross_project_summary = _aggregate_by_project_root(tasks, bugs, agent_instances)
        if len(cross_project_summary) > 1:
            multi_project_data = cross_project_summary
        else:
            multi_project_data = {}

        live_status = _live_status_report({"cross_project_summary": multi_project_data})

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "server": "agent-leader-orchestrator",
            "version": "test-version", # Placeholder for actual __version__
            "root_name": orch.root.name,
            "policy_name": orch.policy.name,
            "manager": roles.get("leader"),
            "roles": roles,
            "task_count": len(tasks),
            "task_status_counts": by_status,
            "team_lane_counters": _aggregate_team_lanes(tasks),
            "bug_count": len(bugs),
            "in_progress": [
                {
                    "id": t.get("id"),
                    "owner": t.get("owner"),
                    "title": t.get("title"),
                    "updated_at": t.get("updated_at"),
                }
                for t in sorted([t for t in tasks if t.get("status") == "in_progress"], key=lambda x: str(x.get("updated_at", "")), reverse=True)[:8]
            ],
            "wingman_count": len([t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") in {"pending", "rejected"}]),
            "recovery_actions": live_status.get("report", {}).get("suggested_recovery_actions", []),
            "active_agents": [a["agent"] for a in agents],
            "active_agent_identities": [
                {
                    "agent": agent.get("agent"),
                    "instance_id": agent.get("instance_id"),
                    "status": agent.get("status"),
                    "last_seen": agent.get("last_seen"),
                }
                for agent in agents
            ],
            "agent_instances": [
                {
                    "agent_name": item.get("agent_name"),
                    "instance_id": item.get("instance_id"),
                    "role": item.get("role"),
                    "status": item.get("status"),
                    "project_root": item.get("project_root"),
                    "current_task_id": item.get("current_task_id"),
                    "last_seen": item.get("last_seen"),
                }
                for item in instances
            ],
            "live_status_text": live_status.get("report_text", ""),
            "live_status": live_status.get("report", {}),
            "integrity": integrity,
            "runtime_source_consistency": rsc,
            "server_binding": binding,
            "stats_provenance": {
                "dashboard_percent": "live_status_report_estimate",
                "task_summary": integrity.get("provenance", {}).get("task_counts"),
                "integrity_state": "ok" if (integrity.get("ok") and rsc["ok"]) else "degraded",
            },
            "recommended_status_cadence_seconds": live_status.get("recommended_cadence_seconds", 600),
            "run_context": {
                "run_id": None, # Placeholder
                "orchestrator_version": "test-version", # Placeholder
                "policy_name": orch.policy.name,
                "prompt_profile_version": None, # Placeholder
                "root_name": orch.root.name,
            },
            "metrics": _status_metrics(tasks=tasks, bugs_open=bugs, blockers_open=[]),
            "auto_manager_cycle": {
                "running": False, # Placeholder
                "interval_seconds": 15, # Placeholder
            },
            "stop_policy": orch.evaluate_stop_policy(),
            "cross_project_summary": multi_project_data,
        }

    def test_empty_state_payload_has_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            payload = self._build_status_payload(orch)

            for key in EXPECTED_STATUS_KEYS:
                self.assertIn(key, payload, f"Missing key: {key}")

            metrics = payload.get("metrics", {})
            for key in EXPECTED_METRICS_KEYS:
                self.assertIn(key, metrics, f"Missing metrics key: {key}")

            usage = metrics.get("usage", {})
            for key in EXPECTED_USAGE_KEYS:
                self.assertIn(key, usage, f"Missing usage key: {key}")

    def test_empty_state_has_zero_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            payload = self._build_status_payload(orch)

            self.assertEqual(0, payload["task_count"])
            self.assertEqual(0, payload["bug_count"])
            self.assertEqual({}, payload["task_status_counts"])

    def test_active_agents_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_full_metadata(root, "claude_code"),
                source="claude_code",
            )
            payload = self._build_status_payload(orch)

            self.assertIn("claude_code", payload["active_agents"])

    def test_active_agent_identities_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_full_metadata(root, "claude_code", "cc#worker-01"),
                source="claude_code",
            )
            payload = self._build_status_payload(orch)

            self.assertGreaterEqual(len(payload["active_agent_identities"]), 1)
            identity = payload["active_agent_identities"][0]
            for key in EXPECTED_AGENT_IDENTITY_KEYS:
                self.assertIn(key, identity, f"Missing identity key: {key}")

    def test_integrity_and_stats_provenance_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            payload = self._build_status_payload(orch)

            for key in EXPECTED_INTEGRITY_KEYS:
                self.assertIn(key, payload["integrity"], f"Missing integrity key: {key}")
            for key in EXPECTED_STATS_PROVENANCE_KEYS:
                self.assertIn(key, payload["stats_provenance"], f"Missing stats provenance key: {key}")

    def test_cross_project_summary_on_multi_root(self) -> None:
        """Verify cross_project_summary is present and structured correctly when tasks span multiple project roots."""
        with tempfile.TemporaryDirectory() as tmp_root:
            orch_root = Path(tmp_root)
            orch = _make_orch(orch_root) # Single orchestrator instance

            # Simulate two distinct project roots
            simulated_project_root_1 = "/tmp/project_alpha"
            simulated_project_name_1 = "project_alpha"
            simulated_project_root_2 = "/tmp/project_beta"
            simulated_project_name_2 = "project_beta"

            # Create tasks with distinct project roots to test cross-project grouping
            task1_alpha = orch.create_task("Task 1 Alpha", "backend", ["done"], owner="codex", project_root=simulated_project_root_1, project_name=simulated_project_name_1)
            task2_alpha = orch.create_task("Task 2 Alpha", "backend", ["in_progress"], owner="codex", project_root=simulated_project_root_1, project_name=simulated_project_name_1)
            task1_beta = orch.create_task("Task 1 Beta", "frontend", ["done"], owner="gemini", project_root=simulated_project_root_2, project_name=simulated_project_name_2)
            task2_beta = orch.create_task("Task 2 Beta", "frontend", ["assigned"], owner="gemini", project_root=simulated_project_root_2, project_name=simulated_project_name_2)

            with orch._state_lock():
                tasks = orch._read_json(orch.tasks_path)
                for task in tasks:
                    if task["id"] == task1_alpha["id"]:
                        task["status"] = "done"
                    elif task["id"] == task2_alpha["id"]:
                        task["status"] = "in_progress"
                    elif task["id"] == task1_beta["id"]:
                        task["status"] = "done"
                orch._write_tasks_json(tasks)

            # Connect agents, also specifying their project roots in metadata
            orch.connect_to_leader(
                agent="codex",
                metadata=_full_metadata(Path(simulated_project_root_1), "codex", "codex#inst1", simulated_project_name_1),
                source="codex",
            )
            orch.connect_to_leader(
                agent="gemini",
                metadata=_full_metadata(Path(simulated_project_root_2), "gemini", "gemini#inst1", simulated_project_name_2),
                source="gemini",
            )
            
            # Build the status payload from the single orchestrator instance
            payload = self._build_status_payload(orch)

            self.assertIn("cross_project_summary", payload)
            summary = payload["cross_project_summary"]
            self.assertIsInstance(summary, dict)
            self.assertGreater(len(summary), 1) # Should contain data for both simulated projects

            # Verify content for simulated Project 1 (keyed by project_name when available)
            project1_summary = summary.get(simulated_project_name_1)
            self.assertIsNotNone(project1_summary)
            self.assertEqual(project1_summary["project_name"], simulated_project_name_1)
            self.assertEqual(project1_summary["task_counts"].get("total", 0), 2)
            self.assertEqual(project1_summary["task_counts"].get("done", 0), 1)
            self.assertEqual(project1_summary["task_counts"].get("in_progress", 0), 1)
            self.assertEqual(project1_summary["task_counts"].get("blocked", 0), 0)
            self.assertGreaterEqual(project1_summary.get("active_agent_count", 0), 1) # codex is active
            self.assertEqual(project1_summary["bug_counts"].get("open", 0), 0)

            # Verify content for simulated Project 2
            project2_summary = summary.get(simulated_project_name_2)
            self.assertIsNotNone(project2_summary)
            self.assertEqual(project2_summary["project_name"], simulated_project_name_2)
            self.assertEqual(project2_summary["task_counts"].get("total", 0), 2)
            self.assertEqual(project2_summary["task_counts"].get("done", 0), 1)
            self.assertEqual(project2_summary["task_counts"].get("assigned", 0), 1)
            self.assertEqual(project2_summary["task_counts"].get("in_progress", 0), 0)
            self.assertEqual(project2_summary["task_counts"].get("blocked", 0), 0)
            self.assertGreaterEqual(project2_summary.get("active_agent_count", 0), 1) # gemini is active
            self.assertEqual(project2_summary["bug_counts"].get("open", 0), 0)




class StatusPayloadWithMixedInstancesTests(unittest.TestCase):
    """Fixture: status payload with active and offline instances."""

    def _build_status_payload(self, orch: Orchestrator) -> dict:
        tasks = orch.list_tasks()
        bugs = orch.list_bugs()
        agents = orch.list_agents(active_only=True)
        instances = orch.list_agent_instances(active_only=False)

        by_status: dict = {}
        for task in tasks:
            by_status[task["status"]] = by_status.get(task["status"], 0) + 1

        from orchestrator_mcp_server import _aggregate_team_lanes
        return {
            "task_count": len(tasks),
            "task_status_counts": by_status,
            "team_lane_counters": _aggregate_team_lanes(tasks),
            "bug_count": len(bugs),
            "active_agents": [a["agent"] for a in agents],
            "active_agent_identities": [
                {
                    "agent": a.get("agent"),
                    "instance_id": a.get("instance_id"),
                    "status": a.get("status"),
                    "last_seen": a.get("last_seen"),
                }
                for a in agents
            ],
            "agent_instances": [
                {
                    "agent_name": item.get("agent_name"),
                    "instance_id": item.get("instance_id"),
                    "role": item.get("role"),
                    "status": item.get("status"),
                    "project_root": item.get("project_root"),
                    "current_task_id": item.get("current_task_id"),
                    "last_seen": item.get("last_seen"),
                }
                for item in instances
            ],
            "integrity": {
                "ok": True,
                "warnings": [],
                "provenance": {"task_counts": "live_state"},
            },
            "stats_provenance": {
                "dashboard_percent": "live_status_report_estimate",
                "task_summary": "live_state",
                "integrity_state": "ok",
            },
        }

    def test_mixed_active_and_offline_instances(self) -> None:
        """Fixture: three agents connected, one forced offline."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Connect three agents
            for agent in ("claude_code", "gemini"):
                orch.connect_to_leader(
                    agent=agent,
                    metadata=_full_metadata(root, agent, f"{agent}#w1"),
                    source=agent,
                )
            # Force gemini offline
            agents_data = orch._read_json(orch.agents_path)
            agents_data["gemini"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents_data)

            payload = self._build_status_payload(orch)

            # claude_code should be active, gemini not
            self.assertIn("claude_code", payload["active_agents"])
            self.assertNotIn("gemini", payload["active_agents"])

            # But both should appear in agent_instances
            instance_agents = {i["agent_name"] for i in payload["agent_instances"]}
            self.assertIn("claude_code", instance_agents)
            self.assertIn("gemini", instance_agents)

            # Verify instance shape
            for inst in payload["agent_instances"]:
                for key in EXPECTED_INSTANCE_KEYS:
                    self.assertIn(key, inst, f"Missing instance key: {key}")

    def test_task_status_counts_accurate(self) -> None:
        """Verify status counts match actual task states."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_full_metadata(root, "claude_code"),
                source="claude_code",
            )
            # Create tasks in different states
            orch.create_task("T1", "backend", ["done"], owner="claude_code")
            orch.create_task("T2", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            payload = self._build_status_payload(orch)

            self.assertEqual(2, payload["task_count"])
            self.assertEqual(1, payload["task_status_counts"].get("assigned", 0))
            self.assertEqual(1, payload["task_status_counts"].get("in_progress", 0))

    def test_multiple_instances_same_agent(self) -> None:
        """Fixture: same agent with two instance IDs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_full_metadata(root, "claude_code", "cc#worker-01"),
                source="claude_code",
            )
            orch.heartbeat("claude_code", {
                **_full_metadata(root, "claude_code"),
                "instance_id": "cc#worker-02",
                "session_id": "sess-2",
                "connection_id": "conn-2",
            })

            payload = self._build_status_payload(orch)

            cc_instances = [i for i in payload["agent_instances"] if i["agent_name"] == "claude_code"]
            self.assertEqual(2, len(cc_instances))
            instance_ids = {i["instance_id"] for i in cc_instances}
            self.assertEqual({"cc#worker-01", "cc#worker-02"}, instance_ids)

    def test_payload_is_json_serializable(self) -> None:
        """Status payload should be fully JSON-serializable for dashboard consumers."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.connect_to_leader(
                agent="claude_code",
                metadata=_full_metadata(root, "claude_code"),
                source="claude_code",
            )
            orch.create_task("Serialize test", "backend", ["done"], owner="claude_code")

            payload = self._build_status_payload(orch)

            # Should not raise
            serialized = json.dumps(payload)
            deserialized = json.loads(serialized)
            self.assertEqual(payload["task_count"], deserialized["task_count"])


if __name__ == "__main__":
    unittest.main()
