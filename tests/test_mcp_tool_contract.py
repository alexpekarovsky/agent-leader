"""MCP Tool Contract Tests.

Validates that the MCP server's tool definitions match the frozen contract
in tools.json. Any schema change without a contract_version bump will fail
these tests, enforcing intentional, versioned API evolution.

References: TASK-30600c9c
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TOOLS_JSON = PROJECT_ROOT / "tools.json"


def _load_contract() -> dict:
    """Load the frozen tools.json contract."""
    assert TOOLS_JSON.exists(), f"Contract file missing: {TOOLS_JSON}"
    return json.loads(TOOLS_JSON.read_text(encoding="utf-8"))


def _load_live_tools() -> list[dict]:
    """Extract current tool definitions from the MCP server."""
    from orchestrator_mcp_server import handle_tools_list

    result = handle_tools_list("contract-test")
    return result["result"]["tools"]


class TestToolContractIntegrity(unittest.TestCase):
    """tools.json must exist, parse correctly, and have required structure."""

    def test_contract_file_exists(self) -> None:
        self.assertTrue(TOOLS_JSON.exists(), "tools.json must exist at project root")

    def test_contract_has_version(self) -> None:
        contract = _load_contract()
        self.assertIn("contract_version", contract)
        parts = contract["contract_version"].split(".")
        self.assertEqual(3, len(parts), "contract_version must be semver (X.Y.Z)")

    def test_contract_has_tools(self) -> None:
        contract = _load_contract()
        self.assertIn("tools", contract)
        self.assertIsInstance(contract["tools"], dict)
        self.assertGreater(len(contract["tools"]), 0)

    def test_contract_tool_count_matches(self) -> None:
        contract = _load_contract()
        self.assertEqual(
            contract["tool_count"],
            len(contract["tools"]),
            "tool_count field must match actual number of tools in contract",
        )


class TestToolNamesMatch(unittest.TestCase):
    """Every tool in the live server must appear in the contract, and vice versa."""

    def test_no_missing_tools_in_contract(self) -> None:
        """Fail if the server exposes a tool not in tools.json."""
        contract = _load_contract()
        live_tools = _load_live_tools()
        live_names = {t["name"] for t in live_tools}
        contract_names = set(contract["tools"].keys())
        added = live_names - contract_names
        self.assertEqual(
            set(),
            added,
            f"New tools added without contract update: {sorted(added)}. "
            f"Regenerate tools.json and bump contract_version.",
        )

    def test_no_removed_tools_from_contract(self) -> None:
        """Fail if a tool in tools.json no longer exists in the server."""
        contract = _load_contract()
        live_tools = _load_live_tools()
        live_names = {t["name"] for t in live_tools}
        contract_names = set(contract["tools"].keys())
        removed = contract_names - live_names
        self.assertEqual(
            set(),
            removed,
            f"Tools removed without contract update: {sorted(removed)}. "
            f"Update tools.json and bump contract_version.",
        )

    def test_tool_count_matches_server(self) -> None:
        live_tools = _load_live_tools()
        contract = _load_contract()
        self.assertEqual(
            len(live_tools),
            len(contract["tools"]),
            "Live server tool count must match contract tool count.",
        )


class TestToolSchemasMatch(unittest.TestCase):
    """Every tool's inputSchema must match the frozen contract exactly."""

    def test_input_schemas_unchanged(self) -> None:
        contract = _load_contract()
        live_tools = _load_live_tools()

        mismatches = []
        for tool in live_tools:
            name = tool["name"]
            if name not in contract["tools"]:
                continue  # Covered by TestToolNamesMatch

            expected_schema = contract["tools"][name]["inputSchema"]
            actual_schema = tool["inputSchema"]

            if actual_schema != expected_schema:
                mismatches.append(name)

        self.assertEqual(
            [],
            mismatches,
            f"Input schema changed for tools: {mismatches}. "
            f"Update tools.json and bump contract_version.",
        )

    def test_descriptions_unchanged(self) -> None:
        contract = _load_contract()
        live_tools = _load_live_tools()

        mismatches = []
        for tool in live_tools:
            name = tool["name"]
            if name not in contract["tools"]:
                continue

            if tool["description"] != contract["tools"][name]["description"]:
                mismatches.append(name)

        self.assertEqual(
            [],
            mismatches,
            f"Description changed for tools: {mismatches}. "
            f"Update tools.json and bump contract_version.",
        )


class TestContractVersioning(unittest.TestCase):
    """Contract version must be valid semver."""

    def test_version_is_semver(self) -> None:
        contract = _load_contract()
        version = contract["contract_version"]
        parts = version.split(".")
        self.assertEqual(3, len(parts))
        for part in parts:
            self.assertTrue(part.isdigit(), f"Non-numeric semver component: {part}")


if __name__ == "__main__":
    unittest.main()
