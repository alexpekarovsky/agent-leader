import unittest
from scripts.autopilot.dashboard_tui import (
    DashboardSnapshot,
    _health_score,
    _render_claude_v3a,
    _now_utc,
)


def _make_snapshot(**overrides):
    """Build a DashboardSnapshot with sensible defaults, overridden by kwargs."""
    defaults = dict(
        project_root="/test/project",
        total_tasks=50,
        open_tasks=5,
        done_tasks=45,
        progress_percent=90,
        status_counts={"done": 45, "in_progress": 3, "assigned": 2},
        in_progress=[
            {"id": "TASK-1", "owner": "claude_code", "updated_at": _now_utc().isoformat(), "title": "Implement feature X"},
            {"id": "TASK-2", "owner": "gemini", "updated_at": _now_utc().isoformat(), "title": "Fix bug Y"},
        ],
        assigned=[
            {"id": "TASK-3", "status": "assigned", "owner": "claude_code", "title": "Queued work"},
        ],
        blockers_open=1,
        bugs_open=2,
        active_agents=[
            {"agent": "claude_code", "status": "active", "age_s": 30, "instance_id": "claude_code#1"},
            {"agent": "gemini", "status": "active", "age_s": 60, "instance_id": "gemini#1"},
        ],
        review_events=[],
        budget_calls_today=85,
        budget_by_process={"manager": 25, "worker-claude": 60},
        loc_added_total=1200,
        loc_deleted_total=300,
        loc_net_total=900,
        reports_count=10,
        token_prompt_total=50000,
        token_completion_total=25000,
        token_total=75000,
        team_lane_counts={
            "team-api": {"total": 30, "open": 3, "done": 27, "in_progress": 2, "assigned": 1, "blocked": 0},
            "team-web": {"total": 20, "open": 2, "done": 18, "in_progress": 1, "assigned": 1, "blocked": 0},
        },
        stale_in_progress=0,
        recent_events=[],
        supervisor_processes=[{"name": "manager", "alive": True, "pid": 12345, "age_s": 7200}],
        done_last_hour=3,
        throughput_per_hour=3.0,
        eta_minutes=2,
        next_actions=["Flow healthy. Continue monitoring throughput and review cadence."],
        validation_passed=8,
        validation_failed=2,
        review_pass_rate=80.0,
        oldest_open_task_age_s=1800,
        queue_pressure=2.5,
        active_agent_count=2,
        idle_agent_count=0,
        avg_loc_per_report=150.0,
        avg_tokens_per_report=7500.0,
        avg_task_lead_time_s=900,
        avg_validation_cycle_time_s=300,
        agent_utilization_percent=100.0,
        task_failure_rate_percent=20.0,
        cost_efficiency_loc_per_k_tokens=20.0,
    )
    defaults.update(overrides)
    return DashboardSnapshot(**defaults)


class TestHealthScore(unittest.TestCase):
    def test_healthy_system(self):
        snap = _make_snapshot(
            progress_percent=100,
            review_pass_rate=100.0,
            agent_utilization_percent=100.0,
            task_failure_rate_percent=0.0,
            blockers_open=0,
            stale_in_progress=0,
        )
        score = _health_score(snap)
        self.assertGreaterEqual(score, 95)
        self.assertLessEqual(score, 100)

    def test_degraded_system(self):
        snap = _make_snapshot(
            progress_percent=50,
            review_pass_rate=50.0,
            agent_utilization_percent=50.0,
            task_failure_rate_percent=50.0,
            blockers_open=3,
            stale_in_progress=3,
        )
        score = _health_score(snap)
        self.assertGreater(score, 0)
        self.assertLess(score, 60)

    def test_score_bounds(self):
        snap = _make_snapshot(
            progress_percent=0,
            review_pass_rate=0.0,
            agent_utilization_percent=0.0,
            task_failure_rate_percent=100.0,
            blockers_open=10,
            stale_in_progress=10,
        )
        score = _health_score(snap)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_none_defaults(self):
        snap = _make_snapshot(
            review_pass_rate=None,
            agent_utilization_percent=None,
            task_failure_rate_percent=None,
        )
        score = _health_score(snap)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)


class TestClaudeV3ARender(unittest.TestCase):
    def test_render_contains_header(self):
        snap = _make_snapshot()
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("CLAUDE V3A EXECUTIVE", output)
        self.assertIn("RUNNING", output)
        self.assertIn("Project: /test/project", output)

    def test_render_contains_health_score(self):
        snap = _make_snapshot()
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("HEALTH", output)
        self.assertIn("/100", output)

    def test_render_new_metrics_avg_lead_time(self):
        snap = _make_snapshot(avg_task_lead_time_s=900)
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("Avg Lead Time: 15m", output)

    def test_render_new_metrics_avg_validation(self):
        snap = _make_snapshot(avg_validation_cycle_time_s=300)
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("Avg Validation: 5m", output)

    def test_render_new_metrics_utilization(self):
        snap = _make_snapshot(agent_utilization_percent=100.0)
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("util=100%", output)

    def test_render_new_metrics_failure_rate(self):
        snap = _make_snapshot(task_failure_rate_percent=20.0)
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("Failure Rate: 20%", output)

    def test_render_new_metrics_cost_efficiency(self):
        snap = _make_snapshot(cost_efficiency_loc_per_k_tokens=20.0)
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("Efficiency: 20 LOC/k-tok", output)

    def test_render_new_metrics_avg_loc_per_report(self):
        snap = _make_snapshot(avg_loc_per_report=150.0)
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("Avg LOC/Report: 150", output)

    def test_render_panels_present(self):
        snap = _make_snapshot()
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("Progress & Throughput", output)
        self.assertIn("Cost & Efficiency", output)
        self.assertIn("Fleet", output)
        self.assertIn("Active Work", output)
        self.assertIn("Alerts & Actions", output)

    def test_render_completed_mode(self):
        snap = _make_snapshot()
        output = _render_claude_v3a(snap, completed=True, auto_stopped=False, color_enabled=False)
        self.assertIn("COMPLETED", output)

    def test_render_auto_stopped(self):
        snap = _make_snapshot()
        output = _render_claude_v3a(snap, completed=True, auto_stopped=True, color_enabled=False)
        self.assertIn("AUTO-STOP", output)

    def test_render_critical_indicators(self):
        snap = _make_snapshot(blockers_open=3, bugs_open=2, stale_in_progress=1)
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("BLOCKERS:3", output)
        self.assertIn("BUGS:2", output)
        self.assertIn("STALE:1", output)

    def test_render_style_tag(self):
        snap = _make_snapshot()
        output = _render_claude_v3a(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("style=claude-v3a", output)

    def test_render_dispatch(self):
        from scripts.autopilot.dashboard_tui import _render
        snap = _make_snapshot()
        output = _render(snap, completed=False, auto_stopped=False, style="claude-v3a", color_enabled=False)
        self.assertIn("CLAUDE V3A EXECUTIVE", output)

    def test_stable_fixed_height(self):
        snap_full = _make_snapshot()
        snap_empty = _make_snapshot(
            in_progress=[], assigned=[], active_agents=[],
            supervisor_processes=[], team_lane_counts={},
        )
        out_full = _render_claude_v3a(snap_full, completed=False, auto_stopped=False, color_enabled=False)
        out_empty = _render_claude_v3a(snap_empty, completed=False, auto_stopped=False, color_enabled=False)
        self.assertEqual(len(out_full.splitlines()), len(out_empty.splitlines()))


if __name__ == "__main__":
    unittest.main()
