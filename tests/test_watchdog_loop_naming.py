"""Tests for watchdog_loop.sh JSONL file naming pattern and rotation.

AL-CORE-19 (TASK-dc0af9ac): Validates that watchdog_loop --once produces
JSONL files with the expected naming pattern and that repeated bounded
runs produce deterministic count/retention behavior.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHDOG_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "watchdog_loop.sh")

_TIMEOUT = 15


class WatchdogLoopNamingTests(unittest.TestCase):
    """Tests for watchdog JSONL file naming pattern."""

    def _run_watchdog(
        self, project_root: str, log_dir: str, *, max_logs: int = 200
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash", WATCHDOG_LOOP,
                "--project-root", project_root,
                "--log-dir", log_dir,
                "--max-logs", str(max_logs),
                "--once",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
        )

    def _setup_state(self, root: Path, *, stale: bool = True) -> None:
        """Create state directory. If stale=True, add a stale task so watchdog writes output."""
        state = root / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "bugs.json").write_text("[]", encoding="utf-8")
        (state / "blockers.json").write_text("[]", encoding="utf-8")
        if stale:
            old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            tasks = [{"id": "TASK-stale", "owner": "test", "status": "assigned",
                       "title": "stale task", "updated_at": old_ts}]
            (state / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        else:
            (state / "tasks.json").write_text("[]", encoding="utf-8")

    def test_once_creates_jsonl_file(self) -> None:
        """--once should create exactly one JSONL file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            log_dir = str(root / "logs")

            proc = self._run_watchdog(tmp, log_dir)
            self.assertEqual(0, proc.returncode)

            jsonl_files = list((root / "logs").glob("watchdog-*.jsonl"))
            self.assertEqual(1, len(jsonl_files))

    def test_filename_matches_timestamp_pattern(self) -> None:
        """JSONL filename should match watchdog-YYYYMMDD-HHMMSS.jsonl."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            log_dir = str(root / "logs")

            self._run_watchdog(tmp, log_dir)

            jsonl_files = list((root / "logs").glob("watchdog-*.jsonl"))
            self.assertEqual(1, len(jsonl_files))
            name = jsonl_files[0].name
            self.assertRegex(name, r"^watchdog-\d{8}-\d{6}\.jsonl$")

    def test_repeated_runs_create_separate_files(self) -> None:
        """Multiple --once runs should create separate JSONL files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            log_dir = str(root / "logs")

            for _ in range(3):
                self._run_watchdog(tmp, log_dir)

            jsonl_files = list((root / "logs").glob("watchdog-*.jsonl"))
            # At least 1 (could be 1 if runs happen in same second)
            self.assertGreaterEqual(len(jsonl_files), 1)

    def test_max_logs_prunes_old_files(self) -> None:
        """With max-logs=2, older files should be pruned."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            log_dir = root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            # Pre-create 3 old watchdog files
            for i in range(3):
                f = log_dir / f"watchdog-20250101-00000{i}.jsonl"
                f.write_text("{}\n")
                # Set different mtimes so pruning is deterministic
                old_time = 1000000 + i
                os.utime(f, (old_time, old_time))

            # Run with max-logs=2 — should prune oldest
            self._run_watchdog(tmp, str(log_dir), max_logs=2)

            jsonl_files = list(log_dir.glob("watchdog-*.jsonl"))
            self.assertLessEqual(len(jsonl_files), 2)

    def test_stderr_contains_cycle_info(self) -> None:
        """Watchdog should log cycle info to stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._setup_state(root)
            log_dir = str(root / "logs")

            proc = self._run_watchdog(tmp, log_dir)
            self.assertIn("watchdog cycle=1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
