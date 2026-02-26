"""Smoke tests for worker_loop.sh argument handling.

Validates that worker_loop.sh rejects unknown arguments with a non-zero
exit code and expected error text on stderr.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")

_TIMEOUT = 5


class WorkerLoopArgTests(unittest.TestCase):
    """Bounded tests for CLI argument validation."""

    def _run_worker(
        self, args: list[str], *, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        return subprocess.run(
            ["bash", WORKER_LOOP, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_TIMEOUT,
            env=merged_env,
        )

    def test_unknown_arg_exits_nonzero(self) -> None:
        proc = self._run_worker(["--bogus-flag"])
        self.assertNotEqual(0, proc.returncode)
        self.assertEqual(1, proc.returncode)

    def test_unknown_arg_stderr_contains_error_text(self) -> None:
        proc = self._run_worker(["--bogus-flag"])
        self.assertIn("Unknown arg", proc.stderr)
        self.assertIn("--bogus-flag", proc.stderr)

    def test_unknown_arg_stderr_contains_error_level(self) -> None:
        proc = self._run_worker(["--not-a-real-option"])
        self.assertIn("[ERROR]", proc.stderr)

    def test_multiple_unknown_args_rejects_first(self) -> None:
        """Script should fail on the first unrecognized arg."""
        proc = self._run_worker(["--aaa", "--bbb"])
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("--aaa", proc.stderr)

    def test_missing_required_args_exits_nonzero_with_message(self) -> None:
        proc = self._run_worker(["--cli", "codex"])
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("--cli and --agent are required", proc.stderr)

    def test_missing_cli_and_agent_exact_error_format(self) -> None:
        """AL-CORE-27: stderr must contain '[ERROR] --cli and --agent are required'."""
        proc = self._run_worker([])
        self.assertEqual(1, proc.returncode)
        error_lines = [l for l in proc.stderr.splitlines() if "--cli and --agent" in l]
        self.assertEqual(1, len(error_lines), f"expected 1 error line, got {error_lines}")
        line = error_lines[0]
        self.assertIn("[ERROR]", line)
        self.assertIn("--cli and --agent are required", line)
        self.assertRegex(line, r"\[.*\] \[ERROR\] --cli and --agent are required")

    def test_missing_agent_only_exact_error_format(self) -> None:
        """AL-CORE-27: providing --cli without --agent must still show the required args error."""
        proc = self._run_worker(["--cli", "codex"])
        self.assertEqual(1, proc.returncode)
        error_lines = [l for l in proc.stderr.splitlines() if "--cli and --agent" in l]
        self.assertEqual(1, len(error_lines))
        self.assertRegex(error_lines[0], r"\[.*\] \[ERROR\] --cli and --agent are required")

    def test_missing_cli_only_exact_error_format(self) -> None:
        """AL-CORE-27: providing --agent without --cli must still show the required args error."""
        proc = self._run_worker(["--agent", "claude_code"])
        self.assertEqual(1, proc.returncode)
        error_lines = [l for l in proc.stderr.splitlines() if "--cli and --agent" in l]
        self.assertEqual(1, len(error_lines))
        self.assertRegex(error_lines[0], r"\[.*\] \[ERROR\] --cli and --agent are required")

    def test_unsupported_cli_exits_nonzero_with_error_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake_cli = bin_dir / "fakecli"
            fake_cli.write_text("#!/usr/bin/env bash\nexit 0\n")
            fake_cli.chmod(0o755)

            proc = self._run_worker(
                [
                    "--cli",
                    "fakecli",
                    "--agent",
                    "claude_code",
                    "--once",
                    "--project-root",
                    tmp,
                    "--log-dir",
                    str(Path(tmp) / "logs"),
                ],
                env={"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            )
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("Unsupported CLI: fakecli", proc.stderr)
            self.assertIn("worker cycle failed", proc.stderr)


if __name__ == "__main__":
    unittest.main()
