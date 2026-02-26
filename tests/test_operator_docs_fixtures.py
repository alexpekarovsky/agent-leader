"""Operator documentation fixtures and validation tests.

Covers:
- TASK-657331c3: Data source trust matrix (status vs audit vs watchdog logs)
- TASK-8759477d: Dashboard gap analysis and MVP dashboard proposal
- TASK-8f2649d2: Dashboard data schema proposal from orchestrator_status + audit logs
- TASK-8ea5e8df: Status percent interpretation note (overall vs milestone)
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


def _full_metadata(root: Path, agent: str) -> dict:
    return {
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


def _connect(orch: Orchestrator, root: Path, agent: str) -> None:
    orch.connect_to_leader(agent=agent, metadata=_full_metadata(root, agent), source=agent)


# ═══════════════════════════════════════════════════════════════════════
# TASK-657331c3: Data source trust matrix
# ═══════════════════════════════════════════════════════════════════════

# Authority: what each data source is the ground truth for.
# Discrepancies: where divergence can occur and how to resolve.

DATA_SOURCE_TRUST_MATRIX = {
    "orchestrator_status": {
        "description": "MCP handler returning real-time task/agent/instance state",
        "authoritative_for": [
            "Current task counts and status distribution",
            "Active agent list and instance identities",
            "Live project percentage estimates",
            "Pipeline health (open blockers, bugs, reported tasks)",
            "Integrity and provenance metadata",
        ],
        "data_freshness": "Real-time (computed on each call from state/*.json files)",
        "limitations": [
            "Percentages are estimates from done/total ratio, not manager-curated",
            "agent_instances may include stale records from previous sessions",
            "No historical trend data — only point-in-time snapshot",
        ],
    },
    "audit_logs": {
        "description": "Append-only JSONL log of all MCP tool calls (bus/audit.jsonl)",
        "authoritative_for": [
            "Chronological record of all orchestrator tool invocations",
            "Request/response payloads for debugging",
            "Tool call success/failure status",
            "Timestamp-ordered agent activity trail",
        ],
        "data_freshness": "Append-only log; entries are immutable once written",
        "limitations": [
            "Does not capture internal engine state changes between calls",
            "Volume grows unbounded without log rotation",
            "Not authoritative for current state (use orchestrator_status instead)",
        ],
    },
    "watchdog_jsonl": {
        "description": "Periodic health check JSONL files (watchdog-YYYYMMDD-HHMMSS.jsonl)",
        "authoritative_for": [
            "Stale task age diagnostics from external observer",
            "Periodic health snapshots independent of MCP server",
            "System-level availability checks",
        ],
        "data_freshness": "Periodic snapshots (configurable interval, typically 60s)",
        "limitations": [
            "Watchdog is a passive observer — does NOT mutate state",
            "Stale task heuristic uses updated_at age, NOT lease.expires_at",
            "May report stale tasks that have valid leases (divergence from core)",
            "File rotation controlled by --max-logs flag",
        ],
    },
    "events_jsonl": {
        "description": "EventBus append-only event log (bus/events.jsonl)",
        "authoritative_for": [
            "Task lifecycle events (assigned, claimed, reported, done)",
            "Dispatch telemetry (command, ack, noop)",
            "Agent connection and heartbeat events",
            "Blocker and validation events",
        ],
        "data_freshness": "Append-only; emitted at event time",
        "limitations": [
            "Not authoritative for current state — events are historical",
            "Events may reference tasks/agents that no longer exist in current state",
            "No built-in compaction or deduplication",
        ],
    },
    "status_snapshots": {
        "description": "Periodic status snapshot JSONL appended on each orchestrator_status call",
        "authoritative_for": [
            "Historical trend of task counts and percentages over time",
            "Integrity state progression (ok vs degraded)",
            "Run context correlation (run_id, version)",
        ],
        "data_freshness": "Appended each time orchestrator_status is called",
        "limitations": [
            "Frequency depends on how often orchestrator_status is invoked",
            "No independent capture — only written during MCP calls",
        ],
    },
}

# Discrepancy examples: where data sources can diverge.
DISCREPANCY_EXAMPLES = [
    {
        "scenario": "Watchdog reports stale task, but core lease is valid",
        "sources": ["watchdog_jsonl", "orchestrator_status"],
        "explanation": "Watchdog uses updated_at age heuristic; core uses lease.expires_at. "
                       "A task with recent lease renewal but old updated_at can appear stale to watchdog.",
        "resolution": "Trust orchestrator_status for lease validity. Watchdog is informational only.",
    },
    {
        "scenario": "Audit log shows task claimed, but status shows assigned",
        "sources": ["audit_logs", "orchestrator_status"],
        "explanation": "If the claim call succeeded but a subsequent lease expiry recovery "
                       "requeued the task, the audit log retains the claim record but status reflects current state.",
        "resolution": "Trust orchestrator_status for current state. Use audit logs for historical tracing.",
    },
    {
        "scenario": "Events show agent connected, but active_agents list is empty",
        "sources": ["events_jsonl", "orchestrator_status"],
        "explanation": "Agent may have connected but heartbeat timed out. Events are immutable history; "
                       "active_agents is computed from current heartbeat freshness.",
        "resolution": "Trust orchestrator_status for liveness. Events show historical activity.",
    },
    {
        "scenario": "Status percentages differ between live_status and dashboard_percent",
        "sources": ["orchestrator_status"],
        "explanation": "live_status auto-calculates from done/total ratio. dashboard_percent "
                       "can be overridden by manager via args. They may diverge if manager sets custom values.",
        "resolution": "stats_provenance field indicates the source of each metric.",
    },
]


class DataSourceTrustMatrixTests(unittest.TestCase):
    """Validate data source trust matrix documentation."""

    def test_all_five_sources_documented(self) -> None:
        expected = {"orchestrator_status", "audit_logs", "watchdog_jsonl", "events_jsonl", "status_snapshots"}
        self.assertEqual(expected, set(DATA_SOURCE_TRUST_MATRIX.keys()))

    def test_each_source_has_required_fields(self) -> None:
        for name, source in DATA_SOURCE_TRUST_MATRIX.items():
            for field in ("description", "authoritative_for", "data_freshness", "limitations"):
                self.assertIn(field, source, f"{name} missing {field}")

    def test_authoritative_for_non_empty(self) -> None:
        for name, source in DATA_SOURCE_TRUST_MATRIX.items():
            self.assertGreater(len(source["authoritative_for"]), 0, f"{name} has empty authoritative_for")

    def test_limitations_non_empty(self) -> None:
        for name, source in DATA_SOURCE_TRUST_MATRIX.items():
            self.assertGreater(len(source["limitations"]), 0, f"{name} has empty limitations")

    def test_discrepancy_examples_defined(self) -> None:
        self.assertGreaterEqual(len(DISCREPANCY_EXAMPLES), 3)

    def test_each_discrepancy_has_resolution(self) -> None:
        for ex in DISCREPANCY_EXAMPLES:
            for field in ("scenario", "sources", "explanation", "resolution"):
                self.assertIn(field, ex)

    def test_matrix_json_serializable(self) -> None:
        serialized = json.dumps(DATA_SOURCE_TRUST_MATRIX)
        self.assertIsInstance(json.loads(serialized), dict)

    def test_discrepancies_json_serializable(self) -> None:
        serialized = json.dumps(DISCREPANCY_EXAMPLES)
        self.assertIsInstance(json.loads(serialized), list)


# ═══════════════════════════════════════════════════════════════════════
# TASK-8759477d: Dashboard gap analysis and MVP dashboard proposal
# ═══════════════════════════════════════════════════════════════════════

DASHBOARD_GAP_ANALYSIS = {
    "existing_visibility": [
        {"source": "orchestrator_status", "provides": "Task counts, agent list, instances, percentages, integrity"},
        {"source": "orchestrator_live_status_report", "provides": "Human-readable project summary text"},
        {"source": "orchestrator_list_audit_logs", "provides": "Tool call history with payloads"},
        {"source": "watchdog_loop.sh", "provides": "Periodic stale-task diagnostics and health checks"},
        {"source": "events.jsonl", "provides": "Task lifecycle and dispatch telemetry events"},
    ],
    "missing_pieces": [
        "No unified dashboard view combining all sources",
        "No real-time websocket/SSE push — requires polling",
        "No historical charting of progress over time",
        "No alert/notification system for blockers or bugs",
        "No diff view between consecutive status snapshots",
        "current_task_id not updated in agent_instances on claim",
    ],
    "mvp_proposal": {
        "format": "CLI/TUI (no web server needed for MVP)",
        "data_sources": [
            "orchestrator_status (primary — task counts, agents, instances)",
            "orchestrator_list_audit_logs (secondary — activity trail)",
            "watchdog JSONL (tertiary — external health perspective)",
        ],
        "mvp_scope": [
            "Real-time task status summary table",
            "Active agent list with instance details",
            "Open blockers and bugs list",
            "Project percentage with phase breakdown",
            "Last N audit log entries",
        ],
        "out_of_mvp_scope": [
            "Web dashboard",
            "Historical charting",
            "Real-time push notifications",
            "Multi-project aggregation",
        ],
        "alignment": "Restart milestone — uses only existing MCP tools, no new backend needed",
    },
}


class DashboardGapAnalysisTests(unittest.TestCase):
    """Validate dashboard gap analysis documentation."""

    def test_existing_visibility_non_empty(self) -> None:
        self.assertGreaterEqual(len(DASHBOARD_GAP_ANALYSIS["existing_visibility"]), 4)

    def test_missing_pieces_identified(self) -> None:
        self.assertGreaterEqual(len(DASHBOARD_GAP_ANALYSIS["missing_pieces"]), 4)

    def test_mvp_proposal_has_required_sections(self) -> None:
        proposal = DASHBOARD_GAP_ANALYSIS["mvp_proposal"]
        for field in ("format", "data_sources", "mvp_scope", "out_of_mvp_scope", "alignment"):
            self.assertIn(field, proposal)

    def test_mvp_scope_maps_to_existing_sources(self) -> None:
        """MVP scope should use only existing data sources."""
        sources = DASHBOARD_GAP_ANALYSIS["mvp_proposal"]["data_sources"]
        self.assertTrue(any("orchestrator_status" in s for s in sources))

    def test_gap_analysis_json_serializable(self) -> None:
        serialized = json.dumps(DASHBOARD_GAP_ANALYSIS)
        self.assertIsInstance(json.loads(serialized), dict)


# ═══════════════════════════════════════════════════════════════════════
# TASK-8f2649d2: Dashboard data schema proposal
# ═══════════════════════════════════════════════════════════════════════

DASHBOARD_SCHEMA = {
    "team_instances": {
        "description": "Agent instance rows for operator visibility",
        "fields": {
            "agent_name": {"type": "string", "source": "orchestrator_status.agent_instances"},
            "instance_id": {"type": "string", "source": "orchestrator_status.agent_instances"},
            "role": {"type": "string|null", "source": "orchestrator_status.agent_instances"},
            "status": {"type": "string", "source": "orchestrator_status.agent_instances", "values": ["active", "offline"]},
            "project_root": {"type": "string|null", "source": "orchestrator_status.agent_instances"},
            "current_task_id": {"type": "string|null", "source": "orchestrator_status.agent_instances", "gap": "Not updated on claim — future enhancement"},
            "last_seen": {"type": "ISO8601", "source": "orchestrator_status.agent_instances"},
        },
    },
    "task_summary": {
        "description": "Task status distribution",
        "fields": {
            "task_count": {"type": "integer", "source": "orchestrator_status.task_count"},
            "task_status_counts": {"type": "object", "source": "orchestrator_status.task_status_counts"},
            "overall_percent": {"type": "integer", "source": "orchestrator_status.live_status.overall_project_percent"},
        },
    },
    "blockers": {
        "description": "Open blockers requiring attention",
        "fields": {
            "id": {"type": "string", "source": "orchestrator_status via list_blockers"},
            "task_id": {"type": "string", "source": "blocker record"},
            "agent": {"type": "string", "source": "blocker record"},
            "question": {"type": "string", "source": "blocker record"},
            "severity": {"type": "string", "source": "blocker record"},
        },
    },
    "alerts": {
        "description": "Recent notable events for operator attention",
        "fields": {
            "event_type": {"type": "string", "source": "events.jsonl (filtered)"},
            "task_id": {"type": "string|null", "source": "event payload"},
            "timestamp": {"type": "ISO8601", "source": "event record"},
            "source": {"type": "string", "source": "event record"},
        },
        "filter_types": [
            "task.lease_expired_blocked",
            "task.reassigned_stale",
            "validation.failed",
            "dispatch.noop",
            "team_member.degraded_comm",
        ],
    },
    "activity_log": {
        "description": "Recent MCP tool calls from audit",
        "fields": {
            "tool_name": {"type": "string", "source": "audit.jsonl"},
            "status": {"type": "string", "source": "audit record", "values": ["ok", "error"]},
            "timestamp": {"type": "ISO8601", "source": "audit record"},
            "request_id": {"type": "string", "source": "audit record"},
        },
    },
}

# Fields requiring new backend work (gaps).
SCHEMA_GAPS = [
    {"field": "team_instances.current_task_id", "issue": "Not updated on claim/report transitions", "priority": "medium"},
    {"field": "alerts (filtered events)", "issue": "No built-in event filtering API — requires client-side filter", "priority": "low"},
    {"field": "task_summary.trend", "issue": "No historical trend endpoint — use status_snapshots JSONL", "priority": "low"},
]


class DashboardSchemaProposalTests(unittest.TestCase):
    """Validate dashboard data schema proposal."""

    def test_schema_covers_required_sections(self) -> None:
        for section in ("team_instances", "task_summary", "blockers", "alerts", "activity_log"):
            self.assertIn(section, DASHBOARD_SCHEMA)

    def test_each_section_has_fields_and_source(self) -> None:
        for name, section in DASHBOARD_SCHEMA.items():
            self.assertIn("description", section, f"{name} missing description")
            self.assertIn("fields", section, f"{name} missing fields")
            for field_name, field_def in section["fields"].items():
                self.assertIn("source", field_def, f"{name}.{field_name} missing source")

    def test_schema_maps_to_known_sources(self) -> None:
        """All source references should trace to known data sources."""
        known_sources = {"orchestrator_status", "audit", "events", "blocker", "event"}
        for name, section in DASHBOARD_SCHEMA.items():
            for field_name, field_def in section["fields"].items():
                source = field_def["source"].lower()
                has_known = any(k in source for k in known_sources)
                self.assertTrue(has_known, f"{name}.{field_name} source '{source}' not traceable")

    def test_gaps_documented(self) -> None:
        self.assertGreaterEqual(len(SCHEMA_GAPS), 2)

    def test_schema_json_serializable(self) -> None:
        serialized = json.dumps(DASHBOARD_SCHEMA)
        self.assertIsInstance(json.loads(serialized), dict)


# ═══════════════════════════════════════════════════════════════════════
# TASK-8ea5e8df: Status percent interpretation note
# ═══════════════════════════════════════════════════════════════════════

PERCENT_INTERPRETATION = {
    "overall_project_percent": {
        "description": "Auto-calculated ratio of done tasks to total tasks across all workstreams",
        "formula": "done_tasks / total_tasks * 100",
        "source": "orchestrator_status.live_status.overall_project_percent",
        "example": "If 50 of 200 tasks are done, overall_project_percent = 25%",
        "can_be_overridden": True,
        "override_mechanism": "Manager can pass overall_percent arg to live_status_report",
    },
    "milestone_percent": {
        "description": "Phase-specific progress (Phase 1: Architecture, Phase 2: Content, Phase 3: Production)",
        "formula": "Defaults to overall_project_percent; can be set independently per phase",
        "source": "orchestrator_status.live_status.phase_N_percent",
        "example": "Phase 1 may be 80% while overall is 25% — Phase 1 is nearly done but other phases haven't started",
        "can_be_overridden": True,
        "override_mechanism": "Manager passes phase_1_percent, phase_2_percent, phase_3_percent args",
    },
    "workstream_percent": {
        "description": "Per-workstream progress (backend, frontend, QA)",
        "formula": "workstream_done / workstream_total * 100",
        "source": "orchestrator_status.live_status.backend_percent / frontend_percent / qa_validation_percent",
        "example": "Backend at 60% and frontend at 10% means backend is further along",
        "can_be_overridden": True,
        "override_mechanism": "Manager passes backend_percent, frontend_percent, qa_percent args",
    },
}

DIVERGENCE_REASONS = [
    {
        "reason": "Phase progress vs overall progress",
        "example": "Phase 1 at 90% but overall at 30% — later phases have many uncompleted tasks",
        "guidance": "Focus on the phase relevant to current milestone (AUTO-M1 = Phase 1)",
    },
    {
        "reason": "Auto-calculated vs manager-overridden",
        "example": "Auto-calc shows 40% but manager sets 55% — manager accounts for partial task completion",
        "guidance": "Check stats_provenance.dashboard_percent field for source",
    },
    {
        "reason": "Backend vs frontend progress divergence",
        "example": "Backend at 70%, frontend at 5% — backend team active, frontend agent offline",
        "guidance": "Check active_agents to see if frontend worker is connected",
    },
    {
        "reason": "Task count inflation from auto-generated tasks",
        "example": "200 tasks but many are auto-generated stubs — done% looks low despite real work being complete",
        "guidance": "Filter by workstream or check task titles for AUTO- prefix to distinguish generated vs manual tasks",
    },
]


class PercentInterpretationTests(unittest.TestCase):
    """Validate percent interpretation documentation."""

    def test_three_percent_types_documented(self) -> None:
        for ptype in ("overall_project_percent", "milestone_percent", "workstream_percent"):
            self.assertIn(ptype, PERCENT_INTERPRETATION)

    def test_each_type_has_formula_and_example(self) -> None:
        for name, info in PERCENT_INTERPRETATION.items():
            for field in ("description", "formula", "source", "example"):
                self.assertIn(field, info, f"{name} missing {field}")

    def test_divergence_reasons_documented(self) -> None:
        self.assertGreaterEqual(len(DIVERGENCE_REASONS), 3)

    def test_each_divergence_has_guidance(self) -> None:
        for dr in DIVERGENCE_REASONS:
            for field in ("reason", "example", "guidance"):
                self.assertIn(field, dr)

    def test_auto_m1_checklist_reference(self) -> None:
        """At least one divergence reason should reference AUTO-M1."""
        texts = " ".join(dr["guidance"] for dr in DIVERGENCE_REASONS)
        self.assertIn("AUTO-M1", texts)

    def test_live_status_produces_percentages(self) -> None:
        """Engine should produce task counts usable for percentage calc."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            orch.create_task("T1", "backend", ["done"], owner="claude_code")
            orch.create_task("T2", "backend", ["done"], owner="claude_code")

            tasks = orch.list_tasks()
            total = len(tasks)
            done = len([t for t in tasks if t["status"] == "done"])
            self.assertEqual(2, total)
            self.assertEqual(0, done)
            # Auto-calc would be 0% since none done
            auto_percent = int(done / total * 100) if total > 0 else 0
            self.assertEqual(0, auto_percent)

    def test_interpretation_json_serializable(self) -> None:
        serialized = json.dumps(PERCENT_INTERPRETATION)
        self.assertIsInstance(json.loads(serialized), dict)
        serialized2 = json.dumps(DIVERGENCE_REASONS)
        self.assertIsInstance(json.loads(serialized2), list)


if __name__ == "__main__":
    unittest.main()
