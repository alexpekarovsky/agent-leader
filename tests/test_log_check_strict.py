"""Tests for log_check.sh strict mode with malformed JSONL and missing files.

AL-CORE-17 (TASK-82466844): Validates that log_check.sh --strict exits
non-zero on malformed watchdog JSONL and missing required log files.
Uses synthetic temp log directories with bounded shell invocations.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_CHECK = str(REPO_ROOT / "scripts" / "autopilot" / "log_check.sh")

_TIMEOUT = 10


class LogCheckStrictTests(unittest.TestCase):
    """Bounded tests for log_check.sh strict mode."""

    def _run_log_check(
        self, log_dir: str, *, strict: bool = True
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["bash", LOG_CHECK, "--log-dir", log_dir]
        if strict:
            cmd.append("--strict")
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )

    def test_strict_missing_required_logs_exits_nonzero(self) -> None:
        """Empty log dir in strict mode → non-zero exit (missing manager/worker/watchdog)."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run_log_check(tmp, strict=True)
            self.assertNotEqual(0, proc.returncode)

    def test_strict_missing_logs_reports_errors(self) -> None:
        """Strict mode should report missing required log types."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run_log_check(tmp, strict=True)
            self.assertIn("no log files found", proc.stdout)

    def test_strict_malformed_jsonl_exits_nonzero(self) -> None:
        """Malformed watchdog JSONL in strict mode → non-zero exit."""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            # Create valid manager and worker logs so only JSONL fails
            (log_dir / "manager-codex-20260101-000000.log").write_text("cycle\n")
            (log_dir / "worker-claude-20260101-000000.log").write_text("cycle\n")
            # Create malformed watchdog JSONL
            (log_dir / "watchdog-20260101-000000.jsonl").write_text(
                "not valid json\n{broken\n"
            )
            proc = self._run_log_check(tmp, strict=True)
            self.assertNotEqual(0, proc.returncode)

    def test_strict_malformed_jsonl_reports_line_errors(self) -> None:
        """Malformed JSONL should report specific line errors."""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            (log_dir / "manager-codex-20260101-000000.log").write_text("cycle\n")
            (log_dir / "worker-claude-20260101-000000.log").write_text("cycle\n")
            (log_dir / "watchdog-20260101-000000.jsonl").write_text(
                "not valid json\n"
            )
            proc = self._run_log_check(tmp, strict=True)
            self.assertIn("Malformed JSONL", proc.stdout)

    def test_nonstrict_malformed_jsonl_exits_zero(self) -> None:
        """Without strict, malformed JSONL should not cause non-zero exit."""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            (log_dir / "manager-codex-20260101-000000.log").write_text("cycle\n")
            (log_dir / "worker-claude-20260101-000000.log").write_text("cycle\n")
            (log_dir / "watchdog-20260101-000000.jsonl").write_text(
                "not valid json\n"
            )
            proc = self._run_log_check(tmp, strict=False)
            self.assertEqual(0, proc.returncode)

    def test_strict_valid_logs_exits_zero(self) -> None:
        """All valid logs in strict mode → exit zero."""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            (log_dir / "manager-codex-20260101-000000.log").write_text("cycle\n")
            (log_dir / "worker-claude-20260101-000000.log").write_text("cycle\n")
            (log_dir / "watchdog-20260101-000000.jsonl").write_text(
                '{"kind":"stale_task","timestamp":"2026-01-01T00:00:00Z"}\n'
            )
            proc = self._run_log_check(tmp, strict=True)
            self.assertEqual(0, proc.returncode)
            self.assertIn("All checks passed", proc.stdout)

    def test_strict_missing_log_dir_exits_nonzero(self) -> None:
        """Non-existent log dir in strict mode → non-zero exit."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nonexistent")
            proc = self._run_log_check(missing, strict=True)
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("Log directory not found", proc.stdout)

    def test_nonstrict_missing_log_dir_exits_zero(self) -> None:
        """Non-existent log dir without strict → exit zero."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nonexistent")
            proc = self._run_log_check(missing, strict=False)
            self.assertEqual(0, proc.returncode)


if __name__ == "__main__":
    unittest.main()
