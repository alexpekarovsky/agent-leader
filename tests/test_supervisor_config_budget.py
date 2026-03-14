"""Tests for SupervisorConfig idle/budget fields and low-burn mode.

Covers the idle_backoff, max_idle_cycles, daily_call_budget, and low_burn
fields added to SupervisorConfig, and their passthrough to proc_cmd output.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.supervisor import SupervisorConfig, proc_cmd


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


class SupervisorConfigDefaultsTests(unittest.TestCase):
    """Verify default values for idle/budget fields."""

    def test_default_idle_backoff(self):
        cfg = _default_cfg()
        self.assertEqual(cfg.idle_backoff, "30,60,120,300,900")

    def test_default_max_idle_cycles(self):
        cfg = _default_cfg()
        self.assertEqual(cfg.max_idle_cycles, 0)

    def test_default_daily_call_budget(self):
        cfg = _default_cfg()
        self.assertEqual(cfg.daily_call_budget, 0)

    def test_default_low_burn_false(self):
        cfg = _default_cfg()
        self.assertFalse(cfg.low_burn)


class LowBurnModeTests(unittest.TestCase):
    """Verify low-burn mode applies conservative defaults."""

    def test_low_burn_increases_manager_interval(self):
        cfg = _default_cfg(low_burn=True)
        self.assertGreaterEqual(cfg.manager_interval, 120)

    def test_low_burn_increases_worker_interval(self):
        cfg = _default_cfg(low_burn=True)
        self.assertGreaterEqual(cfg.worker_interval, 180)

    def test_low_burn_sets_max_idle_cycles(self):
        cfg = _default_cfg(low_burn=True)
        self.assertGreater(cfg.max_idle_cycles, 0)

    def test_low_burn_preserves_custom_intervals(self):
        cfg = _default_cfg(low_burn=True, manager_interval=300, worker_interval=600)
        self.assertEqual(cfg.manager_interval, 300)
        self.assertEqual(cfg.worker_interval, 600)

    def test_low_burn_preserves_custom_max_idle(self):
        cfg = _default_cfg(low_burn=True, max_idle_cycles=5)
        self.assertEqual(cfg.max_idle_cycles, 5)


class ProcCmdPassthroughTests(unittest.TestCase):
    """Verify idle/budget flags appear in generated process commands."""

    def test_manager_cmd_includes_idle_flags(self):
        cfg = _default_cfg(idle_backoff="10,20", max_idle_cycles=5, daily_call_budget=100)
        cmd = proc_cmd("manager", cfg)
        self.assertIn("--idle-backoff 10,20", cmd)
        self.assertIn("--max-idle-cycles 5", cmd)
        self.assertIn("--daily-call-budget 100", cmd)

    def test_claude_worker_cmd_includes_idle_flags(self):
        cfg = _default_cfg(idle_backoff="60", max_idle_cycles=10, daily_call_budget=50)
        cmd = proc_cmd("claude", cfg)
        self.assertIn("--idle-backoff 60", cmd)
        self.assertIn("--max-idle-cycles 10", cmd)
        self.assertIn("--daily-call-budget 50", cmd)

    def test_gemini_worker_cmd_includes_idle_flags(self):
        cfg = _default_cfg(daily_call_budget=200)
        cmd = proc_cmd("gemini", cfg)
        self.assertIn("--daily-call-budget 200", cmd)

    def test_wingman_cmd_includes_idle_flags(self):
        cfg = _default_cfg(max_idle_cycles=3)
        cmd = proc_cmd("wingman", cfg)
        self.assertIn("--max-idle-cycles 3", cmd)

    def test_codex_worker_cmd_includes_idle_flags(self):
        cfg = _default_cfg(idle_backoff="5,10,15")
        cmd = proc_cmd("codex_worker", cfg)
        self.assertIn("--idle-backoff 5,10,15", cmd)

    def test_watchdog_cmd_does_not_include_idle_flags(self):
        cfg = _default_cfg(idle_backoff="10,20", max_idle_cycles=5, daily_call_budget=100)
        cmd = proc_cmd("watchdog", cfg)
        self.assertNotIn("--idle-backoff", cmd)
        self.assertNotIn("--max-idle-cycles", cmd)
        self.assertNotIn("--daily-call-budget", cmd)


if __name__ == "__main__":
    unittest.main()
