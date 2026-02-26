"""Operator documentation fixture tests – batch 4.

Covers:
- TASK-cc3e078f: Dashboard layout variants (ops-heavy vs dev-heavy)
- TASK-e343596e: Instance-aware status examples for 1/2/3 CC sessions
- TASK-323bf57f: FAQ addendum for three-worker pre-swarm operation
- TASK-fc0642d9: Dashboard degraded-mode alert bundles
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
# TASK-cc3e078f: Dashboard layout variants (ops-heavy vs dev-heavy)
# ══════════════════════════════════════════════════════════════════════

DASHBOARD_LAYOUT_VARIANTS: list[dict] = [
    {
        "variant": "ops-heavy",
        "focus": "Operations monitoring — team health, alerts, blockers first",
        "panels": [
            {
                "name": "Team Health",
                "position": "top-left",
                "fields": ["agent_name", "instance_id", "status", "last_seen", "current_task_id"],
                "source": "orchestrator_status.agent_instances",
                "source_available": True,
            },
            {
                "name": "Alert Feed",
                "position": "top-right",
                "fields": ["severity", "type", "title", "source", "action"],
                "source": "watchdog_jsonl + orchestrator_status.integrity",
                "source_available": True,
            },
            {
                "name": "Blocker Queue",
                "position": "middle-left",
                "fields": ["task_id", "question", "status", "raised_by", "raised_at"],
                "source": "orchestrator_list_blockers",
                "source_available": True,
            },
            {
                "name": "Task Pipeline",
                "position": "middle-right",
                "fields": ["status", "count", "oldest_age_seconds"],
                "source": "orchestrator_status.task_status_counts",
                "source_available": True,
            },
            {
                "name": "Milestone Summary",
                "position": "bottom",
                "fields": ["overall_percent", "phase_1_percent", "backend_percent", "frontend_percent"],
                "source": "orchestrator_status.live_status",
                "source_available": True,
            },
        ],
        "tradeoffs": [
            "Alerts and blockers prominent — fast incident response",
            "Task detail hidden — engineer may need drill-down",
            "Milestone % is secondary — less useful for planning",
        ],
    },
    {
        "variant": "dev-heavy",
        "focus": "Engineering progress — task pipeline, milestone %, queue depth first",
        "panels": [
            {
                "name": "Milestone Progress",
                "position": "top",
                "fields": ["overall_percent", "phase_1_percent", "backend_percent", "frontend_percent", "qa_percent"],
                "source": "orchestrator_status.live_status",
                "source_available": True,
            },
            {
                "name": "Task Board",
                "position": "middle-left",
                "fields": ["task_id", "title", "owner", "status", "workstream"],
                "source": "orchestrator_list_tasks",
                "source_available": True,
            },
            {
                "name": "Agent Workload",
                "position": "middle-right",
                "fields": ["agent_name", "in_progress_count", "done_count", "current_task_id"],
                "source": "orchestrator_status.agent_instances + task counts",
                "source_available": True,
                "future_fields": ["avg_task_duration", "throughput_per_hour"],
            },
            {
                "name": "Recent Events",
                "position": "bottom-left",
                "fields": ["type", "payload.task_id", "payload.agent", "timestamp"],
                "source": "orchestrator_poll_events",
                "source_available": True,
            },
            {
                "name": "Compact Alerts",
                "position": "bottom-right",
                "fields": ["severity", "title", "count"],
                "source": "watchdog_jsonl + blockers",
                "source_available": True,
            },
        ],
        "tradeoffs": [
            "Progress and pipeline prominent — good for planning",
            "Alerts minimized — may miss urgent issues",
            "Workload panel needs future fields for full value",
        ],
    },
]


class DashboardLayoutVariantTests(unittest.TestCase):
    """TASK-cc3e078f: Dashboard layout variants (ops vs dev)."""

    def test_two_variants_defined(self) -> None:
        self.assertEqual(2, len(DASHBOARD_LAYOUT_VARIANTS))

    def test_variant_names(self) -> None:
        names = {v["variant"] for v in DASHBOARD_LAYOUT_VARIANTS}
        self.assertEqual({"ops-heavy", "dev-heavy"}, names)

    def test_each_variant_has_panels(self) -> None:
        for v in DASHBOARD_LAYOUT_VARIANTS:
            self.assertGreaterEqual(len(v["panels"]), 3,
                                    f"{v['variant']} needs at least 3 panels")

    def test_each_panel_has_required_fields(self) -> None:
        required = {"name", "position", "fields", "source", "source_available"}
        for v in DASHBOARD_LAYOUT_VARIANTS:
            for p in v["panels"]:
                self.assertTrue(required.issubset(p.keys()),
                                f"Missing fields in {v['variant']}/{p['name']}")

    def test_tradeoffs_documented(self) -> None:
        for v in DASHBOARD_LAYOUT_VARIANTS:
            self.assertIn("tradeoffs", v)
            self.assertGreaterEqual(len(v["tradeoffs"]), 2)

    def test_mapped_to_existing_sources(self) -> None:
        """Panels should reference existing data sources."""
        known_fragments = ["orchestrator_status", "orchestrator_list", "watchdog",
                           "poll_events", "blockers", "task"]
        for v in DASHBOARD_LAYOUT_VARIANTS:
            for p in v["panels"]:
                source_lower = p["source"].lower()
                matched = any(f in source_lower for f in known_fragments)
                self.assertTrue(matched,
                                f"Unknown source {p['source']} in {v['variant']}/{p['name']}")

    def test_future_fields_flagged(self) -> None:
        """At least one panel should flag future/missing fields."""
        has_future = False
        for v in DASHBOARD_LAYOUT_VARIANTS:
            for p in v["panels"]:
                if p.get("future_fields"):
                    has_future = True
        self.assertTrue(has_future, "At least one panel should note future fields")

    def test_json_serializable(self) -> None:
        serialized = json.dumps(DASHBOARD_LAYOUT_VARIANTS)
        self.assertIsInstance(json.loads(serialized), list)


# ══════════════════════════════════════════════════════════════════════
# TASK-e343596e: Instance-aware status examples for 1/2/3 CC sessions
# ══════════════════════════════════════════════════════════════════════

CC_SESSION_EXAMPLES: list[dict] = [
    {
        "scenario": "single_cc_session",
        "cc_count": 1,
        "description": "One Claude Code session — standard operation",
        "active_agents": ["claude_code"],
        "agent_instances": [
            {
                "agent_name": "claude_code",
                "instance_id": "claude_code#default",
                "status": "active",
                "session_id": "sess-001",
                "current_task_id": "TASK-abc123",
                "project_root": "/Users/alex/claude-multi-ai",
            },
        ],
        "active_agent_identities": [
            {"agent": "claude_code", "instance_id": "claude_code#default", "status": "active"},
        ],
        "notes": "Default instance_id derived from agent name. No disambiguation needed.",
        "interim_vs_swarm": "Works identically in both modes.",
    },
    {
        "scenario": "dual_cc_session",
        "cc_count": 2,
        "description": "Two Claude Code sessions — interim dual-CC mode",
        "active_agents": ["claude_code"],
        "agent_instances": [
            {
                "agent_name": "claude_code",
                "instance_id": "sess-cc-1",
                "status": "active",
                "session_id": "sess-cc-1",
                "current_task_id": "TASK-backend01",
                "project_root": "/Users/alex/claude-multi-ai",
            },
            {
                "agent_name": "claude_code",
                "instance_id": "sess-cc-2",
                "status": "active",
                "session_id": "sess-cc-2",
                "current_task_id": "TASK-docs01",
                "project_root": "/Users/alex/claude-multi-ai",
            },
        ],
        "active_agent_identities": [
            {"agent": "claude_code", "instance_id": "sess-cc-2", "status": "active"},
        ],
        "notes": "Both sessions share agent identity 'claude_code'. "
                 "active_agent_identities shows most recent heartbeat winner. "
                 "agent_instances shows both sessions. Use [CC1]/[CC2] labels in reports.",
        "interim_vs_swarm": "Interim: shared agent slot, last-heartbeat wins identity. "
                            "Swarm: each session gets unique instance_id automatically.",
    },
    {
        "scenario": "triple_cc_session",
        "cc_count": 3,
        "description": "Three Claude Code sessions — maximum interim capacity",
        "active_agents": ["claude_code"],
        "agent_instances": [
            {
                "agent_name": "claude_code",
                "instance_id": "sess-cc-1",
                "status": "active",
                "session_id": "sess-cc-1",
                "current_task_id": "TASK-backend01",
                "project_root": "/Users/alex/claude-multi-ai",
            },
            {
                "agent_name": "claude_code",
                "instance_id": "sess-cc-2",
                "status": "active",
                "session_id": "sess-cc-2",
                "current_task_id": "TASK-docs01",
                "project_root": "/Users/alex/claude-multi-ai",
            },
            {
                "agent_name": "claude_code",
                "instance_id": "sess-cc-3",
                "status": "active",
                "session_id": "sess-cc-3",
                "current_task_id": "TASK-qa01",
                "project_root": "/Users/alex/claude-multi-ai",
            },
        ],
        "active_agent_identities": [
            {"agent": "claude_code", "instance_id": "sess-cc-3", "status": "active"},
        ],
        "notes": "Three sessions share one agent slot. Only latest heartbeat in identities. "
                 "All three visible in agent_instances. Use [CC1]/[CC2]/[CC3] labels. "
                 "Override coordination is critical — overrides are per-agent, not per-session.",
        "interim_vs_swarm": "Interim: high collision risk on claims/overrides. "
                            "Swarm: independent instance_ids, independent claim paths.",
    },
]


class CCSessionExampleTests(unittest.TestCase):
    """TASK-e343596e: Instance-aware status examples for 1/2/3 CC sessions."""

    def test_examples_for_1_2_3_sessions(self) -> None:
        counts = {e["cc_count"] for e in CC_SESSION_EXAMPLES}
        self.assertEqual({1, 2, 3}, counts)

    def test_each_example_has_required_fields(self) -> None:
        required = {"scenario", "cc_count", "description", "active_agents",
                     "agent_instances", "active_agent_identities", "notes",
                     "interim_vs_swarm"}
        for e in CC_SESSION_EXAMPLES:
            self.assertTrue(required.issubset(e.keys()),
                            f"Missing fields in {e['scenario']}")

    def test_instance_count_matches_cc_count(self) -> None:
        for e in CC_SESSION_EXAMPLES:
            cc_instances = [i for i in e["agent_instances"]
                           if i["agent_name"] == "claude_code"]
            self.assertEqual(e["cc_count"], len(cc_instances),
                             f"{e['scenario']}: instance count mismatch")

    def test_uses_current_field_names(self) -> None:
        """Fields should use actual orchestrator field names."""
        known_fields = {"agent_name", "instance_id", "status", "session_id",
                        "current_task_id", "project_root"}
        for e in CC_SESSION_EXAMPLES:
            for inst in e["agent_instances"]:
                self.assertTrue(known_fields.issubset(inst.keys()),
                                f"Bad fields in {e['scenario']}")

    def test_interim_vs_swarm_documented(self) -> None:
        for e in CC_SESSION_EXAMPLES:
            self.assertGreater(len(e["interim_vs_swarm"]), 10)

    def test_single_session_default_instance(self) -> None:
        """Single session should use default instance_id derivation."""
        single = next(e for e in CC_SESSION_EXAMPLES if e["cc_count"] == 1)
        inst = single["agent_instances"][0]
        self.assertIn("default", inst["instance_id"])

    def test_multi_session_distinct_instance_ids(self) -> None:
        """Multi-session examples should have distinct instance_ids."""
        for e in CC_SESSION_EXAMPLES:
            if e["cc_count"] > 1:
                ids = [i["instance_id"] for i in e["agent_instances"]]
                self.assertEqual(len(ids), len(set(ids)),
                                 f"Duplicate instance_ids in {e['scenario']}")

    def test_engine_creates_multiple_instances(self) -> None:
        """Engine should track multiple CC instances via heartbeat."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            for i in range(1, 4):
                orch.heartbeat("claude_code", {
                    **_full_metadata(root, "claude_code"),
                    "instance_id": f"cc#w{i}",
                    "session_id": f"sess-{i}",
                    "connection_id": f"conn-{i}",
                })
            instances = orch.list_agent_instances(active_only=False)
            cc = [inst for inst in instances if inst["agent_name"] == "claude_code"]
            self.assertEqual(3, len(cc))

    def test_json_serializable(self) -> None:
        serialized = json.dumps(CC_SESSION_EXAMPLES)
        self.assertIsInstance(json.loads(serialized), list)


# ══════════════════════════════════════════════════════════════════════
# TASK-323bf57f: FAQ addendum for three-worker pre-swarm operation
# ══════════════════════════════════════════════════════════════════════

THREE_WORKER_FAQ: list[dict] = [
    {
        "id": "FAQ-3W-01",
        "question": "Can I run 3 Claude Code sessions simultaneously?",
        "answer": "Yes, but all three share the single 'claude_code' agent identity. "
                  "Use [CC1]/[CC2]/[CC3] session labels in report notes for traceability.",
        "category": "basics",
    },
    {
        "id": "FAQ-3W-02",
        "question": "How do claim overrides work with 3 sessions?",
        "answer": "Overrides are per-agent, not per-session. Setting an override from any session "
                  "replaces the previous one. Coordinate overrides sequentially: set, claim, then set next.",
        "category": "claims",
    },
    {
        "id": "FAQ-3W-03",
        "question": "What happens if two sessions call claim_next_task at the same time?",
        "answer": "The engine's atomic claim prevents double-assignment. One session gets the task, "
                  "the other gets the next available. This may cause unintended task assignments.",
        "category": "claims",
    },
    {
        "id": "FAQ-3W-04",
        "question": "Will the status show all 3 sessions as separate instances?",
        "answer": "Yes, if each session uses a distinct session_id or instance_id in metadata. "
                  "agent_instances will show all three. active_agent_identities shows only the "
                  "most recent heartbeat winner.",
        "category": "status",
    },
    {
        "id": "FAQ-3W-05",
        "question": "What are the main collision risks?",
        "answer": "1) Claim override clobbering (last writer wins). "
                  "2) Git conflicts if sessions touch same files. "
                  "3) Heartbeat slot contention (last heartbeat wins identity metadata).",
        "category": "risks",
    },
    {
        "id": "FAQ-3W-06",
        "question": "How should I partition work across 3 sessions?",
        "answer": "Assign by workstream: CC1=backend, CC2=frontend/docs, CC3=QA/tests. "
                  "Use set_claim_override to direct tasks. Avoid free-claim races.",
        "category": "workflow",
    },
    {
        "id": "FAQ-3W-07",
        "question": "What changes when swarm mode ships?",
        "answer": "Each session gets a unique instance_id automatically. Claims are per-instance, "
                  "not per-agent. Override conflicts disappear. Session labels become optional.",
        "category": "future",
    },
    {
        "id": "FAQ-3W-08",
        "question": "How do I tell if a session crashed vs is just idle?",
        "answer": "Check agent_instances for each instance_id's last_seen. If beyond heartbeat_timeout, "
                  "the session is likely dead. If recent but no task progress, check worker logs.",
        "category": "troubleshooting",
    },
    {
        "id": "FAQ-3W-09",
        "question": "Can I mix Claude Code and Gemini sessions for more than 3 workers?",
        "answer": "Yes. Gemini gets its own agent identity, so adding Gemini doesn't conflict "
                  "with Claude Code sessions. A typical setup: 3 CC + 1 Gemini = 4 workers.",
        "category": "scaling",
    },
    {
        "id": "FAQ-3W-10",
        "question": "How do events work across 3 sessions?",
        "answer": "All sessions share the 'claude_code' event cursor. Events published by one "
                  "session are visible to all via poll_events. This is desirable for corrections "
                  "and plan changes, but means events are consumed once across sessions.",
        "category": "events",
    },
]

THREE_WORKER_LIMITATIONS = [
    "Claim overrides are per-agent, not per-session — last writer wins",
    "Heartbeat slot is shared — only latest session's metadata visible in active_agent_identities",
    "Event cursor is shared — consuming an event in one session hides it from others",
    "Git branch contention — all sessions commit to same branch by default",
    "No automatic instance-aware identity — must use manual session labels",
]

THREE_WORKER_WORKAROUNDS = [
    "Use [CC1]/[CC2]/[CC3] session labels in all report notes",
    "Coordinate claim overrides sequentially (set → claim → set next)",
    "Partition tasks by workstream to minimize contention",
    "Use distinct session_id in connection metadata for instance tracking",
    "Pull-rebase before committing to catch other sessions' changes",
]


class ThreeWorkerFAQTests(unittest.TestCase):
    """TASK-323bf57f: FAQ addendum for three-worker pre-swarm operation."""

    def test_at_least_eight_questions(self) -> None:
        self.assertGreaterEqual(len(THREE_WORKER_FAQ), 8)

    def test_each_faq_has_required_fields(self) -> None:
        required = {"id", "question", "answer", "category"}
        for faq in THREE_WORKER_FAQ:
            self.assertTrue(required.issubset(faq.keys()),
                            f"Missing fields in {faq['id']}")

    def test_covers_limitations_and_workarounds(self) -> None:
        self.assertGreaterEqual(len(THREE_WORKER_LIMITATIONS), 4)
        self.assertGreaterEqual(len(THREE_WORKER_WORKAROUNDS), 4)

    def test_mentions_instance_aware_improvements(self) -> None:
        """At least one FAQ should mention swarm/instance-aware improvements."""
        future = [f for f in THREE_WORKER_FAQ if f["category"] == "future"]
        self.assertGreaterEqual(len(future), 1)
        text = " ".join(f["answer"] for f in future).lower()
        self.assertTrue("instance_id" in text or "swarm" in text)

    def test_clear_expectation_setting(self) -> None:
        """FAQ should cover risks and limitations clearly."""
        risk_faqs = [f for f in THREE_WORKER_FAQ if f["category"] in ("risks", "claims")]
        self.assertGreaterEqual(len(risk_faqs), 2, "Need risk/claim FAQs for expectation setting")

    def test_categories_diverse(self) -> None:
        categories = {f["category"] for f in THREE_WORKER_FAQ}
        self.assertGreaterEqual(len(categories), 4, "Should cover diverse categories")

    def test_ids_unique(self) -> None:
        ids = [f["id"] for f in THREE_WORKER_FAQ]
        self.assertEqual(len(ids), len(set(ids)))

    def test_json_serializable(self) -> None:
        payload = {
            "faq": THREE_WORKER_FAQ,
            "limitations": THREE_WORKER_LIMITATIONS,
            "workarounds": THREE_WORKER_WORKAROUNDS,
        }
        serialized = json.dumps(payload)
        self.assertIsInstance(json.loads(serialized), dict)


# ══════════════════════════════════════════════════════════════════════
# TASK-fc0642d9: Dashboard degraded-mode alert bundles
# ══════════════════════════════════════════════════════════════════════

DEGRADED_MODE_BUNDLES: list[dict] = [
    {
        "bundle_id": "DEGRADED-01",
        "title": "Worker Offline Cascade",
        "trigger": "Agent goes offline (heartbeat timeout exceeded)",
        "alerts": [
            {"type": "agent_offline", "severity": "high",
             "source": "orchestrator_list_agents", "provenance": "status/real-time"},
            {"type": "stale_instances", "severity": "medium",
             "source": "agent_instances", "provenance": "status/real-time"},
            {"type": "lease_expiry_pending", "severity": "high",
             "source": "recover_expired_task_leases", "provenance": "event_bus/triggered"},
            {"type": "task_requeue_or_block", "severity": "medium",
             "source": "event_bus (task.requeued/blocked)", "provenance": "event_bus/triggered"},
        ],
        "operator_next_actions": [
            "Verify agent process health (check worker logs)",
            "Restart agent and reconnect via connect_to_leader",
            "Run recover_expired_task_leases if lease already expired",
            "Monitor re-claim of requeued tasks",
        ],
    },
    {
        "bundle_id": "DEGRADED-02",
        "title": "Blocker Spike",
        "trigger": "Multiple blockers raised in short window (3+ open blockers)",
        "alerts": [
            {"type": "blocker_count_high", "severity": "high",
             "source": "orchestrator_list_blockers(status=open)", "provenance": "status/real-time"},
            {"type": "blocked_task_count_rising", "severity": "medium",
             "source": "orchestrator_status.task_status_counts", "provenance": "status/real-time"},
            {"type": "pipeline_stall", "severity": "medium",
             "source": "orchestrator_status.live_status", "provenance": "status/computed"},
        ],
        "operator_next_actions": [
            "Review each open blocker's question and context",
            "Resolve blockers that have clear answers (resolve_blocker)",
            "Unblock tasks after blocker resolution (set_task_status → assigned)",
            "Escalate unresolvable blockers to project lead",
        ],
    },
    {
        "bundle_id": "DEGRADED-03",
        "title": "Queue Jam (No Progress)",
        "trigger": "Tasks assigned but none claiming or progressing for extended period",
        "alerts": [
            {"type": "no_claims_recent", "severity": "medium",
             "source": "audit_log (claim_next_task)", "provenance": "audit/historical"},
            {"type": "stale_assigned_tasks", "severity": "medium",
             "source": "watchdog_jsonl (stale_task, assigned)", "provenance": "watchdog/periodic"},
            {"type": "agent_idle", "severity": "low",
             "source": "orchestrator_list_agents", "provenance": "status/real-time"},
        ],
        "operator_next_actions": [
            "Check if agents are online and responding",
            "Verify task routing matches available agents",
            "Use set_claim_override to direct tasks if routing is wrong",
            "Check for policy misconfiguration blocking claims",
        ],
    },
    {
        "bundle_id": "DEGRADED-04",
        "title": "State Corruption Alert",
        "trigger": "Watchdog detects wrong type in state files or task count regression",
        "alerts": [
            {"type": "state_corruption_detected", "severity": "critical",
             "source": "watchdog_jsonl (state_corruption_detected)", "provenance": "watchdog/periodic"},
            {"type": "task_count_regression", "severity": "critical",
             "source": "orchestrator_status.integrity", "provenance": "status/real-time"},
            {"type": "state_guard_reject", "severity": "high",
             "source": "audit_log (state_guard)", "provenance": "audit/historical"},
        ],
        "operator_next_actions": [
            "STOP all agents immediately to prevent further corruption",
            "Inspect state files (tasks.json, bugs.json, blockers.json)",
            "Check audit log for concurrent write patterns",
            "Restore from most recent known-good snapshot if needed",
            "Restart orchestrator and verify integrity",
        ],
    },
    {
        "bundle_id": "DEGRADED-05",
        "title": "Multi-Agent Disconnect",
        "trigger": "Two or more agents go offline simultaneously",
        "alerts": [
            {"type": "multiple_agents_offline", "severity": "critical",
             "source": "orchestrator_list_agents", "provenance": "status/real-time"},
            {"type": "lease_expiry_wave", "severity": "high",
             "source": "recover_expired_task_leases", "provenance": "event_bus/triggered"},
            {"type": "no_eligible_workers", "severity": "high",
             "source": "blocker (no eligible worker)", "provenance": "status/real-time"},
        ],
        "operator_next_actions": [
            "Check infrastructure health (network, machine resources)",
            "Restart agents in priority order (manager first, then workers)",
            "Run recover_expired_task_leases after agents reconnect",
            "Review blockers created during outage and resolve",
        ],
    },
]


class DegradedModeAlertBundleTests(unittest.TestCase):
    """TASK-fc0642d9: Dashboard degraded-mode alert bundles."""

    def test_at_least_four_bundles(self) -> None:
        self.assertGreaterEqual(len(DEGRADED_MODE_BUNDLES), 4)

    def test_each_bundle_has_required_fields(self) -> None:
        required = {"bundle_id", "title", "trigger", "alerts", "operator_next_actions"}
        for b in DEGRADED_MODE_BUNDLES:
            self.assertTrue(required.issubset(b.keys()),
                            f"Missing fields in {b['bundle_id']}")

    def test_each_alert_has_source_provenance(self) -> None:
        for b in DEGRADED_MODE_BUNDLES:
            for a in b["alerts"]:
                self.assertIn("source", a, f"Missing source in {b['bundle_id']}")
                self.assertIn("provenance", a, f"Missing provenance in {b['bundle_id']}")
                self.assertIn("severity", a, f"Missing severity in {b['bundle_id']}")

    def test_operator_next_actions_non_empty(self) -> None:
        for b in DEGRADED_MODE_BUNDLES:
            self.assertGreaterEqual(len(b["operator_next_actions"]), 2,
                                    f"{b['bundle_id']} needs at least 2 actions")

    def test_bundle_ids_unique(self) -> None:
        ids = [b["bundle_id"] for b in DEGRADED_MODE_BUNDLES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_severities_valid(self) -> None:
        valid = {"critical", "high", "medium", "low"}
        for b in DEGRADED_MODE_BUNDLES:
            for a in b["alerts"]:
                self.assertIn(a["severity"], valid)

    def test_provenance_uses_known_sources(self) -> None:
        known_prefixes = ["status", "audit", "watchdog", "event_bus"]
        for b in DEGRADED_MODE_BUNDLES:
            for a in b["alerts"]:
                prov = a["provenance"].split("/")[0]
                self.assertIn(prov, known_prefixes,
                              f"Unknown provenance {a['provenance']} in {b['bundle_id']}")

    def test_covers_worker_offline_blocker_queue_corruption(self) -> None:
        """Should cover the main degraded scenarios."""
        titles_lower = {b["title"].lower() for b in DEGRADED_MODE_BUNDLES}
        all_text = " ".join(titles_lower)
        self.assertIn("offline", all_text)
        self.assertIn("blocker", all_text)
        self.assertIn("queue", all_text)
        self.assertIn("corruption", all_text)

    def test_json_serializable(self) -> None:
        serialized = json.dumps(DEGRADED_MODE_BUNDLES)
        self.assertIsInstance(json.loads(serialized), list)


if __name__ == "__main__":
    unittest.main()
