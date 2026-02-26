"""Tests for common.sh prune_old_logs prefix filtering.

AL-CORE-26 (TASK-7f20a316): Validates that prune_old_logs only deletes
files matching the given prefix, leaving unrelated files untouched.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = REPO_ROOT / "scripts" / "autopilot" / "common.sh"

_TIMEOUT = 10


def _run_prune(
    log_dir: str, prefix: str, max_files: int
) -> subprocess.CompletedProcess[str]:
    """Source common.sh and call prune_old_logs."""
    script = f"""
source "{COMMON_SH}"
prune_old_logs "{log_dir}" "{prefix}" {max_files}
"""
    return subprocess.run(
        ["bash", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_TIMEOUT,
    )


class PruneOldLogsUnrelatedPrefixTests(unittest.TestCase):
    """Tests ensuring unrelated prefixes are preserved."""

    def test_unrelated_prefix_files_preserved(self) -> None:
        """Files with a different prefix should not be pruned."""
        with tempfile.TemporaryDirectory() as tmp:
            # Create files with matching prefix
            for i in range(5):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text(f"log {i}\n")
                os.utime(f, (1000 + i, 1000 + i))

            # Create files with unrelated prefix
            for i in range(3):
                f = Path(tmp) / f"worker-{i:03d}.log"
                f.write_text(f"worker {i}\n")

            # Prune manager prefix with max_files=2
            proc = _run_prune(tmp, "manager-", 2)
            self.assertEqual(0, proc.returncode)

            # Worker files should all still exist
            worker_files = list(Path(tmp).glob("worker-*.log"))
            self.assertEqual(3, len(worker_files))

            # Manager files should be pruned to 2
            manager_files = list(Path(tmp).glob("manager-*.log"))
            self.assertLessEqual(len(manager_files), 2)

    def test_matching_prefix_pruned(self) -> None:
        """Files matching prefix should be pruned to max_files."""
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(10):
                f = Path(tmp) / f"watchdog-{i:03d}.jsonl"
                f.write_text("{}\n")
                os.utime(f, (1000 + i, 1000 + i))

            proc = _run_prune(tmp, "watchdog-", 3)
            self.assertEqual(0, proc.returncode)

            remaining = list(Path(tmp).glob("watchdog-*.jsonl"))
            self.assertEqual(3, len(remaining))

    def test_fewer_than_max_files_no_pruning(self) -> None:
        """When files < max_files, nothing should be pruned."""
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text(f"log {i}\n")

            proc = _run_prune(tmp, "manager-", 10)
            self.assertEqual(0, proc.returncode)

            remaining = list(Path(tmp).glob("manager-*.log"))
            self.assertEqual(3, len(remaining))

    def test_empty_prefix_prunes_all_files(self) -> None:
        """Empty prefix should match all files."""
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                f = Path(tmp) / f"file-{i}.log"
                f.write_text("data\n")
                os.utime(f, (1000 + i, 1000 + i))

            proc = _run_prune(tmp, "", 2)
            self.assertEqual(0, proc.returncode)

            remaining = list(Path(tmp).glob("*.log"))
            self.assertLessEqual(len(remaining), 2)

    def test_max_files_one_keeps_only_newest(self) -> None:
        """AL-CORE-31: max_files=1 must keep exactly 1 file (the newest)."""
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text(f"log {i}\n")
                os.utime(f, (1000 + i * 100, 1000 + i * 100))

            proc = _run_prune(tmp, "manager-", 1)
            self.assertEqual(0, proc.returncode)

            remaining = list(Path(tmp).glob("manager-*.log"))
            self.assertEqual(1, len(remaining))
            # The newest file (004) should survive
            self.assertEqual("manager-004.log", remaining[0].name)

    def test_max_files_one_single_file_no_op(self) -> None:
        """AL-CORE-31: max_files=1 with exactly 1 file is a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "manager-000.log"
            f.write_text("only one\n")

            proc = _run_prune(tmp, "manager-", 1)
            self.assertEqual(0, proc.returncode)

            remaining = list(Path(tmp).glob("manager-*.log"))
            self.assertEqual(1, len(remaining))
            self.assertEqual("manager-000.log", remaining[0].name)

    def test_exact_at_max_files_no_pruning(self) -> None:
        """AL-CORE-31: when file count == max_files, nothing should be pruned."""
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text(f"log {i}\n")
                os.utime(f, (1000 + i, 1000 + i))

            proc = _run_prune(tmp, "manager-", 3)
            self.assertEqual(0, proc.returncode)

            remaining = list(Path(tmp).glob("manager-*.log"))
            self.assertEqual(3, len(remaining))

    def test_nonexistent_dir_no_error(self) -> None:
        """Non-existent directory should not cause errors."""
        proc = _run_prune("/tmp/nonexistent-prune-test-xyz", "manager-", 5)
        self.assertEqual(0, proc.returncode)

    def test_keeps_newest_files(self) -> None:
        """Pruning should keep the newest files."""
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text(f"log {i}\n")
                # Each file gets progressively newer mtime
                os.utime(f, (1000 + i * 100, 1000 + i * 100))

            proc = _run_prune(tmp, "manager-", 2)
            self.assertEqual(0, proc.returncode)

            remaining = sorted(Path(tmp).glob("manager-*.log"))
            # Should keep the 2 newest: 003 and 004
            names = [f.name for f in remaining]
            self.assertIn("manager-004.log", names)
            self.assertIn("manager-003.log", names)

    def test_directories_not_pruned(self) -> None:
        """Subdirectories should not be counted or pruned."""
        with tempfile.TemporaryDirectory() as tmp:
            # Create a subdirectory with matching prefix
            (Path(tmp) / "manager-subdir").mkdir()
            # Create files
            for i in range(3):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text("data\n")
                os.utime(f, (1000 + i, 1000 + i))

            proc = _run_prune(tmp, "manager-", 2)
            self.assertEqual(0, proc.returncode)

            # Directory should still exist
            self.assertTrue((Path(tmp) / "manager-subdir").is_dir())
            # Files pruned to 2
            remaining = list(Path(tmp).glob("manager-*.log"))
            self.assertLessEqual(len(remaining), 2)


if __name__ == "__main__":
    unittest.main()
