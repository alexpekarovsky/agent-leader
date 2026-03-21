from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "autopilot" / "dashboard_tui.py"

spec = importlib.util.spec_from_file_location("dashboard_tui", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)  # type: ignore[arg-type]


class DashboardTuiTests(unittest.TestCase):
    def test_agent_profile_operator_labels(self) -> None:
        profile = mod._agent_profile("ccm", {"model": "claude-sonnet"})
        self.assertEqual(profile["display_name"], "Claude Wingman")
        self.assertEqual(profile["role_label"], "Wingman/Reviewer")
        self.assertEqual(profile["type_label"], "Claude Code")
        self.assertEqual(profile["model_label"], "claude-sonnet")

    def test_project_meta_reads_name_version_and_active_milestones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project.yaml").write_text(
                "\n".join(
                    [
                        "name: Agent Leader Orchestrator",
                        "version:",
                        "  current: v0.2.0",
                        '  name: "Stability + Multi-Project Foundation"',
                        "  milestones:",
                        "    - id: ci-github-integrations",
                        "      title: Integrate GitHub issue/PR handoff and CI result ingestion into validation loop",
                        "      status: in_progress",
                    ]
                ),
                encoding="utf-8",
            )
            meta = mod._read_project_meta(root)
            self.assertEqual(meta["project_name"], "Agent Leader Orchestrator")
            self.assertEqual(meta["version_current"], "v0.2.0")
            self.assertEqual(meta["version_name"], "Stability + Multi-Project Foundation")
            self.assertEqual(meta["active_milestones"], ["Integrate GitHub issue/PR handoff and CI result ingestion into validation loop"])

    def test_clean_task_title_and_description(self) -> None:
        self.assertEqual(mod._clean_task_title("Milestone: Codebase Comprehension Phase - task type rollout"), "Codebase Comprehension Phase")
        self.assertEqual(mod._clean_task_description("Implement comprehend_project task type and structured summary artifacts before planning begins."), "comprehend_project task type and structured summary artifacts before planning begins")

    def test_extract_token_usage_variants(self) -> None:
        p, c, t = mod._extract_token_usage({"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        self.assertEqual((p, c, t), (10, 5, 15))

        p, c, t = mod._extract_token_usage({"usage": {"prompt_tokens": 7, "completion_tokens": 9, "total_tokens": 20}})
        self.assertEqual((p, c, t), (7, 9, 20))

        p, c, t = mod._extract_token_usage({})
        self.assertEqual((p, c, t), (None, None, None))

    def test_build_snapshot_progress_budget_and_loc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "bus" / "reports").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

            project_root = "/tmp/my-project"
            tasks = [
                {
                    "id": "T1",
                    "project_root": project_root,
                    "status": "done",
                    "owner": "codex",
                    "title": "Done",
                    "team_id": "team-api",
                    "created_at": "2026-03-17T10:00:00+00:00",
                    "reported_at": "2026-03-17T10:20:00+00:00",
                    "validated_at": "2026-03-17T10:30:00+00:00",
                    "updated_at": "2026-03-17T10:30:00+00:00",
                },
                {
                    "id": "T3",
                    "project_root": project_root,
                    "status": "done",
                    "owner": "claude_code",
                    "title": "Claude Done",
                    "team_id": "team-api",
                    "updated_at": "2099-01-01T00:00:00+00:00",
                },
                {"id": "T2", "project_root": project_root, "status": "assigned", "owner": "gemini", "title": "Open", "team_id": "team-web"},
            ]
            (root / "state" / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            (root / "state" / "blockers.json").write_text("[]", encoding="utf-8")
            (root / "state" / "bugs.json").write_text("[]", encoding="utf-8")
            (root / "state" / "agents.json").write_text(
                json.dumps({"codex": {"status": "active", "last_seen": "2026-03-17T00:00:00+00:00", "metadata": {"instance_id": "codex#1"}}}),
                encoding="utf-8",
            )
            (root / "bus" / "events.jsonl").write_text("", encoding="utf-8")

            report = {
                "project_root": project_root,
                "task_id": "T1",
                "commit_sha": "abc123",
                "commit_metrics": {"lines_added": 100, "lines_deleted": 30},
                "token_usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
            }
            report_path = root / "bus" / "reports" / "TASK-T1.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            now_ts = mod._now_utc().timestamp()
            os.utime(report_path, (now_ts, now_ts))
            pid_dir = root / ".autopilot-pids"
            pid_dir.mkdir(parents=True, exist_ok=True)
            pid_file = pid_dir / "manager.pid"
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
            os.utime(pid_file, (now_ts, now_ts))

            # Blockers for project
            blockers = [
                {
                    "id": "B1",
                    "task_id": "T1",
                    "status": "resolved",
                    "created_at": "2026-03-17T11:00:00+00:00",
                    "resolved_at": "2026-03-17T11:10:00+00:00",
                }
            ]
            (root / "state" / "blockers.json").write_text(json.dumps(blockers), encoding="utf-8")

            # Events for project
            (root / "bus" / "events.jsonl").write_text(
                json.dumps({"timestamp": "2026-03-17T11:00:00+00:00", "type": "validation.passed", "source": "codex", "payload": {"task_id": "T1"}}) + "\n" +
                json.dumps({"timestamp": "2026-03-17T11:05:00+00:00", "type": "validation.failed", "source": "ccm", "payload": {"task_id": "T1"}}) + "\n" +
                json.dumps({"timestamp": "2026-03-17T11:07:00+00:00", "type": "validation.passed", "source": "claude_code", "payload": {"task_id": "T3"}}) + "\n",
                encoding="utf-8"
            )

            stamp = mod._now_utc().strftime("%Y%m%d")
            (root / ".autopilot-logs" / f".budget-worker-codex-codex-{stamp}.count").write_text("17", encoding="utf-8")

            snap = mod.build_snapshot(project_root=project_root, root=root)

            self.assertEqual(snap.total_tasks, 3)
            self.assertEqual(snap.open_tasks, 1)
            self.assertEqual(snap.done_tasks, 2)
            self.assertEqual(snap.progress_percent, 66)
            self.assertEqual(snap.loc_added_total, 100)
            self.assertEqual(snap.loc_deleted_total, 30)
            self.assertEqual(snap.loc_net_total, 70)
            self.assertEqual(snap.budget_calls_today, 17)
            self.assertEqual(snap.token_total, 33)
            self.assertIn("team-api", snap.team_lane_counts)
            self.assertIn("team-web", snap.team_lane_counts)
            self.assertTrue(len(snap.next_actions) >= 1)
            
            # V3B Verify
            self.assertEqual(snap.avg_task_lead_time_s, 1800)
            self.assertEqual(snap.avg_validation_cycle_time_s, 600)
            self.assertEqual(snap.agent_utilization_percent, 0.0) # No in_progress tasks
            self.assertEqual(snap.cost_efficiency_loc_per_k_tokens, 130 / (33 / 1000.0))

            # 5 New Metrics Verify
            self.assertEqual(snap.avg_blocker_resolution_time_s, 600)
            self.assertEqual(snap.stale_task_percent, 0.0)
            self.assertEqual(snap.agent_diversity, 2) # codex + claude_code
            self.assertEqual(snap.total_validations, 3)
            self.assertEqual(snap.avg_review_loop_depth, 0.5) # 1 fail / 2 pass
            self.assertEqual(snap.claude_throughput_per_hour, 1.0)
            self.assertAlmostEqual(snap.wingman_validation_contribution_percent or 0.0, 33.33333333333333)
            self.assertAlmostEqual(snap.claude_validation_contribution_percent or 0.0, 33.33333333333333)
            self.assertEqual(snap.commits_today, 1)
            self.assertEqual(snap.commits_session, 1)
            self.assertEqual(snap.tasks_done_today, 1)
            self.assertEqual(snap.tasks_done_session, 1)
            self.assertEqual(snap.reports_today, 1)
            self.assertEqual(snap.reports_session, 1)
            self.assertEqual(snap.loc_added_today, 100)
            self.assertEqual(snap.loc_deleted_today, 30)
            self.assertEqual(snap.loc_added_session, 100)
            self.assertEqual(snap.loc_deleted_session, 30)
            self.assertEqual(snap.token_total_today, 33)
            self.assertEqual(snap.token_total_session, 33)

    def test_build_snapshot_distinguishes_process_heartbeat_and_task_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "bus" / "reports").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-pids").mkdir(parents=True, exist_ok=True)

            project_root = "/tmp/my-project"
            tasks = [
                {"id": "T1", "project_root": project_root, "status": "in_progress", "owner": "claude_code", "title": "Implement feature", "updated_at": "2099-01-01T00:00:00+00:00"},
                {"id": "T2", "project_root": project_root, "status": "assigned", "owner": "gemini", "title": "Queued task", "updated_at": "2099-01-01T00:00:00+00:00"},
            ]
            (root / "state" / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            (root / "state" / "blockers.json").write_text("[]", encoding="utf-8")
            (root / "state" / "bugs.json").write_text("[]", encoding="utf-8")
            (root / "state" / "agents.json").write_text(
                json.dumps(
                    {
                        "claude_code": {"status": "active", "last_seen": mod._now_utc().isoformat(), "metadata": {"instance_id": "claude_code#default"}},
                        "gemini": {"status": "active", "last_seen": "2026-03-18T00:00:00+00:00", "metadata": {"instance_id": "gemini#default"}},
                    }
                ),
                encoding="utf-8",
            )
            (root / "bus" / "events.jsonl").write_text("", encoding="utf-8")
            for name in ("claude.pid", "gemini.pid", "manager.pid"):
                (root / ".autopilot-pids" / name).write_text(str(os.getpid()), encoding="utf-8")

            snap = mod.build_snapshot(project_root=project_root, root=root)
            rows = {row["agent"]: row for row in snap.active_agents}
            self.assertEqual(rows["claude_code"]["process_state"], "up")
            self.assertEqual(rows["claude_code"]["heartbeat_state"], "active")
            self.assertEqual(rows["claude_code"]["task_activity"], "working")
            self.assertEqual(rows["gemini"]["process_state"], "up")
            self.assertIn(rows["gemini"]["heartbeat_state"], {"stale", "offline"})
            self.assertEqual(rows["gemini"]["task_activity"], "queued")

    def test_dashboard_default_style_is_gemini_v3b(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('default="gemini-v3b"', source)

    def test_render_gemini_v3b(self) -> None:
        # Create a dummy snapshot
        snap = mod.DashboardSnapshot(
            project_root="/tmp/test",
            total_tasks=10,
            open_tasks=5,
            done_tasks=5,
            progress_percent=50,
            status_counts={"done": 5, "assigned": 5},
            in_progress=[{"id": "TASK-7", "owner": "gemini", "updated_at": "2026-03-17T12:00:00+00:00", "title": "Milestone: CI/GitHub Integrations - phase execution", "description": "Implement CI result ingestion + GitHub PR/issue handoff integration path and validation hooks."}],
            assigned=[{"id": "TASK-8", "status": "assigned", "owner": "claude_code", "title": "Planned Next: Iterative Self-Review loop scaffold", "description": "Design and scaffold multi-round self-review loop before manager/wingman handoff."}],
            blockers_open=1,
            bugs_open=2,
            active_agents=[
                {"agent": "codex", "status": "active", "age_s": 100, "instance_id": "i1", "display_name": "Codex", "role_label": "Leader/Manager", "provider": "OpenAI", "client": "Codex CLI", "model": "-"},
                {"agent": "gemini", "status": "active", "age_s": 80, "instance_id": "i2", "display_name": "Gemini", "role_label": "Worker", "provider": "Google", "client": "Gemini CLI", "model": "gemini-2.5-flash"},
            ],
            review_events=[],
            budget_calls_today=100,
            budget_by_process={"p1": 100},
            loc_added_total=500,
            loc_deleted_total=100,
            loc_net_total=400,
            reports_count=5,
            token_prompt_total=1000,
            token_completion_total=500,
            token_total=1500,
            team_lane_counts={"default": {"total": 10, "open": 5, "done": 5, "in_progress": 0, "assigned": 5, "blocked": 0}},
            stale_in_progress=0,
            recent_events=[],
            supervisor_processes=[],
            done_last_hour=2,
            throughput_per_hour=2.0,
            eta_minutes=150,
            next_actions=["action1"],
            validation_passed=4,
            validation_failed=1,
            review_pass_rate=80.0,
            oldest_open_task_age_s=3600,
            queue_pressure=5.0,
            active_agent_count=1,
            idle_agent_count=1,
            avg_loc_per_report=120.0,
            avg_tokens_per_report=300.0,
            avg_task_lead_time_s=1800,
            avg_validation_cycle_time_s=600,
            agent_utilization_percent=0.0,
            task_failure_rate_percent=20.0,
            cost_efficiency_loc_per_k_tokens=400.0,
            avg_blocker_resolution_time_s=1200,
            stale_task_percent=0.0,
            agent_diversity=2,
            total_validations=5,
            avg_review_loop_depth=0.25,
            claude_throughput_per_hour=1.0,
            claude_validation_contribution_percent=40.0,
            wingman_validation_contribution_percent=20.0,
            claude_latest_lane_event_type="validation.passed",
            wingman_latest_lane_event_type="validation.failed",
            project_name_display="Agent Leader Orchestrator",
            version_current="v0.2.0",
            version_name="Stability + Multi-Project Foundation",
            active_milestones=["CI/GitHub Integrations", "Codebase Comprehension Phase"],
            session_started_at=mod._now_utc(),
            session_duration_s=420,
            commits_today=3,
            commits_session=2,
            tasks_done_today=4,
            tasks_done_session=2,
            reports_today=4,
            reports_session=2,
            files_changed_today=12,
            files_changed_session=7,
            loc_added_today=220,
            loc_deleted_today=40,
            loc_added_session=90,
            loc_deleted_session=10,
            token_total_today=700,
            token_total_session=250,
            validations_today=4,
            validations_session=2,
        )
        
        out = mod._render_gemini_v3b(snap, completed=False, auto_stopped=False, color_enabled=False)
        
        # Check for new metrics in output
        self.assertIn("Velocity & Quality", out)
        self.assertIn("Agent Leader Orchestrator", out)
        self.assertIn("Version: v0.2.0 - Stability + Multi-Project Foundation", out)
        self.assertIn("Version focus: CI/GitHub Integrations | Codebase Comprehension Phase", out)
        self.assertIn("Team Topology", out)
        self.assertIn("Delivery: today t4/c3/loc180", out)
        self.assertIn("Codex | Leader | proc:-(0) hb:-", out)
        self.assertIn("Agent Session Stats:", out)
        self.assertIn("Current Work:", out)
        self.assertIn("Queued Next:", out)
        self.assertIn("Blocked:", out)
        self.assertIn("Done this session: 2", out)
        self.assertIn("Today: tasks=4 commits=3 files=12", out)
        self.assertIn("Session: tasks=2 commits=2 files=7", out)
        self.assertIn("Today LOC: +220/-40 net=180", out)
        self.assertIn("Session LOC: +90/-10 net=80", out)
        self.assertIn("Validations Today/Session: 4/2", out)
        self.assertIn("CI/GitHub Integrations", out)
        self.assertIn("CI result ingestion + GitHub PR/issue handoff integration path and validation hooks", out)
        self.assertIn("Total Validations: 5", out)
        self.assertIn("Failure Rate: 20", out)
        self.assertIn("Review Depth: 0.2x", out)
        self.assertIn("Stale Tasks: 0", out)
        self.assertIn("Blocker Res: 20m", out)
        self.assertIn("Active: 1 (div:2)", out)
        self.assertIn("Claude-only signals:", out)
        self.assertIn("claude validation share: 40", out)
        self.assertIn("style=gemini-v3b", out)


    def test_project_meta_milestone_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project.yaml").write_text(
                "\n".join(
                    [
                        "name: Test Project",
                        "version:",
                        "  current: v0.2.0",
                        '  name: "Test Phase"',
                        "  milestones:",
                        "    - id: m1",
                        "      title: First milestone",
                        "      status: done",
                        "    - id: m2",
                        "      title: Second milestone",
                        "      status: done",
                        "    - id: m3",
                        "      title: Third milestone",
                        "      status: in_progress",
                        "    - id: m4",
                        "      title: Fourth milestone",
                        "      status: planned",
                    ]
                ),
                encoding="utf-8",
            )
            meta = mod._read_project_meta(root)
            self.assertEqual(meta["milestones_total"], 4)
            self.assertEqual(meta["milestones_done"], 2)
            self.assertEqual(meta["active_milestones"], ["Third milestone"])

    def test_completion_blocked_by_open_blockers(self) -> None:
        """Dashboard must not report COMPLETED when blockers are open."""
        snap = mod.DashboardSnapshot(
            project_root="/tmp/test",
            total_tasks=2, open_tasks=0, done_tasks=2, progress_percent=100,
            status_counts={"done": 2}, in_progress=[], assigned=[],
            blockers_open=1, bugs_open=0,
            active_agents=[], review_events=[],
            budget_calls_today=0, budget_by_process={},
            loc_added_total=0, loc_deleted_total=0, loc_net_total=0,
            reports_count=0, token_prompt_total=None, token_completion_total=None,
            token_total=None, team_lane_counts={}, stale_in_progress=0,
            recent_events=[], supervisor_processes=[],
            done_last_hour=0, throughput_per_hour=None, eta_minutes=None,
            next_actions=[], validation_passed=0, validation_failed=0,
            review_pass_rate=None, oldest_open_task_age_s=None,
            queue_pressure=None, active_agent_count=0, idle_agent_count=0,
            avg_loc_per_report=None, avg_tokens_per_report=None,
            milestones_total=2, milestones_done=2,
        )
        # open_tasks==0 but blockers_open > 0 → should NOT be COMPLETED
        has_open_blockers = snap.blockers_open > 0
        has_pending_milestones = snap.milestones_total > 0 and snap.milestones_done < snap.milestones_total
        has_live_supervisor = any(p.get("alive") for p in snap.supervisor_processes)
        truly_complete = (
            snap.open_tasks == 0
            and not has_open_blockers
            and not has_pending_milestones
            and not has_live_supervisor
        )
        self.assertFalse(truly_complete, "Should not be complete with open blockers")

    def test_completion_blocked_by_pending_milestones(self) -> None:
        """Dashboard must not report COMPLETED when milestones are not all done."""
        snap = mod.DashboardSnapshot(
            project_root="/tmp/test",
            total_tasks=2, open_tasks=0, done_tasks=2, progress_percent=100,
            status_counts={"done": 2}, in_progress=[], assigned=[],
            blockers_open=0, bugs_open=0,
            active_agents=[], review_events=[],
            budget_calls_today=0, budget_by_process={},
            loc_added_total=0, loc_deleted_total=0, loc_net_total=0,
            reports_count=0, token_prompt_total=None, token_completion_total=None,
            token_total=None, team_lane_counts={}, stale_in_progress=0,
            recent_events=[], supervisor_processes=[],
            done_last_hour=0, throughput_per_hour=None, eta_minutes=None,
            next_actions=[], validation_passed=0, validation_failed=0,
            review_pass_rate=None, oldest_open_task_age_s=None,
            queue_pressure=None, active_agent_count=0, idle_agent_count=0,
            avg_loc_per_report=None, avg_tokens_per_report=None,
            milestones_total=5, milestones_done=3,
            active_milestones=["In-progress milestone"],
        )
        has_pending_milestones = snap.milestones_total > 0 and snap.milestones_done < snap.milestones_total
        self.assertTrue(has_pending_milestones)
        truly_complete = (
            snap.open_tasks == 0
            and snap.blockers_open == 0
            and not has_pending_milestones
            and not any(p.get("alive") for p in snap.supervisor_processes)
        )
        self.assertFalse(truly_complete, "Should not be complete with pending milestones")

    def test_completion_blocked_by_live_supervisor(self) -> None:
        """Dashboard must not report COMPLETED when supervisor processes are alive."""
        snap = mod.DashboardSnapshot(
            project_root="/tmp/test",
            total_tasks=2, open_tasks=0, done_tasks=2, progress_percent=100,
            status_counts={"done": 2}, in_progress=[], assigned=[],
            blockers_open=0, bugs_open=0,
            active_agents=[], review_events=[],
            budget_calls_today=0, budget_by_process={},
            loc_added_total=0, loc_deleted_total=0, loc_net_total=0,
            reports_count=0, token_prompt_total=None, token_completion_total=None,
            token_total=None, team_lane_counts={}, stale_in_progress=0,
            recent_events=[], supervisor_processes=[{"name": "manager", "alive": True}],
            done_last_hour=0, throughput_per_hour=None, eta_minutes=None,
            next_actions=[], validation_passed=0, validation_failed=0,
            review_pass_rate=None, oldest_open_task_age_s=None,
            queue_pressure=None, active_agent_count=0, idle_agent_count=0,
            avg_loc_per_report=None, avg_tokens_per_report=None,
            milestones_total=2, milestones_done=2,
        )
        has_live_supervisor = any(p.get("alive") for p in snap.supervisor_processes)
        self.assertTrue(has_live_supervisor)
        truly_complete = (
            snap.open_tasks == 0
            and snap.blockers_open == 0
            and not (snap.milestones_total > 0 and snap.milestones_done < snap.milestones_total)
            and not has_live_supervisor
        )
        self.assertFalse(truly_complete, "Should not be complete with live supervisor")

    def test_completion_allowed_when_all_clear(self) -> None:
        """Dashboard should allow COMPLETED when all conditions are met."""
        snap = mod.DashboardSnapshot(
            project_root="/tmp/test",
            total_tasks=2, open_tasks=0, done_tasks=2, progress_percent=100,
            status_counts={"done": 2}, in_progress=[], assigned=[],
            blockers_open=0, bugs_open=0,
            active_agents=[], review_events=[],
            budget_calls_today=0, budget_by_process={},
            loc_added_total=0, loc_deleted_total=0, loc_net_total=0,
            reports_count=0, token_prompt_total=None, token_completion_total=None,
            token_total=None, team_lane_counts={}, stale_in_progress=0,
            recent_events=[], supervisor_processes=[],
            done_last_hour=0, throughput_per_hour=None, eta_minutes=None,
            next_actions=[], validation_passed=0, validation_failed=0,
            review_pass_rate=None, oldest_open_task_age_s=None,
            queue_pressure=None, active_agent_count=0, idle_agent_count=0,
            avg_loc_per_report=None, avg_tokens_per_report=None,
            milestones_total=2, milestones_done=2,
        )
        truly_complete = (
            snap.open_tasks == 0
            and snap.blockers_open == 0
            and not (snap.milestones_total > 0 and snap.milestones_done < snap.milestones_total)
            and not any(p.get("alive") for p in snap.supervisor_processes)
        )
        self.assertTrue(truly_complete, "Should be complete when all conditions are met")

    def test_render_milestone_progress_bar(self) -> None:
        """Dashboard should render milestone progress bar when milestones exist."""
        snap = mod.DashboardSnapshot(
            project_root="/tmp/test",
            total_tasks=10, open_tasks=5, done_tasks=5, progress_percent=50,
            status_counts={"done": 5, "assigned": 5},
            in_progress=[], assigned=[],
            blockers_open=0, bugs_open=0,
            active_agents=[], review_events=[],
            budget_calls_today=0, budget_by_process={},
            loc_added_total=0, loc_deleted_total=0, loc_net_total=0,
            reports_count=0, token_prompt_total=None, token_completion_total=None,
            token_total=None, team_lane_counts={}, stale_in_progress=0,
            recent_events=[], supervisor_processes=[],
            done_last_hour=0, throughput_per_hour=None, eta_minutes=None,
            next_actions=["action1"], validation_passed=0, validation_failed=0,
            review_pass_rate=None, oldest_open_task_age_s=None,
            queue_pressure=None, active_agent_count=0, idle_agent_count=0,
            avg_loc_per_report=None, avg_tokens_per_report=None,
            project_name_display="Test Project",
            version_current="v0.2.0",
            version_name="Test Phase",
            active_milestones=["Active Milestone"],
            milestones_total=10, milestones_done=7,
        )
        out = mod._render_gemini_v3b(snap, completed=False, auto_stopped=False, color_enabled=False)
        self.assertIn("Milestones:", out)
        self.assertIn("(7/10)", out)
        self.assertIn("70%", out)
        self.assertIn("Version focus: Active Milestone", out)


    # ------------------------------------------------------------------
    # AC3 — Idle lifecycle: leader / worker / watchdog visibility
    # ------------------------------------------------------------------

    def test_idle_leader_with_stale_heartbeat_triggers_remediation(self) -> None:
        """When leader process is up but heartbeat is stale, next_actions must
        include a stale-leader remediation hint."""
        active_agents = [
            {
                "agent": "codex",
                "status": "stale",
                "heartbeat_state": "stale",
                "age_s": 900,
                "process_state": "up",
                "process_count": 1,
                "process_names": ["manager"],
                "task_activity": "idle",
                "role_label": "Leader/Manager",
                "display_name": "Codex",
                "provider": "OpenAI",
                "client": "Codex CLI",
                "model": "-",
                "instance_id": "codex#default",
            },
        ]
        actions = mod._compute_next_actions(
            open_tasks=3,
            assigned_count=2,
            in_progress_count=1,
            blockers_open=0,
            bugs_open=0,
            stale_in_progress=0,
            supervisor_processes=[{"name": "manager", "alive": True}],
            active_agents=active_agents,
        )
        stale_leader_actions = [a for a in actions if "Leader heartbeat stale" in a]
        self.assertEqual(len(stale_leader_actions), 1, "Expected exactly one stale-leader remediation action")
        self.assertIn("manager_loop", stale_leader_actions[0])

    def test_idle_leader_active_heartbeat_no_remediation(self) -> None:
        """When leader heartbeat is active, no stale-leader action should appear."""
        active_agents = [
            {
                "agent": "codex",
                "heartbeat_state": "active",
                "process_state": "up",
                "task_activity": "idle",
                "role_label": "Leader/Manager",
            },
        ]
        actions = mod._compute_next_actions(
            open_tasks=0,
            assigned_count=0,
            in_progress_count=0,
            blockers_open=0,
            bugs_open=0,
            stale_in_progress=0,
            supervisor_processes=[],
            active_agents=active_agents,
        )
        self.assertFalse(
            any("Leader heartbeat stale" in a for a in actions),
            "Active leader should not trigger stale-leader action",
        )

    def test_watchdog_disabled_state_in_snapshot(self) -> None:
        """When watchdog has no PID file, supervisor should report 'disabled'
        state with task_activity='expected_stopped' rather than 'stopped'."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "bus" / "reports").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-pids").mkdir(parents=True, exist_ok=True)

            project_root = "/tmp/test-watchdog"
            (root / "state" / "tasks.json").write_text("[]", encoding="utf-8")
            (root / "state" / "blockers.json").write_text("[]", encoding="utf-8")
            (root / "state" / "bugs.json").write_text("[]", encoding="utf-8")
            (root / "state" / "agents.json").write_text("{}", encoding="utf-8")
            (root / "bus" / "events.jsonl").write_text("", encoding="utf-8")

            # Manager PID exists (current process) — no watchdog PID file at all.
            now_ts = mod._now_utc().timestamp()
            pid_file = root / ".autopilot-pids" / "manager.pid"
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
            os.utime(pid_file, (now_ts, now_ts))

            # Read supervisor processes as the TUI does.
            procs = mod._read_supervisor_processes(root)
            proc_names = {p["name"] for p in procs}
            # Watchdog should not appear in supervisor processes (no PID file).
            self.assertNotIn("watchdog", proc_names)
            # Manager should appear and be alive.
            manager = next(p for p in procs if p["name"] == "manager")
            self.assertTrue(manager["alive"])

    def test_idle_worker_visible_with_no_tasks(self) -> None:
        """An idle worker with active heartbeat and no owned tasks should show
        task_activity='idle' and remain visible in the agent list."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "bus" / "reports").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-pids").mkdir(parents=True, exist_ok=True)

            project_root = "/tmp/test-idle-worker"
            # Tasks owned by other agents, none by claude_code.
            tasks = [
                {"id": "T1", "project_root": project_root, "status": "done", "owner": "codex", "title": "Done task"},
            ]
            (root / "state" / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            (root / "state" / "blockers.json").write_text("[]", encoding="utf-8")
            (root / "state" / "bugs.json").write_text("[]", encoding="utf-8")
            (root / "state" / "agents.json").write_text(
                json.dumps({
                    "claude_code": {
                        "status": "active",
                        "last_seen": mod._now_utc().isoformat(),
                        "metadata": {"instance_id": "claude_code#default"},
                    },
                    "codex": {
                        "status": "active",
                        "last_seen": mod._now_utc().isoformat(),
                        "metadata": {"instance_id": "codex#default"},
                    },
                }),
                encoding="utf-8",
            )
            (root / "bus" / "events.jsonl").write_text("", encoding="utf-8")

            now_ts = mod._now_utc().timestamp()
            for name in ("claude.pid", "manager.pid"):
                pf = root / ".autopilot-pids" / name
                pf.write_text(str(os.getpid()), encoding="utf-8")
                os.utime(pf, (now_ts, now_ts))

            snap = mod.build_snapshot(project_root=project_root, root=root)
            rows = {row["agent"]: row for row in snap.active_agents}

            # claude_code should be visible, up, active heartbeat, idle task activity
            self.assertIn("claude_code", rows)
            self.assertEqual(rows["claude_code"]["process_state"], "up")
            self.assertEqual(rows["claude_code"]["heartbeat_state"], "active")
            self.assertEqual(rows["claude_code"]["task_activity"], "idle")

            # Idle agent count should include claude_code
            self.assertGreaterEqual(snap.idle_agent_count, 1)

    def test_leader_stale_worker_idle_watchdog_disabled_snapshot(self) -> None:
        """Combined scenario: leader has stale heartbeat, worker is idle, and
        watchdog is disabled (no PID).  Verifies all three visibility semantics."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "bus" / "reports").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-pids").mkdir(parents=True, exist_ok=True)

            project_root = "/tmp/test-combined"
            tasks = [
                {"id": "T1", "project_root": project_root, "status": "assigned", "owner": "gemini", "title": "Queued"},
            ]
            (root / "state" / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            (root / "state" / "blockers.json").write_text("[]", encoding="utf-8")
            (root / "state" / "bugs.json").write_text("[]", encoding="utf-8")
            # Leader heartbeat is stale (old last_seen); worker heartbeat active.
            (root / "state" / "agents.json").write_text(
                json.dumps({
                    "codex": {
                        "status": "active",
                        "last_seen": "2025-01-01T00:00:00+00:00",
                        "metadata": {"instance_id": "codex#default"},
                    },
                    "claude_code": {
                        "status": "active",
                        "last_seen": mod._now_utc().isoformat(),
                        "metadata": {"instance_id": "claude_code#default"},
                    },
                }),
                encoding="utf-8",
            )
            (root / "bus" / "events.jsonl").write_text("", encoding="utf-8")

            # Manager and claude processes up; no watchdog PID.
            now_ts = mod._now_utc().timestamp()
            for name in ("manager.pid", "claude.pid"):
                pf = root / ".autopilot-pids" / name
                pf.write_text(str(os.getpid()), encoding="utf-8")
                os.utime(pf, (now_ts, now_ts))

            snap = mod.build_snapshot(project_root=project_root, root=root)
            rows = {row["agent"]: row for row in snap.active_agents}

            # Leader: process up, heartbeat stale/offline
            self.assertEqual(rows["codex"]["process_state"], "up")
            self.assertIn(rows["codex"]["heartbeat_state"], {"stale", "offline"})

            # Worker: process up, heartbeat active, idle
            self.assertEqual(rows["claude_code"]["process_state"], "up")
            self.assertEqual(rows["claude_code"]["heartbeat_state"], "active")
            self.assertEqual(rows["claude_code"]["task_activity"], "idle")

            # Watchdog: not in supervisor processes (no PID)
            proc_names = {p["name"] for p in snap.supervisor_processes}
            self.assertNotIn("watchdog", proc_names)

            # Next actions should include stale-leader remediation
            stale_leader_hints = [a for a in snap.next_actions if "Leader heartbeat stale" in a]
            self.assertTrue(
                len(stale_leader_hints) >= 1,
                f"Expected stale-leader remediation in next_actions, got: {snap.next_actions}",
            )


if __name__ == "__main__":
    unittest.main()
