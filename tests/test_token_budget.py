"""Tests for token budget tracking: daily/hourly ceilings and supervisor restart guard.

Covers:
- SupervisorConfig token budget fields and defaults
- proc_cmd passthrough of --daily-token-budget / --hourly-token-budget / --tokens-per-call
- consume_token_budget shell function (via subprocess)
- Budget exhaustion marker write/read lifecycle
- Supervisor _is_budget_window_active helper
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.persistent_worker import PersistentWorker, PersistentWorkerConfig
from orchestrator.supervisor import (
    SupervisorConfig,
    build_config_from_args,
    proc_cmd,
    _budget_exhaustion_file,
    _is_budget_window_active,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = REPO_ROOT / "scripts" / "autopilot" / "common.sh"


def _default_cfg(**overrides) -> SupervisorConfig:
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


# ---------------------------------------------------------------------------
# SupervisorConfig defaults
# ---------------------------------------------------------------------------

class TokenBudgetConfigDefaultsTests(unittest.TestCase):
    """Verify default values for token budget fields."""

    def test_default_daily_token_budget_is_zero(self):
        cfg = _default_cfg()
        self.assertEqual(cfg.daily_token_budget, 1000000)

    def test_default_hourly_token_budget_is_zero(self):
        cfg = _default_cfg()
        self.assertEqual(cfg.hourly_token_budget, 100000)

    def test_default_tokens_per_call(self):
        cfg = _default_cfg()
        self.assertEqual(cfg.tokens_per_call, 10000)


class TokenBudgetParserTests(unittest.TestCase):
    """Verify CLI arg parser picks up token budget flags."""

    def test_parser_default_daily_token_budget(self):
        _action, cfg = build_config_from_args(["status"])
        self.assertEqual(cfg.daily_token_budget, 0)

    def test_parser_custom_daily_token_budget(self):
        _action, cfg = build_config_from_args(["status", "--daily-token-budget", "500000"])
        self.assertEqual(cfg.daily_token_budget, 500000)

    def test_parser_custom_hourly_token_budget(self):
        _action, cfg = build_config_from_args(["status", "--hourly-token-budget", "100000"])
        self.assertEqual(cfg.hourly_token_budget, 100000)

    def test_parser_custom_tokens_per_call(self):
        _action, cfg = build_config_from_args(["status", "--tokens-per-call", "5000"])
        self.assertEqual(cfg.tokens_per_call, 5000)


# ---------------------------------------------------------------------------
# proc_cmd passthrough
# ---------------------------------------------------------------------------

class TokenBudgetProcCmdTests(unittest.TestCase):
    """Verify token budget flags appear in generated process commands."""

    def test_manager_cmd_includes_token_budget_flags(self):
        cfg = _default_cfg(daily_token_budget=500000, hourly_token_budget=100000, tokens_per_call=5000)
        cmd = proc_cmd("manager", cfg)
        self.assertIn("--daily-token-budget 500000", cmd)
        self.assertIn("--hourly-token-budget 100000", cmd)
        self.assertIn("--tokens-per-call 5000", cmd)

    def test_claude_worker_cmd_includes_token_budget_flags(self):
        cfg = _default_cfg(daily_token_budget=1000000)
        cmd = proc_cmd("claude", cfg)
        self.assertIn("--daily-token-budget 1000000", cmd)

    def test_gemini_worker_cmd_includes_token_budget_flags(self):
        cfg = _default_cfg(hourly_token_budget=50000)
        cmd = proc_cmd("gemini", cfg)
        self.assertIn("--hourly-token-budget 50000", cmd)

    def test_wingman_cmd_includes_token_budget_flags(self):
        cfg = _default_cfg(daily_token_budget=200000)
        cmd = proc_cmd("wingman", cfg)
        self.assertIn("--daily-token-budget 200000", cmd)

    def test_codex_worker_cmd_includes_token_budget_flags(self):
        cfg = _default_cfg(daily_token_budget=300000, tokens_per_call=15000)
        cmd = proc_cmd("codex_worker", cfg)
        self.assertIn("--daily-token-budget 300000", cmd)
        self.assertIn("--tokens-per-call 15000", cmd)

    def test_no_token_flags_when_disabled(self):
        cfg = _default_cfg(daily_token_budget=0, hourly_token_budget=0, tokens_per_call=10000)
        cmd = proc_cmd("manager", cfg)
        self.assertNotIn("--daily-token-budget", cmd)
        self.assertNotIn("--hourly-token-budget", cmd)
        self.assertNotIn("--tokens-per-call", cmd)

    def test_watchdog_cmd_no_token_flags(self):
        cfg = _default_cfg(daily_token_budget=500000, hourly_token_budget=100000)
        cmd = proc_cmd("watchdog", cfg)
        self.assertNotIn("--daily-token-budget", cmd)
        self.assertNotIn("--hourly-token-budget", cmd)


# ---------------------------------------------------------------------------
# consume_token_budget shell function
# ---------------------------------------------------------------------------

class ConsumeTokenBudgetShellTests(unittest.TestCase):
    """Test consume_token_budget via subprocess."""

    def _run_budget(self, daily: int, hourly: int, tokens: int, key: str, root: str) -> int:
        script = f"""
        source "{COMMON_SH}"
        consume_token_budget {daily} {hourly} {tokens} "{key}" "{root}"
        """
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
        )
        return result.returncode

    def test_both_disabled_always_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = self._run_budget(0, 0, 10000, "test", tmp)
            self.assertEqual(rc, 0)

    def test_daily_under_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = self._run_budget(100000, 0, 10000, "test", tmp)
            self.assertEqual(rc, 0)

    def test_daily_over_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            # First call: 50000 tokens, ceiling 100000 → OK
            rc = self._run_budget(100000, 0, 50000, "test", tmp)
            self.assertEqual(rc, 0)
            # Second call: another 50000 → total 100000, still OK
            rc = self._run_budget(100000, 0, 50000, "test", tmp)
            self.assertEqual(rc, 0)
            # Third call: would be 150000 > 100000 → FAIL
            rc = self._run_budget(100000, 0, 50000, "test", tmp)
            self.assertEqual(rc, 1)

    def test_hourly_over_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            # First call: 20000 tokens, hourly ceiling 30000 → OK
            rc = self._run_budget(0, 30000, 20000, "test", tmp)
            self.assertEqual(rc, 0)
            # Second call: another 20000 → total 40000 > 30000 → FAIL
            rc = self._run_budget(0, 30000, 20000, "test", tmp)
            self.assertEqual(rc, 1)

    def test_independent_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Exhaust budget for key "a"
            self._run_budget(10000, 0, 10000, "key-a", tmp)
            rc = self._run_budget(10000, 0, 10000, "key-a", tmp)
            self.assertEqual(rc, 1)
            # Key "b" should still have budget
            rc = self._run_budget(10000, 0, 10000, "key-b", tmp)
            self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# Budget exhaustion marker
# ---------------------------------------------------------------------------

class BudgetExhaustionMarkerTests(unittest.TestCase):
    """Test budget exhaustion marker write/read and window check."""

    def test_no_marker_means_not_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_is_budget_window_active(tmp, "test"))

    def test_future_marker_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = _budget_exhaustion_file(tmp, "test")
            future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            marker.write_text(json.dumps({
                "window": "hourly",
                "exhausted_at": datetime.now(timezone.utc).isoformat(),
                "next_window_at": future,
            }))
            self.assertTrue(_is_budget_window_active(tmp, "test"))

    def test_past_marker_is_not_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = _budget_exhaustion_file(tmp, "test")
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            marker.write_text(json.dumps({
                "window": "hourly",
                "exhausted_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "next_window_at": past,
            }))
            self.assertFalse(_is_budget_window_active(tmp, "test"))

    def test_corrupt_marker_is_not_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = _budget_exhaustion_file(tmp, "test")
            marker.write_text("not json")
            self.assertFalse(_is_budget_window_active(tmp, "test"))


# ---------------------------------------------------------------------------
# write_budget_exhaustion_marker shell function
# ---------------------------------------------------------------------------

class WriteBudgetExhaustionMarkerShellTests(unittest.TestCase):
    """Test the shell write_budget_exhaustion_marker function."""

    def test_writes_valid_json_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_dir = f"{tmp}/pids"
            script = f"""
            source "{COMMON_SH}"
            write_budget_exhaustion_marker "{pid_dir}" "test-proc" "daily"
            """
            subprocess.run(["bash", "-c", script], capture_output=True)
            marker_file = Path(pid_dir) / "test-proc.token_budget_exhausted"
            self.assertTrue(marker_file.exists())
            data = json.loads(marker_file.read_text().strip())
            self.assertEqual(data["window"], "daily")
            self.assertIn("exhausted_at", data)
            self.assertIn("next_window_at", data)

    def test_hourly_marker_has_hourly_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_dir = f"{tmp}/pids"
            script = f"""
            source "{COMMON_SH}"
            write_budget_exhaustion_marker "{pid_dir}" "test-proc" "hourly"
            """
            subprocess.run(["bash", "-c", script], capture_output=True)
            marker_file = Path(pid_dir) / "test-proc.token_budget_exhausted"
            data = json.loads(marker_file.read_text().strip())
            self.assertEqual(data["window"], "hourly")


# ---------------------------------------------------------------------------
# PersistentWorker Budget Tests
# ---------------------------------------------------------------------------

class PersistentWorkerBudgetTests(unittest.TestCase):
    """Tests for PersistentWorker budget exhaustion and event publishing."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmpdir.name) / "logs"
        self.log_dir.mkdir()
        self.pid_dir = Path(self.tmpdir.name) / "pids"
        self.pid_dir.mkdir()
        self.cfg = PersistentWorkerConfig(
            agent="test-agent",
            cli="test-cli",
            process_name="test-agent",
            log_dir=str(self.log_dir),
            pid_dir=str(self.pid_dir),
            project_root=self.tmpdir.name,
            daily_token_budget=100,  # Set a low budget for testing
            hourly_token_budget=100,
            tokens_per_call=50,
        )
        self.worker = PersistentWorker(self.cfg)

        # Mock the orchestrator
        self.mock_orch = MagicMock()
        self.published_events = []
        self.mock_orch.publish_event.side_effect = lambda **kwargs: self.published_events.append(kwargs)

        # Patch _get_orchestrator to return our mock
        patcher = patch('orchestrator.persistent_worker.PersistentWorker._get_orchestrator', return_value=self.mock_orch)
        self.addCleanup(patcher.stop)
        patcher.start()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_daily_token_budget_exhaustion_emits_event_and_shuts_down(self):
        # Consume budget twice to exceed the daily_token_budget (50 + 50 = 100, budget is 100)
        # The third call should exhaust and trigger shutdown/event.
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call)) # 50 tokens
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call)) # 50 tokens

        # This call should exhaust the budget
        self.assertFalse(self.worker._consume_budget(self.cfg.tokens_per_call))

        # Verify event was published
        self.assertEqual(len(self.published_events), 1)
        event = self.published_events[0]
        self.assertEqual(event["event_type"], "agent.budget_exhausted")
        self.assertEqual(event["source"], self.cfg.agent)
        self.assertEqual(event["payload"]["budget_type"], "daily")

    def test_hourly_token_budget_exhaustion_emits_event_and_shuts_down(self):
        # Reset daily budget to 0 to only test hourly
        self.cfg.daily_token_budget = 0
        self.worker._consume_budget(self.cfg.tokens_per_call) # 50 tokens
        self.worker._consume_budget(self.cfg.tokens_per_call) # 50 tokens

        # This call should exhaust the budget
        self.assertFalse(self.worker._consume_budget(self.cfg.tokens_per_call))

        # Verify event was published
        self.assertEqual(len(self.published_events), 1)
        event = self.published_events[0]
        self.assertEqual(event["event_type"], "agent.budget_exhausted")
        self.assertEqual(event["source"], self.cfg.agent)
        self.assertEqual(event["payload"]["budget_type"], "hourly")

    def test_daily_call_budget_exhaustion_does_not_emit_event_or_shutdown(self):
        # Reset token budgets to 0 to only test call budget
        self.cfg.daily_token_budget = 0
        self.cfg.hourly_token_budget = 0
        self.cfg.daily_call_budget = 2 # Set a low call budget

        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call)) # 1st call
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call)) # 2nd call

        # This call should exhaust the call budget, but not token budget
        self.assertFalse(self.worker._consume_budget(self.cfg.tokens_per_call))

        # No event should be published for call budget exhaustion
        self.assertEqual(len(self.published_events), 0)
        # Worker should not shutdown for call budget exhaustion, only token
        self.assertFalse(self.worker._shutdown)

    def test_no_budget_exhaustion(self):
        # With high budget, no exhaustion
        self.cfg.daily_token_budget = 1000
        self.cfg.hourly_token_budget = 1000
        self.cfg.tokens_per_call = 100

        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))

        self.assertEqual(len(self.published_events), 0)
        self.assertFalse(self.worker._shutdown)


if __name__ == "__main__":
    unittest.main()
