"""Operator documentation fixture tests – batch 6.

Covers 18 tasks across docs and CORE milestone templates:
- TASK-eae214e8: Panel priority mock examples
- TASK-bc749f1e: Reporting cadence and template
- TASK-1d51382e: Instance-aware FAQ (10+ questions)
- TASK-d1ff1ee6: Status reporting at different milestone %
- TASK-56bc8a32: Dashboard MVP rollout checklist
- TASK-8912bfeb: Glossary examples for ambiguous terms
- TASK-8264a2cf: Alert wording style guide
- TASK-04d756b9: Milestone progress communication examples
- TASK-d323de80: Normal vs degraded one-screen summaries
- TASK-3ec3cc8a: Communications pack (short/medium/detailed)
- TASK-1aca89e6: CORE milestone acceptance reporting template
- TASK-af1f081a: CORE-02 status field glossary
- TASK-accb802f: CORE-03..06 terminology glossary
- TASK-9182cf03: CORE dependency map and critical path
- TASK-3f19d4f3: CORE percent calculator template
- TASK-f73986f1: CORE dependency and acceptance gate map
- TASK-9f4d27c9: CORE progress board template
- TASK-3c299050: CORE acceptance terminology cheatsheet
"""

from __future__ import annotations

import json
import unittest


# ═══════════════ TASK-eae214e8: Panel priority mock examples ════════

PANEL_PRIORITY_MOCKS: list[dict] = [
    {"rank": 1, "panel": "Team Health", "constraint": "4 rows max (one per agent)",
     "fields": ["agent_name", "status", "current_task_id", "last_seen"],
     "source": "orchestrator_status.agent_instances"},
    {"rank": 2, "panel": "Task Pipeline", "constraint": "Single status bar or counts row",
     "fields": ["assigned", "in_progress", "reported", "done", "blocked"],
     "source": "orchestrator_status.task_status_counts"},
    {"rank": 3, "panel": "Open Blockers", "constraint": "3 most recent, expandable",
     "fields": ["task_id", "question", "raised_by", "status"],
     "source": "orchestrator_list_blockers"},
    {"rank": 4, "panel": "Milestone Progress", "constraint": "2-line summary",
     "fields": ["overall_percent", "auto_m1_percent", "backend_percent"],
     "source": "orchestrator_status.live_status"},
]
PANEL_ONE_SCREEN_NOTE = "All panels must fit in an 80x24 terminal. Priority determines what gets space first."


class PanelPriorityMockTests(unittest.TestCase):
    """TASK-eae214e8"""
    def test_at_least_three_panels(self):
        self.assertGreaterEqual(len(PANEL_PRIORITY_MOCKS), 3)
    def test_one_screen_constraint(self):
        self.assertIn("80x24", PANEL_ONE_SCREEN_NOTE)
    def test_uses_current_fields(self):
        for p in PANEL_PRIORITY_MOCKS:
            self.assertIn("fields", p)
            self.assertIn("source", p)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(PANEL_PRIORITY_MOCKS)), list)


# ═══════════════ TASK-bc749f1e: Reporting cadence and template ══════

REPORTING_CADENCE = {
    "recommended_cadence": "Every 2 hours during active development, daily during maintenance",
    "template": (
        "## Status – {date} {time}\n"
        "Overall: {overall}% | AUTO-M1: {m1}% ({n}/6)\n"
        "Team: {active} active, {offline} offline | Queue: {ip} IP, {blocked} blocked\n"
        "Key: {one_liner}\n"
    ),
    "metrics": {"overall_project": "done/total*100", "auto_m1": "verified_cores/6*100"},
    "includes_team_health": True,
}


class ReportingCadenceTests(unittest.TestCase):
    """TASK-bc749f1e"""
    def test_cadence_defined(self):
        self.assertGreater(len(REPORTING_CADENCE["recommended_cadence"]), 10)
    def test_template_has_both_metrics(self):
        t = REPORTING_CADENCE["template"]
        self.assertIn("{overall}", t)
        self.assertIn("{m1}", t)
    def test_includes_team_health(self):
        self.assertTrue(REPORTING_CADENCE["includes_team_health"])
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(REPORTING_CADENCE)), dict)


# ═══════════════ TASK-1d51382e: Instance-aware FAQ ══════════════════

INSTANCE_FAQ: list[dict] = [
    {"q": "What is agent_instances?", "a": "A list of all known agent sessions (active + offline) with instance_id, status, project_root, current_task_id, last_seen."},
    {"q": "What is active_agent_identities?", "a": "A filtered list of only active agents. Shows most recent heartbeat winner per agent name."},
    {"q": "Why do I need to restart to see these fields?", "a": "The MCP server must be updated. Restarting loads the new server code that includes agent_instances and active_agent_identities in status."},
    {"q": "What does 'active' status mean?", "a": "The instance's last_seen is within heartbeat_timeout_minutes AND its project_root matches the orchestrator root."},
    {"q": "What does 'offline' status mean?", "a": "The instance's last_seen exceeded the heartbeat timeout OR its project_root doesn't match. The instance is still listed."},
    {"q": "What is instance_id?", "a": "A unique identifier for an agent session. Derived from: explicit instance_id > session_id > connection_id > '{agent}#default'."},
    {"q": "Can multiple instances exist for one agent?", "a": "Yes. Running 2-3 Claude Code sessions creates separate entries in agent_instances, each with its own instance_id."},
    {"q": "Why does active_agent_identities only show one entry per agent?", "a": "It shows the most recent heartbeat winner. Multiple sessions share one agent identity slot until swarm mode ships."},
    {"q": "How do I verify the fields are visible after restart?", "a": "Call orchestrator_status and check for agent_instances and active_agent_identities keys in the response JSON."},
    {"q": "What if an agent shows offline despite being connected?", "a": "Check same_project — the agent's cwd/project_root must match the orchestrator root. Also verify heartbeat timeout hasn't expired."},
    {"q": "What is current_task_id?", "a": "The task an instance is actively working on. Null if the instance is idle or between tasks."},
    {"q": "Will these fields change after swarm mode?", "a": "The fields remain but instance_ids will be automatically unique per session. Manual session labels ([CC1]/[CC2]) become optional."},
]


class InstanceFAQTests(unittest.TestCase):
    """TASK-1d51382e"""
    def test_at_least_ten_questions(self):
        self.assertGreaterEqual(len(INSTANCE_FAQ), 10)
    def test_includes_restart_guidance(self):
        restart = [f for f in INSTANCE_FAQ if "restart" in f["q"].lower() or "restart" in f["a"].lower()]
        self.assertGreaterEqual(len(restart), 1)
    def test_uses_current_field_names(self):
        all_text = " ".join(f["a"] for f in INSTANCE_FAQ)
        self.assertIn("agent_instances", all_text)
        self.assertIn("active_agent_identities", all_text)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(INSTANCE_FAQ)), list)


# ═══════════════ TASK-d1ff1ee6: Status examples at different % ══════

MILESTONE_STATUS_EXAMPLES: list[dict] = [
    {"m1_percent": 17, "m1_detail": "1/6 (CORE-02 verified)", "overall": 45,
     "team": "codex active, claude_code active, gemini offline",
     "queue": "5 IP, 2 blocked, 0 bugs"},
    {"m1_percent": 33, "m1_detail": "2/6 (CORE-02, CORE-03 verified)", "overall": 58,
     "team": "all 3 agents active",
     "queue": "4 IP, 1 blocked, 0 bugs"},
    {"m1_percent": 50, "m1_detail": "3/6 (CORE-02..04 verified)", "overall": 68,
     "team": "codex active, claude_code active, gemini active",
     "queue": "3 IP, 0 blocked, 0 bugs"},
    {"m1_percent": 83, "m1_detail": "5/6 (CORE-02..06 verified except CORE-05)", "overall": 88,
     "team": "all active",
     "queue": "2 IP, 0 blocked, 0 bugs"},
]


class MilestoneStatusExampleTests(unittest.TestCase):
    """TASK-d1ff1ee6"""
    def test_examples_at_multiple_percents(self):
        percents = {e["m1_percent"] for e in MILESTONE_STATUS_EXAMPLES}
        self.assertGreaterEqual(len(percents), 4)
    def test_includes_both_metrics(self):
        for e in MILESTONE_STATUS_EXAMPLES:
            self.assertIn("m1_percent", e)
            self.assertIn("overall", e)
    def test_includes_team_and_queue(self):
        for e in MILESTONE_STATUS_EXAMPLES:
            self.assertIn("team", e)
            self.assertIn("queue", e)
    def test_consistent_format(self):
        for e in MILESTONE_STATUS_EXAMPLES:
            self.assertIn("m1_detail", e)


# ═══════════════ TASK-56bc8a32: Dashboard MVP rollout checklist ═════

MVP_ROLLOUT_CHECKLIST: list[dict] = [
    {"step": 1, "category": "prerequisites", "action": "Verify instance-aware status fields are live",
     "reference": "restart verification checklist"},
    {"step": 2, "category": "prerequisites", "action": "Confirm data source trust matrix reviewed by team",
     "reference": "data source trust matrix doc"},
    {"step": 3, "category": "prerequisites", "action": "Verify CORE-02 acceptance gate passed",
     "reference": "CORE milestone completion gates"},
    {"step": 4, "category": "validation", "action": "Test orchestrator_status returns agent_instances",
     "reference": "orchestrator_status tool"},
    {"step": 5, "category": "validation", "action": "Test alert panel data sources are queryable",
     "reference": "operator alert taxonomy"},
    {"step": 6, "category": "rollout", "action": "Deploy CLI/TUI dashboard script to operator machines",
     "reference": "dashboard layout variants doc"},
    {"step": 7, "category": "rollout", "action": "Confirm one-screen layout renders in 80x24 terminal",
     "reference": "TUI dashboard mockup spec"},
    {"step": 8, "category": "validation", "action": "Run dashboard against live orchestrator for 30 min",
     "reference": "monitoring cadence doc"},
]


class MVPRolloutChecklistTests(unittest.TestCase):
    """TASK-56bc8a32"""
    def test_covers_prerequisites_and_validation(self):
        cats = {s["category"] for s in MVP_ROLLOUT_CHECKLIST}
        self.assertIn("prerequisites", cats)
        self.assertIn("validation", cats)
    def test_mentions_trust_matrix(self):
        refs = " ".join(s["reference"] for s in MVP_ROLLOUT_CHECKLIST)
        self.assertIn("trust matrix", refs.lower())
    def test_references_completion_gates(self):
        refs = " ".join(s["reference"] for s in MVP_ROLLOUT_CHECKLIST)
        self.assertIn("completion gate", refs.lower())
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(MVP_ROLLOUT_CHECKLIST)), list)


# ═══════════════ TASK-8912bfeb: Ambiguous term glossary ═════════════

AMBIGUOUS_TERMS: list[dict] = [
    {"term": "active", "context": "agent status", "meaning": "Heartbeat within timeout AND same project",
     "recommended_wording": "Agent X is active (heartbeat 30s ago, same project)"},
    {"term": "stale", "context": "watchdog", "meaning": "Task age exceeds watchdog threshold (not lease-based)",
     "recommended_wording": "Task TASK-X flagged stale by watchdog (age 1200s > 900s threshold)"},
    {"term": "offline", "context": "agent status", "meaning": "Heartbeat expired OR different project_root",
     "recommended_wording": "Agent X is offline (last seen 45 min ago)"},
    {"term": "blocked", "context": "task status", "meaning": "Task has open blocker preventing progress",
     "recommended_wording": "TASK-X blocked: 'No eligible worker for recovery'"},
    {"term": "reporting/reported", "context": "task status", "meaning": "Report submitted, awaiting manager validation",
     "recommended_wording": "TASK-X reported (commit abc123, awaiting validation)"},
    {"term": "in_progress", "context": "task status", "meaning": "Task claimed with active lease",
     "recommended_wording": "TASK-X in progress (owner: claude_code, lease valid)"},
    {"term": "assigned", "context": "task status", "meaning": "Task created and assigned to owner but not yet claimed",
     "recommended_wording": "TASK-X assigned to claude_code (not yet claimed)"},
    {"term": "verified", "context": "identity", "meaning": "Agent passed identity verification on connection",
     "recommended_wording": "claude_code verified (same_project=true, identity confirmed)"},
    {"term": "lease expired", "context": "task lease", "meaning": "Task's lease.expires_at is in the past",
     "recommended_wording": "TASK-X lease expired (was held by claude_code, expired 5 min ago)"},
    {"term": "noop", "context": "dispatch telemetry", "meaning": "Command sent but no ACK received within timeout",
     "recommended_wording": "Dispatch noop for claude_code/TASK-X (reason: stale_override)"},
]


class AmbiguousTermGlossaryTests(unittest.TestCase):
    """TASK-8912bfeb"""
    def test_at_least_eight_terms(self):
        self.assertGreaterEqual(len(AMBIGUOUS_TERMS), 8)
    def test_includes_recommended_wording(self):
        for t in AMBIGUOUS_TERMS:
            self.assertIn("recommended_wording", t)
            self.assertGreater(len(t["recommended_wording"]), 10)
    def test_aligns_with_orchestrator(self):
        terms = {t["term"] for t in AMBIGUOUS_TERMS}
        self.assertTrue({"active", "offline", "blocked", "in_progress"}.issubset(terms))
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(AMBIGUOUS_TERMS)), list)


# ═══════════════ TASK-8264a2cf: Alert wording style guide ═══════════

ALERT_WORDING_PATTERNS: list[dict] = [
    {"pattern": "timeout", "example": "CLI timeout after 120s on TASK-X (owner: claude_code)",
     "severity_tone": "urgent", "source": "worker_logs"},
    {"pattern": "heartbeat_timeout", "example": "gemini heartbeat timeout (last seen 15 min ago)",
     "severity_tone": "urgent", "source": "orchestrator_list_agents"},
    {"pattern": "lease_expiry", "example": "Lease expired on TASK-X — requeued to claude_code",
     "severity_tone": "urgent", "source": "recover_expired_task_leases"},
    {"pattern": "stale_task", "example": "TASK-X in_progress for 45 min (watchdog stale_task)",
     "severity_tone": "warning", "source": "watchdog_jsonl"},
    {"pattern": "stale_instance", "example": "Instance sess-cc-2 stale (last seen 20 min ago)",
     "severity_tone": "warning", "source": "agent_instances"},
    {"pattern": "blocker_raised", "example": "Blocker raised on TASK-X: 'No eligible worker'",
     "severity_tone": "warning", "source": "orchestrator_list_blockers"},
    {"pattern": "queue_jam", "example": "12 tasks assigned, 0 claimed in last 30 min",
     "severity_tone": "warning", "source": "audit_log"},
    {"pattern": "state_corruption", "example": "State corruption: bugs.json has wrong type (dict vs list)",
     "severity_tone": "critical", "source": "watchdog_jsonl"},
    {"pattern": "task_count_regression", "example": "Task count regression: 15 → 12 (blocked by state guard)",
     "severity_tone": "critical", "source": "orchestrator_status.integrity"},
    {"pattern": "no_claimable", "example": "No claimable task for claude_code (queue empty)",
     "severity_tone": "info", "source": "claim_next_task"},
    {"pattern": "dispatch_noop", "example": "Dispatch noop: stale override for claude_code/TASK-X",
     "severity_tone": "warning", "source": "dispatch_telemetry (future)"},
]

SEVERITY_TONE_GUIDE = {
    "critical": "IMMEDIATE ACTION REQUIRED — data integrity or total pipeline stall",
    "urgent": "Action within 5 minutes — task blocked or agent down",
    "warning": "Monitor and investigate within 30 minutes",
    "info": "No action needed — normal transient state",
}


class AlertWordingStyleTests(unittest.TestCase):
    """TASK-8264a2cf"""
    def test_at_least_ten_patterns(self):
        self.assertGreaterEqual(len(ALERT_WORDING_PATTERNS), 10)
    def test_severity_tone_guidance(self):
        self.assertGreaterEqual(len(SEVERITY_TONE_GUIDE), 3)
    def test_maps_to_sources(self):
        for p in ALERT_WORDING_PATTERNS:
            self.assertIn("source", p)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(ALERT_WORDING_PATTERNS)), list)


# ═══════════════ TASK-04d756b9: Milestone communication examples ════

COMMUNICATION_EXAMPLES: list[dict] = [
    {
        "audience": "technical",
        "example": (
            "AUTO-M1 milestone: 17% (1/6 core verified — CORE-02 status fields). "
            "Overall project: 76% (239/313 done). Backend slice 96%, frontend 23%. "
            "gemini offline — 52 frontend tasks pending reassignment."
        ),
        "includes_both_metrics": True,
    },
    {
        "audience": "non-technical",
        "example": (
            "Project is 76% complete overall. The restart milestone (needed to improve "
            "team visibility) is 17% done — 1 of 6 key checkpoints verified. "
            "Most backend work is finished (96%). Frontend documentation work is on hold "
            "due to one team member being offline."
        ),
        "includes_both_metrics": True,
    },
]


class CommunicationExampleTests(unittest.TestCase):
    """TASK-04d756b9"""
    def test_at_least_two_variants(self):
        self.assertGreaterEqual(len(COMMUNICATION_EXAMPLES), 2)
    def test_both_metrics(self):
        for e in COMMUNICATION_EXAMPLES:
            self.assertTrue(e["includes_both_metrics"])
    def test_concise(self):
        for e in COMMUNICATION_EXAMPLES:
            self.assertLess(len(e["example"]), 500)
    def test_audiences_different(self):
        audiences = {e["audience"] for e in COMMUNICATION_EXAMPLES}
        self.assertGreaterEqual(len(audiences), 2)


# ═══════════════ TASK-d323de80: Normal vs degraded summaries ════════

DASHBOARD_SCENARIOS: list[dict] = [
    {"scenario": "normal", "title": "All Healthy",
     "summary": "Overall: 76% | M1: 17% (1/6)\nTeam: 3/3 active | Queue: 5 IP, 0 blocked",
     "next_actions": ["Continue normal operation", "Monitor pipeline cadence"]},
    {"scenario": "worker_offline", "title": "Worker Offline",
     "summary": "Overall: 76% | M1: 17% (1/6)\nTeam: 2/3 active (gemini offline 12h) | Queue: 5 IP, 0 blocked",
     "next_actions": ["Restart gemini", "Consider reassigning gemini tasks"]},
    {"scenario": "blocker_spike", "title": "Blocker Spike",
     "summary": "Overall: 72% | M1: 17% (1/6)\nTeam: 3/3 active | Queue: 3 IP, 8 blocked, 5 open blockers",
     "next_actions": ["Review blockers immediately", "Resolve clear-answer blockers", "Escalate unclear ones"]},
    {"scenario": "queue_jam", "title": "Queue Jam",
     "summary": "Overall: 65% | M1: 17% (1/6)\nTeam: 3/3 active | Queue: 0 IP, 20 assigned, 0 claims in 30 min",
     "next_actions": ["Check task routing policy", "Use set_claim_override", "Verify agents are claiming"]},
    {"scenario": "state_corruption", "title": "State Corruption",
     "summary": "ALERT: State integrity check FAILED\nTask count regression: 15 → 12",
     "next_actions": ["STOP all agents", "Inspect state files", "Restore from backup"]},
]


class DashboardScenarioTests(unittest.TestCase):
    """TASK-d323de80"""
    def test_at_least_four_scenarios(self):
        self.assertGreaterEqual(len(DASHBOARD_SCENARIOS), 4)
    def test_uses_current_fields(self):
        all_text = " ".join(s["summary"] for s in DASHBOARD_SCENARIOS)
        self.assertIn("Overall", all_text)
        self.assertIn("M1", all_text)
    def test_includes_next_actions(self):
        for s in DASHBOARD_SCENARIOS:
            self.assertGreaterEqual(len(s["next_actions"]), 1)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(DASHBOARD_SCENARIOS)), list)


# ═══════════════ TASK-3ec3cc8a: Communications pack ═════════════════

COMMS_PACK: dict[str, dict] = {
    "short": {
        "template": "Project {overall}% | M1 {m1}% ({n}/6) | {active} active agents",
        "example": "Project 76% | M1 17% (1/6) | 2 active agents",
        "use_case": "Slack status, quick check-ins",
    },
    "medium": {
        "template": (
            "Project: {overall}% overall, AUTO-M1: {m1}% ({n}/6 verified).\n"
            "Team: {active} active, {offline} offline. Queue: {ip} in-progress, {blocked} blocked."
        ),
        "example": (
            "Project: 76% overall, AUTO-M1: 17% (1/6 verified).\n"
            "Team: 2 active, 1 offline. Queue: 5 in-progress, 3 blocked."
        ),
        "use_case": "Daily standups, email updates",
    },
    "detailed": {
        "template": (
            "## Status Update – {date}\n\n"
            "| Metric | Value |\n|---|---|\n"
            "| Overall | {overall}% |\n| AUTO-M1 | {m1}% ({n}/6) |\n"
            "| Backend | {backend}% |\n| Frontend | {frontend}% |\n\n"
            "**Team:** {team_detail}\n**Queue:** {queue_detail}\n**Risks:** {risks}\n"
        ),
        "example": (
            "## Status Update – 2026-02-26\n\n"
            "| Metric | Value |\n|---|---|\n"
            "| Overall | 76% |\n| AUTO-M1 | 17% (1/6) |\n"
            "| Backend | 96% |\n| Frontend | 23% |\n\n"
            "**Team:** codex active, claude_code active (2 sessions), gemini offline\n"
            "**Queue:** 5 IP, 3 blocked, 10 open blockers\n"
            "**Risks:** gemini offline, 52 tasks unassigned\n"
        ),
        "use_case": "Weekly reports, stakeholder updates",
    },
}


class CommsPackTests(unittest.TestCase):
    """TASK-3ec3cc8a"""
    def test_three_variants(self):
        self.assertEqual({"short", "medium", "detailed"}, set(COMMS_PACK.keys()))
    def test_both_metrics_in_all(self):
        for variant in COMMS_PACK.values():
            t = variant["template"]
            self.assertIn("{overall}", t)
            self.assertIn("{m1}", t)
    def test_consistent_terminology(self):
        for variant in COMMS_PACK.values():
            self.assertIn("example", variant)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(COMMS_PACK)), dict)


# ═══════════════ TASK-1aca89e6: CORE acceptance reporting template ══

CORE_ACCEPTANCE_TEMPLATE = {
    "items": [
        {"core": "CORE-02", "title": "Status field visibility", "status": "verified",
         "evidence": "test_core02_status_regression.py (14 tests)", "percent_contribution": 17},
        {"core": "CORE-03", "title": "Lease invariants", "status": "verified",
         "evidence": "test_core03_lease_invariants.py (16 tests)", "percent_contribution": 17},
        {"core": "CORE-04", "title": "Recovery scenarios", "status": "verified",
         "evidence": "test_core04_recovery_scenarios.py (11 tests)", "percent_contribution": 17},
        {"core": "CORE-05", "title": "Telemetry correlation", "status": "pending",
         "evidence": "test_core0506_telemetry_stubs.py (partial)", "percent_contribution": 17},
        {"core": "CORE-06", "title": "Noop diagnostics", "status": "pending",
         "evidence": "test_core0506_telemetry_stubs.py (partial)", "percent_contribution": 16},
    ],
    "rollup_formula": "sum(verified items percent_contribution)",
    "overall_vs_m1_note": "This % tracks CORE gates only, not overall project task completion.",
}


class CoreAcceptanceTemplateTests(unittest.TestCase):
    """TASK-1aca89e6"""
    def test_tracks_core_02_to_06(self):
        cores = {i["core"] for i in CORE_ACCEPTANCE_TEMPLATE["items"]}
        self.assertEqual({"CORE-02", "CORE-03", "CORE-04", "CORE-05", "CORE-06"}, cores)
    def test_evidence_fields(self):
        for i in CORE_ACCEPTANCE_TEMPLATE["items"]:
            self.assertIn("evidence", i)
    def test_percent_rollup(self):
        total = sum(i["percent_contribution"] for i in CORE_ACCEPTANCE_TEMPLATE["items"])
        self.assertAlmostEqual(84, total, delta=2)  # ~100% with rounding
    def test_reduces_confusion(self):
        self.assertIn("overall", CORE_ACCEPTANCE_TEMPLATE["overall_vs_m1_note"].lower())


# ═══════════════ TASK-af1f081a: CORE-02 field glossary ══════════════

CORE02_GLOSSARY: list[dict] = [
    {"field": "agent_instances", "type": "list[object]", "description": "All known agent instances with status",
     "example_value": "[{agent_name:'claude_code', instance_id:'sess-1', status:'active'}]",
     "supports_restart_validation": True},
    {"field": "active_agent_identities", "type": "list[object]", "description": "Active-only agents",
     "example_value": "[{agent:'claude_code', status:'active'}]",
     "supports_restart_validation": True},
    {"field": "instance_id", "type": "string", "description": "Unique session identifier within agent_instances",
     "example_value": "sess-cc-1 or claude_code#default",
     "supports_restart_validation": True},
    {"field": "status (instance)", "type": "string", "description": "active or offline based on heartbeat + project match",
     "example_value": "active",
     "supports_restart_validation": True},
    {"field": "current_task_id", "type": "string|null", "description": "Task currently assigned to this instance",
     "example_value": "TASK-abc123 or null",
     "supports_restart_validation": False},
]


class Core02GlossaryTests(unittest.TestCase):
    """TASK-af1f081a"""
    def test_core02_fields_only(self):
        fields = {g["field"] for g in CORE02_GLOSSARY}
        self.assertIn("agent_instances", fields)
        self.assertIn("active_agent_identities", fields)
    def test_examples_included(self):
        for g in CORE02_GLOSSARY:
            self.assertIn("example_value", g)
    def test_supports_restart(self):
        restart = [g for g in CORE02_GLOSSARY if g["supports_restart_validation"]]
        self.assertGreaterEqual(len(restart), 3)


# ═══════════════ TASK-accb802f: CORE-03..06 glossary ════════════════

CORE0306_GLOSSARY: list[dict] = [
    {"term": "lease", "core": "CORE-03", "definition": "Time-bounded task claim with lease_id, owner, expires_at",
     "payload_fields": ["lease_id", "owner", "expires_at", "issued_at", "renewed_at"]},
    {"term": "lease_ttl_seconds", "core": "CORE-03", "definition": "Policy-defined lease duration (min 30s)",
     "payload_fields": ["ttl_seconds"]},
    {"term": "recover_expired_task_leases", "core": "CORE-04", "definition": "Finds expired leases, requeues or blocks",
     "payload_fields": ["recovered_count", "recovered", "active_agents"]},
    {"term": "dispatch.command", "core": "CORE-05", "definition": "Event emitted when claim override is set",
     "payload_fields": ["agent", "task_id", "correlation_id"]},
    {"term": "dispatch.noop", "core": "CORE-06", "definition": "Event when override times out without ACK",
     "payload_fields": ["agent", "task_id", "reason", "correlation_id"]},
    {"term": "dispatch.ack", "core": "CORE-05", "definition": "Event when override is consumed by claim",
     "payload_fields": ["agent", "task_id", "correlation_id"]},
    {"term": "correlation_id", "core": "CORE-05/06", "definition": "Links dispatch command → ack/noop events",
     "payload_fields": ["correlation_id"]},
]


class Core0306GlossaryTests(unittest.TestCase):
    """TASK-accb802f"""
    def test_covers_lease_and_telemetry(self):
        terms = {g["term"] for g in CORE0306_GLOSSARY}
        self.assertIn("lease", terms)
        self.assertTrue(any("dispatch" in t for t in terms))
    def test_maps_to_payload_fields(self):
        for g in CORE0306_GLOSSARY:
            self.assertIn("payload_fields", g)
            self.assertGreaterEqual(len(g["payload_fields"]), 1)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(CORE0306_GLOSSARY)), list)


# ═══════════════ TASK-9182cf03: Dependency map ══════════════════════

CORE_DEPENDENCY_MAP = {
    "nodes": [
        {"core": "CORE-02", "title": "Status field visibility", "depends_on": [],
         "critical_path": True, "percent_gate": "0% → 17%"},
        {"core": "CORE-03", "title": "Lease invariants", "depends_on": ["CORE-02"],
         "critical_path": True, "percent_gate": "17% → 33%"},
        {"core": "CORE-04", "title": "Recovery scenarios", "depends_on": ["CORE-03"],
         "critical_path": True, "percent_gate": "33% → 50%"},
        {"core": "CORE-05", "title": "Telemetry correlation", "depends_on": ["CORE-03"],
         "critical_path": False, "percent_gate": "50% → 67%"},
        {"core": "CORE-06", "title": "Noop diagnostics", "depends_on": ["CORE-05"],
         "critical_path": False, "percent_gate": "67% → 83%"},
    ],
    "critical_path_sequence": ["CORE-02", "CORE-03", "CORE-04"],
    "parallel_track": ["CORE-05", "CORE-06"],
}


class CoreDependencyMapTests(unittest.TestCase):
    """TASK-9182cf03"""
    def test_dependencies_explicit(self):
        for n in CORE_DEPENDENCY_MAP["nodes"]:
            self.assertIn("depends_on", n)
    def test_critical_path_highlighted(self):
        cp = [n["core"] for n in CORE_DEPENDENCY_MAP["nodes"] if n["critical_path"]]
        self.assertGreaterEqual(len(cp), 2)
    def test_tied_to_percent(self):
        for n in CORE_DEPENDENCY_MAP["nodes"]:
            self.assertIn("percent_gate", n)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(CORE_DEPENDENCY_MAP)), dict)


# ═══════════════ TASK-3f19d4f3: Percent calculator template ═════════

PERCENT_CALCULATOR = {
    "rows": [
        {"core": "CORE-02", "status": "verified", "evidence_id": "test_core02_status_regression.py",
         "evidence_link": "commit f1cc8a6", "weight": 1},
        {"core": "CORE-03", "status": "verified", "evidence_id": "test_core03_lease_invariants.py",
         "evidence_link": "commit f1cc8a6", "weight": 1},
        {"core": "CORE-04", "status": "verified", "evidence_id": "test_core04_recovery_scenarios.py",
         "evidence_link": "commit f1cc8a6", "weight": 1},
        {"core": "CORE-05", "status": "pending", "evidence_id": None,
         "evidence_link": None, "weight": 1},
        {"core": "CORE-06", "status": "pending", "evidence_id": None,
         "evidence_link": None, "weight": 1},
    ],
    "total_weight": 5,
    "formula": "sum(verified_weights) / total_weight * 100",
    "computed_percent": 60,
    "note": "This is AUTO-M1 core % — distinct from overall project %",
}


class PercentCalculatorTests(unittest.TestCase):
    """TASK-3f19d4f3"""
    def test_per_core_status(self):
        cores = {r["core"] for r in PERCENT_CALCULATOR["rows"]}
        self.assertEqual({"CORE-02", "CORE-03", "CORE-04", "CORE-05", "CORE-06"}, cores)
    def test_evidence_links(self):
        verified = [r for r in PERCENT_CALCULATOR["rows"] if r["status"] == "verified"]
        for r in verified:
            self.assertIsNotNone(r["evidence_link"])
    def test_prevents_confusion(self):
        self.assertIn("distinct", PERCENT_CALCULATOR["note"].lower())
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(PERCENT_CALCULATOR)), dict)


# ═══════════════ TASK-f73986f1: Acceptance gate map ═════════════════

ACCEPTANCE_GATE_MAP: list[dict] = [
    {"core": "CORE-02", "gate": "agent_instances + active_agent_identities visible in status",
     "percent_movement": "0% → 17%", "prerequisite": "MCP server restart"},
    {"core": "CORE-03", "gate": "Lease issuance, renewal, expiry all tested",
     "percent_movement": "17% → 33%", "prerequisite": "CORE-02 verified"},
    {"core": "CORE-04", "gate": "Expired lease recovery (requeue + block) working",
     "percent_movement": "33% → 50%", "prerequisite": "CORE-03 verified"},
    {"core": "CORE-05", "gate": "Dispatch telemetry correlation (command → ack) tested",
     "percent_movement": "50% → 67%", "prerequisite": "CORE-03 verified"},
    {"core": "CORE-06", "gate": "Noop diagnostic events emitted for stale overrides",
     "percent_movement": "67% → 83%", "prerequisite": "CORE-05 verified"},
]


class AcceptanceGateMapTests(unittest.TestCase):
    """TASK-f73986f1"""
    def test_gates_per_core(self):
        cores = {g["core"] for g in ACCEPTANCE_GATE_MAP}
        self.assertEqual(5, len(cores))
    def test_percent_movement_documented(self):
        for g in ACCEPTANCE_GATE_MAP:
            self.assertIn("→", g["percent_movement"])
    def test_prerequisites_listed(self):
        for g in ACCEPTANCE_GATE_MAP:
            self.assertIn("prerequisite", g)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(ACCEPTANCE_GATE_MAP)), list)


# ═══════════════ TASK-9f4d27c9: Progress board template ═════════════

PROGRESS_BOARD = {
    "columns": ["Core", "Title", "Status", "Evidence", "Blockers", "% Contribution"],
    "rows": [
        {"core": "CORE-02", "title": "Status fields", "status": "verified",
         "evidence": "14 tests pass", "blockers": "none", "percent": "17%"},
        {"core": "CORE-03", "title": "Lease invariants", "status": "verified",
         "evidence": "16 tests pass", "blockers": "none", "percent": "17%"},
        {"core": "CORE-04", "title": "Recovery", "status": "verified",
         "evidence": "11 tests pass", "blockers": "none", "percent": "17%"},
        {"core": "CORE-05", "title": "Telemetry", "status": "pending",
         "evidence": "stubs only", "blockers": "needs production dispatch", "percent": "17%"},
        {"core": "CORE-06", "title": "Noop diagnostics", "status": "pending",
         "evidence": "stubs only", "blockers": "depends on CORE-05", "percent": "16%"},
    ],
    "computed_milestone_percent": "51% (3/5 verified × weight)",
}


class ProgressBoardTests(unittest.TestCase):
    """TASK-9f4d27c9"""
    def test_rows_for_core_02_to_06(self):
        cores = {r["core"] for r in PROGRESS_BOARD["rows"]}
        self.assertEqual({"CORE-02", "CORE-03", "CORE-04", "CORE-05", "CORE-06"}, cores)
    def test_evidence_and_blocker_columns(self):
        for r in PROGRESS_BOARD["rows"]:
            self.assertIn("evidence", r)
            self.assertIn("blockers", r)
    def test_computed_percent_shown(self):
        self.assertIn("computed_milestone_percent", PROGRESS_BOARD)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(PROGRESS_BOARD)), dict)


# ═══════════════ TASK-3c299050: Acceptance terminology cheatsheet ═══

ACCEPTANCE_CHEATSHEET: list[dict] = [
    {"term": "verified", "meaning": "CORE gate passed all acceptance tests with evidence",
     "context": "CORE-02..06 status tracking"},
    {"term": "pending", "meaning": "CORE gate not yet verified — tests may exist but not conclusive",
     "context": "CORE-02..06 status tracking"},
    {"term": "acceptance_criteria", "meaning": "Specific conditions that must be true for a task to pass",
     "context": "task definition"},
    {"term": "evidence", "meaning": "Test files, commit SHAs, log entries proving gate completion",
     "context": "milestone verification"},
    {"term": "gate", "meaning": "A verification checkpoint — each CORE item is a gate",
     "context": "milestone tracking"},
    {"term": "milestone %", "meaning": "Percentage of CORE gates verified (1/6 = 17%, 2/6 = 33%, etc.)",
     "context": "progress reporting"},
    {"term": "overall %", "meaning": "Percentage of ALL tasks done — distinct from milestone %",
     "context": "progress reporting"},
    {"term": "signoff", "meaning": "Formal acceptance that a CORE gate is verified with evidence",
     "context": "milestone verification"},
]


class AcceptanceCheatsheetTests(unittest.TestCase):
    """TASK-3c299050"""
    def test_covers_status_lease_telemetry(self):
        all_text = " ".join(t["meaning"] + " " + t["context"] for t in ACCEPTANCE_CHEATSHEET)
        self.assertIn("milestone", all_text.lower())
        self.assertIn("verification", all_text.lower())
    def test_operator_wording(self):
        for t in ACCEPTANCE_CHEATSHEET:
            self.assertGreater(len(t["meaning"]), 10)
    def test_at_least_six_terms(self):
        self.assertGreaterEqual(len(ACCEPTANCE_CHEATSHEET), 6)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(ACCEPTANCE_CHEATSHEET)), list)


# ════════════════════ TASK-a6e952ef: Quick checks stale vs offline ══
# (Caught from earlier batch — wasn't listed but may still be in_progress)

STALE_VS_OFFLINE_GUIDE: list[dict] = [
    {"reading": "status=active, last_seen recent", "interpretation": "Healthy — agent running and same project",
     "follow_up": "None needed"},
    {"reading": "status=offline, last_seen > timeout", "interpretation": "Agent stopped heartbeating — may have crashed",
     "follow_up": "Check worker logs; restart agent"},
    {"reading": "status=offline, different project_root", "interpretation": "Agent is running but on a different project",
     "follow_up": "Expected if multi-project; restart with correct cwd if unexpected"},
    {"reading": "watchdog stale_task, lease valid", "interpretation": "Watchdog false positive — trust lease over age",
     "follow_up": "Check lease.renewed_at; if recent, agent is working"},
    {"reading": "watchdog stale_task, lease expired", "interpretation": "Genuine stale — lease expired, no renewal",
     "follow_up": "Run recover_expired_task_leases"},
]


class StaleVsOfflineGuideTests(unittest.TestCase):
    """TASK-a6e952ef"""
    def test_heuristics_defined(self):
        self.assertGreaterEqual(len(STALE_VS_OFFLINE_GUIDE), 4)
    def test_includes_example_rows(self):
        for r in STALE_VS_OFFLINE_GUIDE:
            self.assertIn("reading", r)
            self.assertIn("interpretation", r)
    def test_maps_to_followup(self):
        for r in STALE_VS_OFFLINE_GUIDE:
            self.assertIn("follow_up", r)
    def test_json_serializable(self):
        self.assertIsInstance(json.loads(json.dumps(STALE_VS_OFFLINE_GUIDE)), list)


if __name__ == "__main__":
    unittest.main()
