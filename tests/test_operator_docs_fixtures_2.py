"""Operator documentation fixtures part 2: dashboard, restart, and gaps.

Covers:
- TASK-d635cc0f: Future dashboard data contract gap tracker
- TASK-76a77ada: Mixed project-root status interpretation examples
- TASK-249c4b0e: Visual mockup spec for CLI/TUI operator dashboard
- TASK-c3ad9196: One-screen dashboard content priority list (MVP)
- TASK-8e889bf2: Restart checklist for loading new status visibility fields
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


def _full_metadata(root: Path, agent: str, **overrides: str) -> dict:
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
    meta.update(overrides)
    return meta


# ═══════════════════════════════════════════════════════════════════════
# TASK-d635cc0f: Dashboard data contract gap tracker
# ═══════════════════════════════════════════════════════════════════════

DASHBOARD_DATA_GAPS = [
    {
        "gap_id": "GAP-01",
        "field": "current_task_id in agent_instances",
        "current_state": "Field exists but is not updated on claim/report transitions",
        "needed_for": "Show which task each instance is working on in dashboard",
        "roadmap_phase": "Phase 1 (CORE-02 enhancement)",
        "priority": "high",
        "operator_impact": "Operators cannot see at-a-glance what each agent is doing",
    },
    {
        "gap_id": "GAP-02",
        "field": "Event filtering API",
        "current_state": "poll_events returns all events; no server-side type filter",
        "needed_for": "Dashboard alerts panel — filter to lease_expired, noop, degraded_comm events",
        "roadmap_phase": "Phase 1 (CORE-05 enhancement)",
        "priority": "medium",
        "operator_impact": "Client must filter large event streams; increases latency for alerts",
    },
    {
        "gap_id": "GAP-03",
        "field": "Historical progress trend",
        "current_state": "status_snapshots JSONL exists but no query API",
        "needed_for": "Show progress chart over time (tasks done per hour, % trend)",
        "roadmap_phase": "Phase 2",
        "priority": "low",
        "operator_impact": "No trend visibility; operator can only see point-in-time",
    },
    {
        "gap_id": "GAP-04",
        "field": "Push notifications / SSE",
        "current_state": "Polling only — no real-time push mechanism",
        "needed_for": "Instant alerts when blockers raised or agents go offline",
        "roadmap_phase": "Phase 3",
        "priority": "low",
        "operator_impact": "Dashboard requires periodic polling; alerts delayed by poll interval",
    },
    {
        "gap_id": "GAP-05",
        "field": "Lease time remaining",
        "current_state": "Lease data available in task state but not surfaced in status response",
        "needed_for": "Show time-to-expiry for each in-progress task",
        "roadmap_phase": "Phase 1 (CORE-03 enhancement)",
        "priority": "medium",
        "operator_impact": "Cannot predict when tasks will auto-recover from expired leases",
    },
]


class DashboardGapTrackerTests(unittest.TestCase):
    """Validate dashboard data contract gap tracker."""

    def test_at_least_four_gaps_tracked(self) -> None:
        self.assertGreaterEqual(len(DASHBOARD_DATA_GAPS), 4)

    def test_each_gap_has_required_fields(self) -> None:
        for gap in DASHBOARD_DATA_GAPS:
            for field in ("gap_id", "field", "current_state", "needed_for", "roadmap_phase", "priority", "operator_impact"):
                self.assertIn(field, gap, f"Missing {field} in {gap['gap_id']}")

    def test_gaps_reference_current_tools(self) -> None:
        """At least some gaps should reference existing tools/schemas."""
        all_text = " ".join(g["current_state"] for g in DASHBOARD_DATA_GAPS)
        self.assertTrue(any(kw in all_text.lower() for kw in ("poll_events", "status", "snapshot", "lease", "agent_instances")))

    def test_gaps_mapped_to_phases(self) -> None:
        phases = {g["roadmap_phase"] for g in DASHBOARD_DATA_GAPS}
        self.assertGreaterEqual(len(phases), 2, "Gaps should span multiple phases")

    def test_gaps_prioritized(self) -> None:
        priorities = {g["priority"] for g in DASHBOARD_DATA_GAPS}
        self.assertTrue(priorities.intersection({"high", "medium", "low"}))

    def test_gaps_json_serializable(self) -> None:
        serialized = json.dumps(DASHBOARD_DATA_GAPS)
        self.assertIsInstance(json.loads(serialized), list)


# ═══════════════════════════════════════════════════════════════════════
# TASK-76a77ada: Mixed project-root examples
# ═══════════════════════════════════════════════════════════════════════

MIXED_ROOT_EXAMPLES = [
    {
        "example_id": "MR-01",
        "scenario": "Two projects on same machine, same agent family",
        "instances": [
            {"agent": "claude_code", "instance_id": "cc#proj-A", "project_root": "/home/user/project-A", "status": "active"},
            {"agent": "claude_code", "instance_id": "cc#proj-B", "project_root": "/home/user/project-B", "status": "offline"},
        ],
        "interpretation": "Only cc#proj-A is active because project-B root does not match the orchestrator's root. "
                          "Offline instances from other projects appear in agent_instances but are excluded from active lists.",
        "guidance": "Filter by project_root to see only relevant instances for the current project.",
    },
    {
        "example_id": "MR-02",
        "scenario": "Manager and workers on different project subdirectories",
        "instances": [
            {"agent": "codex", "instance_id": "codex#mgr", "project_root": "/home/user/mono-repo", "status": "active"},
            {"agent": "claude_code", "instance_id": "cc#worker", "project_root": "/home/user/mono-repo/packages/api", "status": "active"},
        ],
        "interpretation": "Both are active because cwd is within the orchestrator root (mono-repo). "
                          "The _path_within_project check allows subdirectories.",
        "guidance": "Subdirectory workers are valid. project_root shows their configured root, but they're within orchestrator scope.",
    },
    {
        "example_id": "MR-03",
        "scenario": "Agent with no project_root metadata",
        "instances": [
            {"agent": "gemini", "instance_id": "gem#legacy", "project_root": None, "status": "offline"},
        ],
        "interpretation": "Agents without project_root or cwd metadata are treated as offline (project_mismatch). "
                          "This protects against unverified agents appearing as active.",
        "guidance": "Ensure all agents provide cwd and project_root in their metadata for proper visibility.",
    },
]


class MixedProjectRootExampleTests(unittest.TestCase):
    """Validate mixed project-root interpretation examples."""

    def test_at_least_three_examples(self) -> None:
        self.assertGreaterEqual(len(MIXED_ROOT_EXAMPLES), 3)

    def test_each_example_has_required_fields(self) -> None:
        for ex in MIXED_ROOT_EXAMPLES:
            for field in ("example_id", "scenario", "instances", "interpretation", "guidance"):
                self.assertIn(field, ex, f"Missing {field} in {ex['example_id']}")

    def test_instances_have_status(self) -> None:
        for ex in MIXED_ROOT_EXAMPLES:
            for inst in ex["instances"]:
                self.assertIn("status", inst)
                self.assertIn(inst["status"], ("active", "offline"))

    def test_live_different_root_is_offline(self) -> None:
        """Agent with different project_root should be offline in real engine."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            meta = _full_metadata(root, "claude_code")
            meta["project_root"] = "/tmp/other-project"
            meta["cwd"] = "/tmp/other-project"
            orch.connect_to_leader(agent="claude_code", metadata=meta, source="claude_code")

            instances = orch.list_agent_instances(active_only=False)
            cc = [i for i in instances if i["agent_name"] == "claude_code"]
            self.assertGreaterEqual(len(cc), 1)
            self.assertEqual("offline", cc[0]["status"])

    def test_examples_json_serializable(self) -> None:
        serialized = json.dumps(MIXED_ROOT_EXAMPLES)
        self.assertIsInstance(json.loads(serialized), list)


# ═══════════════════════════════════════════════════════════════════════
# TASK-249c4b0e: CLI/TUI dashboard visual mockup spec
# ═══════════════════════════════════════════════════════════════════════

TUI_DASHBOARD_MOCKUP = """
┌─ Orchestrator Dashboard ─────────────────────────────────────────┐
│ Project: claude-multi-ai   Policy: test-policy   v0.1.0         │
│ Overall: 45%   Phase 1: 80%   Backend: 60%   Frontend: 10%     │
├─ Team Instances ─────────────────────────────────────────────────┤
│ Agent        Instance      Role         Status   Task           │
│ codex        codex#mgr     manager      active   —              │
│ claude_code  cc#worker-01  team_member  active   TASK-abc123    │
│ claude_code  cc#worker-02  team_member  active   TASK-def456    │
│ gemini       gem#w1        team_member  offline  —              │
├─ Queue Health ───────────────────────────────────────────────────┤
│ Tasks: 50 total  │  12 assigned  │  8 in_progress  │  25 done  │
│ Reported: 3      │  Blocked: 2   │  Bugs: 1        │           │
├─ Alerts (recent) ────────────────────────────────────────────────┤
│ [!] task.lease_expired_blocked  TASK-ghi789  10m ago            │
│ [!] dispatch.noop              CMD-xyz001   5m ago              │
│ [i] team_member.degraded_comm  gemini       30m ago             │
└──────────────────────────────────────────────────────────────────┘
""".strip()

TUI_LAYOUT_SECTIONS = [
    {"section": "header", "content": "Project name, policy, version, overall/phase percentages", "source": "orchestrator_status.live_status"},
    {"section": "team_instances", "content": "Agent/instance table with role, status, current task", "source": "orchestrator_status.agent_instances"},
    {"section": "queue_health", "content": "Task count breakdown by status, blockers, bugs", "source": "orchestrator_status.task_status_counts + live_status.pipeline_health"},
    {"section": "alerts", "content": "Recent notable events filtered by type", "source": "events.jsonl (filtered)", "future_data": "Requires event filtering API (GAP-02)"},
]


class TuiDashboardMockupTests(unittest.TestCase):
    """Validate TUI dashboard mockup specification."""

    def test_mockup_defined(self) -> None:
        self.assertGreater(len(TUI_DASHBOARD_MOCKUP), 100)

    def test_mockup_has_key_sections(self) -> None:
        for section in ("Team Instances", "Queue Health", "Alerts"):
            self.assertIn(section, TUI_DASHBOARD_MOCKUP)

    def test_mockup_includes_restart_fields(self) -> None:
        """Mockup should show instance_id and status (restart visibility)."""
        self.assertIn("Instance", TUI_DASHBOARD_MOCKUP)
        self.assertIn("active", TUI_DASHBOARD_MOCKUP)
        self.assertIn("offline", TUI_DASHBOARD_MOCKUP)

    def test_layout_sections_defined(self) -> None:
        self.assertGreaterEqual(len(TUI_LAYOUT_SECTIONS), 4)

    def test_each_section_has_source(self) -> None:
        for section in TUI_LAYOUT_SECTIONS:
            self.assertIn("source", section)

    def test_future_data_flagged(self) -> None:
        """At least one section should flag future data needs."""
        future_flags = [s for s in TUI_LAYOUT_SECTIONS if "future_data" in s]
        self.assertGreaterEqual(len(future_flags), 1)


# ═══════════════════════════════════════════════════════════════════════
# TASK-c3ad9196: One-screen dashboard content priority list
# ═══════════════════════════════════════════════════════════════════════

DASHBOARD_PRIORITY_LIST = [
    {
        "rank": 1,
        "item": "Task status summary (total, by status)",
        "justification": "Core operator need: understand queue state at a glance",
        "source": "orchestrator_status.task_count + task_status_counts",
        "gap": None,
    },
    {
        "rank": 2,
        "item": "Active team members with status",
        "justification": "Critical for knowing who is working and who is offline",
        "source": "orchestrator_status.active_agents + active_agent_identities",
        "gap": None,
    },
    {
        "rank": 3,
        "item": "Open blockers and bugs count",
        "justification": "Blockers halt progress; operator must resolve quickly",
        "source": "orchestrator_status.bug_count + live_status.pipeline_health",
        "gap": None,
    },
    {
        "rank": 4,
        "item": "Project progress percentages",
        "justification": "Manager and stakeholder visibility into completion",
        "source": "orchestrator_status.live_status (overall, phase, workstream)",
        "gap": None,
    },
    {
        "rank": 5,
        "item": "Agent instance details (instance_id, role, project)",
        "justification": "Multi-session visibility for post-restart verification",
        "source": "orchestrator_status.agent_instances",
        "gap": "current_task_id not updated (GAP-01)",
    },
    {
        "rank": 6,
        "item": "Recent alerts (lease expired, noop, degraded comm)",
        "justification": "Proactive issue detection without reading raw logs",
        "source": "events.jsonl (client-side filtered)",
        "gap": "No server-side event filter API (GAP-02)",
    },
    {
        "rank": 7,
        "item": "Recent audit log entries",
        "justification": "Activity trail for debugging; lower priority for monitoring",
        "source": "orchestrator_list_audit_logs",
        "gap": None,
    },
]


class DashboardPriorityListTests(unittest.TestCase):
    """Validate one-screen dashboard content priority list."""

    def test_at_least_five_items(self) -> None:
        self.assertGreaterEqual(len(DASHBOARD_PRIORITY_LIST), 5)

    def test_items_ranked_in_order(self) -> None:
        ranks = [item["rank"] for item in DASHBOARD_PRIORITY_LIST]
        self.assertEqual(ranks, sorted(ranks))

    def test_each_item_justified(self) -> None:
        for item in DASHBOARD_PRIORITY_LIST:
            for field in ("rank", "item", "justification", "source"):
                self.assertIn(field, item)
            self.assertGreater(len(item["justification"]), 10)

    def test_items_map_to_existing_sources(self) -> None:
        for item in DASHBOARD_PRIORITY_LIST:
            self.assertIn("source", item)
            self.assertGreater(len(item["source"]), 0)

    def test_gaps_identified_where_applicable(self) -> None:
        gapped = [item for item in DASHBOARD_PRIORITY_LIST if item.get("gap")]
        self.assertGreaterEqual(len(gapped), 1)

    def test_priority_list_json_serializable(self) -> None:
        serialized = json.dumps(DASHBOARD_PRIORITY_LIST)
        self.assertIsInstance(json.loads(serialized), list)


# ═══════════════════════════════════════════════════════════════════════
# TASK-8e889bf2: Restart checklist for status visibility
# ═══════════════════════════════════════════════════════════════════════

RESTART_CHECKLIST = [
    {
        "step": 1,
        "action": "Stop all running agent sessions (Codex, Claude Code, Gemini)",
        "command": "# Kill existing MCP server processes and agent sessions",
        "verification": None,
    },
    {
        "step": 2,
        "action": "Verify state files are intact before restart",
        "command": "ls state/tasks.json state/agents.json state/agent_instances.json state/roles.json",
        "verification": "All files exist and are valid JSON",
    },
    {
        "step": 3,
        "action": "Restart the MCP server (orchestrator_mcp_server.py)",
        "command": "python3 orchestrator_mcp_server.py --root . --policy policy.json",
        "verification": "Server starts without errors; prints version and root",
    },
    {
        "step": 4,
        "action": "Connect Codex (manager) first",
        "command": "orchestrator_connect_to_leader(agent='codex', role='manager')",
        "verification": "Response: connected=true, verified=true",
    },
    {
        "step": 5,
        "action": "Connect Claude Code worker sessions",
        "command": "orchestrator_connect_to_leader(agent='claude_code', role='team_member')",
        "verification": "Response: connected=true, auto_claimed_task present if tasks available",
    },
    {
        "step": 6,
        "action": "Connect Gemini worker session",
        "command": "orchestrator_connect_to_leader(agent='gemini', role='team_member')",
        "verification": "Response: connected=true, verified=true",
    },
    {
        "step": 7,
        "action": "Verify agent_instances visibility via orchestrator_status",
        "command": "orchestrator_status()",
        "verification": "agent_instances array contains all connected agents with correct instance_ids and status=active",
    },
    {
        "step": 8,
        "action": "Verify active_agent_identities matches connected agents",
        "command": "Check orchestrator_status response",
        "verification": "active_agent_identities lists codex, claude_code, gemini with verified instance_ids",
    },
    {
        "step": 9,
        "action": "Verify task counts are preserved from before restart",
        "command": "orchestrator_status() → task_count, task_status_counts",
        "verification": "Task counts match pre-restart values; no tasks lost",
    },
    {
        "step": 10,
        "action": "Resume task processing",
        "command": "orchestrator_claim_next_task(agent='claude_code')",
        "verification": "Workers can claim and process tasks normally",
    },
]

POST_RESTART_INDICATORS = {
    "healthy": [
        "All agents show status=active in agent_instances",
        "active_agents list includes codex, claude_code, gemini",
        "task_count matches pre-restart snapshot",
        "integrity.ok is true",
        "No open blockers with 'restart' in question",
    ],
    "degraded": [
        "Some agents show status=offline (may need reconnection)",
        "integrity.ok is false with warnings",
        "task_count differs from pre-restart snapshot",
        "Missing agent_instances entries",
    ],
}


class RestartChecklistTests(unittest.TestCase):
    """Validate restart checklist for status visibility fields."""

    def test_checklist_has_steps(self) -> None:
        self.assertGreaterEqual(len(RESTART_CHECKLIST), 8)

    def test_steps_in_order(self) -> None:
        steps = [s["step"] for s in RESTART_CHECKLIST]
        self.assertEqual(steps, sorted(steps))

    def test_each_step_has_action_and_command(self) -> None:
        for step in RESTART_CHECKLIST:
            self.assertIn("action", step)
            self.assertIn("command", step)

    def test_includes_codex_claude_gemini(self) -> None:
        all_text = " ".join(s["action"] + " " + s["command"] for s in RESTART_CHECKLIST)
        for agent in ("Codex", "claude_code", "Gemini"):
            self.assertIn(agent, all_text, f"Missing {agent} in checklist")

    def test_includes_verification_commands(self) -> None:
        verified = [s for s in RESTART_CHECKLIST if s.get("verification")]
        self.assertGreaterEqual(len(verified), 5)

    def test_post_restart_indicators_defined(self) -> None:
        self.assertIn("healthy", POST_RESTART_INDICATORS)
        self.assertIn("degraded", POST_RESTART_INDICATORS)
        self.assertGreaterEqual(len(POST_RESTART_INDICATORS["healthy"]), 3)

    def test_agent_instances_visibility_verified(self) -> None:
        """Checklist should include a step verifying agent_instances."""
        texts = " ".join(s["action"] + " " + str(s.get("verification", "")) for s in RESTART_CHECKLIST)
        self.assertIn("agent_instances", texts)

    def test_checklist_json_serializable(self) -> None:
        serialized = json.dumps(RESTART_CHECKLIST)
        self.assertIsInstance(json.loads(serialized), list)


if __name__ == "__main__":
    unittest.main()
