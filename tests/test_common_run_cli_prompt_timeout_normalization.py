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
                ["bash", "-lc", cmd],
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


if __name__ == "__main__":
    unittest.main()
