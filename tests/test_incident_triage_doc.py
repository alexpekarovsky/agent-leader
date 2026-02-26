"""Static validation of docs/incident-triage-order.md.

Checks sequential step numbering, supervisor commands, orchestrator
API references, script references, decision tree, and failure classes.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "incident-triage-order.md"
DOCS_DIR = REPO_ROOT / "docs"

VALID_SUPERVISOR_ACTIONS = {"start", "stop", "status", "restart", "clean"}
VALID_ORCHESTRATOR_APIS = {
    "orchestrator_status",
    "orchestrator_list_tasks",
}
REQUIRED_SCRIPTS = [
    "scripts/autopilot/supervisor.sh",
    "scripts/autopilot/log_check.sh",
]
REQUIRED_FAILURE_CLASSES = [
    "Timeout",
    "Scope mismatch",
    "Stale task accumulation",
    "State corruption",
]


class IncidentTriageDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_steps_numbered_sequentially(self) -> None:
        """Steps must be numbered Step 1 through Step 6."""
        for i in range(1, 7):
            self.assertIn(
                f"Step {i}",
                self.content,
                f"missing Step {i} in triage order",
            )

    def test_supervisor_commands_valid(self) -> None:
        """Supervisor action arguments must be known commands."""
        actions = re.findall(r"supervisor\.sh\s+(\w+)", self.content)
        self.assertGreaterEqual(len(actions), 1, "no supervisor commands found")
        for action in actions:
            self.assertIn(
                action, VALID_SUPERVISOR_ACTIONS,
                f"unknown supervisor action: {action}",
            )

    def test_orchestrator_api_references_valid(self) -> None:
        """orchestrator API calls in the doc must be known functions."""
        api_calls = re.findall(r"(orchestrator_\w+)\s*\(", self.content)
        self.assertGreaterEqual(len(api_calls), 1, "no orchestrator API refs found")
        for api in api_calls:
            self.assertIn(
                api, VALID_ORCHESTRATOR_APIS,
                f"unknown orchestrator API reference: {api}",
            )

    def test_script_references_exist(self) -> None:
        for script_path in REQUIRED_SCRIPTS:
            self.assertIn(
                script_path, self.content,
                f"script not referenced in doc: {script_path}",
            )
            full_path = REPO_ROOT / script_path
            self.assertTrue(
                full_path.exists(),
                f"referenced script does not exist: {script_path}",
            )

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        for link in links:
            target = DOCS_DIR / link
            self.assertTrue(target.exists(), f"link to {link} does not resolve")

    def test_quick_decision_tree_present(self) -> None:
        self.assertIn(
            "Quick Decision Tree", self.content,
            "missing 'Quick Decision Tree' section",
        )

    def test_common_failure_classes_present(self) -> None:
        self.assertIn(
            "Common Failure Classes", self.content,
            "missing 'Common Failure Classes' section",
        )

    def test_key_failure_classes(self) -> None:
        """Each documented failure class must appear in the doc."""
        for failure_class in REQUIRED_FAILURE_CLASSES:
            self.assertIn(
                failure_class, self.content,
                f"missing failure class: '{failure_class}'",
            )


if __name__ == "__main__":
    unittest.main()
