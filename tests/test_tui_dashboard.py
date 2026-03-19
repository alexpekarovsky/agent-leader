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
        self.assertIn("Codex (codex) | Leader/Manager", out)
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
        self.assertIn("claude validation share: 40", out)
        self.assertIn("wingman validation share: 20", out)
        self.assertIn("style=gemini-v3b", out)


if __name__ == "__main__":
    unittest.main()
