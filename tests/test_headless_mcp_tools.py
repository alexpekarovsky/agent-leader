from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import json
from unittest.mock import patch


class HeadlessMcpToolsTests(unittest.TestCase):
    def test_tools_list_exposes_headless_runtime_tools(self) -> None:
        from orchestrator_mcp_server import handle_tools_list

        result = handle_tools_list("req-1")
        self.assertIn("result", result)
        tools = result["result"]["tools"]
        names = {item["name"] for item in tools}
        self.assertIn("orchestrator_headless_start", names)
        self.assertIn("orchestrator_headless_stop", names)
        self.assertIn("orchestrator_headless_status", names)
        self.assertIn("orchestrator_headless_restart", names)
        self.assertIn("orchestrator_headless_clean", names)

    def test_supervisor_from_tool_args_applies_project_root(self) -> None:
        from orchestrator_mcp_server import _supervisor_from_tool_args

        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp))
            supervisor = _supervisor_from_tool_args({"project_root": root, "leader_agent": "claude_code"})
            self.assertEqual(root, supervisor.cfg.project_root)
            self.assertEqual("claude_code", supervisor.cfg.leader_agent)

    def test_run_supervisor_action_returns_machine_readable_payload(self) -> None:
        from orchestrator_mcp_server import _run_supervisor_action, _supervisor_from_tool_args

        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp))
            supervisor = _supervisor_from_tool_args({"project_root": root})
            payload = _run_supervisor_action(supervisor, "stop")
            self.assertTrue(payload["ok"])
            self.assertEqual("stop", payload["action"])
            self.assertEqual(root, payload["project_root"])
            self.assertIsInstance(payload["processes"], list)

    def test_run_supervisor_action_supports_restart_and_clean(self) -> None:
        from orchestrator_mcp_server import _run_supervisor_action, _supervisor_from_tool_args

        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp))
            supervisor = _supervisor_from_tool_args({"project_root": root})
            with patch.object(supervisor, "restart", return_value=None) as mock_restart:
                payload = _run_supervisor_action(supervisor, "restart")
                self.assertEqual("restart", payload["action"])
                mock_restart.assert_called_once()
            with patch.object(supervisor, "clean", return_value=None) as mock_clean:
                payload = _run_supervisor_action(supervisor, "clean")
                self.assertEqual("clean", payload["action"])
                mock_clean.assert_called_once()

    def test_handle_tool_call_headless_status_returns_payload(self) -> None:
        from orchestrator_mcp_server import handle_tool_call

        with tempfile.TemporaryDirectory() as tmp:
            response = handle_tool_call(
                "req-2",
                {
                    "name": "orchestrator_headless_status",
                    "arguments": {"project_root": str(Path(tmp))},
                },
            )
            content = response["result"]["content"][0]["text"]
            payload = json.loads(content)
            self.assertTrue(payload["ok"])
            self.assertEqual(str(Path(tmp)), payload["project_root"])
            self.assertIn("processes", payload)

    def test_handle_tool_call_headless_restart_and_clean_return_payload(self) -> None:
        from orchestrator_mcp_server import handle_tool_call

        with tempfile.TemporaryDirectory() as tmp:
            for tool_name in ("orchestrator_headless_restart", "orchestrator_headless_clean"):
                action = tool_name.replace("orchestrator_headless_", "")
                with patch("orchestrator_mcp_server._run_supervisor_action") as mock_action:
                    mock_action.return_value = {
                        "ok": True,
                        "action": action,
                        "project_root": str(Path(tmp)),
                        "leader_agent": "codex",
                        "processes": [],
                    }
                    response = handle_tool_call(
                        f"req-{tool_name}",
                        {
                            "name": tool_name,
                            "arguments": {"project_root": str(Path(tmp))},
                        },
                    )
                content = response["result"]["content"][0]["text"]
                payload = json.loads(content)
                self.assertTrue(payload["ok"])
                self.assertEqual(action, payload["action"])
                self.assertEqual(str(Path(tmp)), payload["project_root"])

    def test_select_root_dir_prefers_explicit_env(self) -> None:
        from orchestrator_mcp_server import _select_root_dir

        with tempfile.TemporaryDirectory() as tmp:
            root = _select_root_dir(
                orchestrator_root_raw=tmp,
                startup_cwd=Path("/tmp"),
                script_dir=Path("/opt/shared/agent-leader/current"),
            )
            self.assertEqual(Path(tmp).resolve(), root)

    def test_select_root_dir_uses_project_cwd_when_no_env(self) -> None:
        from orchestrator_mcp_server import _select_root_dir

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "orchestrator").mkdir()
            (d / "orchestrator_mcp_server.py").write_text("# stub\n", encoding="utf-8")
            (d / "project.yaml").write_text("name: test\n", encoding="utf-8")
            root = _select_root_dir(
                orchestrator_root_raw="",
                startup_cwd=d,
                script_dir=Path("/opt/shared/agent-leader/current"),
            )
            self.assertEqual(d.resolve(), root)

    def test_select_root_dir_rejects_temp_cwd_without_project_markers(self) -> None:
        from orchestrator_mcp_server import _select_root_dir

        with tempfile.TemporaryDirectory() as tmp:
            startup = Path(tmp)
            script_dir = Path("/opt/shared/agent-leader/current")
            root = _select_root_dir(
                orchestrator_root_raw="",
                startup_cwd=startup,
                script_dir=script_dir,
            )
            self.assertEqual(script_dir.resolve(), root)

    @patch("orchestrator_mcp_server.ORCH")
    def test_instance_id_propagated_to_register_agent(self, mock_orch) -> None:
        from orchestrator_mcp_server import handle_tool_call

        with patch("orchestrator_mcp_server._ORCHESTRATOR_INSTANCE_ID", "test_agent#headless-default-register"):
            tool_call = {
                "name": "orchestrator_register_agent",
                "arguments": {
                    "agent": "test_agent",
                    "metadata": {"client": "test_client"},
                },
            }

            mock_orch.register_agent.return_value = {}

            handle_tool_call("req-1", tool_call)

            mock_orch.register_agent.assert_called_once()
            args, kwargs = mock_orch.register_agent.call_args
            self.assertIn("metadata", kwargs)
            metadata = kwargs["metadata"]
            self.assertIn("instance_id", metadata)
            self.assertEqual(metadata["instance_id"], "test_agent#headless-default-register")
            self.assertNotEqual(metadata["instance_id"], "")

    @patch("orchestrator_mcp_server.ORCH")
    def test_instance_id_propagated_to_heartbeat(self, mock_orch) -> None:
        from orchestrator_mcp_server import handle_tool_call

        with patch("orchestrator_mcp_server._ORCHESTRATOR_INSTANCE_ID", "test_agent#headless-default-heartbeat"):
            tool_call = {
                "name": "orchestrator_heartbeat",
                "arguments": {
                    "agent": "test_agent",
                    "metadata": {"client": "test_client"},
                },
            }

            mock_orch.heartbeat.return_value = {}

            handle_tool_call("req-1", tool_call)

            mock_orch.heartbeat.assert_called_once()
            args, kwargs = mock_orch.heartbeat.call_args
            self.assertIn("metadata", kwargs)
            metadata = kwargs["metadata"]
            self.assertIn("instance_id", metadata)
            self.assertEqual(metadata["instance_id"], "test_agent#headless-default-heartbeat")
            self.assertNotEqual(metadata["instance_id"], "")



if __name__ == "__main__":
    unittest.main()
