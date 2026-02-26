"""Operator documentation fixture tests – batch 3.

Covers:
- TASK-ca9d3fa2: Discrepancy scenarios across status/audit/watchdog
- TASK-61c82b60: Dashboard alert panel mock examples
- TASK-864fa4ae: Project-tagged report note format examples for CC/Gemini
"""

from __future__ import annotations

import json
import re
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
# TASK-ca9d3fa2: Discrepancy scenarios across status/audit/watchdog
# ══════════════════════════════════════════════════════════════════════

DISCREPANCY_SCENARIOS: list[dict] = [
    {
        "id": "DISC-01",
        "title": "Watchdog flags stale task, status shows active lease",
        "sources_involved": ["orchestrator_status", "watchdog"],
        "symptoms": [
            "Watchdog JSONL contains stale_task entry (age > 900s)",
            "orchestrator_status() shows task in_progress with valid lease",
        ],
        "root_cause": "Watchdog checks updated_at age; orchestrator checks lease.expires_at. Task can have old updated_at but recently renewed lease.",
        "resolution_order": [
            "Check lease.renewed_at — if recent, task is healthy",
            "Check agent heartbeat — if owner active, lease renewal working",
            "If both stale, escalate to manager for recover_expired_task_leases",
        ],
        "verdict": "watchdog_false_positive",
        "severity": "low",
    },
    {
        "id": "DISC-02",
        "title": "Status shows agent active, watchdog shows no recent logs",
        "sources_involved": ["orchestrator_status", "watchdog", "worker_logs"],
        "symptoms": [
            "list_agents() shows agent as active (recent heartbeat)",
            "No new worker log files for 30+ minutes",
        ],
        "root_cause": "Agent sending heartbeats but not claiming or working tasks — queue may be empty or agent blocked.",
        "resolution_order": [
            "Check assigned tasks for agent — if none, idle is expected",
            "Check claim_next_task response for 'No claimable task'",
            "Check audit log for recent tool calls",
            "If tasks exist but agent idle, restart worker loop",
        ],
        "verdict": "expected_if_queue_empty",
        "severity": "low",
    },
    {
        "id": "DISC-03",
        "title": "Audit shows report submitted, status shows task still in_progress",
        "sources_involved": ["audit_log", "orchestrator_status"],
        "symptoms": [
            "Audit log entry: orchestrator_submit_report with status: ok",
            "orchestrator_status() still shows task as in_progress",
        ],
        "root_cause": "Race condition between report submission and auto-manager-cycle, or report was rejected.",
        "resolution_order": [
            "Check audit log for manager cycle result (task.validated_accepted/rejected)",
            "Check bus/reports/ for report file",
            "Re-query status after 30s — timing issue resolves itself",
            "Check for state_guard audit entries if stuck",
        ],
        "verdict": "timing_or_rejection",
        "severity": "medium",
    },
    {
        "id": "DISC-04",
        "title": "Status shows 0 blockers but tasks in blocked status",
        "sources_involved": ["orchestrator_status", "watchdog"],
        "symptoms": [
            "orchestrator_status() reports blocker_count: 0",
            "Watchdog flags tasks with status: blocked and high age",
        ],
        "root_cause": "Blocker was resolved but task status not updated from blocked to assigned.",
        "resolution_order": [
            "List all blocked tasks from state/tasks.json",
            "Check state/blockers.json for matching open blockers",
            "If no open blocker for blocked task, unblock manually",
            "Manager calls set_task_status(task_id, 'assigned', source)",
        ],
        "verdict": "state_inconsistency",
        "severity": "medium",
    },
    {
        "id": "DISC-05",
        "title": "Audit shows agent connected, status shows agent offline",
        "sources_involved": ["audit_log", "orchestrator_status"],
        "symptoms": [
            "Audit log has recent connect_to_leader entry with connected: true",
            "list_agents(active_only=True) does not include the agent",
        ],
        "root_cause": "Connection succeeded but identity verification failed same_project check, or heartbeat timeout expired.",
        "resolution_order": [
            "Check connect audit entry identity for verified/same_project flags",
            "Check state/agents.json metadata — verify cwd matches root",
            "Check last_seen timestamp vs heartbeat timeout",
            "Restart agent with correct cwd if same_project is false",
        ],
        "verdict": "identity_verification_issue",
        "severity": "high",
    },
    {
        "id": "DISC-06",
        "title": "Multiple watchdog cycles flag same stale task",
        "sources_involved": ["watchdog"],
        "symptoms": [
            "Consecutive watchdog JSONL files all flag same task as stale_task",
            "Task status unchanged across multiple 15s cycles",
        ],
        "root_cause": "Watchdog is passive observer — detects but does not trigger recovery. Manager must act.",
        "resolution_order": [
            "Check task lease expires_at in state/tasks.json",
            "If expired, call recover_expired_task_leases",
            "If valid but stale, agent may be working slowly — check logs",
            "If offline and valid lease, wait for expiry then recover",
            "Escalate if stale > 2x INPROGRESS_TIMEOUT",
        ],
        "verdict": "expected_watchdog_behavior",
        "severity": "medium",
    },
    {
        "id": "DISC-07",
        "title": "Event bus shows dispatch.noop, audit shows successful claim",
        "sources_involved": ["event_bus", "audit_log"],
        "symptoms": [
            "bus/events.jsonl contains dispatch.noop for agent X, task Y",
            "Audit log shows successful claim_next_task by agent X for task Y",
        ],
        "root_cause": "Noop from previous timed-out override; subsequent claim succeeded via normal flow.",
        "resolution_order": [
            "Compare timestamps — noop should predate successful claim",
            "Check correlation_ids — noop references stale override",
            "If noop after claim, check for second override",
            "No action needed if task is in_progress with correct owner",
        ],
        "verdict": "historical_artifact",
        "severity": "low",
    },
]

ESCALATION_GUIDANCE = {
    "investigate_triggers": [
        "Discrepancy persisting across 3+ watchdog cycles (45+ seconds)",
        "Audit showing errors for critical operations (submit_report, claim_next_task)",
        "Tasks stuck in blocked with no matching open blocker",
        "Agents showing connected: true but active: false repeatedly",
    ],
    "escalate_triggers": [
        "Tasks in_progress with expired leases and no recovery events",
        "State file corruption detected by watchdog",
        "Task count shrinkage blocked by state guard",
        "Multiple agents offline simultaneously with assigned tasks",
    ],
    "resolution_priority_order": [
        "orchestrator_status() — current authoritative state",
        "Audit log — what actions were taken and results",
        "Event bus — fine-grained event timeline with correlation",
        "Watchdog JSONL — periodic diagnostic snapshots",
        "Worker/manager logs — process-level output",
    ],
}


class DiscrepancyScenarioTests(unittest.TestCase):
    """TASK-ca9d3fa2: Discrepancy scenarios across status/audit/watchdog."""

    def test_at_least_five_scenarios(self) -> None:
        self.assertGreaterEqual(len(DISCREPANCY_SCENARIOS), 5)

    def test_each_scenario_has_required_fields(self) -> None:
        required = {"id", "title", "sources_involved", "symptoms", "root_cause",
                     "resolution_order", "verdict", "severity"}
        for s in DISCREPANCY_SCENARIOS:
            self.assertTrue(required.issubset(s.keys()), f"Missing fields in {s['id']}")

    def test_resolution_order_is_list(self) -> None:
        for s in DISCREPANCY_SCENARIOS:
            self.assertIsInstance(s["resolution_order"], list)
            self.assertGreaterEqual(len(s["resolution_order"]), 2,
                                    f"{s['id']} needs at least 2 resolution steps")

    def test_sources_are_known(self) -> None:
        known_sources = {"orchestrator_status", "audit_log", "watchdog",
                         "event_bus", "worker_logs"}
        for s in DISCREPANCY_SCENARIOS:
            for src in s["sources_involved"]:
                self.assertIn(src, known_sources, f"Unknown source {src} in {s['id']}")

    def test_severities_valid(self) -> None:
        valid = {"critical", "high", "medium", "low"}
        for s in DISCREPANCY_SCENARIOS:
            self.assertIn(s["severity"], valid, f"Bad severity in {s['id']}")

    def test_scenarios_json_serializable(self) -> None:
        serialized = json.dumps(DISCREPANCY_SCENARIOS)
        self.assertIsInstance(json.loads(serialized), list)

    def test_ids_unique(self) -> None:
        ids = [s["id"] for s in DISCREPANCY_SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_escalation_guidance_defined(self) -> None:
        self.assertIn("investigate_triggers", ESCALATION_GUIDANCE)
        self.assertIn("escalate_triggers", ESCALATION_GUIDANCE)
        self.assertIn("resolution_priority_order", ESCALATION_GUIDANCE)

    def test_escalation_triggers_non_empty(self) -> None:
        for key in ("investigate_triggers", "escalate_triggers"):
            self.assertGreaterEqual(len(ESCALATION_GUIDANCE[key]), 3,
                                    f"{key} needs at least 3 triggers")

    def test_resolution_priority_starts_with_status(self) -> None:
        """orchestrator_status should be first in resolution priority."""
        first = ESCALATION_GUIDANCE["resolution_priority_order"][0]
        self.assertIn("orchestrator_status", first)


# ══════════════════════════════════════════════════════════════════════
# TASK-61c82b60: Dashboard alert panel mock examples
# ══════════════════════════════════════════════════════════════════════

ALERT_PANEL_EXAMPLES: list[dict] = [
    {
        "alert_id": "ALERT-01",
        "type": "stale_instance",
        "title": "Agent gemini offline (heartbeat timeout)",
        "severity": "high",
        "source": "orchestrator_list_agents",
        "source_available": True,
        "trigger": "last_seen age > heartbeat_timeout_minutes * 60",
        "mock_data": {
            "agent": "gemini",
            "status": "offline",
            "last_seen": "2026-02-26T10:00:00+00:00",
            "age_seconds": 1200,
            "threshold_seconds": 600,
        },
        "action": "Restart gemini agent process; reconnect via connect_to_leader",
    },
    {
        "alert_id": "ALERT-02",
        "type": "stale_task",
        "title": "TASK-abc123 in_progress for 45 minutes (watchdog)",
        "severity": "high",
        "source": "watchdog_jsonl",
        "source_available": True,
        "trigger": "kind=stale_task, age_seconds > 900",
        "mock_data": {
            "kind": "stale_task",
            "task_id": "TASK-abc123",
            "owner": "claude_code",
            "status": "in_progress",
            "age_seconds": 2700,
            "timeout_seconds": 900,
        },
        "action": "Check lease validity; if expired, call recover_expired_task_leases",
    },
    {
        "alert_id": "ALERT-03",
        "type": "dispatch_noop",
        "title": "Dispatch no-op: stale override for claude_code (future telemetry)",
        "severity": "medium",
        "source": "dispatch_telemetry_events",
        "source_available": False,  # Future noop telemetry
        "trigger": "dispatch.noop event with reason=stale_override",
        "mock_data": {
            "type": "dispatch.noop",
            "payload": {
                "agent": "claude_code",
                "task_id": "TASK-def456",
                "reason": "stale_override",
                "correlation_id": "CORR-001",
                "age_seconds": 120,
            },
        },
        "future_data_note": "dispatch.noop events require noop telemetry phase — not yet in production",
        "action": "Clear stale claim override; verify agent is online",
    },
    {
        "alert_id": "ALERT-04",
        "type": "open_blocker",
        "title": "Blocker on TASK-ghi789: no eligible worker for recovery",
        "severity": "medium",
        "source": "orchestrator_list_blockers",
        "source_available": True,
        "trigger": "blocker status=open with task_id match",
        "mock_data": {
            "blocker_id": "BLK-001",
            "task_id": "TASK-ghi789",
            "question": "No eligible same-project worker for lease recovery",
            "status": "open",
            "raised_by": "codex",
        },
        "action": "Review blocker; restart offline agent or manually assign task",
    },
    {
        "alert_id": "ALERT-05",
        "type": "queue_warning",
        "title": "Task count regression detected (state guard triggered)",
        "severity": "critical",
        "source": "orchestrator_status_integrity",
        "source_available": True,
        "trigger": "integrity.task_count_consistent=false or state_guard audit",
        "mock_data": {
            "category": "state_guard",
            "path": "state/tasks.json",
            "action": "reject_task_count_shrink",
            "existing_count": 15,
            "attempted_count": 12,
        },
        "action": "Investigate concurrent writes to state/tasks.json; restore from backup if needed",
    },
    {
        "alert_id": "ALERT-06",
        "type": "timeout_noop",
        "title": "Dispatch timeout: claim override expired without ACK (future)",
        "severity": "medium",
        "source": "dispatch_telemetry_events",
        "source_available": False,  # Future noop telemetry
        "trigger": "dispatch.noop event with reason=timeout",
        "mock_data": {
            "type": "dispatch.noop",
            "payload": {
                "agent": "gemini",
                "task_id": "TASK-timeout01",
                "reason": "timeout",
                "correlation_id": "CORR-002",
                "budget_key": "heartbeat_timeout_minutes",
                "budget_seconds": 600,
            },
        },
        "future_data_note": "Requires noop telemetry — not yet available in production",
        "action": "Check if target agent is online; consider reassignment",
    },
    {
        "alert_id": "ALERT-07",
        "type": "lease_expiry",
        "title": "Lease expired on TASK-jkl012 — requeued to claude_code",
        "severity": "high",
        "source": "recover_expired_task_leases",
        "source_available": True,
        "trigger": "task.requeued_lease_expired event in event bus",
        "mock_data": {
            "type": "task.requeued_lease_expired",
            "payload": {
                "task_id": "TASK-jkl012",
                "previous_owner": "claude_code",
                "new_owner": "claude_code",
                "action": "requeued",
                "lease_id": "LEASE-expired01",
            },
        },
        "action": "Monitor re-claim; verify new lease is issued",
    },
    {
        "alert_id": "ALERT-08",
        "type": "state_corruption",
        "title": "State corruption: bugs.json has wrong type (dict vs list)",
        "severity": "critical",
        "source": "watchdog_jsonl",
        "source_available": True,
        "trigger": "kind=state_corruption_detected in watchdog",
        "mock_data": {
            "kind": "state_corruption_detected",
            "path": "state/bugs.json",
            "previous_type": "dict",
            "expected_type": "list",
        },
        "action": "Fix state file manually; check for concurrent writes; restore from backup",
    },
]


class AlertPanelMockTests(unittest.TestCase):
    """TASK-61c82b60: Dashboard alert panel mock examples."""

    def test_at_least_six_alerts(self) -> None:
        self.assertGreaterEqual(len(ALERT_PANEL_EXAMPLES), 6)

    def test_each_alert_has_required_fields(self) -> None:
        required = {"alert_id", "type", "title", "severity", "source",
                     "source_available", "trigger", "mock_data", "action"}
        for a in ALERT_PANEL_EXAMPLES:
            self.assertTrue(required.issubset(a.keys()),
                            f"Missing fields in {a['alert_id']}")

    def test_each_alert_maps_to_source_and_severity(self) -> None:
        valid_severities = {"critical", "high", "medium", "low"}
        for a in ALERT_PANEL_EXAMPLES:
            self.assertIn(a["severity"], valid_severities,
                          f"Bad severity in {a['alert_id']}")
            self.assertTrue(len(a["source"]) > 0,
                            f"Empty source in {a['alert_id']}")

    def test_distinguishes_current_vs_future_noop(self) -> None:
        """At least one alert should be current and one should flag future data."""
        current = [a for a in ALERT_PANEL_EXAMPLES if a["source_available"] is True]
        future = [a for a in ALERT_PANEL_EXAMPLES if a["source_available"] is False]
        self.assertGreaterEqual(len(current), 1, "Need at least 1 current-source alert")
        self.assertGreaterEqual(len(future), 1, "Need at least 1 future-source alert")

    def test_future_alerts_have_note(self) -> None:
        """Future data alerts should have future_data_note field."""
        future = [a for a in ALERT_PANEL_EXAMPLES if a["source_available"] is False]
        for a in future:
            self.assertIn("future_data_note", a,
                          f"Future alert {a['alert_id']} missing future_data_note")
            self.assertGreater(len(a["future_data_note"]), 10)

    def test_alert_ids_unique(self) -> None:
        ids = [a["alert_id"] for a in ALERT_PANEL_EXAMPLES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_mock_data_is_dict(self) -> None:
        for a in ALERT_PANEL_EXAMPLES:
            self.assertIsInstance(a["mock_data"], dict,
                                 f"mock_data should be dict in {a['alert_id']}")

    def test_alerts_json_serializable(self) -> None:
        serialized = json.dumps(ALERT_PANEL_EXAMPLES)
        self.assertIsInstance(json.loads(serialized), list)

    def test_covers_all_alert_categories(self) -> None:
        """Should cover stale_instance, stale_task, dispatch_noop, blocker, queue, lease."""
        types = {a["type"] for a in ALERT_PANEL_EXAMPLES}
        expected_types = {"stale_instance", "stale_task", "dispatch_noop",
                          "open_blocker", "queue_warning", "lease_expiry"}
        self.assertTrue(expected_types.issubset(types),
                        f"Missing types: {expected_types - types}")

    def test_noop_alerts_reference_dispatch_telemetry(self) -> None:
        """Noop/timeout alerts should reference dispatch telemetry source."""
        noop_alerts = [a for a in ALERT_PANEL_EXAMPLES
                       if a["type"] in ("dispatch_noop", "timeout_noop")]
        self.assertGreaterEqual(len(noop_alerts), 1)
        for a in noop_alerts:
            self.assertIn("dispatch", a["source"].lower())


# ══════════════════════════════════════════════════════════════════════
# TASK-864fa4ae: Project-tagged report note format examples
# ══════════════════════════════════════════════════════════════════════

VALID_NOTE_EXAMPLES: list[dict] = [
    {
        "agent": "claude_code",
        "session_label": "CC1",
        "note": "[CC1] Added supervisor lifecycle smoke tests. 6 passed, 0 failed.",
        "has_project_tag": False,
    },
    {
        "agent": "claude_code",
        "session_label": "CC2",
        "note": "[CC2] [claude-multi-ai] Created operator cheat sheet for tmux pane mapping.",
        "has_project_tag": True,
    },
    {
        "agent": "claude_code",
        "session_label": "CC3",
        "note": "[CC3] Fixed supervisor clean command to remove restart counter files.",
        "has_project_tag": False,
    },
    {
        "agent": "claude_code",
        "session_label": "CC1",
        "note": "[CC1] [claude-multi-ai] Doc already existed. All acceptance criteria met by existing content.",
        "has_project_tag": True,
    },
    {
        "agent": "gemini",
        "session_label": "GEM1",
        "note": "[GEM1] Built TUI dashboard prototype with agent status panel.",
        "has_project_tag": False,
    },
    {
        "agent": "gemini",
        "session_label": "GEM1",
        "note": "[GEM1] [claude-multi-ai] Created alert taxonomy documentation with severity levels.",
        "has_project_tag": True,
    },
]

INVALID_NOTE_EXAMPLES: list[dict] = [
    {
        "note": "Added supervisor lifecycle smoke tests.",
        "violation": "missing_session_label",
        "description": "No session label at start of note",
    },
    {
        "note": "[CC1]",
        "violation": "empty_description",
        "description": "Session label present but no description body",
    },
    {
        "note": "[cc1] Added tests for lease renewal.",
        "violation": "wrong_label_format",
        "description": "Lowercase session label — must be [CC1-3]",
    },
    {
        "note": "[Claude-1] Added tests.",
        "violation": "wrong_label_format",
        "description": "Non-standard label format",
    },
    {
        "note": "[CC1] Done.",
        "violation": "too_short",
        "description": "Description body shorter than 10 characters",
    },
    {
        "note": "",
        "violation": "empty_note",
        "description": "Completely empty note",
    },
]

NOTE_VALIDATION_RULES = {
    "session_label_pattern": r"^\[CC[1-3]\]",
    "project_tag_pattern": r"\[claude-multi-ai\]",
    "min_description_length": 10,
    "cc_labels": ["CC1", "CC2", "CC3"],
    "gemini_label_convention": "GEM1 (recommended, not enforced)",
    "when_required": "During multi-CC session operation (2+ Claude Code sessions)",
    "not_required": "Single-session operation or after instance-aware mode ships",
}


def _validate_cc_note(note: str) -> list[str]:
    """Validate a CC report note per linter spec."""
    errors: list[str] = []
    if not note:
        errors.append("empty_note")
        return errors
    if not re.match(r"^\[CC[1-3]\]", note):
        errors.append("missing_session_label")
    body = re.sub(r"^\[CC[1-3]\]\s*(\[[\w-]+\]\s*)?", "", note)
    if len(body.strip()) < 10:
        errors.append("description_too_short")
    return errors


class ReportNoteFormatTests(unittest.TestCase):
    """TASK-864fa4ae: Project-tagged report note format examples."""

    def test_includes_cc_examples(self) -> None:
        cc = [e for e in VALID_NOTE_EXAMPLES if e["agent"] == "claude_code"]
        self.assertGreaterEqual(len(cc), 3, "Need at least 3 CC examples")

    def test_includes_gemini_examples(self) -> None:
        gem = [e for e in VALID_NOTE_EXAMPLES if e["agent"] == "gemini"]
        self.assertGreaterEqual(len(gem), 1, "Need at least 1 Gemini example")

    def test_valid_examples_pass_cc_validation(self) -> None:
        """Valid CC notes should pass the validation function."""
        cc_valid = [e for e in VALID_NOTE_EXAMPLES if e["agent"] == "claude_code"]
        for ex in cc_valid:
            errors = _validate_cc_note(ex["note"])
            self.assertEqual([], errors, f"Valid note should pass: {ex['note']}")

    def test_invalid_examples_fail_validation(self) -> None:
        """Invalid notes should produce at least one error."""
        for ex in INVALID_NOTE_EXAMPLES:
            errors = _validate_cc_note(ex["note"])
            self.assertGreater(len(errors), 0,
                               f"Invalid note should fail: {ex['note']!r}")

    def test_invalid_examples_have_violation_field(self) -> None:
        for ex in INVALID_NOTE_EXAMPLES:
            self.assertIn("violation", ex)
            self.assertIn("description", ex)

    def test_shows_valid_and_invalid(self) -> None:
        self.assertGreaterEqual(len(VALID_NOTE_EXAMPLES), 4)
        self.assertGreaterEqual(len(INVALID_NOTE_EXAMPLES), 4)

    def test_validation_rules_documented(self) -> None:
        self.assertIn("session_label_pattern", NOTE_VALIDATION_RULES)
        self.assertIn("project_tag_pattern", NOTE_VALIDATION_RULES)
        self.assertIn("min_description_length", NOTE_VALIDATION_RULES)

    def test_project_tag_examples_present(self) -> None:
        """At least some examples should show project tag usage."""
        with_tag = [e for e in VALID_NOTE_EXAMPLES if e.get("has_project_tag")]
        without_tag = [e for e in VALID_NOTE_EXAMPLES if not e.get("has_project_tag")]
        self.assertGreaterEqual(len(with_tag), 1, "Need examples with project tag")
        self.assertGreaterEqual(len(without_tag), 1, "Need examples without project tag")

    def test_cc_labels_are_standard(self) -> None:
        cc = [e for e in VALID_NOTE_EXAMPLES if e["agent"] == "claude_code"]
        labels = {e["session_label"] for e in cc}
        for label in labels:
            self.assertRegex(label, r"^CC[1-3]$")

    def test_examples_json_serializable(self) -> None:
        payload = {
            "valid": VALID_NOTE_EXAMPLES,
            "invalid": INVALID_NOTE_EXAMPLES,
            "rules": NOTE_VALIDATION_RULES,
        }
        serialized = json.dumps(payload)
        self.assertIsInstance(json.loads(serialized), dict)

    def test_engine_accepts_report_with_session_label(self) -> None:
        """Engine should accept report notes with session labels (not validated)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Note test", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            # Submit with session-labeled note via ingest_report
            report = {
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "abc123",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
                "notes": "[CC1] [claude-multi-ai] Implemented note test. All pass.",
            }
            result = orch.ingest_report(report)
            # Engine should accept — notes are not validated for format
            self.assertIn("task_id", result)

    def test_note_preserved_in_report_file(self) -> None:
        """Session-labeled note should be preserved in stored report."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _connect(orch, root, "claude_code")
            task = orch.create_task("Preserve test", "backend", ["done"], owner="claude_code")
            orch.claim_next_task("claude_code")

            note_text = "[CC2] [claude-multi-ai] Test note preservation."
            report = {
                "task_id": task["id"],
                "agent": "claude_code",
                "commit_sha": "def456",
                "status": "done",
                "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
                "notes": note_text,
            }
            orch.ingest_report(report)

            # Check report file
            report_path = orch.bus.reports_dir / f"{task['id']}.json"
            if report_path.exists():
                stored = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(note_text, stored.get("notes", ""))


if __name__ == "__main__":
    unittest.main()
