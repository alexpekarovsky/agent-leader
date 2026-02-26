"""Tests for scripts/autopilot/log_check.sh — autopilot log sanity checker.

Covers stale age warnings, strict-mode non-zero exit on missing required
logs, JSONL validation, and timeout marker detection. Uses synthetic temp
log directories with controlled file ages for deterministic assertions.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = ROOT_DIR / "scripts" / "autopilot" / "log_check.sh"


def run_log_check(
    log_dir: str,
    max_age_minutes: int = 10,
    strict: bool = False,
) -> subprocess.CompletedProcess:
    """Run log_check.sh and return the result."""
    cmd = [
        "bash", str(SCRIPT),
        "--log-dir", log_dir,
        "--max-age-minutes", str(max_age_minutes),
    ]
    if strict:
        cmd.append("--strict")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestMissingLogDir(unittest.TestCase):
    """Tests for when the log directory doesn't exist."""

    def test_missing_dir_nonstrict_exits_zero(self) -> None:
        result = run_log_check("/tmp/nonexistent-log-dir-abc123")
        self.assertEqual(result.returncode, 0)
        self.assertIn("not found", result.stdout)

    def test_missing_dir_strict_exits_nonzero(self) -> None:
        result = run_log_check("/tmp/nonexistent-log-dir-abc123", strict=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not found", result.stdout)


class TestMissingRequiredLogs(unittest.TestCase):
    """Tests for strict-mode failure when required logs are missing."""

    def test_empty_dir_nonstrict_exits_zero(self) -> None:
        """Empty log dir in non-strict should warn but exit 0."""
        with tempfile.TemporaryDirectory() as tmp:
            result = run_log_check(tmp)
            self.assertEqual(result.returncode, 0)
            self.assertIn("MISSING", result.stdout)

    def test_empty_dir_strict_exits_nonzero(self) -> None:
        """Empty log dir in strict mode should exit 1 (required logs missing)."""
        with tempfile.TemporaryDirectory() as tmp:
            result = run_log_check(tmp, strict=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("MISSING", result.stdout)
            self.assertIn("error", result.stdout.lower())

    def test_only_manager_log_strict_still_fails(self) -> None:
        """Having only manager log still fails strict — worker/watchdog missing."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("log line\n")
            result = run_log_check(tmp, strict=True)
            self.assertEqual(result.returncode, 1)

    def test_all_required_present_strict_passes(self) -> None:
        """Having all 3 required log types in strict should pass."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("log line\n")
            (Path(tmp) / "worker-001.log").write_text("log line\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "stale_task", "ts": "2026-01-01"}) + "\n"
            )
            result = run_log_check(tmp, strict=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn("All checks passed", result.stdout)


class TestStaleAgeWarnings(unittest.TestCase):
    """Tests for stale log age warning output."""

    def test_fresh_logs_no_stale_warning(self) -> None:
        """Logs modified just now should not produce stale warnings."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("ok\n")
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
            )
            result = run_log_check(tmp, max_age_minutes=10)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("STALE", result.stdout)
            self.assertIn("All checks passed", result.stdout)

    def test_old_logs_produce_stale_warning(self) -> None:
        """Logs older than max-age-minutes should produce STALE warning."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manager-001.log"
            p.write_text("old log\n")
            # Set mtime to 20 minutes ago
            old_time = time.time() - (20 * 60)
            os.utime(p, (old_time, old_time))

            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
            )

            result = run_log_check(tmp, max_age_minutes=10)
            self.assertEqual(result.returncode, 0)
            self.assertIn("STALE", result.stdout)
            self.assertIn("manager", result.stdout.lower())

    def test_stale_with_short_threshold(self) -> None:
        """Even slightly old logs flag as stale with max-age-minutes=0."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manager-001.log"
            p.write_text("ok\n")
            old_time = time.time() - 120  # 2 minutes ago
            os.utime(p, (old_time, old_time))

            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
            )

            result = run_log_check(tmp, max_age_minutes=1)
            self.assertIn("STALE", result.stdout)

    def test_stale_warning_shows_age_minutes(self) -> None:
        """Stale warning should include the age in minutes."""
        with tempfile.TemporaryDirectory() as tmp:
            for name in ["manager-001.log", "worker-001.log"]:
                p = Path(tmp) / name
                p.write_text("ok\n")
                old_time = time.time() - (30 * 60)
                os.utime(p, (old_time, old_time))
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
            )

            result = run_log_check(tmp, max_age_minutes=5)
            # Should mention "30m" or similar in stale output
            self.assertIn("STALE", result.stdout)
            # The warnings section should reference the age
            self.assertIn("old", result.stdout.lower())


class TestJsonlValidation(unittest.TestCase):
    """Tests for watchdog JSONL parse validation."""

    def test_valid_jsonl_no_errors(self) -> None:
        """Valid JSONL produces no errors."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("ok\n")
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "stale_task"}) + "\n"
                + json.dumps({"kind": "heartbeat"}) + "\n"
            )
            result = run_log_check(tmp, strict=True)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("BAD LINES", result.stdout)

    def test_malformed_jsonl_strict_fails(self) -> None:
        """Malformed JSONL in strict mode should exit 1."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("ok\n")
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
                + "this is not json\n"
            )
            result = run_log_check(tmp, strict=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("BAD LINES", result.stdout)
            self.assertIn("Malformed JSONL", result.stdout)

    def test_malformed_jsonl_nonstrict_warns(self) -> None:
        """Malformed JSONL in non-strict mode should still report but exit 0."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("ok\n")
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                "not json at all\n"
            )
            result = run_log_check(tmp)
            self.assertEqual(result.returncode, 0)
            self.assertIn("BAD LINES", result.stdout)

    def test_empty_jsonl_lines_skipped(self) -> None:
        """Empty lines in JSONL should be silently skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("ok\n")
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n\n\n"
            )
            result = run_log_check(tmp, strict=True)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("BAD LINES", result.stdout)

    def test_jsonl_kind_counts_displayed(self) -> None:
        """JSONL diagnostic kind counts should appear in output."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("ok\n")
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            lines = [
                json.dumps({"kind": "stale_task"}),
                json.dumps({"kind": "stale_task"}),
                json.dumps({"kind": "heartbeat"}),
            ]
            (Path(tmp) / "watchdog-001.jsonl").write_text("\n".join(lines) + "\n")
            result = run_log_check(tmp)
            self.assertIn("stale_task", result.stdout)
            self.assertIn("heartbeat", result.stdout)


class TestTimeoutMarkers(unittest.TestCase):
    """Tests for timeout marker detection in CLI logs."""

    def test_no_timeouts_shows_ok(self) -> None:
        """Logs without timeout markers should show ok."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("normal output\n")
            (Path(tmp) / "worker-001.log").write_text("normal output\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
            )
            result = run_log_check(tmp)
            # Both manager and worker should show "ok" for timeout markers
            lines = result.stdout.split("\n")
            timeout_section = False
            for line in lines:
                if "Timeout markers" in line:
                    timeout_section = True
                    continue
                if timeout_section and line.strip().startswith(("manager", "worker")):
                    self.assertIn("ok", line)

    def test_timeout_markers_detected(self) -> None:
        """Logs with [AUTOPILOT] CLI timeout should be counted."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text(
                "line1\n[AUTOPILOT] CLI timeout after 30s\nline3\n"
                "[AUTOPILOT] CLI timeout after 30s\n"
            )
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
            )
            result = run_log_check(tmp)
            self.assertIn("2 timeout(s)", result.stdout)


class TestUnknownArg(unittest.TestCase):
    """Tests for argument validation."""

    def test_unknown_arg_exits_nonzero(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT), "--bogus"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown arg", result.stderr)


class TestOptionalSupervisorLog(unittest.TestCase):
    """Supervisor logs are optional and should not cause failures."""

    def test_missing_supervisor_no_error(self) -> None:
        """Missing supervisor log should show 'none' not 'MISSING'."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-001.log").write_text("ok\n")
            (Path(tmp) / "worker-001.log").write_text("ok\n")
            (Path(tmp) / "watchdog-001.jsonl").write_text(
                json.dumps({"kind": "ok"}) + "\n"
            )
            result = run_log_check(tmp, strict=True)
            self.assertEqual(result.returncode, 0)
            # Supervisor should show "none" not "MISSING"
            for line in result.stdout.split("\n"):
                if "supervisor" in line.lower() and "files=" in line:
                    self.assertIn("none", line.lower())
                    self.assertNotIn("MISSING", line)


if __name__ == "__main__":
    unittest.main()
