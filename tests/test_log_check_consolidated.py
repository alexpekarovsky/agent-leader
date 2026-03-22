"""Tests for scripts/autopilot/log_check.sh -- autopilot log sanity checker."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "autopilot" / "log_check.sh")


def _run(log_dir: str, *, strict: bool = False, max_age: int = 10) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", SCRIPT, "--log-dir", log_dir, "--max-age-minutes", str(max_age)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _make_healthy(d: Path) -> None:
    """Create the three required log files so the check passes."""
    (d / "manager-001.log").write_text("ok\n")
    (d / "worker-001.log").write_text("ok\n")
    (d / "watchdog-001.jsonl").write_text('{"kind":"heartbeat"}\n')


def _age_file(p: Path, minutes: int) -> None:
    t = time.time() - minutes * 60
    os.utime(p, (t, t))


# -- Log directory missing ---------------------------------------------------

class TestMissingDir(unittest.TestCase):
    _BOGUS = "/tmp/nonexistent-log-dir-abc123"

    def test_non_strict_exits_zero(self) -> None:
        r = _run(self._BOGUS)
        self.assertEqual(r.returncode, 0)
        self.assertIn("not found", r.stdout.lower())

    def test_strict_exits_nonzero(self) -> None:
        r = _run(self._BOGUS, strict=True)
        self.assertNotEqual(r.returncode, 0)


# -- Missing required logs ---------------------------------------------------

class TestMissingRequired(unittest.TestCase):
    def test_empty_dir_non_strict_exits_zero_with_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(tmp)
            self.assertEqual(r.returncode, 0)
            self.assertIn("MISSING", r.stdout)

    def test_empty_dir_strict_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(tmp, strict=True)
            self.assertNotEqual(r.returncode, 0)

    def test_missing_manager_strict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "worker-001.log").write_text("ok\n")
            (d / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
            r = _run(tmp, strict=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("manager", r.stdout.lower())

    def test_missing_worker_strict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "manager-001.log").write_text("ok\n")
            (d / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
            r = _run(tmp, strict=True)
            self.assertNotEqual(r.returncode, 0)

    def test_missing_watchdog_strict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "manager-001.log").write_text("ok\n")
            (d / "worker-001.log").write_text("ok\n")
            r = _run(tmp, strict=True)
            self.assertNotEqual(r.returncode, 0)

    def test_all_required_present_strict_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_healthy(Path(tmp))
            r = _run(tmp, strict=True)
            self.assertEqual(r.returncode, 0)
            self.assertIn("All checks passed", r.stdout)


# -- Supervisor (optional) ---------------------------------------------------

class TestSupervisorOptional(unittest.TestCase):
    def test_missing_supervisor_strict_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_healthy(Path(tmp))
            r = _run(tmp, strict=True)
            self.assertEqual(r.returncode, 0)

    def test_missing_supervisor_shows_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_healthy(Path(tmp))
            r = _run(tmp)
            sup_lines = [l for l in r.stdout.splitlines() if "supervisor" in l.lower()]
            self.assertTrue(sup_lines)
            self.assertIn("none", sup_lines[0].lower())


# -- Healthy logs -------------------------------------------------------------

class TestHealthyLogs(unittest.TestCase):
    def test_healthy_exit_zero_all_checks_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_healthy(Path(tmp))
            r = _run(tmp)
            self.assertEqual(r.returncode, 0)
            self.assertIn("All checks passed", r.stdout)
            self.assertNotIn("STALE", r.stdout)

    def test_healthy_shows_valid_line_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_healthy(Path(tmp))
            r = _run(tmp)
            self.assertIn("1/1 lines valid", r.stdout)


# -- Stale age warnings ------------------------------------------------------

class TestStaleWarnings(unittest.TestCase):
    def test_old_log_shows_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _make_healthy(d)
            _age_file(d / "manager-001.log", 20)
            r = _run(tmp, max_age=10)
            self.assertEqual(r.returncode, 0)  # stale is warning, not error
            self.assertIn("STALE", r.stdout)

    def test_custom_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _make_healthy(d)
            _age_file(d / "worker-001.log", 3)
            # 2-min threshold, 3m old file -> STALE
            r = _run(tmp, max_age=2)
            self.assertIn("STALE", r.stdout)

    def test_generous_threshold_no_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _make_healthy(d)
            _age_file(d / "worker-001.log", 3)
            r = _run(tmp, max_age=60)
            self.assertNotIn("STALE", r.stdout)


# -- JSONL validation --------------------------------------------------------

class TestJsonlValidation(unittest.TestCase):
    def _setup(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        t = tempfile.TemporaryDirectory()
        d = Path(t.name)
        (d / "manager-001.log").write_text("ok\n")
        (d / "worker-001.log").write_text("ok\n")
        return t, d

    def test_valid_jsonl_strict_passes(self) -> None:
        t, d = self._setup()
        (d / "watchdog-001.jsonl").write_text('{"kind":"heartbeat"}\n{"kind":"check"}\n')
        r = _run(t.name, strict=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("2/2 lines valid", r.stdout)
        t.cleanup()

    def test_malformed_jsonl_strict_fails(self) -> None:
        t, d = self._setup()
        (d / "watchdog-001.jsonl").write_text('{"kind":"ok"}\nNOT JSON\n')
        r = _run(t.name, strict=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Malformed JSONL", r.stdout)
        t.cleanup()

    def test_malformed_jsonl_non_strict_exits_zero(self) -> None:
        t, d = self._setup()
        (d / "watchdog-001.jsonl").write_text('{"kind":"ok"}\nNOT JSON\n')
        r = _run(t.name)
        self.assertEqual(r.returncode, 0)
        t.cleanup()

    def test_blank_lines_skipped(self) -> None:
        t, d = self._setup()
        (d / "watchdog-001.jsonl").write_text('\n{"kind":"check"}\n\n')
        r = _run(t.name)
        self.assertIn("1/1 lines valid", r.stdout)
        t.cleanup()

    def test_kind_counts_reported(self) -> None:
        t, d = self._setup()
        lines = '{"kind":"heartbeat"}\n{"kind":"heartbeat"}\n{"kind":"check"}\n'
        (d / "watchdog-001.jsonl").write_text(lines)
        r = _run(t.name)
        self.assertIn("heartbeat", r.stdout)
        self.assertIn("check", r.stdout)
        t.cleanup()

    def test_empty_jsonl_shows_no_entries(self) -> None:
        t, d = self._setup()
        (d / "watchdog-001.jsonl").write_text("")
        r = _run(t.name)
        self.assertIn("No JSONL entries found", r.stdout)
        t.cleanup()


# -- Timeout markers ---------------------------------------------------------

class TestTimeoutMarkers(unittest.TestCase):
    def test_no_timeouts_shows_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _make_healthy(Path(tmp))
            r = _run(tmp)
            lines = r.stdout.splitlines()
            manager_ok = any("manager" in l and "ok" in l for l in lines)
            worker_ok = any("worker" in l and "ok" in l for l in lines)
            self.assertTrue(manager_ok and worker_ok)

    def test_timeout_markers_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "manager-001.log").write_text(
                "line1\n[AUTOPILOT] CLI timeout\n[AUTOPILOT] CLI timeout\n"
            )
            (d / "worker-001.log").write_text("ok\n")
            (d / "watchdog-001.jsonl").write_text('{"kind":"hb"}\n')
            r = _run(tmp)
            self.assertIn("2 timeout(s)", r.stdout)


# -- Argument validation -----------------------------------------------------

class TestArgValidation(unittest.TestCase):
    def test_unknown_arg_exits_nonzero(self) -> None:
        r = subprocess.run(
            ["bash", SCRIPT, "--bogus"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Unknown arg", r.stderr)


if __name__ == "__main__":
    unittest.main()
