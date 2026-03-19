"""Tests for common.sh run_cli_prompt timeout normalization.

AL-CORE-11 (TASK-90686b48): invalid/non-positive timeout values should
normalize to the default timeout instead of failing immediately.
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


def _make_sleeping_codex_stub(bin_dir: Path, sleep_seconds: float = 0.2) -> None:
    stub = bin_dir / "codex"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "shift 4\n"  # drop: exec --dangerously... -C <cwd>
        f"python3 - <<'PY'\nimport time; time.sleep({sleep_seconds})\nPY\n"
        "cat -\n"
    )
    stub.chmod(0o755)


def _make_retrying_gemini_stub(bin_dir: Path) -> Path:
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
        "  exit 1\n"
        "fi\n"
        "echo 'gemini success'\n"
        "cat - >/dev/null\n"
    )
    stub.chmod(0o755)
    return attempts_file


class RunCliPromptTimeoutNormalizationTests(unittest.TestCase):
    def _run(self, timeout_value: str) -> tuple[subprocess.CompletedProcess[str], float, str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            _make_sleeping_codex_stub(bin_dir)

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
                ["bash", "-c", cmd],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_TIMEOUT,
            )
            elapsed = time.time() - start

            return proc, elapsed, out_file.read_text(encoding="utf-8")

    def _assert_normalized_and_completed(self, timeout_value: str) -> None:
        proc, elapsed, content = self._run(timeout_value)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertLess(elapsed, 8.0)
        self.assertGreater(elapsed, 0.1)
        self.assertIn("hello", content)
        self.assertNotIn("[AUTOPILOT] CLI timeout", content)

    def test_non_numeric_timeout_normalizes_to_default(self) -> None:
        self._assert_normalized_and_completed("not-a-number")

    def test_zero_timeout_normalizes_to_default(self) -> None:
        self._assert_normalized_and_completed("0")

    def test_negative_timeout_normalizes_to_default(self) -> None:
        self._assert_normalized_and_completed("-5")

    def test_gemini_capacity_retry_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            attempts_file = _make_retrying_gemini_stub(bin_dir)

            prompt_file = tmp_path / "prompt.txt"
            out_file = tmp_path / "out.log"
            prompt_file.write_text("hello\n", encoding="utf-8")

            cmd = (
                f"source '{COMMON_SH}' && "
                f"run_cli_prompt gemini '{tmp_path}' '{prompt_file}' '{out_file}' '30'"
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            env["ORCHESTRATOR_GEMINI_MODEL"] = "gemini-2.5-flash"
            env["ORCHESTRATOR_GEMINI_CAPACITY_RETRIES"] = "1"
            env["ORCHESTRATOR_GEMINI_CAPACITY_BACKOFF_SECONDS"] = "0"

            proc = subprocess.run(
                ["bash", "-c", cmd],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_TIMEOUT,
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertEqual("2", attempts_file.read_text(encoding="utf-8").strip())
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("Gemini capacity exhausted; retry 1/1", content)
            self.assertIn("gemini success", content)


if __name__ == "__main__":
    unittest.main()
