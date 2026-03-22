import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase, mock

from orchestrator.persistent_worker import PersistentWorker, PersistentWorkerConfig, _get_budget_state, _original_time_strftime, _get_token_exhaustion_marker_path

class TestPersistentWorkerBudget(TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_dir = os.path.join(self.temp_dir, "log")
        os.makedirs(self.log_dir)
        self.project_root = os.path.join(self.temp_dir, "project")
        os.makedirs(os.path.join(self.project_root, "state")) # Needed for _signal_file

        self.cfg = PersistentWorkerConfig(
            cli="gemini",
            agent="test_agent",
            project_root=self.project_root,
            log_dir=self.log_dir,
            tokens_per_call=100, # Defaulting this to 100 for all tests
            max_idle_cycles=1, # Exit quickly if idle
            daily_call_budget=0, # Explicitly set to 0
            daily_token_budget=0, # Explicitly set to 0
            hourly_token_budget=0, # Explicitly set to 0
        )
        # Mock orchestrator methods to prevent actual calls
        # These mocks need to be on the instance, not the class, so re-create worker
        self.worker = PersistentWorker(self.cfg)
        self._setup_worker_mocks()

    def _setup_worker_mocks(self):
        """Sets up mocks for the worker's orchestrator interaction methods."""
        self.worker._get_orchestrator = mock.Mock(return_value=mock.Mock())
        self.worker._connect = mock.Mock(return_value={"verified": True})
        self.worker._heartbeat = mock.Mock()
        self.worker._has_claimable_work = mock.Mock(return_value=False)
        self.worker._claim_next_task = mock.Mock(return_value=None)
        self.worker._wait_for_signal = mock.Mock(return_value=False) # Don't wait for signal in tests

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @mock.patch('time.time', return_value=0) # Control time for testing
    @mock.patch('time.strftime', side_effect=lambda fmt, t=None: "19700101" if "%Y%m%d" in fmt else ("1970010100" if "%Y%m%d%H" in fmt else _original_time_strftime(fmt, t or time.localtime(0))))
    def test_daily_token_budget_exhaustion(self, mock_strftime, mock_time):
        self.cfg.daily_token_budget = 200 # Allow 2 calls (2 * 100 tokens_per_call)
        self.cfg.tokens_per_call = 100
        self.worker = PersistentWorker(self.cfg) # Re-init with updated cfg
        self._setup_worker_mocks() # Re-apply mocks

        # First call, should be fine
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))
        self.assertFalse(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
        daily_token_file = os.path.join(self.log_dir, f".budget-worker-gemini-test_agent-19700101.token_count.json")
        self.assertEqual(_get_budget_state(daily_token_file)["token_count"], 100)

        # Second call, should still be fine
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))
        self.assertFalse(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
        self.assertEqual(_get_budget_state(daily_token_file)["token_count"], 200)

        # Third call, should exhaust the budget
        self.assertFalse(self.worker._consume_budget(self.cfg.tokens_per_call))
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
        # Token count should not exceed budget in the file
        self.assertEqual(_get_budget_state(daily_token_file)["token_count"], 200)


    @mock.patch('time.time', return_value=0) # Control time for testing
    @mock.patch('time.strftime', side_effect=lambda fmt, t=None: "19700101" if "%Y%m%d" in fmt else ("1970010100" if "%Y%m%d%H" in fmt else _original_time_strftime(fmt, t or time.localtime(0))))
    def test_hourly_token_budget_exhaustion(self, mock_strftime, mock_time):
        cfg = PersistentWorkerConfig(
            cli="gemini",
            agent="test_agent",
            project_root=self.project_root,
            log_dir=self.log_dir,
            tokens_per_call=100,
            max_idle_cycles=1,
            daily_call_budget=0,
            daily_token_budget=0,
            hourly_token_budget=150, # Allow 1 call, second call will exceed
        )
        self.worker = PersistentWorker(cfg)
        self._setup_worker_mocks() # Re-apply mocks

        # First call, should be fine
        self.assertTrue(self.worker._consume_budget(cfg.tokens_per_call))
        self.assertFalse(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
        day_str = time.strftime("%Y%m%d", time.localtime(mock_time.return_value))
        hour_str = time.strftime("%Y%m%d%H", time.localtime(mock_time.return_value))
        hourly_token_file = os.path.join(self.log_dir, f".budget-worker-gemini-test_agent-{hour_str}.hourly_token_count.json")
        self.assertEqual(_get_budget_state(hourly_token_file)["token_count"], 100)

        # Second call, should exhaust the budget
        self.assertFalse(self.worker._consume_budget(cfg.tokens_per_call))
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
        # Token count should not exceed budget in the file
        self.assertEqual(_get_budget_state(hourly_token_file)["token_count"], 100)


    @mock.patch('time.time', return_value=0) # Control time for testing
    @mock.patch('time.strftime', side_effect=lambda fmt, t=None: "19700101" if "%Y%m%d" in fmt else ("1970010100" if "%Y%m%d%H" in fmt else _original_time_strftime(fmt, t or time.localtime(0))))
    def test_daily_call_budget_exhaustion(self, mock_strftime, mock_time):
        self.cfg.daily_call_budget = 2 # Allow 2 calls
        self.cfg.tokens_per_call = 100 # Not relevant for this test, but good to have
        self.worker = PersistentWorker(self.cfg) # Re-init with updated cfg
        self._setup_worker_mocks() # Re-apply mocks

        # First call, should be fine
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))
        daily_call_file = os.path.join(self.log_dir, f".budget-worker-gemini-test_agent-19700101.call_count.json")
        self.assertEqual(_get_budget_state(daily_call_file)["call_count"], 1)

        # Second call, should still be fine
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))
        self.assertEqual(_get_budget_state(daily_call_file)["call_count"], 2)

        # Third call, should exhaust the budget
        self.assertFalse(self.worker._consume_budget(self.cfg.tokens_per_call))
        # Call count should not exceed budget in the file
        self.assertEqual(_get_budget_state(daily_call_file)["call_count"], 2)

    @mock.patch('time.time', return_value=0)
    @mock.patch('time.strftime', side_effect=lambda fmt, t=None: "19700101" if "%Y%m%d" in fmt else ("1970010100" if "%Y%m%d%H" in fmt else _original_time_strftime(fmt, t or time.localtime(0))))
    def test_daily_token_budget_reset(self, mock_strftime, mock_time):
        self.cfg.daily_token_budget = 100
        self.cfg.tokens_per_call = 100
        self.worker = PersistentWorker(self.cfg)
        self._setup_worker_mocks()

        # Day 1: Exhaust budget
        self.assertFalse(self.worker._consume_budget(self.cfg.tokens_per_call * 2)) # Exceed budget in one go
        daily_token_file = os.path.join(self.log_dir, f".budget-worker-gemini-test_agent-19700101.token_count.json")
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
        self.assertEqual(_get_budget_state(daily_token_file)["token_count"], 0) # Should be capped at budget

        # Advance to Day 2
        mock_strftime.side_effect = lambda fmt, t=None: _original_time_strftime(fmt, time.localtime(0 + 86400)) # Advance 24 hours
        self.worker = PersistentWorker(self.cfg) # Re-init to clear internal state
        self._setup_worker_mocks() # Re-apply mocks

        # The budget exhaustion file for the previous day should still exist
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())

        # First call on Day 2, should be fine
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))
        daily_token_file_day2 = os.path.join(self.log_dir, f".budget-worker-gemini-test_agent-19700102.token_count.json")
        self.assertEqual(_get_budget_state(daily_token_file_day2)["token_count"], 100)
        # The marker for the new day should not exist after the first successful call
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())

    @mock.patch('time.time', return_value=0)
    @mock.patch('time.strftime', side_effect=lambda fmt, t=None: "19700101" if "%Y%m%d" in fmt else ("1970010100" if "%Y%m%d%H" in fmt else _original_time_strftime(fmt, t or time.localtime(0))))
    def test_hourly_token_budget_reset(self, mock_strftime, mock_time):
        cfg = PersistentWorkerConfig(
            cli="gemini",
            agent="test_agent",
            project_root=self.project_root,
            log_dir=self.log_dir,
            tokens_per_call=100,
            max_idle_cycles=1,
            daily_call_budget=0,
            daily_token_budget=0,
            hourly_token_budget=100,
        )
        self.worker = PersistentWorker(cfg)
        self._setup_worker_mocks()

        # Hour 1: Exhaust budget
        self.assertFalse(self.worker._consume_budget(self.cfg.tokens_per_call * 2)) # Exceed budget
        day_str = time.strftime("%Y%m%d", time.localtime(mock_time.return_value))
        hour_str = time.strftime("%Y%m%d%H", time.localtime(mock_time.return_value))
        hourly_token_file = os.path.join(self.log_dir, f".budget-worker-gemini-test_agent-{hour_str}.hourly_token_count.json")
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
        self.assertEqual(_get_budget_state(hourly_token_file)["token_count"], 0) # Should be capped at budget

        # Advance to Hour 2
        mock_strftime.side_effect = lambda fmt, t=None: _original_time_strftime(fmt, time.localtime(0 + 3600)) # Advance 1 hour
        self.worker = PersistentWorker(self.cfg) # Re-init to clear internal state
        self._setup_worker_mocks() # Re-apply mocks
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())

        # First call on Hour 2, should be fine
        self.assertTrue(self.worker._consume_budget(self.cfg.tokens_per_call))
        hour_str_hr2 = time.strftime("%Y%m%d%H", time.localtime(mock_time.return_value + 3600)) # Adjust for advanced time
        hourly_token_file_hr2 = os.path.join(self.log_dir, f".budget-worker-gemini-test_agent-{hour_str_hr2}.hourly_token_count.json")
        self.assertEqual(_get_budget_state(hourly_token_file_hr2)["token_count"], 100)
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())

    @mock.patch('time.time', return_value=0)
    @mock.patch('time.strftime', side_effect=lambda fmt, t=None: "19700101" if "%Y%m%d" in fmt else ("1970010100" if "%Y%m%d%H" in fmt else _original_time_strftime(fmt, t or time.localtime(0))))
    @mock.patch('orchestrator.persistent_worker.PersistentWorker._run_cli', return_value=0) # Mock CLI to always succeed
    def test_persistent_worker_stops_on_budget_exhaustion(self, mock_run_cli, mock_strftime, mock_time):
        self.cfg.daily_token_budget = 150 # Exceed on second CLI call (100 tokens per call)
        self.cfg.tokens_per_call = 100
        self.worker = PersistentWorker(self.cfg)
        self._setup_worker_mocks()

        # Mock has_claimable_work to always return True for 2 cycles, then False
        # to ensure the run loop attempts tasks.
        self.worker._has_claimable_work.side_effect = [True, True, False]
        self.worker._claim_next_task.return_value = {"id": "TASK-123", "title": "Test Task", "description": "", "acceptance_criteria": []}

        # Run the worker loop. It should exit after the budget is exhausted.
        exit_code = self.worker.run()

        # Should exit with 0 (graceful shutdown)
        self.assertEqual(exit_code, 0)
        # Should have called _run_cli twice (first call, then second call which exhausts budget)
        self.assertEqual(mock_run_cli.call_count, 1)
        # Verify budget exhaustion marker exists
        self.assertTrue(Path(_get_token_exhaustion_marker_path(self.log_dir, self.cfg.agent)).exists())
