"""Tests for scripts/autopilot/log_check.sh — autopilot log sanity checker.

Covers stale age warnings, strict-mode non-zero exit on missing required logs,
JSONL parse validation, and normal healthy-log output. Uses synthetic temp
fixture directories and bounded shell invocations.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "autopilot" / "log_check.sh"


def _run_check(
    log_dir: str,
    *,
    strict: bool = False,
    max_age_minutes: int = 10,
) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(SCRIPT), "--log-dir", log_dir, "--max-age-minutes", str(max_age_minutes)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


class HealthyLogsTests(unittest.TestCase):
    """Tests with a complete, fresh log directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)
        # Create fresh log files for all required loops
        (self.log_dir / "manager-001.log").write_text("started\n")
        (self.log_dir / "worker-001.log").write_text("started\n")
        (self.log_dir / "watchdog-001.jsonl").write_text(
            json.dumps({"kind": "heartbeat", "ts": "2026-01-01T00:00:00Z"}) + "\n"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_healthy_logs_exit_zero(self) -> None:
        result = _run_check(str(self.log_dir))
        self.assertEqual(result.returncode, 0)

    def test_healthy_logs_show_all_checks_passed(self) -> None:
        result = _run_check(str(self.log_dir))
        self.assertIn("All checks passed", result.stdout)

    def test_healthy_logs_show_ok_status(self) -> None:
        result = _run_check(str(self.log_dir))
        self.assertIn("status=ok", result.stdout)

    def test_healthy_logs_strict_exit_zero(self) -> None:
        result = _run_check(str(self.log_dir), strict=True)
        self.assertEqual(result.returncode, 0)

    def test_jsonl_valid_lines_counted(self) -> None:
        result = _run_check(str(self.log_dir))
        self.assertIn("1/1 lines valid", result.stdout)


class MissingRequiredLogsTests(unittest.TestCase):
    """Tests for missing required log files (manager, worker, watchdog)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_dir_non_strict_exit_zero(self) -> None:
        result = _run_check(str(self.log_dir))
        self.assertEqual(result.returncode, 0)

    def test_empty_dir_shows_missing(self) -> None:
        result = _run_check(str(self.log_dir))
        self.assertIn("MISSING", result.stdout)

    def test_empty_dir_strict_exit_nonzero(self) -> None:
        result = _run_check(str(self.log_dir), strict=True)
        self.assertNotEqual(result.returncode, 0)

    def test_missing_manager_strict_exit_nonzero(self) -> None:
        (self.log_dir / "worker-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir), strict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manager", result.stdout.lower())

    def test_missing_worker_strict_exit_nonzero(self) -> None:
        (self.log_dir / "manager-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir), strict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worker", result.stdout.lower())

    def test_missing_watchdog_strict_exit_nonzero(self) -> None:
        (self.log_dir / "manager-001.log").write_text("ok\n")
        (self.log_dir / "worker-001.log").write_text("ok\n")
        result = _run_check(str(self.log_dir), strict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("watchdog", result.stdout.lower())

    def test_missing_supervisor_non_strict_ok(self) -> None:
        """Supervisor is optional — missing should not cause failure."""
        (self.log_dir / "manager-001.log").write_text("ok\n")
        (self.log_dir / "worker-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir), strict=True)
        self.assertEqual(result.returncode, 0)

    def test_missing_supervisor_shows_none_not_missing(self) -> None:
        """Supervisor is optional — status should be 'none', not 'MISSING'."""
        (self.log_dir / "manager-001.log").write_text("ok\n")
        (self.log_dir / "worker-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir))
        lines = [l for l in result.stdout.splitlines() if "supervisor" in l.lower()]
        self.assertTrue(len(lines) > 0)
        self.assertIn("none", lines[0].lower())


class StaleAgeWarningTests(unittest.TestCase):
    """Tests for stale log age detection."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_stale_log_shows_warning(self) -> None:
        log_file = self.log_dir / "manager-001.log"
        log_file.write_text("old entry\n")
        # Set mtime to 20 minutes ago
        old_time = time.time() - 1200
        os.utime(log_file, (old_time, old_time))
        (self.log_dir / "worker-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir), max_age_minutes=10)
        self.assertIn("STALE", result.stdout)

    def test_stale_log_warning_mentions_age(self) -> None:
        log_file = self.log_dir / "manager-001.log"
        log_file.write_text("old entry\n")
        old_time = time.time() - 1200
        os.utime(log_file, (old_time, old_time))
        (self.log_dir / "worker-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir), max_age_minutes=10)
        self.assertIn("warning", result.stdout.lower())

    def test_fresh_log_no_stale_warning(self) -> None:
        (self.log_dir / "manager-001.log").write_text("fresh\n")
        (self.log_dir / "worker-001.log").write_text("fresh\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir), max_age_minutes=10)
        self.assertNotIn("STALE", result.stdout)

    def test_stale_warning_with_custom_threshold(self) -> None:
        log_file = self.log_dir / "worker-001.log"
        log_file.write_text("slightly old\n")
        # 3 minutes ago
        old_time = time.time() - 180
        os.utime(log_file, (old_time, old_time))
        (self.log_dir / "manager-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        # With 2-minute threshold, should be stale
        result = _run_check(str(self.log_dir), max_age_minutes=2)
        self.assertIn("STALE", result.stdout)

    def test_no_stale_with_generous_threshold(self) -> None:
        log_file = self.log_dir / "worker-001.log"
        log_file.write_text("slightly old\n")
        old_time = time.time() - 180
        os.utime(log_file, (old_time, old_time))
        (self.log_dir / "manager-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        # With 60-minute threshold, 3m old is fine
        result = _run_check(str(self.log_dir), max_age_minutes=60)
        self.assertNotIn("STALE", result.stdout)

    def test_stale_does_not_fail_in_non_strict(self) -> None:
        """Stale is a warning, not an error — should exit 0 in non-strict."""
        log_file = self.log_dir / "manager-001.log"
        log_file.write_text("old\n")
        old_time = time.time() - 1200
        os.utime(log_file, (old_time, old_time))
        (self.log_dir / "worker-001.log").write_text("ok\n")
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
        result = _run_check(str(self.log_dir), max_age_minutes=10)
        self.assertEqual(result.returncode, 0)


class WatchdogJsonlTests(unittest.TestCase):
    """Tests for watchdog JSONL parse validation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)
        (self.log_dir / "manager-001.log").write_text("ok\n")
        (self.log_dir / "worker-001.log").write_text("ok\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_jsonl_no_errors(self) -> None:
        (self.log_dir / "watchdog-001.jsonl").write_text(
            '{"kind":"heartbeat"}\n{"kind":"check"}\n'
        )
        result = _run_check(str(self.log_dir), strict=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("2/2 lines valid", result.stdout)

    def test_malformed_jsonl_strict_exit_nonzero(self) -> None:
        (self.log_dir / "watchdog-001.jsonl").write_text(
            '{"kind":"ok"}\nNOT JSON\n'
        )
        result = _run_check(str(self.log_dir), strict=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Malformed JSONL", result.stdout)

    def test_malformed_jsonl_non_strict_exit_zero(self) -> None:
        (self.log_dir / "watchdog-001.jsonl").write_text(
            '{"kind":"ok"}\nNOT JSON\n'
        )
        result = _run_check(str(self.log_dir))
        self.assertEqual(result.returncode, 0)

    def test_jsonl_kind_counts_reported(self) -> None:
        (self.log_dir / "watchdog-001.jsonl").write_text(
            '{"kind":"heartbeat"}\n{"kind":"heartbeat"}\n{"kind":"check"}\n'
        )
        result = _run_check(str(self.log_dir))
        self.assertIn("heartbeat: 2", result.stdout)
        self.assertIn("check: 1", result.stdout)

    def test_empty_jsonl_shows_no_entries(self) -> None:
        (self.log_dir / "watchdog-001.jsonl").write_text("")
        result = _run_check(str(self.log_dir))
        self.assertIn("No JSONL entries found", result.stdout)

    def test_blank_lines_skipped(self) -> None:
        (self.log_dir / "watchdog-001.jsonl").write_text(
            '\n{"kind":"check"}\n\n'
        )
        result = _run_check(str(self.log_dir))
        self.assertIn("1/1 lines valid", result.stdout)


class TimeoutMarkerTests(unittest.TestCase):
    """Tests for timeout marker frequency reporting."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name)
        (self.log_dir / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_timeouts_shows_ok(self) -> None:
        (self.log_dir / "manager-001.log").write_text("normal output\n")
        (self.log_dir / "worker-001.log").write_text("normal output\n")
        result = _run_check(str(self.log_dir))
        # Script outputs "manager    ok" and "worker    ok" lines
        lines = result.stdout.splitlines()
        manager_ok = any("manager" in l and "ok" in l for l in lines)
        worker_ok = any("worker" in l and "ok" in l for l in lines)
        self.assertTrue(manager_ok and worker_ok, f"Expected manager/worker ok lines in:\n{result.stdout}")

    def test_timeout_markers_counted(self) -> None:
        (self.log_dir / "manager-001.log").write_text(
            "line1\n[AUTOPILOT] CLI timeout\nline3\n[AUTOPILOT] CLI timeout\n"
        )
        (self.log_dir / "worker-001.log").write_text("ok\n")
        result = _run_check(str(self.log_dir))
        self.assertIn("2 timeout(s)", result.stdout)


class LogDirMissingTests(unittest.TestCase):
    """Tests for non-existent log directory."""

    def test_missing_dir_non_strict_exit_zero(self) -> None:
        result = _run_check("/nonexistent/path/that/does/not/exist")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Log directory not found", result.stdout)

    def test_missing_dir_strict_exit_nonzero(self) -> None:
        result = _run_check("/nonexistent/path/that/does/not/exist", strict=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
