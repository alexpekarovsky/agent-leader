"""Tests for Gemini capacity fallback/retry policy.

Covers:
- Shell-level detect_gemini_capacity_error() function
- Inline capacity detection in run_cli_prompt (Python _is_gemini_capacity_error)
- SupervisorConfig gemini_fallback_model / capacity fields
- proc_cmd env var passthrough for Gemini capacity config
- Capacity error marker file reading in status output
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = str(REPO_ROOT / "scripts" / "autopilot" / "common.sh")

_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Shell-level detect_gemini_capacity_error tests
# ---------------------------------------------------------------------------

class DetectGeminiCapacityErrorTests(unittest.TestCase):
    """Test the detect_gemini_capacity_error() bash function."""

    def _run_detect(self, output_content: str) -> int:
        """Write content to a temp file and run detect_gemini_capacity_error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(output_content)
            f.flush()
            tmp = f.name
        try:
            result = subprocess.run(
                ["bash", "-c", f"source {COMMON_SH} && detect_gemini_capacity_error {tmp}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_TIMEOUT,
            )
            return result.returncode
        finally:
            os.unlink(tmp)

    def test_detects_model_capacity_exhausted(self) -> None:
        rc = self._run_detect("Error: MODEL_CAPACITY_EXHAUSTED for gemini-2.5-flash")
        self.assertEqual(0, rc)

    def test_detects_resource_exhausted(self) -> None:
        rc = self._run_detect('{"status": "RESOURCE_EXHAUSTED", "message": "quota"}')
        self.assertEqual(0, rc)

    def test_detects_rate_limit_exceeded(self) -> None:
        rc = self._run_detect("API error: rateLimitExceeded")
        self.assertEqual(0, rc)

    def test_detects_429_status(self) -> None:
        rc = self._run_detect("HTTP 429 Too Many Requests")
        self.assertEqual(0, rc)

    def test_detects_no_capacity_available(self) -> None:
        rc = self._run_detect("No capacity available for model gemini-2.5-flash")
        self.assertEqual(0, rc)

    def test_returns_nonzero_for_normal_error(self) -> None:
        rc = self._run_detect("Error: invalid JSON in request body")
        self.assertNotEqual(0, rc)

    def test_returns_nonzero_for_success_output(self) -> None:
        rc = self._run_detect("Task completed successfully. All tests passed.")
        self.assertNotEqual(0, rc)

    def test_returns_nonzero_for_missing_file(self) -> None:
        result = subprocess.run(
            ["bash", "-c", f"source {COMMON_SH} && detect_gemini_capacity_error /nonexistent/file.log"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_TIMEOUT,
        )
        self.assertNotEqual(0, result.returncode)

    def test_returns_nonzero_for_empty_file(self) -> None:
        rc = self._run_detect("")
        self.assertNotEqual(0, rc)


# ---------------------------------------------------------------------------
# Inline _is_gemini_capacity_error tests (Python function in common.sh)
# ---------------------------------------------------------------------------

class InlineCapacityDetectionTests(unittest.TestCase):
    """Test the Python _is_gemini_capacity_error markers used inside run_cli_prompt."""

    MARKERS = (
        "MODEL_CAPACITY_EXHAUSTED",
        "No capacity available for model",
        '"status": "RESOURCE_EXHAUSTED"',
        "rateLimitExceeded",
    )

    def test_each_marker_detected(self) -> None:
        for marker in self.MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, open(COMMON_SH).read(),
                              f"marker {marker!r} should be in common.sh inline detection")


# ---------------------------------------------------------------------------
# SupervisorConfig tests
# ---------------------------------------------------------------------------

class SupervisorConfigCapacityTests(unittest.TestCase):
    """Test SupervisorConfig gemini capacity fields."""

    def test_default_gemini_fallback_model_empty(self) -> None:
        from orchestrator.supervisor import SupervisorConfig
        cfg = SupervisorConfig()
        self.assertEqual(cfg.gemini_fallback_model, "")

    def test_default_gemini_capacity_retries(self) -> None:
        from orchestrator.supervisor import SupervisorConfig
        cfg = SupervisorConfig()
        self.assertEqual(cfg.gemini_capacity_retries, 2)

    def test_default_gemini_capacity_backoff(self) -> None:
        from orchestrator.supervisor import SupervisorConfig
        cfg = SupervisorConfig()
        self.assertEqual(cfg.gemini_capacity_backoff, 15)

    def test_custom_fallback_model(self) -> None:
        from orchestrator.supervisor import SupervisorConfig
        cfg = SupervisorConfig(gemini_fallback_model="gemini-2.0-flash")
        self.assertEqual(cfg.gemini_fallback_model, "gemini-2.0-flash")


# ---------------------------------------------------------------------------
# proc_cmd env var passthrough tests
# ---------------------------------------------------------------------------

class ProcCmdCapacityEnvTests(unittest.TestCase):
    """Verify Gemini capacity env vars appear in proc_cmd output."""

    @staticmethod
    def _default_cfg(**overrides):
        from orchestrator.supervisor import SupervisorConfig
        with tempfile.TemporaryDirectory() as tmp:
            defaults = {
                "project_root": tmp,
                "repo_root": tmp,
                "log_dir": f"{tmp}/logs",
                "leader_agent": "codex",
            }
            defaults.update(overrides)
            cfg = SupervisorConfig(**defaults)
            cfg.finalise()
            return cfg

    def test_gemini_cmd_includes_capacity_retries_env(self) -> None:
        from orchestrator.supervisor import proc_cmd
        cfg = self._default_cfg(gemini_capacity_retries=3)
        cmd = proc_cmd("gemini", cfg)
        self.assertIn("ORCHESTRATOR_GEMINI_CAPACITY_RETRIES=3", cmd)

    def test_gemini_cmd_includes_capacity_backoff_env(self) -> None:
        from orchestrator.supervisor import proc_cmd
        cfg = self._default_cfg(gemini_capacity_backoff=30)
        cmd = proc_cmd("gemini", cfg)
        self.assertIn("ORCHESTRATOR_GEMINI_CAPACITY_BACKOFF_SECONDS=30", cmd)

    def test_gemini_cmd_includes_fallback_model_env(self) -> None:
        from orchestrator.supervisor import proc_cmd
        cfg = self._default_cfg(gemini_fallback_model="gemini-2.0-flash")
        cmd = proc_cmd("gemini", cfg)
        self.assertIn("ORCHESTRATOR_GEMINI_FALLBACK_MODEL=gemini-2.0-flash", cmd)

    def test_gemini_cmd_omits_fallback_when_empty(self) -> None:
        from orchestrator.supervisor import proc_cmd
        cfg = self._default_cfg(gemini_fallback_model="")
        cmd = proc_cmd("gemini", cfg)
        self.assertNotIn("ORCHESTRATOR_GEMINI_FALLBACK_MODEL", cmd)

    def test_claude_cmd_unaffected(self) -> None:
        from orchestrator.supervisor import proc_cmd
        cfg = self._default_cfg(gemini_fallback_model="gemini-2.0-flash")
        cmd = proc_cmd("claude", cfg)
        self.assertNotIn("ORCHESTRATOR_GEMINI_FALLBACK_MODEL", cmd)
        self.assertNotIn("ORCHESTRATOR_GEMINI_CAPACITY", cmd)


# ---------------------------------------------------------------------------
# CLI parser tests
# ---------------------------------------------------------------------------

class BuildConfigCapacityArgsTests(unittest.TestCase):
    """Verify CLI flags are wired to config fields."""

    def test_gemini_fallback_model_flag(self) -> None:
        from orchestrator.supervisor import build_config_from_args
        _, cfg = build_config_from_args(["status", "--gemini-fallback-model", "gemini-2.0-flash"])
        self.assertEqual(cfg.gemini_fallback_model, "gemini-2.0-flash")

    def test_gemini_capacity_retries_flag(self) -> None:
        from orchestrator.supervisor import build_config_from_args
        _, cfg = build_config_from_args(["status", "--gemini-capacity-retries", "5"])
        self.assertEqual(cfg.gemini_capacity_retries, 5)

    def test_gemini_capacity_backoff_flag(self) -> None:
        from orchestrator.supervisor import build_config_from_args
        _, cfg = build_config_from_args(["status", "--gemini-capacity-backoff", "60"])
        self.assertEqual(cfg.gemini_capacity_backoff, 60)

    def test_default_flags(self) -> None:
        from orchestrator.supervisor import build_config_from_args
        _, cfg = build_config_from_args(["status"])
        self.assertEqual(cfg.gemini_fallback_model, "")
        self.assertEqual(cfg.gemini_capacity_retries, 2)
        self.assertEqual(cfg.gemini_capacity_backoff, 15)


# ---------------------------------------------------------------------------
# Capacity error marker file / ProcessStatus tests
# ---------------------------------------------------------------------------

class CapacityErrorMarkerTests(unittest.TestCase):
    """Test that capacity error marker file is read by _capacity_error_file."""

    def test_capacity_error_file_path(self) -> None:
        from orchestrator.supervisor import _capacity_error_file
        p = _capacity_error_file("/tmp/pids", "gemini")
        self.assertEqual(p, Path("/tmp/pids/gemini.capacity_errors"))

    def test_process_status_default_capacity_errors(self) -> None:
        from orchestrator.supervisor import ProcessStatus
        ps = ProcessStatus("gemini", "running", 123, 0, "active", "idle")
        self.assertEqual(ps.capacity_errors, 0)

    def test_process_status_with_capacity_errors(self) -> None:
        from orchestrator.supervisor import ProcessStatus
        ps = ProcessStatus("gemini", "running", 123, 0, "active", "capacity_degraded", 3)
        self.assertEqual(ps.capacity_errors, 3)


if __name__ == "__main__":
    unittest.main()
