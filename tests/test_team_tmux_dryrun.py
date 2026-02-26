"""Tests for team_tmux.sh --dry-run output: session name and CLI timeout propagation.

Verifies that custom --session, --manager-cli-timeout, and --worker-cli-timeout
values appear in the rendered dry-run plan.  Runs without tmux installed and
completes in bounded time (subprocess timeout).
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEAM_TMUX = str(REPO_ROOT / "scripts" / "autopilot" / "team_tmux.sh")

# Subprocess timeout – keeps every test bounded even if the script hangs.
_TIMEOUT = 10


def _dry_run(
    *,
    session: str | None = None,
    manager_cli_timeout: int | None = None,
    worker_cli_timeout: int | None = None,
    log_dir: str | None = None,
    project_root: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke team_tmux.sh --dry-run with optional overrides."""
    cmd: list[str] = ["bash", TEAM_TMUX, "--dry-run"]
    if session is not None:
        cmd += ["--session", session]
    if manager_cli_timeout is not None:
        cmd += ["--manager-cli-timeout", str(manager_cli_timeout)]
    if worker_cli_timeout is not None:
        cmd += ["--worker-cli-timeout", str(worker_cli_timeout)]
    if log_dir is not None:
        cmd += ["--log-dir", log_dir]
    if project_root is not None:
        cmd += ["--project-root", project_root]
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_TIMEOUT,
    )


class TeamTmuxDryRunTests(unittest.TestCase):
    """Deterministic tests that need no tmux binary."""

    def test_dry_run_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertEqual(0, proc.returncode)

    def test_default_session_name_in_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertIn("Session: agents-autopilot", proc.stdout)
            self.assertIn("agents-autopilot", proc.stdout)

    def test_custom_session_name_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(session="my-custom-session", log_dir=tmp)
            self.assertIn("Session: my-custom-session", proc.stdout)
            # Session name should appear in tmux new-session command
            self.assertIn("tmux new-session -d -s my-custom-session", proc.stdout)

    def test_custom_manager_cli_timeout_in_manager_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(manager_cli_timeout=42, log_dir=tmp)
            # Extract manager_loop line and verify timeout
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            self.assertTrue(manager_lines, "no manager_loop line in dry-run output")
            self.assertIn("--cli-timeout '42'", manager_lines[0])

    def test_custom_worker_cli_timeout_in_worker_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(worker_cli_timeout=99, log_dir=tmp)
            lines = proc.stdout.splitlines()
            worker_lines = [l for l in lines if "worker_loop" in l]
            # Should have 2 worker lines (claude + gemini)
            self.assertEqual(2, len(worker_lines), f"expected 2 worker lines, got {len(worker_lines)}")
            for wl in worker_lines:
                self.assertIn("--cli-timeout '99'", wl)

    def test_manager_and_worker_timeouts_are_independent(self) -> None:
        """Manager timeout should not leak into worker commands and vice versa."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(
                manager_cli_timeout=111,
                worker_cli_timeout=222,
                log_dir=tmp,
            )
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            worker_lines = [l for l in lines if "worker_loop" in l]

            self.assertTrue(manager_lines)
            self.assertTrue(worker_lines)

            # Manager gets 111, not 222
            self.assertIn("--cli-timeout '111'", manager_lines[0])
            self.assertNotIn("222", manager_lines[0])

            # Workers get 222, not 111
            for wl in worker_lines:
                self.assertIn("--cli-timeout '222'", wl)
                self.assertNotIn("111", wl)

    def test_default_timeouts_in_output(self) -> None:
        """Default values (manager=300, worker=600) appear when no overrides given."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            manager_lines = [l for l in lines if "manager_loop" in l]
            worker_lines = [l for l in lines if "worker_loop" in l]

            self.assertIn("--cli-timeout '300'", manager_lines[0])
            for wl in worker_lines:
                self.assertIn("--cli-timeout '600'", wl)

    def test_all_tmux_commands_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            self.assertIn("tmux new-session", proc.stdout)
            self.assertIn("tmux split-window", proc.stdout)
            self.assertIn("tmux new-window", proc.stdout)
            self.assertIn("tmux select-layout", proc.stdout)

    def test_monitor_command_present_in_dry_run(self) -> None:
        """AL-CORE-24: dry-run output must include the monitor_loop command."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            monitor_lines = [l for l in lines if "monitor_loop" in l]
            self.assertTrue(monitor_lines, "no monitor_loop line in dry-run output")

    def test_monitor_interval_in_dry_run(self) -> None:
        """AL-CORE-24: monitor command must include the fixed interval value (10)."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            monitor_lines = [l for l in lines if "monitor_loop" in l]
            self.assertTrue(monitor_lines, "no monitor_loop line in dry-run output")
            # monitor_loop.sh is invoked as: monitor_loop.sh $PROJECT_Q 10
            self.assertIn(" 10", monitor_lines[0])

    def test_monitor_in_new_window_tmux_command(self) -> None:
        """AL-CORE-24: monitor should be launched via tmux new-window."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            monitor_window_lines = [
                l for l in lines
                if "tmux new-window" in l and "monitor" in l
            ]
            self.assertTrue(
                monitor_window_lines,
                "no tmux new-window line containing 'monitor' found",
            )

    def test_custom_session_name_with_hyphens(self) -> None:
        """AL-CORE-25: session names with hyphens must propagate correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(session="my-test-session", log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            self.assertIn("Session: my-test-session", proc.stdout)
            self.assertIn("tmux new-session -d -s my-test-session", proc.stdout)

    def test_custom_session_name_with_underscores(self) -> None:
        """AL-CORE-25: session names with underscores must propagate correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(session="my_test_session", log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            self.assertIn("Session: my_test_session", proc.stdout)
            self.assertIn("tmux new-session -d -s my_test_session", proc.stdout)

    def test_custom_session_name_with_mixed_hyphens_underscores(self) -> None:
        """AL-CORE-25: session names mixing hyphens and underscores."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(session="dev-team_alpha", log_dir=tmp)
            self.assertEqual(0, proc.returncode)
            self.assertIn("Session: dev-team_alpha", proc.stdout)
            # Session name should appear in all tmux commands that reference it
            self.assertIn("tmux new-session -d -s dev-team_alpha", proc.stdout)
            self.assertIn("-t dev-team_alpha:", proc.stdout)

    def test_log_dir_propagated_to_loop_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _dry_run(log_dir=tmp)
            lines = proc.stdout.splitlines()
            # manager, claude worker, gemini worker, watchdog use --log-dir;
            # monitor_loop does not, so exclude it.
            loop_lines = [
                l for l in lines
                if "_loop" in l and "tmux" in l and "monitor_loop" not in l
            ]
            self.assertEqual(4, len(loop_lines), f"expected 4 loop commands, got {len(loop_lines)}")
            for ll in loop_lines:
                self.assertIn(tmp, ll, f"log dir not in command: {ll}")


class TeamTmuxDryRunSpacesTests(unittest.TestCase):
    """AL-CORE-30: Stress tests with project-root containing spaces."""

    def test_project_root_with_spaces_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "my project dir"
            spaced.mkdir()
            proc = _dry_run(project_root=str(spaced), log_dir=tmp)
            self.assertEqual(0, proc.returncode)

    def test_project_root_with_spaces_in_commands(self) -> None:
        """All loop commands should contain the quoted project-root path."""
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "path with spaces"
            spaced.mkdir()
            proc = _dry_run(project_root=str(spaced), log_dir=tmp)
            self.assertIn("Project root: " + str(spaced), proc.stdout)
            lines = proc.stdout.splitlines()
            loop_lines = [l for l in lines if "_loop" in l and "tmux" in l]
            self.assertTrue(len(loop_lines) >= 4, f"expected >=4 loop commands, got {len(loop_lines)}")
            for ll in loop_lines:
                # The path should appear shell-quoted somewhere in the command
                self.assertTrue(
                    str(spaced) in ll or str(spaced).replace(" ", "\\ ") in ll
                    or "path\\ with\\ spaces" in ll or "path with spaces" in ll,
                    f"project root not found in: {ll}",
                )

    def test_combined_spaces_custom_session_and_log_dir(self) -> None:
        """All three custom values should appear correctly in rendered output."""
        with tempfile.TemporaryDirectory() as tmp:
            spaced_proj = Path(tmp) / "my project"
            spaced_proj.mkdir()
            spaced_log = Path(tmp) / "my logs"
            spaced_log.mkdir()
            proc = _dry_run(
                project_root=str(spaced_proj),
                session="test-sess_01",
                log_dir=str(spaced_log),
            )
            self.assertEqual(0, proc.returncode)
            self.assertIn("Session: test-sess_01", proc.stdout)
            self.assertIn("test-sess_01", proc.stdout)
            # Log dir should appear in header
            self.assertIn(str(spaced_log), proc.stdout)

    def test_custom_log_dir_with_spaces_propagates_to_loop_commands(self) -> None:
        """Custom spaced log-dir should appear safely in manager/worker/watchdog lines."""
        with tempfile.TemporaryDirectory() as tmp:
            spaced_proj = Path(tmp) / "proj root"
            spaced_proj.mkdir()
            spaced_log = Path(tmp) / "logs with spaces"
            spaced_log.mkdir()
            proc = _dry_run(project_root=str(spaced_proj), log_dir=str(spaced_log))
            self.assertEqual(0, proc.returncode)
            lines = proc.stdout.splitlines()
            loop_lines = [
                l for l in lines
                if "_loop" in l and "tmux" in l and "monitor_loop" not in l
            ]
            self.assertEqual(4, len(loop_lines), f"expected 4 loop commands, got {len(loop_lines)}")
            for ll in loop_lines:
                self.assertTrue(
                    str(spaced_log) in ll
                    or str(spaced_log).replace(" ", "\\ ") in ll
                    or "logs\\ with\\ spaces" in ll,
                    f"spaced log-dir not found in: {ll}",
                )

    def test_spaces_do_not_break_tmux_command_count(self) -> None:
        """Should still emit 5 tmux commands even with spaced paths."""
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "has spaces here"
            spaced.mkdir()
            proc = _dry_run(project_root=str(spaced), log_dir=tmp)
            lines = proc.stdout.splitlines()
            tmux_lines = [l for l in lines if l.strip().startswith("tmux ")]
            # new-session, split-window x2, split-window, new-window, select-layout = 6
            self.assertEqual(6, len(tmux_lines), f"expected 6 tmux commands, got {tmux_lines}")

    def test_monitor_command_intact_with_spaced_project_root(self) -> None:
        """Monitor command should contain the project root even with spaces."""
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "spaced dir"
            spaced.mkdir()
            proc = _dry_run(project_root=str(spaced), log_dir=tmp)
            lines = proc.stdout.splitlines()
            monitor_lines = [l for l in lines if "monitor_loop" in l]
            self.assertTrue(monitor_lines, "no monitor_loop line found")
            # Should contain the project path and the interval
            self.assertIn(" 10", monitor_lines[0])


if __name__ == "__main__":
    unittest.main()
