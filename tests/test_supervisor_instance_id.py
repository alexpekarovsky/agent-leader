import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.supervisor import Supervisor, SupervisorConfig
from orchestrator.engine import Orchestrator


class SupervisorInstanceIDTests(unittest.TestCase):
    """Tests for instance ID propagation in Supervisor status_json."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cfg = SupervisorConfig(
            project_root=self.tmpdir.name,
            log_dir=str(Path(self.tmpdir.name) / "logs"),
            pid_dir=str(Path(self.tmpdir.name) / "pids"),
        )
        self.cfg.finalise()

        # Mock the orchestrator's list_agents method
        self.mock_orchestrator = MagicMock(spec=Orchestrator)
        self.mock_orchestrator.list_agents.return_value = [
            {
                "agent": "gemini",
                "instance_id": "gemini#headless-default-test-instance",
                "status": "active",
                "task_counts": {"in_progress": 1},
            }
        ]

        self.supervisor = Supervisor(self.cfg, self.mock_orchestrator)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_gemini_worker_instance_id_in_status_json(self):
        status = self.supervisor.status_json()
        gemini_status = next((p for p in status if p["name"] == "gemini"), None)

        self.assertIsNotNone(gemini_status)
        self.assertEqual(gemini_status["instance_id"], "gemini#headless-default-test-instance")

    def test_claude_worker_instance_id_in_status_json(self):
        # Add a mock Claude agent to the list_agents return value
        self.mock_orchestrator.list_agents.return_value.append({
            "agent": "claude_code",
            "instance_id": "claude_code#headless-default-1-test-instance",
            "status": "active",
            "task_counts": {"in_progress": 0},
        })
        status = self.supervisor.status_json()
        claude_status = next((p for p in status if p["name"] == "claude"), None)

        self.assertIsNotNone(claude_status)
        self.assertEqual(claude_status["instance_id"], "claude_code#headless-default-1-test-instance")

    def test_wingman_worker_instance_id_in_status_json(self):
        # Mock wingman_agent config
        self.cfg.wingman_agent = "ccm"
        # Add a mock Wingman agent to the list_agents return value
        self.mock_orchestrator.list_agents.return_value.append({
            "agent": "ccm",
            "instance_id": "ccm#headless-wingman-test-instance",
            "status": "active",
            "task_counts": {"in_progress": 0},
        })
        status = self.supervisor.status_json()
        wingman_status = next((p for p in status if p["name"] == "wingman"), None)

        self.assertIsNotNone(wingman_status)
        self.assertEqual(wingman_status["instance_id"], "ccm#headless-wingman-test-instance")

    def test_codex_worker_instance_id_in_status_json(self):
        # Add a mock Codex agent to the list_agents return value
        self.mock_orchestrator.list_agents.return_value.append({
            "agent": "codex",
            "instance_id": "codex#headless-default-test-instance",
            "status": "active",
            "task_counts": {"in_progress": 0},
        })
        status = self.supervisor.status_json()
        codex_status = next((p for p in status if p["name"] == "codex_worker"), None)

        self.assertIsNotNone(codex_status)
        self.assertEqual(codex_status["instance_id"], "codex#headless-default-test-instance")

    def test_fallback_instance_id_if_not_in_list_agents(self):
        # Ensure list_agents returns an empty list for gemini
        self.mock_orchestrator.list_agents.return_value = []
        status = self.supervisor.status_json()
        gemini_status = next((p for p in status if p["name"] == "gemini"), None)

        self.assertIsNotNone(gemini_status)
        # Should fallback to _get_instance_id("gemini")
        self.assertEqual(gemini_status["instance_id"], "gemini#headless-default")


if __name__ == "__main__":
    unittest.main()