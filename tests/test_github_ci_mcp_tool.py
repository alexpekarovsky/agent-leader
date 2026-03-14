from __future__ import annotations

import json
import unittest


class GithubCiMcpToolTests(unittest.TestCase):
    def test_tools_list_contains_github_ci_normalizer(self) -> None:
        from orchestrator_mcp_server import handle_tools_list

        result = handle_tools_list("req-1")
        names = {item["name"] for item in result["result"]["tools"]}
        self.assertIn("orchestrator_normalize_github_ci", names)

    def test_handle_tool_call_normalize_github_ci(self) -> None:
        from orchestrator_mcp_server import handle_tool_call

        response = handle_tool_call(
            "req-2",
            {
                "name": "orchestrator_normalize_github_ci",
                "arguments": {
                    "payload": {
                        "name": "backend-tests",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "abc123",
                    }
                },
            },
        )
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual("github", payload["provider"])
        self.assertEqual("passed", payload["state"])
        self.assertEqual("backend-tests", payload["name"])
        self.assertEqual("abc123", payload["sha"])

    def test_handle_tool_call_normalize_github_ci_accepts_json_string(self) -> None:
        from orchestrator_mcp_server import handle_tool_call

        response = handle_tool_call(
            "req-3",
            {
                "name": "orchestrator_normalize_github_ci",
                "arguments": {
                    "payload": '{"name":"lint","status":"in_progress","conclusion":null}'
                },
            },
        )
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual("running", payload["state"])
        self.assertEqual("lint", payload["name"])

    def test_handle_tool_call_normalize_github_ci_rejects_non_object(self) -> None:
        from orchestrator_mcp_server import handle_tool_call

        response = handle_tool_call(
            "req-4",
            {
                "name": "orchestrator_normalize_github_ci",
                "arguments": {"payload": []},
            },
        )
        self.assertIn("error", response)
        self.assertIn("payload must be an object", response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
