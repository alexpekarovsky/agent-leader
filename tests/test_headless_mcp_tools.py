from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import json


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


if __name__ == "__main__":
    unittest.main()
