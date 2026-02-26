"""Operator documentation fixture tests – batch 5.

Covers:
- TASK-c292650d: Operator quick-reference for restart milestone visibility fields
- TASK-e8da7794: Status dashboard gap analysis and MVP dashboard proposal
- TASK-677982b8: Operator status field glossary for instance-aware visibility
- TASK-85aa013b: Dashboard mock data examples from current orchestrator outputs
- TASK-baf8add0: Percent reporting template (overall vs AUTO-M1)
- TASK-1d27a894: Example one-page status report combining overall % and AUTO-M1 %
- TASK-f79d1fd3: Restart verification script checklist for instance-aware status
- TASK-260de00c: Dashboard MVP command palette proposal (CLI shortcuts)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ── Helpers ──────────────────────────────────────────────────────────

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


def _connect(orch: Orchestrator, root: Path, agent: str, **overrides: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent, **overrides), source=agent)


# ══════════════════════════════════════════════════════════════════════
# TASK-c292650d: Operator quick-reference for restart visibility fields
# ══════════════════════════════════════════════════════════════════════

QUICK_REFERENCE = {
    "title": "Operator Quick-Reference: Restart Milestone Visibility Fields",
    "fields": {
        "agent_instances": {
            "description": "All known agent instances (active + stale/offline), keyed by instance_id.",
            "fields": ["agent_name", "instance_id", "role", "status", "project_root",
                        "current_task_id", "last_seen"],
            "where": "orchestrator_status → agent_instances",
            "example_active": {
                "agent_name": "claude_code",
                "instance_id": "sess-cc-1",
                "status": "active",
                "role": "team_member",
                "project_root": "/Users/alex/claude-multi-ai",
                "current_task_id": "TASK-abc123",
                "last_seen": "2026-02-26T10:00:00+00:00",
            },
            "example_offline": {
                "agent_name": "gemini",
                "instance_id": "gemini#default",
                "status": "offline",
                "role": "team_member",
                "project_root": "/Users/alex/claude-multi-ai",
                "current_task_id": None,
                "last_seen": "2026-02-25T23:00:00+00:00",
            },
        },
        "active_agent_identities": {
            "description": "Active-only agents with identity summary (most recent heartbeat winner per agent).",
            "fields": ["agent", "instance_id", "status", "last_seen"],
            "where": "orchestrator_status → active_agent_identities",
            "example_active": {
                "agent": "claude_code",
                "instance_id": "sess-cc-1",
                "status": "active",
                "last_seen": "2026-02-26T10:00:00+00:00",
            },
        },
    },
    "restart_requirement": "After updating the MCP server, all clients (Codex, Claude Code, Gemini) "
                           "must restart to load the updated server and see the new fields.",
    "how_to_read": [
        "agent_instances shows ALL instances — active and offline",
        "active_agent_identities shows ONLY active agents (filtered by heartbeat timeout + same project)",
        "status='active' means heartbeat within timeout AND same project_root",
        "status='offline' means heartbeat expired OR different project_root",
        "current_task_id shows what the instance is working on (null if idle)",
    ],
}


class QuickReferenceTests(unittest.TestCase):
    """TASK-c292650d: Operator quick-reference for restart visibility fields."""

    def test_quick_ref_has_both_fields(self) -> None:
        self.assertIn("agent_instances", QUICK_REFERENCE["fields"])
        self.assertIn("active_agent_identities", QUICK_REFERENCE["fields"])

    def test_active_example_included(self) -> None:
        ai = QUICK_REFERENCE["fields"]["agent_instances"]
        self.assertIn("example_active", ai)
        self.assertEqual("active", ai["example_active"]["status"])

    def test_offline_example_included(self) -> None:
        ai = QUICK_REFERENCE["fields"]["agent_instances"]
        self.assertIn("example_offline", ai)
        self.assertEqual("offline", ai["example_offline"]["status"])

    def test_restart_requirement_mentioned(self) -> None:
        self.assertIn("restart", QUICK_REFERENCE["restart_requirement"].lower())

    def test_how_to_read_entries(self) -> None:
        self.assertGreaterEqual(len(QUICK_REFERENCE["how_to_read"]), 4)

    def test_engine_produces_matching_fields(self) -> None:
        """Engine agent_instances output should have the documented fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            instances = orch.list_agent_instances(active_only=False)
            self.assertGreaterEqual(len(instances), 1)
            inst = instances[0]
            for field in ["agent_name", "instance_id", "status", "last_seen"]:
                self.assertIn(field, inst)

    def test_json_serializable(self) -> None:
        serialized = json.dumps(QUICK_REFERENCE)
        self.assertIsInstance(json.loads(serialized), dict)


# ══════════════════════════════════════════════════════════════════════
# TASK-e8da7794: Status dashboard gap analysis and MVP proposal
# ══════════════════════════════════════════════════════════════════════

DASHBOARD_GAP_ANALYSIS = {
    "existing_visibility": {
        "orchestrator_status": ["task_count", "task_status_counts", "bug_count",
                                 "active_agents", "active_agent_identities",
                                 "agent_instances", "live_status"],
        "orchestrator_list_tasks": ["id", "title", "owner", "status", "workstream"],
        "orchestrator_list_agents": ["agent", "status", "last_seen", "metadata"],
        "orchestrator_list_blockers": ["task_id", "question", "status", "raised_by"],
        "orchestrator_list_bugs": ["task_id", "owner", "error", "status"],
        "audit_log": ["timestamp", "tool", "status", "args", "result"],
        "watchdog_jsonl": ["timestamp", "kind", "task_id", "age_seconds"],
    },
    "missing_pieces": [
        {"field": "per_agent_throughput", "needed_for": "workload balancing", "phase": "phase_2"},
        {"field": "task_duration_stats", "needed_for": "estimation and planning", "phase": "phase_2"},
        {"field": "dispatch_noop_telemetry", "needed_for": "timeout diagnostics", "phase": "phase_2"},
        {"field": "historical_status_snapshots", "needed_for": "trend analysis", "phase": "phase_3"},
        {"field": "agent_resource_usage", "needed_for": "capacity planning", "phase": "phase_3"},
    ],
    "mvp_proposal": {
        "format": "CLI/TUI single-screen",
        "scope": "Team status + task pipeline + blockers + milestone %",
        "data_sources": ["orchestrator_status", "orchestrator_list_blockers",
                          "orchestrator_list_bugs"],
        "panels": ["team_health", "task_pipeline", "blocker_queue", "milestone_progress"],
        "aligned_with": "restart milestone (Phase 1)",
    },
}


class DashboardGapAnalysisTests(unittest.TestCase):
    """TASK-e8da7794: Status dashboard gap analysis and MVP proposal."""

    def test_existing_visibility_documented(self) -> None:
        self.assertGreaterEqual(len(DASHBOARD_GAP_ANALYSIS["existing_visibility"]), 5)

    def test_missing_pieces_documented(self) -> None:
        self.assertGreaterEqual(len(DASHBOARD_GAP_ANALYSIS["missing_pieces"]), 3)

    def test_missing_pieces_have_phase(self) -> None:
        for m in DASHBOARD_GAP_ANALYSIS["missing_pieces"]:
            self.assertIn("phase", m)
            self.assertIn("needed_for", m)

    def test_mvp_proposal_has_scope(self) -> None:
        mvp = DASHBOARD_GAP_ANALYSIS["mvp_proposal"]
        self.assertIn("scope", mvp)
        self.assertIn("data_sources", mvp)
        self.assertIn("panels", mvp)

    def test_aligned_with_restart_milestone(self) -> None:
        self.assertIn("restart", DASHBOARD_GAP_ANALYSIS["mvp_proposal"]["aligned_with"].lower())

    def test_json_serializable(self) -> None:
        serialized = json.dumps(DASHBOARD_GAP_ANALYSIS)
        self.assertIsInstance(json.loads(serialized), dict)


# ══════════════════════════════════════════════════════════════════════
# TASK-677982b8: Operator status field glossary
# ══════════════════════════════════════════════════════════════════════

STATUS_FIELD_GLOSSARY: list[dict] = [
    {"term": "agent_instances", "definition": "All known agent instances (active + offline). Each entry has agent_name, instance_id, status, project_root, current_task_id, last_seen.",
     "example": "agent_instances: [{agent_name: 'claude_code', instance_id: 'sess-1', status: 'active'}]",
     "audience": "operator"},
    {"term": "active_agent_identities", "definition": "Subset of agents currently active (heartbeat within timeout, same project). Shows most recent heartbeat winner per agent name.",
     "example": "active_agent_identities: [{agent: 'claude_code', status: 'active'}]",
     "audience": "operator"},
    {"term": "instance_id", "definition": "Unique identifier for an agent session. Derived from explicit metadata, session_id, connection_id, or '{agent}#default'.",
     "example": "instance_id: 'sess-cc-1' or 'claude_code#default'",
     "audience": "operator"},
    {"term": "active (status)", "definition": "Agent's last_seen is within heartbeat_timeout_minutes AND project_root matches orchestrator root.",
     "example": "status='active' when last_seen < 10 min ago and same project",
     "audience": "operator"},
    {"term": "offline (status)", "definition": "Agent's last_seen exceeded heartbeat_timeout_minutes OR project_root doesn't match. Instance still listed in agent_instances.",
     "example": "status='offline' when last_seen > 10 min ago",
     "audience": "operator"},
    {"term": "stale", "definition": "Informal term for an instance whose heartbeat is old but not necessarily removed. Watchdog may flag stale tasks independently of agent staleness.",
     "example": "Watchdog: stale_task kind with age_seconds > threshold",
     "audience": "operator"},
    {"term": "current_task_id", "definition": "The task the instance is currently working on. Null/None if idle or between tasks.",
     "example": "current_task_id: 'TASK-abc123' or null",
     "audience": "operator"},
    {"term": "last_seen", "definition": "ISO 8601 timestamp of the most recent heartbeat or connection from the instance.",
     "example": "last_seen: '2026-02-26T10:00:00+00:00'",
     "audience": "operator"},
    {"term": "heartbeat_timeout_minutes", "definition": "Policy-defined threshold. If an agent's last_seen exceeds this, it's considered offline. Default: 10 minutes.",
     "example": "heartbeat_timeout_minutes: 10 in policy.json triggers",
     "audience": "operator"},
    {"term": "same_project", "definition": "Identity verification check: agent's project_root must match orchestrator's root for active status.",
     "example": "same_project: true when cwd matches orchestrator root",
     "audience": "operator"},
    {"term": "lease", "definition": "Time-bounded claim on a task. Has lease_id, owner, expires_at. Prevents double-work. Renewable via renew_task_lease.",
     "example": "lease: {lease_id: 'LEASE-xxx', expires_at: '...', owner: 'claude_code'}",
     "audience": "operator"},
    {"term": "blocker", "definition": "A question or obstacle raised against a task. Task status set to 'blocked' until blocker is resolved.",
     "example": "blocker: {task_id: 'TASK-xxx', question: 'No eligible worker', status: 'open'}",
     "audience": "operator"},
]


class StatusFieldGlossaryTests(unittest.TestCase):
    """TASK-677982b8: Operator status field glossary."""

    def test_covers_new_and_existing_terms(self) -> None:
        terms = {g["term"] for g in STATUS_FIELD_GLOSSARY}
        new_terms = {"agent_instances", "active_agent_identities", "instance_id"}
        existing_terms = {"lease", "blocker", "last_seen"}
        self.assertTrue(new_terms.issubset(terms))
        self.assertTrue(existing_terms.issubset(terms))

    def test_includes_examples_for_ambiguous_fields(self) -> None:
        ambiguous = ["active (status)", "offline (status)", "stale"]
        for a in ambiguous:
            entry = next((g for g in STATUS_FIELD_GLOSSARY if g["term"] == a), None)
            self.assertIsNotNone(entry, f"Missing glossary entry for {a}")
            self.assertGreater(len(entry["example"]), 10)

    def test_operator_targeted(self) -> None:
        for g in STATUS_FIELD_GLOSSARY:
            self.assertEqual("operator", g["audience"])

    def test_each_entry_has_required_fields(self) -> None:
        for g in STATUS_FIELD_GLOSSARY:
            self.assertIn("term", g)
            self.assertIn("definition", g)
            self.assertIn("example", g)

    def test_at_least_ten_terms(self) -> None:
        self.assertGreaterEqual(len(STATUS_FIELD_GLOSSARY), 10)

    def test_json_serializable(self) -> None:
        serialized = json.dumps(STATUS_FIELD_GLOSSARY)
        self.assertIsInstance(json.loads(serialized), list)


# ══════════════════════════════════════════════════════════════════════
# TASK-85aa013b: Dashboard mock data examples
# ══════════════════════════════════════════════════════════════════════

DASHBOARD_MOCK_DATA = {
    "team_panel": {
        "source": "orchestrator_status.agent_instances",
        "synthetic": False,
        "data": [
            {"agent_name": "codex", "instance_id": "codex#mgr", "status": "active",
             "role": "manager", "current_task_id": None, "last_seen": "2026-02-26T10:05:00+00:00"},
            {"agent_name": "claude_code", "instance_id": "sess-cc-1", "status": "active",
             "role": "team_member", "current_task_id": "TASK-backend01", "last_seen": "2026-02-26T10:04:55+00:00"},
            {"agent_name": "claude_code", "instance_id": "sess-cc-2", "status": "active",
             "role": "team_member", "current_task_id": "TASK-docs01", "last_seen": "2026-02-26T10:04:50+00:00"},
            {"agent_name": "gemini", "instance_id": "gemini#default", "status": "offline",
             "role": "team_member", "current_task_id": None, "last_seen": "2026-02-25T23:00:00+00:00"},
        ],
    },
    "queue_panel": {
        "source": "orchestrator_status.task_status_counts",
        "synthetic": False,
        "data": {
            "assigned": 12,
            "in_progress": 5,
            "reported": 1,
            "done": 180,
            "blocked": 3,
            "bug_open": 1,
        },
    },
    "alerts_panel": {
        "source": "watchdog_jsonl + orchestrator_list_blockers",
        "synthetic": True,
        "synthetic_note": "Alert aggregation requires watchdog parsing — not automated yet",
        "data": [
            {"severity": "high", "type": "agent_offline", "title": "gemini offline (12h)",
             "source": "orchestrator_list_agents"},
            {"severity": "medium", "type": "open_blocker", "title": "3 open blockers pending",
             "source": "orchestrator_list_blockers"},
            {"severity": "low", "type": "stale_reported", "title": "1 task reported > 10 min",
             "source": "orchestrator_status"},
        ],
    },
    "percent_panel": {
        "source": "orchestrator_status.live_status",
        "synthetic": False,
        "data": {
            "overall_project_percent": 76,
            "phase_1_percent": 76,
            "backend_percent": 96,
            "frontend_percent": 23,
            "qa_percent": 76,
        },
    },
}


class DashboardMockDataTests(unittest.TestCase):
    """TASK-85aa013b: Dashboard mock data examples."""

    def test_covers_team_queue_alerts_percents(self) -> None:
        self.assertIn("team_panel", DASHBOARD_MOCK_DATA)
        self.assertIn("queue_panel", DASHBOARD_MOCK_DATA)
        self.assertIn("alerts_panel", DASHBOARD_MOCK_DATA)
        self.assertIn("percent_panel", DASHBOARD_MOCK_DATA)

    def test_each_panel_has_source(self) -> None:
        for name, panel in DASHBOARD_MOCK_DATA.items():
            self.assertIn("source", panel, f"{name} missing source")

    def test_synthetic_vs_real_noted(self) -> None:
        for name, panel in DASHBOARD_MOCK_DATA.items():
            self.assertIn("synthetic", panel, f"{name} missing synthetic flag")

    def test_synthetic_panels_have_note(self) -> None:
        for name, panel in DASHBOARD_MOCK_DATA.items():
            if panel["synthetic"]:
                self.assertIn("synthetic_note", panel, f"{name} missing synthetic_note")

    def test_fields_reflect_current_schema(self) -> None:
        team = DASHBOARD_MOCK_DATA["team_panel"]["data"]
        known = {"agent_name", "instance_id", "status", "role", "current_task_id", "last_seen"}
        for entry in team:
            self.assertTrue(known.issubset(entry.keys()))

    def test_json_serializable(self) -> None:
        serialized = json.dumps(DASHBOARD_MOCK_DATA)
        self.assertIsInstance(json.loads(serialized), dict)


# ══════════════════════════════════════════════════════════════════════
# TASK-baf8add0: Percent reporting template (overall vs AUTO-M1)
# ══════════════════════════════════════════════════════════════════════

PERCENT_REPORTING_TEMPLATE = {
    "title": "Status Update – {date}",
    "sections": {
        "overall_project": {
            "label": "Overall Project",
            "definition": "Percentage of ALL tasks (across all phases) in 'done' status.",
            "formula": "done_tasks / total_tasks * 100",
            "example_value": "76%",
        },
        "auto_m1_milestone": {
            "label": "AUTO-M1 (Restart Milestone)",
            "definition": "Percentage of CORE-02..06 acceptance criteria verified. "
                          "Advances in 1/6 increments as each core task passes acceptance.",
            "formula": "verified_core_tasks / 6 * 100",
            "example_value": "17% (1/6 — CORE-02 verified)",
        },
    },
    "why_they_diverge": [
        "Overall % counts all tasks; AUTO-M1 % counts only 6 core acceptance gates",
        "Completing 50 docs tasks raises overall % but not AUTO-M1 %",
        "Verifying one core task raises AUTO-M1 by ~17% but overall by only ~0.3%",
    ],
    "template_text": (
        "## Status Update – {date}\n\n"
        "| Metric | Value |\n"
        "|--------|-------|\n"
        "| Overall project | {overall}% |\n"
        "| AUTO-M1 milestone | {m1}% ({n}/6 core verified) |\n"
        "| Backend slice | {backend}% |\n"
        "| Frontend slice | {frontend}% |\n\n"
        "**Team:** {active_count} active, {offline_count} offline\n"
        "**Queue:** {in_progress} in-progress, {blocked} blocked, {open_bugs} bugs\n"
    ),
}


class PercentReportingTemplateTests(unittest.TestCase):
    """TASK-baf8add0: Percent reporting template (overall vs AUTO-M1)."""

    def test_template_concise(self) -> None:
        self.assertIn("template_text", PERCENT_REPORTING_TEMPLATE)
        self.assertLess(len(PERCENT_REPORTING_TEMPLATE["template_text"]), 1000)

    def test_includes_both_metrics(self) -> None:
        sections = PERCENT_REPORTING_TEMPLATE["sections"]
        self.assertIn("overall_project", sections)
        self.assertIn("auto_m1_milestone", sections)

    def test_definitions_included(self) -> None:
        for key, sec in PERCENT_REPORTING_TEMPLATE["sections"].items():
            self.assertIn("definition", sec)
            self.assertIn("formula", sec)

    def test_divergence_reasons_documented(self) -> None:
        self.assertGreaterEqual(len(PERCENT_REPORTING_TEMPLATE["why_they_diverge"]), 2)

    def test_template_has_placeholders(self) -> None:
        text = PERCENT_REPORTING_TEMPLATE["template_text"]
        self.assertIn("{overall}", text)
        self.assertIn("{m1}", text)

    def test_json_serializable(self) -> None:
        serialized = json.dumps(PERCENT_REPORTING_TEMPLATE)
        self.assertIsInstance(json.loads(serialized), dict)


# ══════════════════════════════════════════════════════════════════════
# TASK-1d27a894: Example one-page status report
# ══════════════════════════════════════════════════════════════════════

ONE_PAGE_STATUS_REPORT = {
    "title": "Project Status – claude-multi-ai – 2026-02-26",
    "metrics": {
        "overall_project_percent": 76,
        "auto_m1_milestone_percent": 17,
        "auto_m1_detail": "1/6 core verified (CORE-02 status fields)",
        "backend_percent": 96,
        "frontend_percent": 23,
        "qa_percent": 76,
    },
    "metrics_definitions": {
        "overall_project_percent": "done_tasks / total_tasks * 100",
        "auto_m1_milestone_percent": "verified_core_tasks / 6 * 100",
    },
    "team_status": [
        {"agent": "codex", "role": "manager", "status": "active"},
        {"agent": "claude_code", "role": "team_member", "status": "active", "sessions": 2},
        {"agent": "gemini", "role": "team_member", "status": "offline"},
    ],
    "queue_health": {
        "total_tasks": 313,
        "done": 239,
        "in_progress": 8,
        "assigned": 44,
        "blocked": 22,
        "open_bugs": 5,
        "open_blockers": 10,
    },
    "key_risks": [
        "Gemini offline — 52 frontend/docs tasks unassigned",
        "22 blocked tasks — 10 open blockers pending resolution",
    ],
}


class OnePageStatusReportTests(unittest.TestCase):
    """TASK-1d27a894: Example one-page status report."""

    def test_includes_both_metrics(self) -> None:
        m = ONE_PAGE_STATUS_REPORT["metrics"]
        self.assertIn("overall_project_percent", m)
        self.assertIn("auto_m1_milestone_percent", m)

    def test_definitions_included(self) -> None:
        self.assertIn("metrics_definitions", ONE_PAGE_STATUS_REPORT)
        self.assertGreaterEqual(len(ONE_PAGE_STATUS_REPORT["metrics_definitions"]), 2)

    def test_team_section_present(self) -> None:
        self.assertGreaterEqual(len(ONE_PAGE_STATUS_REPORT["team_status"]), 2)

    def test_queue_section_present(self) -> None:
        q = ONE_PAGE_STATUS_REPORT["queue_health"]
        self.assertIn("total_tasks", q)
        self.assertIn("done", q)
        self.assertIn("blocked", q)

    def test_concise(self) -> None:
        serialized = json.dumps(ONE_PAGE_STATUS_REPORT)
        self.assertLess(len(serialized), 2000, "One-page report should be concise")

    def test_json_serializable(self) -> None:
        parsed = json.loads(json.dumps(ONE_PAGE_STATUS_REPORT))
        self.assertIsInstance(parsed, dict)


# ══════════════════════════════════════════════════════════════════════
# TASK-f79d1fd3: Restart verification checklist (instance-aware)
# ══════════════════════════════════════════════════════════════════════

RESTART_VERIFICATION_CHECKLIST = {
    "purpose": "Verify post-restart that agent_instances and active_agent_identities are visible.",
    "per_client_steps": [
        {
            "client": "Codex (manager)",
            "steps": [
                {"action": "Restart Codex MCP session", "command": "Restart tmux pane or reconnect"},
                {"action": "Call orchestrator_status", "command": "orchestrator_status"},
                {"action": "Verify agent_instances field present", "command": "Check JSON for 'agent_instances' key"},
                {"action": "Verify active_agent_identities field present", "command": "Check JSON for 'active_agent_identities' key"},
            ],
        },
        {
            "client": "Claude Code (worker)",
            "steps": [
                {"action": "Restart Claude Code session", "command": "Exit and relaunch claude-code CLI"},
                {"action": "Connect to leader", "command": "orchestrator_connect_to_leader(agent='claude_code', ...)"},
                {"action": "Verify identity verified", "command": "Check response: verified=true, same_project=true"},
                {"action": "Confirm instance appears in status", "command": "orchestrator_status → agent_instances contains session"},
            ],
        },
        {
            "client": "Gemini (worker)",
            "steps": [
                {"action": "Restart Gemini session", "command": "Restart gemini worker process"},
                {"action": "Connect to leader", "command": "orchestrator_connect_to_leader(agent='gemini', ...)"},
                {"action": "Verify identity verified", "command": "Check response: verified=true, same_project=true"},
                {"action": "Confirm instance appears", "command": "orchestrator_status → agent_instances contains gemini"},
            ],
        },
    ],
    "expected_visible_fields": [
        "agent_instances[].agent_name",
        "agent_instances[].instance_id",
        "agent_instances[].status",
        "agent_instances[].last_seen",
        "agent_instances[].current_task_id",
        "agent_instances[].project_root",
        "active_agent_identities[].agent",
        "active_agent_identities[].instance_id",
        "active_agent_identities[].status",
    ],
    "troubleshooting": [
        {"symptom": "agent_instances field missing from status", "fix": "Server not updated — restart MCP server process"},
        {"symptom": "Agent shows 'offline' despite being connected", "fix": "Check same_project — cwd may not match orchestrator root"},
        {"symptom": "instance_id shows 'agent#default' instead of session_id", "fix": "Pass session_id in connection metadata"},
        {"symptom": "active_agent_identities empty but agents connected", "fix": "Heartbeat timeout may be too short — check policy triggers"},
    ],
}


class RestartVerificationChecklistTests(unittest.TestCase):
    """TASK-f79d1fd3: Restart verification checklist."""

    def test_per_client_steps_included(self) -> None:
        clients = {s["client"] for s in RESTART_VERIFICATION_CHECKLIST["per_client_steps"]}
        self.assertGreaterEqual(len(clients), 3)

    def test_includes_codex_claude_gemini(self) -> None:
        clients_text = " ".join(s["client"] for s in RESTART_VERIFICATION_CHECKLIST["per_client_steps"]).lower()
        self.assertIn("codex", clients_text)
        self.assertIn("claude", clients_text)
        self.assertIn("gemini", clients_text)

    def test_expected_fields_listed(self) -> None:
        self.assertGreaterEqual(len(RESTART_VERIFICATION_CHECKLIST["expected_visible_fields"]), 6)

    def test_troubleshooting_included(self) -> None:
        self.assertGreaterEqual(len(RESTART_VERIFICATION_CHECKLIST["troubleshooting"]), 3)

    def test_each_troubleshoot_has_symptom_and_fix(self) -> None:
        for t in RESTART_VERIFICATION_CHECKLIST["troubleshooting"]:
            self.assertIn("symptom", t)
            self.assertIn("fix", t)

    def test_json_serializable(self) -> None:
        serialized = json.dumps(RESTART_VERIFICATION_CHECKLIST)
        self.assertIsInstance(json.loads(serialized), dict)


# ══════════════════════════════════════════════════════════════════════
# TASK-260de00c: Dashboard MVP command palette proposal
# ══════════════════════════════════════════════════════════════════════

COMMAND_PALETTE: list[dict] = [
    {
        "shortcut": "s",
        "command": "orchestrator_status",
        "label": "Full Status",
        "rationale": "Primary entry point — shows all metrics, team, queue in one call",
        "needs_new_backend": False,
    },
    {
        "shortcut": "t",
        "command": "orchestrator_list_tasks",
        "label": "Task List",
        "rationale": "Drill into task pipeline — filter by status or owner",
        "needs_new_backend": False,
    },
    {
        "shortcut": "a",
        "command": "orchestrator_list_agents",
        "label": "Agent List",
        "rationale": "Quick check on who's active/offline",
        "needs_new_backend": False,
    },
    {
        "shortcut": "b",
        "command": "orchestrator_list_blockers(status=open)",
        "label": "Open Blockers",
        "rationale": "Blockers are the #1 cause of pipeline stalls",
        "needs_new_backend": False,
    },
    {
        "shortcut": "g",
        "command": "orchestrator_list_bugs(status=bug_open)",
        "label": "Open Bugs",
        "rationale": "Bugs need validation review — critical for quality gate",
        "needs_new_backend": False,
    },
    {
        "shortcut": "l",
        "command": "orchestrator_list_audit_logs(limit=20)",
        "label": "Recent Audit",
        "rationale": "See what happened recently — causal chain for debugging",
        "needs_new_backend": False,
    },
    {
        "shortcut": "e",
        "command": "orchestrator_poll_events(agent=codex)",
        "label": "Event Feed",
        "rationale": "Real-time event stream for lifecycle monitoring",
        "needs_new_backend": False,
    },
    {
        "shortcut": "r",
        "command": "orchestrator_manager_cycle",
        "label": "Run Manager Cycle",
        "rationale": "Process pending reports and advance tasks",
        "needs_new_backend": False,
    },
    {
        "shortcut": "w",
        "command": "watchdog_check",
        "label": "Watchdog Check",
        "rationale": "Parse latest watchdog JSONL for stale tasks and corruption",
        "needs_new_backend": True,
        "backend_note": "Needs CLI wrapper to parse .autopilot-logs/watchdog-*.jsonl",
    },
    {
        "shortcut": "d",
        "command": "dispatch_noop_summary",
        "label": "Dispatch Noops",
        "rationale": "Summarize stale overrides and timeout diagnostics",
        "needs_new_backend": True,
        "backend_note": "Needs noop telemetry aggregation — future phase",
    },
]


class CommandPaletteTests(unittest.TestCase):
    """TASK-260de00c: Dashboard MVP command palette proposal."""

    def test_shortcuts_mapped_to_tools(self) -> None:
        for cmd in COMMAND_PALETTE:
            self.assertIn("shortcut", cmd)
            self.assertIn("command", cmd)
            self.assertTrue(len(cmd["shortcut"]) == 1, f"Shortcut should be single char: {cmd['shortcut']}")

    def test_rationale_included(self) -> None:
        for cmd in COMMAND_PALETTE:
            self.assertIn("rationale", cmd)
            self.assertGreater(len(cmd["rationale"]), 10)

    def test_notes_new_backend_needs(self) -> None:
        new_backend = [c for c in COMMAND_PALETTE if c["needs_new_backend"]]
        existing = [c for c in COMMAND_PALETTE if not c["needs_new_backend"]]
        self.assertGreaterEqual(len(new_backend), 1, "Should flag at least 1 new backend need")
        self.assertGreaterEqual(len(existing), 5, "Most commands should use existing tools")

    def test_new_backend_has_note(self) -> None:
        for cmd in COMMAND_PALETTE:
            if cmd["needs_new_backend"]:
                self.assertIn("backend_note", cmd)

    def test_shortcuts_unique(self) -> None:
        shortcuts = [c["shortcut"] for c in COMMAND_PALETTE]
        self.assertEqual(len(shortcuts), len(set(shortcuts)))

    def test_at_least_eight_commands(self) -> None:
        self.assertGreaterEqual(len(COMMAND_PALETTE), 8)

    def test_json_serializable(self) -> None:
        serialized = json.dumps(COMMAND_PALETTE)
        self.assertIsInstance(json.loads(serialized), list)


if __name__ == "__main__":
    unittest.main()
