"""
Operator docs fixtures batch 7 — Data provenance labels and panel examples.

Covers:
  TASK-a362acbf  CC-MIRROR AUTO-M1-DOCS-30 Data provenance labels for dashboard panels
  TASK-5c1421dc  CC-MIRROR AUTO-M1-DOCS-32 Dashboard panel provenance examples
"""

import unittest

# ---------------------------------------------------------------------------
# TASK-a362acbf: Data provenance labels for dashboard panels
# ---------------------------------------------------------------------------

PROVENANCE_CATEGORIES = {
    "status": {
        "label": "LIVE",
        "description": "Value sourced from orchestrator_status() — real-time state query",
        "color_hint": "green",
        "trust_level": "authoritative",
        "update_frequency": "on-demand per MCP call",
        "examples": [
            "task_status_counts",
            "active_agents",
            "live_status.overall_project_percent",
            "task_count",
            "bug_count",
        ],
    },
    "audit": {
        "label": "AUDIT",
        "description": "Value derived from bus/audit.jsonl — append-only historical record",
        "color_hint": "blue",
        "trust_level": "authoritative_historical",
        "update_frequency": "append-only on each tool call",
        "examples": [
            "report submission timestamps",
            "claim_next_task results",
            "connect_to_leader identity verification",
            "manager_cycle validation outcomes",
        ],
    },
    "watchdog": {
        "label": "WATCH",
        "description": "Value from .autopilot-logs/watchdog-*.jsonl — periodic diagnostic snapshot",
        "color_hint": "yellow",
        "trust_level": "heuristic",
        "update_frequency": "every 15s (configurable)",
        "examples": [
            "stale_task age detection",
            "agent offline duration",
            "task staleness alerts",
            "state file integrity checks",
        ],
    },
    "synthetic": {
        "label": "CALC",
        "description": "Value computed by aggregating multiple sources — not directly observed",
        "color_hint": "gray",
        "trust_level": "derived",
        "update_frequency": "computed on render",
        "examples": [
            "milestone completion percentage",
            "team velocity estimates",
            "queue depth trends",
            "estimated time to completion",
        ],
    },
}

PROVENANCE_LABEL_FORMAT = {
    "display_pattern": "[{label}] {value}",
    "tooltip_pattern": "Source: {description} | Updated: {update_frequency}",
    "examples": [
        {"raw": "[LIVE] 90%", "meaning": "Overall project % from orchestrator_status"},
        {"raw": "[AUDIT] 14:32 UTC", "meaning": "Last report submitted at time from audit log"},
        {"raw": "[WATCH] 3 stale", "meaning": "Stale task count from watchdog snapshot"},
        {"raw": "[CALC] 67%", "meaning": "Milestone % computed from multiple sources"},
    ],
}

PROVENANCE_CONFLICT_RESOLUTION = {
    "rules": [
        {
            "conflict": "status vs watchdog disagree on task staleness",
            "resolution": "Trust status (LIVE) for current state; watchdog (WATCH) uses age heuristic",
            "label_precedence": "LIVE > WATCH",
        },
        {
            "conflict": "audit shows report submitted but status shows in_progress",
            "resolution": "Check manager cycle result in audit; likely timing issue",
            "label_precedence": "AUDIT (causal) informs LIVE (eventual)",
        },
        {
            "conflict": "synthetic metric contradicts live status",
            "resolution": "Re-derive synthetic from fresh sources; synthetic is never authoritative",
            "label_precedence": "LIVE > CALC",
        },
        {
            "conflict": "watchdog and audit show different agent activity",
            "resolution": "Audit is authoritative for actions; watchdog for periodic snapshots",
            "label_precedence": "AUDIT > WATCH for actions; WATCH > AUDIT for timing",
        },
    ],
    "precedence_order": ["LIVE", "AUDIT", "WATCH", "CALC"],
}

# ---------------------------------------------------------------------------
# TASK-5c1421dc: Dashboard panel provenance examples and confidence wording
# ---------------------------------------------------------------------------

PANEL_PROVENANCE_EXAMPLES = [
    {
        "panel": "Team Status",
        "field": "Agent count (active)",
        "value_example": "2 of 3 active",
        "provenance_label": "LIVE",
        "source_tool": "orchestrator_status().active_agents",
        "confidence_wording": "Current as of last status query",
        "staleness_note": "Refreshes on each MCP call; no cache",
    },
    {
        "panel": "Team Status",
        "field": "Agent last seen",
        "value_example": "gemini: 4h ago",
        "provenance_label": "LIVE",
        "source_tool": "list_agents().last_seen",
        "confidence_wording": "Precise to last heartbeat timestamp",
        "staleness_note": "May lag by heartbeat interval (default 30s)",
    },
    {
        "panel": "Queue Health",
        "field": "Tasks by status",
        "value_example": "286 done / 10 assigned / 22 blocked",
        "provenance_label": "LIVE",
        "source_tool": "orchestrator_status().task_status_counts",
        "confidence_wording": "Authoritative count from state file",
        "staleness_note": "Reflects state at query time; concurrent writes possible",
    },
    {
        "panel": "Queue Health",
        "field": "Last claim time",
        "value_example": "2 min ago",
        "provenance_label": "AUDIT",
        "source_tool": "bus/audit.jsonl claim_next_task entries",
        "confidence_wording": "Historical record — timestamp is exact",
        "staleness_note": "Audit is append-only; never overwritten",
    },
    {
        "panel": "Alerts",
        "field": "Stale task count",
        "value_example": "3 tasks > 15min old",
        "provenance_label": "WATCH",
        "source_tool": ".autopilot-logs/watchdog-*.jsonl stale_task entries",
        "confidence_wording": "Heuristic — based on updated_at age, not lease status",
        "staleness_note": "Snapshot from last watchdog cycle (up to 15s old)",
    },
    {
        "panel": "Alerts",
        "field": "Dispatch noop count",
        "value_example": "1 noop in last hour",
        "provenance_label": "AUDIT",
        "source_tool": "bus/events.jsonl dispatch.noop entries",
        "confidence_wording": "Exact count from event bus",
        "staleness_note": "Requires scanning event log; may be expensive for large logs",
    },
    {
        "panel": "Progress",
        "field": "Overall project %",
        "value_example": "90%",
        "provenance_label": "LIVE",
        "source_tool": "orchestrator_status().live_status.overall_project_percent",
        "confidence_wording": "Computed by server from done/total task ratio",
        "staleness_note": "Authoritative; recalculated on each status call",
    },
    {
        "panel": "Progress",
        "field": "Milestone % (AUTO-M1)",
        "value_example": "67% (4/6 cores verified)",
        "provenance_label": "CALC",
        "source_tool": "Derived from CORE task statuses in tasks.json",
        "confidence_wording": "Computed metric — verify against individual CORE task statuses",
        "staleness_note": "Only as fresh as last task state change",
    },
    {
        "panel": "Progress",
        "field": "Phase completion",
        "value_example": "Phase 1: 90% | Phase 2: 0%",
        "provenance_label": "LIVE",
        "source_tool": "orchestrator_status().live_status.phase_1_percent",
        "confidence_wording": "Server-computed phase breakdown",
        "staleness_note": "Authoritative per status query",
    },
    {
        "panel": "Blockers",
        "field": "Open blocker count",
        "value_example": "0 open",
        "provenance_label": "LIVE",
        "source_tool": "orchestrator_status().live_status.pipeline_health.open_blockers",
        "confidence_wording": "Count from state/blockers.json via status",
        "staleness_note": "May diverge from blocked task count if resolution missed task update",
    },
    {
        "panel": "Blockers",
        "field": "Blocker resolution history",
        "value_example": "Last resolved: 2h ago",
        "provenance_label": "AUDIT",
        "source_tool": "bus/audit.jsonl resolve_blocker entries",
        "confidence_wording": "Historical — exact timestamp of resolution action",
        "staleness_note": "Append-only; resolution may not have updated task status",
    },
    {
        "panel": "Team Velocity",
        "field": "Tasks completed per hour",
        "value_example": "~8 tasks/hr (last 4h)",
        "provenance_label": "CALC",
        "source_tool": "Derived from audit.jsonl submit_report timestamps",
        "confidence_wording": "Estimated — based on report submission rate, not task complexity",
        "staleness_note": "Rolling window calculation; spikes during batch submissions",
    },
]

CONFIDENCE_WORDING_GUIDE = {
    "levels": [
        {
            "level": "authoritative",
            "provenance": "LIVE",
            "wording_patterns": [
                "Current as of last query",
                "Authoritative from state file",
                "Precise to last heartbeat",
            ],
            "when_to_use": "Data comes directly from orchestrator_status or state files",
        },
        {
            "level": "historical_exact",
            "provenance": "AUDIT",
            "wording_patterns": [
                "Historical record — timestamp is exact",
                "Exact count from event bus",
                "Append-only — never overwritten",
            ],
            "when_to_use": "Data comes from audit.jsonl or events.jsonl entries",
        },
        {
            "level": "heuristic",
            "provenance": "WATCH",
            "wording_patterns": [
                "Heuristic — based on age threshold",
                "Snapshot from last watchdog cycle",
                "May differ from lease-based status",
            ],
            "when_to_use": "Data from watchdog periodic snapshots using age-based detection",
        },
        {
            "level": "derived",
            "provenance": "CALC",
            "wording_patterns": [
                "Computed metric — verify against source data",
                "Estimated — based on rate calculation",
                "Aggregated from multiple sources",
            ],
            "when_to_use": "Value computed by combining or aggregating multiple data sources",
        },
    ],
    "formatting_rules": [
        "Always show provenance label in brackets before the value",
        "Include staleness note when data could be outdated",
        "Use 'estimated' for any derived/computed values",
        "Use 'authoritative' only for direct state queries",
        "Flag divergence risks when combining LIVE and WATCH sources",
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvenanceCategories(unittest.TestCase):
    """TASK-a362acbf: provenance label definitions."""

    def test_four_categories_defined(self):
        self.assertEqual(
            set(PROVENANCE_CATEGORIES.keys()),
            {"status", "audit", "watchdog", "synthetic"},
        )

    def test_each_category_has_required_fields(self):
        required = {"label", "description", "color_hint", "trust_level",
                     "update_frequency", "examples"}
        for cat, data in PROVENANCE_CATEGORIES.items():
            with self.subTest(cat=cat):
                self.assertTrue(required.issubset(data.keys()))

    def test_labels_are_short_codes(self):
        for cat, data in PROVENANCE_CATEGORIES.items():
            with self.subTest(cat=cat):
                self.assertLessEqual(len(data["label"]), 5)
                self.assertEqual(data["label"], data["label"].upper())

    def test_each_category_has_examples(self):
        for cat, data in PROVENANCE_CATEGORIES.items():
            with self.subTest(cat=cat):
                self.assertGreaterEqual(len(data["examples"]), 3)

    def test_trust_levels_distinct(self):
        levels = [d["trust_level"] for d in PROVENANCE_CATEGORIES.values()]
        self.assertEqual(len(levels), len(set(levels)))

    def test_status_is_authoritative(self):
        self.assertEqual(PROVENANCE_CATEGORIES["status"]["trust_level"], "authoritative")

    def test_synthetic_is_derived(self):
        self.assertEqual(PROVENANCE_CATEGORIES["synthetic"]["trust_level"], "derived")

    def test_watchdog_is_heuristic(self):
        self.assertEqual(PROVENANCE_CATEGORIES["watchdog"]["trust_level"], "heuristic")


class TestProvenanceLabelFormat(unittest.TestCase):
    """TASK-a362acbf: label display patterns."""

    def test_display_pattern_has_placeholders(self):
        self.assertIn("{label}", PROVENANCE_LABEL_FORMAT["display_pattern"])
        self.assertIn("{value}", PROVENANCE_LABEL_FORMAT["display_pattern"])

    def test_tooltip_pattern_has_placeholders(self):
        self.assertIn("{description}", PROVENANCE_LABEL_FORMAT["tooltip_pattern"])

    def test_examples_cover_all_labels(self):
        labels_in_examples = set()
        for ex in PROVENANCE_LABEL_FORMAT["examples"]:
            for cat_data in PROVENANCE_CATEGORIES.values():
                if cat_data["label"] in ex["raw"]:
                    labels_in_examples.add(cat_data["label"])
        expected = {d["label"] for d in PROVENANCE_CATEGORIES.values()}
        self.assertEqual(labels_in_examples, expected)

    def test_each_example_has_raw_and_meaning(self):
        for ex in PROVENANCE_LABEL_FORMAT["examples"]:
            self.assertIn("raw", ex)
            self.assertIn("meaning", ex)
            self.assertTrue(ex["raw"].startswith("["))


class TestProvenanceConflictResolution(unittest.TestCase):
    """TASK-a362acbf: conflict resolution rules."""

    def test_at_least_four_rules(self):
        self.assertGreaterEqual(len(PROVENANCE_CONFLICT_RESOLUTION["rules"]), 4)

    def test_each_rule_has_required_fields(self):
        for rule in PROVENANCE_CONFLICT_RESOLUTION["rules"]:
            self.assertIn("conflict", rule)
            self.assertIn("resolution", rule)
            self.assertIn("label_precedence", rule)

    def test_precedence_order_matches_categories(self):
        order = PROVENANCE_CONFLICT_RESOLUTION["precedence_order"]
        all_labels = {d["label"] for d in PROVENANCE_CATEGORIES.values()}
        self.assertEqual(set(order), all_labels)

    def test_live_is_highest_precedence(self):
        self.assertEqual(PROVENANCE_CONFLICT_RESOLUTION["precedence_order"][0], "LIVE")

    def test_calc_is_lowest_precedence(self):
        self.assertEqual(PROVENANCE_CONFLICT_RESOLUTION["precedence_order"][-1], "CALC")


class TestPanelProvenanceExamples(unittest.TestCase):
    """TASK-5c1421dc: panel provenance examples."""

    def test_at_least_eight_examples(self):
        self.assertGreaterEqual(len(PANEL_PROVENANCE_EXAMPLES), 8)

    def test_each_example_has_required_fields(self):
        required = {"panel", "field", "value_example", "provenance_label",
                     "source_tool", "confidence_wording", "staleness_note"}
        for i, ex in enumerate(PANEL_PROVENANCE_EXAMPLES):
            with self.subTest(i=i):
                self.assertTrue(required.issubset(ex.keys()))

    def test_provenance_labels_are_valid(self):
        valid_labels = {d["label"] for d in PROVENANCE_CATEGORIES.values()}
        for ex in PANEL_PROVENANCE_EXAMPLES:
            with self.subTest(field=ex["field"]):
                self.assertIn(ex["provenance_label"], valid_labels)

    def test_all_provenance_types_represented(self):
        used_labels = {ex["provenance_label"] for ex in PANEL_PROVENANCE_EXAMPLES}
        all_labels = {d["label"] for d in PROVENANCE_CATEGORIES.values()}
        self.assertEqual(used_labels, all_labels)

    def test_multiple_panels_covered(self):
        panels = {ex["panel"] for ex in PANEL_PROVENANCE_EXAMPLES}
        self.assertGreaterEqual(len(panels), 4)

    def test_confidence_wording_non_empty(self):
        for ex in PANEL_PROVENANCE_EXAMPLES:
            with self.subTest(field=ex["field"]):
                self.assertGreater(len(ex["confidence_wording"]), 10)

    def test_staleness_note_non_empty(self):
        for ex in PANEL_PROVENANCE_EXAMPLES:
            with self.subTest(field=ex["field"]):
                self.assertGreater(len(ex["staleness_note"]), 10)

    def test_source_tool_non_empty(self):
        for ex in PANEL_PROVENANCE_EXAMPLES:
            with self.subTest(field=ex["field"]):
                self.assertGreater(len(ex["source_tool"]), 5)


class TestConfidenceWordingGuide(unittest.TestCase):
    """TASK-5c1421dc: confidence wording guidelines."""

    def test_four_levels_defined(self):
        self.assertEqual(len(CONFIDENCE_WORDING_GUIDE["levels"]), 4)

    def test_each_level_has_required_fields(self):
        required = {"level", "provenance", "wording_patterns", "when_to_use"}
        for lvl in CONFIDENCE_WORDING_GUIDE["levels"]:
            with self.subTest(level=lvl["level"]):
                self.assertTrue(required.issubset(lvl.keys()))

    def test_each_level_has_multiple_patterns(self):
        for lvl in CONFIDENCE_WORDING_GUIDE["levels"]:
            with self.subTest(level=lvl["level"]):
                self.assertGreaterEqual(len(lvl["wording_patterns"]), 3)

    def test_provenances_match_categories(self):
        guide_provenances = {lvl["provenance"] for lvl in CONFIDENCE_WORDING_GUIDE["levels"]}
        cat_labels = {d["label"] for d in PROVENANCE_CATEGORIES.values()}
        self.assertEqual(guide_provenances, cat_labels)

    def test_formatting_rules_exist(self):
        self.assertGreaterEqual(len(CONFIDENCE_WORDING_GUIDE["formatting_rules"]), 4)

    def test_formatting_rules_are_strings(self):
        for rule in CONFIDENCE_WORDING_GUIDE["formatting_rules"]:
            self.assertIsInstance(rule, str)
            self.assertGreater(len(rule), 10)

    def test_authoritative_level_maps_to_live(self):
        auth = [l for l in CONFIDENCE_WORDING_GUIDE["levels"]
                if l["level"] == "authoritative"][0]
        self.assertEqual(auth["provenance"], "LIVE")

    def test_derived_level_maps_to_calc(self):
        derived = [l for l in CONFIDENCE_WORDING_GUIDE["levels"]
                   if l["level"] == "derived"][0]
        self.assertEqual(derived["provenance"], "CALC")


if __name__ == "__main__":
    unittest.main()
