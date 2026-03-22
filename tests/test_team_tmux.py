"""Consolidated tests for team_tmux.sh --dry-run and team lane counters.

Covers: session naming, CLI timeout propagation, interval propagation,
command ordering, watchdog, monitor, spaces in paths, and lane aggregation.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEAM_TMUX = str(REPO_ROOT / "scripts" / "autopilot" / "team_tmux.sh")
_TIMEOUT = 10


def _dry_run(
    *,
    session: str | None = None,
    manager_cli_timeout: int | None = None,
    worker_cli_timeout: int | None = None,
    manager_interval: int | None = None,
    worker_interval: int | None = None,
    log_dir: str | None = None,
    project_root: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd: list[str] = ["bash", TEAM_TMUX, "--dry-run"]
    if session is not None:
        cmd += ["--session", session]
    if manager_cli_timeout is not None:
        cmd += ["--manager-cli-timeout", str(manager_cli_timeout)]
    if worker_cli_timeout is not None:
        cmd += ["--worker-cli-timeout", str(worker_cli_timeout)]
    if manager_interval is not None:
        cmd += ["--manager-interval", str(manager_interval)]
    if worker_interval is not None:
        cmd += ["--worker-interval", str(worker_interval)]
    if log_dir is not None:
        cmd += ["--log-dir", log_dir]
    if project_root is not None:
        cmd += ["--project-root", project_root]
    return subprocess.run(
        cmd, cwd=REPO_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=_TIMEOUT,
    )


def _tmux_lines(output: str) -> list[str]:
    return [l.strip() for l in output.splitlines() if l.strip().startswith("tmux ")]


def _lines_matching(output: str, keyword: str) -> list[str]:
    return [l for l in output.splitlines() if keyword in l]


# ---------------------------------------------------------------------------
# Dry-run basics
# ---------------------------------------------------------------------------
class TestDryRunBasics(unittest.TestCase):

    def test_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertEqual(0, proc.returncode)

    def test_default_session_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertIn("Session: agents-autopilot", proc.stdout)

    def test_custom_session_name_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(session="dev-team_alpha", log_dir=tmp)
            self.assertIn("Session: dev-team_alpha", proc.stdout)
            self.assertIn("tmux new-session -d -s dev-team_alpha", proc.stdout)
            self.assertIn("-t dev-team_alpha:", proc.stdout)

    def test_seven_tmux_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmds = _tmux_lines(_dry_run(log_dir=tmp).stdout)
            self.assertEqual(7, len(cmds), f"expected 7, got {cmds}")

    def test_log_dir_in_loop_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lines = _lines_matching(_dry_run(log_dir=tmp).stdout, "_loop")
            loop_lines = [l for l in lines if "tmux" in l and "monitor_loop" not in l]
            self.assertEqual(5, len(loop_lines))
            for ll in loop_lines:
                self.assertIn(tmp, ll)


# ---------------------------------------------------------------------------
# CLI timeout propagation
# ---------------------------------------------------------------------------
class TestTimeoutPropagation(unittest.TestCase):

    def test_default_timeouts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(log_dir=tmp).stdout
            self.assertIn("--cli-timeout '300'", _lines_matching(out, "manager_loop")[0])
            for wl in _lines_matching(out, "worker_loop"):
                self.assertIn("--cli-timeout '600'", wl)

    def test_custom_manager_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(manager_cli_timeout=42, log_dir=tmp).stdout
            self.assertIn("--cli-timeout '42'", _lines_matching(out, "manager_loop")[0])

    def test_custom_worker_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(worker_cli_timeout=99, log_dir=tmp).stdout
            workers = _lines_matching(out, "worker_loop")
            self.assertEqual(3, len(workers))
            for wl in workers:
                self.assertIn("--cli-timeout '99'", wl)

    def test_timeouts_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(manager_cli_timeout=111, worker_cli_timeout=222, log_dir=tmp).stdout
            mgr = _lines_matching(out, "manager_loop")[0]
            self.assertIn("--cli-timeout '111'", mgr)
            self.assertNotIn("222", mgr)
            for wl in _lines_matching(out, "worker_loop"):
                self.assertIn("--cli-timeout '222'", wl)
                self.assertNotIn("111", wl)


# ---------------------------------------------------------------------------
# Interval propagation
# ---------------------------------------------------------------------------
class TestIntervalPropagation(unittest.TestCase):

    def test_default_intervals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(log_dir=tmp).stdout
            self.assertIn("--interval '20'", _lines_matching(out, "manager_loop")[0])
            for wl in _lines_matching(out, "worker_loop"):
                self.assertIn("--interval '25'", wl)

    def test_custom_intervals_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(manager_interval=45, worker_interval=60, log_dir=tmp).stdout
            self.assertIn("--interval '45'", _lines_matching(out, "manager_loop")[0])
            for wl in _lines_matching(out, "worker_loop"):
                self.assertIn("--interval '60'", wl)

    def test_watchdog_interval_fixed_at_15(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(manager_interval=99, worker_interval=99, log_dir=tmp).stdout
            wd = _lines_matching(out, "watchdog_loop")
            self.assertTrue(wd)
            self.assertIn("--interval 15", wd[0])


# ---------------------------------------------------------------------------
# Command ordering
# ---------------------------------------------------------------------------
class TestCommandOrdering(unittest.TestCase):

    def _cmds(self) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return _tmux_lines(_dry_run(log_dir=tmp).stdout)

    def test_new_session_first(self) -> None:
        self.assertTrue(self._cmds()[0].startswith("tmux new-session"))

    def test_select_layout_last_and_tiled(self) -> None:
        cmds = self._cmds()
        self.assertIn("select-layout", cmds[-1])
        self.assertIn("tiled", cmds[-1])

    def test_splits_before_monitor_window(self) -> None:
        cmds = self._cmds()
        splits = [i for i, c in enumerate(cmds) if "split-window" in c]
        monitor = [i for i, c in enumerate(cmds) if "new-window" in c and "monitor" in c]
        self.assertEqual(3, len(splits))
        self.assertEqual(1, len(monitor))
        self.assertGreater(monitor[0], max(splits))

    def test_first_split_is_worker(self) -> None:
        cmds = self._cmds()
        splits = [c for c in cmds if "split-window" in c]
        self.assertIn("worker_loop", splits[0])


# ---------------------------------------------------------------------------
# Watchdog command
# ---------------------------------------------------------------------------
class TestWatchdog(unittest.TestCase):

    def test_watchdog_in_split_with_log_dir_and_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(log_dir=tmp).stdout
            wd = _lines_matching(out, "watchdog_loop")
            self.assertTrue(wd)
            self.assertIn("tmux split-window", wd[0])
            self.assertIn(tmp, wd[0])
            self.assertIn("--project-root", wd[0])


# ---------------------------------------------------------------------------
# Monitor command
# ---------------------------------------------------------------------------
class TestMonitor(unittest.TestCase):

    def test_monitor_in_new_window_with_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = _dry_run(log_dir=tmp).stdout
            mon = _lines_matching(out, "monitor_loop")
            self.assertTrue(mon)
            self.assertIn(" 10", mon[0])
            win = [l for l in out.splitlines() if "tmux new-window" in l and "monitor" in l]
            self.assertTrue(win)


# ---------------------------------------------------------------------------
# Paths with spaces
# ---------------------------------------------------------------------------
class TestSpacedPaths(unittest.TestCase):

    def test_project_root_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "my project dir"
            spaced.mkdir()
            proc = _dry_run(project_root=str(spaced), log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            self.assertIn("Project root: " + str(spaced), proc.stdout)
            cmds = _tmux_lines(proc.stdout)
            self.assertEqual(7, len(cmds))

    def test_spaced_log_dir_in_loop_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spaced_log = Path(tmp) / "logs with spaces"
            spaced_log.mkdir()
            spaced_proj = Path(tmp) / "proj root"
            spaced_proj.mkdir()
            proc = _dry_run(project_root=str(spaced_proj), log_dir=str(spaced_log))
            self.assertEqual(0, proc.returncode)
            loops = [l for l in proc.stdout.splitlines()
                     if "_loop" in l and "tmux" in l and "monitor_loop" not in l]
            self.assertEqual(5, len(loops))
            for ll in loops:
                self.assertTrue(
                    str(spaced_log) in ll or "logs\\ with\\ spaces" in ll,
                    f"log-dir not found in: {ll}",
                )


# ---------------------------------------------------------------------------
# Team lane counters (unit + integration)
# ---------------------------------------------------------------------------
class TestTeamLaneCounters(unittest.TestCase):

    def _aggregate(self, tasks: list) -> dict:
        from orchestrator_mcp_server import _aggregate_team_lanes
        return _aggregate_team_lanes(tasks)

    def test_empty_and_no_team_id(self) -> None:
        self.assertEqual({}, self._aggregate([]))
        self.assertEqual({}, self._aggregate([
            {"status": "in_progress", "team_id": None},
            {"status": "done"},
        ]))

    def test_single_team_counts(self) -> None:
        tasks = [
            {"status": "in_progress", "team_id": "a"},
            {"status": "reported", "team_id": "a"},
            {"status": "blocked", "team_id": "a"},
            {"status": "done", "team_id": "a"},
            {"status": "done", "team_id": "a"},
        ]
        r = self._aggregate(tasks)
        self.assertEqual(5, r["a"]["total"])
        self.assertEqual(1, r["a"]["in_progress"])
        self.assertEqual(2, r["a"]["done"])

    def test_multiple_teams(self) -> None:
        tasks = [
            {"status": "in_progress", "team_id": "a"},
            {"status": "done", "team_id": "b"},
            {"status": "done", "team_id": "b"},
            {"status": "blocked", "team_id": "c"},
        ]
        r = self._aggregate(tasks)
        self.assertEqual({"a", "b", "c"}, set(r.keys()))
        self.assertEqual(2, r["b"]["done"])
        self.assertEqual(1, r["c"]["blocked"])

    def test_missing_status_defaults_to_unknown(self) -> None:
        r = self._aggregate([{"team_id": "x"}])
        self.assertEqual(1, r["x"].get("unknown", 0))

    def test_json_serializable(self) -> None:
        lanes = self._aggregate([
            {"status": "done", "team_id": "a"},
            {"status": "in_progress", "team_id": "a"},
        ])
        self.assertEqual(lanes, json.loads(json.dumps(lanes)))


class TestTeamLaneCountersIntegration(unittest.TestCase):

    def test_team_lanes_in_status(self) -> None:
        from orchestrator.engine import Orchestrator
        from orchestrator.policy import Policy

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = {
                "name": "test-policy",
                "roles": {"manager": "codex"},
                "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
                "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
                "triggers": {"heartbeat_timeout_minutes": 10},
            }
            (root / "policy.json").write_text(json.dumps(raw), encoding="utf-8")
            policy = Policy.load(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()
            orch.connect_to_leader(
                agent="claude_code",
                metadata={"client": "test", "model": "test", "cwd": str(root),
                          "project_root": str(root), "permissions_mode": "default",
                          "sandbox_mode": "false", "session_id": "s1",
                          "connection_id": "c1", "server_version": "1.0",
                          "verification_source": "test"},
                source="claude_code",
            )
            orch.create_task("T1", "backend", ["done"], owner="claude_code", team_id="team-core")
            orch.create_task("T2", "backend", ["done"], owner="claude_code", team_id="team-core")
            orch.create_task("T3", "frontend", ["done"], owner="gemini", team_id="team-ui")
            orch.claim_next_task("claude_code", team_id="team-core")

            from orchestrator_mcp_server import _aggregate_team_lanes
            lanes = _aggregate_team_lanes(orch.list_tasks())
            self.assertIn("team-core", lanes)
            self.assertIn("team-ui", lanes)
            self.assertEqual(2, lanes["team-core"]["total"])
            self.assertEqual(1, lanes["team-ui"]["total"])


if __name__ == "__main__":
    unittest.main()
