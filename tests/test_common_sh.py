"""Tests for scripts/autopilot/common.sh helpers.

Covers prune_old_logs, require_cmd, and run_cli_prompt timeout normalization.
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


def _source_and_run(script_body: str, **kwargs) -> subprocess.CompletedProcess[str]:
    script = f'source "{COMMON_SH}"\n{script_body}'
    return subprocess.run(
        ["bash", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_TIMEOUT,
        **kwargs,
    )


class PruneOldLogsTests(unittest.TestCase):
    def _run_prune(self, log_dir: str, prefix: str, max_files: int):
        return _source_and_run(f'prune_old_logs "{log_dir}" "{prefix}" {max_files}')

    def test_prefix_filtering_preserves_unrelated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text(f"log {i}\n")
                os.utime(f, (time.time() - 3600 + i, time.time() - 3600 + i))
            for i in range(3):
                (Path(tmp) / f"worker-{i:03d}.log").write_text(f"w{i}\n")

            proc = self._run_prune(tmp, "manager-", 2)
            self.assertEqual(0, proc.returncode)
            self.assertEqual(3, len(list(Path(tmp).glob("worker-*.log"))))
            self.assertLessEqual(len(list(Path(tmp).glob("manager-*.log"))), 2)

    def test_prunes_to_max_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(10):
                f = Path(tmp) / f"watchdog-{i:03d}.jsonl"
                f.write_text("{}\n")
                os.utime(f, (time.time() - 3600 + i, time.time() - 3600 + i))

            self.assertEqual(0, self._run_prune(tmp, "watchdog-", 3).returncode)
            self.assertEqual(3, len(list(Path(tmp).glob("watchdog-*.jsonl"))))

    def test_fewer_than_max_no_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                (Path(tmp) / f"manager-{i:03d}.log").write_text(f"log {i}\n")

            self.assertEqual(0, self._run_prune(tmp, "manager-", 10).returncode)
            self.assertEqual(3, len(list(Path(tmp).glob("manager-*.log"))))

    def test_keeps_newest_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text(f"log {i}\n")
                os.utime(f, (time.time() - 3600 + i * 100, time.time() - 3600 + i * 100))

            self.assertEqual(0, self._run_prune(tmp, "manager-", 1).returncode)
            remaining = list(Path(tmp).glob("manager-*.log"))
            self.assertEqual(1, len(remaining))
            self.assertEqual("manager-004.log", remaining[0].name)

    def test_nonexistent_dir_no_error(self) -> None:
        self.assertEqual(0, self._run_prune("/tmp/nonexistent-prune-test-xyz", "manager-", 5).returncode)

    def test_directories_not_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manager-subdir").mkdir()
            for i in range(3):
                f = Path(tmp) / f"manager-{i:03d}.log"
                f.write_text("data\n")
                os.utime(f, (time.time() - 3600 + i, time.time() - 3600 + i))

            self.assertEqual(0, self._run_prune(tmp, "manager-", 2).returncode)
            self.assertTrue((Path(tmp) / "manager-subdir").is_dir())


class RequireCmdTests(unittest.TestCase):
    def test_missing_command_exits_nonzero_with_error(self) -> None:
        proc = _source_and_run('require_cmd "nonexistent_cmd_xyz_12345"')
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("Missing required command", proc.stderr)
        self.assertIn("[ERROR]", proc.stderr)

    def test_existing_command_exits_zero(self) -> None:
        proc = _source_and_run('require_cmd "bash"')
        self.assertEqual(0, proc.returncode)


class RunCliPromptTimeoutTests(unittest.TestCase):
    def _run_with_timeout(self, timeout_value: str) -> tuple[subprocess.CompletedProcess[str], float, str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            stub = bin_dir / "codex"
            stub.write_text(
                "#!/usr/bin/env bash\nshift 4\n"
                "python3 - <<'PY'\nimport time; time.sleep(0.2)\nPY\ncat -\n"
            )
            stub.chmod(0o755)

            prompt_file = tmp_path / "prompt.txt"
            out_file = tmp_path / "out.log"
            prompt_file.write_text("hello\n", encoding="utf-8")

            cmd = (
                f"source '{COMMON_SH}' && "
                f"run_cli_prompt codex '{tmp_path}' '{prompt_file}' '{out_file}' '{timeout_value}'"
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            start = time.time()
            proc = subprocess.run(
                ["bash", "-c", cmd], cwd=REPO_ROOT, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=_TIMEOUT,
            )
            return proc, time.time() - start, out_file.read_text(encoding="utf-8")

    def test_non_numeric_timeout_normalizes(self) -> None:
        proc, elapsed, content = self._run_with_timeout("not-a-number")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("hello", content)

    def test_zero_timeout_normalizes(self) -> None:
        proc, elapsed, content = self._run_with_timeout("0")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("hello", content)

    def test_gemini_capacity_retry_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            attempts_file = bin_dir / ".gemini_attempts"
            stub = bin_dir / "gemini"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                f"count=0\n[[ -f '{attempts_file}' ]] && count=$(cat '{attempts_file}')\n"
                "count=$((count + 1))\n"
                f"echo \"$count\" > '{attempts_file}'\n"
                "if [[ \"$count\" -eq 1 ]]; then\n"
                "  echo 'MODEL_CAPACITY_EXHAUSTED'\n"
                "  echo 'No capacity available for model gemini-2.5-flash on the server'\n"
                "  exit 1\nfi\necho 'gemini success'\ncat - >/dev/null\n"
            )
            stub.chmod(0o755)

            prompt_file = tmp_path / "prompt.txt"
            out_file = tmp_path / "out.log"
            prompt_file.write_text("hello\n", encoding="utf-8")

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            env["ORCHESTRATOR_GEMINI_MODEL"] = "gemini-2.5-flash"
            env["ORCHESTRATOR_GEMINI_CAPACITY_RETRIES"] = "1"
            env["ORCHESTRATOR_GEMINI_CAPACITY_BACKOFF_SECONDS"] = "0"

            proc = subprocess.run(
                ["bash", "-c", f"source '{COMMON_SH}' && run_cli_prompt gemini '{tmp_path}' '{prompt_file}' '{out_file}' '30'"],
                cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=_TIMEOUT,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("Gemini capacity exhausted; retry 1/1", content)


if __name__ == "__main__":
    unittest.main()
