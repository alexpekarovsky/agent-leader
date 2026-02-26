"""Static validation of docs/restart-milestone-checklist.md.

Checks task IDs, supervisor commands, orchestrator API references,
doc links, section headers, and script references.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "restart-milestone-checklist.md"
DOCS_DIR = REPO_ROOT / "docs"

VALID_SUPERVISOR_ACTIONS = {"start", "stop", "status", "restart", "clean"}
VALID_ORCHESTRATOR_APIS = {
    "orchestrator_status",
    "orchestrator_list_tasks",
    "reassign_stale_tasks",
}
REQUIRED_SECTIONS = {
    "Pre-Restart Checklist",
    "Restart Procedure",
    "Post-Restart Validation Steps",
    "Smoke Test",
}
REQUIRED_SCRIPTS = [
    "scripts/autopilot/supervisor.sh",
    "scripts/autopilot/team_tmux.sh",
    "scripts/autopilot/smoke_test.sh",
    "scripts/autopilot/log_check.sh",
]


class RestartMilestoneChecklistDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_task_ids_follow_pattern(self) -> None:
        """Task IDs must match TASK-{hex} with at least 3 hex chars."""
        task_ids = re.findall(r"TASK-([0-9a-fA-F]+)", self.content)
        self.assertGreaterEqual(len(task_ids), 1, "no task IDs found")
        for tid in task_ids:
            self.assertGreaterEqual(
                len(tid), 3,
                f"task ID suffix too short: TASK-{tid}",
            )
            self.assertRegex(
                tid, r"^[0-9a-fA-F]+$",
                f"task ID suffix is not hex: TASK-{tid}",
            )

    def test_supervisor_commands_valid(self) -> None:
        """Supervisor action arguments must be start/stop/status/restart/clean."""
        actions = re.findall(r"supervisor\.sh\s+(\w+)", self.content)
        self.assertGreaterEqual(len(actions), 1, "no supervisor commands found")
        for action in actions:
            self.assertIn(
                action, VALID_SUPERVISOR_ACTIONS,
                f"unknown supervisor action: {action}",
            )

    def test_orchestrator_api_references_valid(self) -> None:
        """orchestrator API calls in the doc must be known functions."""
        api_calls = re.findall(r"(orchestrator_\w+|reassign_stale_tasks)\s*\(", self.content)
        self.assertGreaterEqual(len(api_calls), 1, "no orchestrator API refs found")
        for api in api_calls:
            self.assertIn(
                api, VALID_ORCHESTRATOR_APIS,
                f"unknown orchestrator API reference: {api}",
            )

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        for link in links:
            target = DOCS_DIR / link
            self.assertTrue(target.exists(), f"link to {link} does not resolve")

    def test_no_duplicate_headers(self) -> None:
        headers = re.findall(r"^## (.+)$", self.content, re.MULTILINE)
        seen: set[str] = set()
        for h in headers:
            self.assertNotIn(h, seen, f"duplicate header: '{h}'")
            seen.add(h)

    def test_key_sections_present(self) -> None:
        headers = re.findall(r"^##+ (.+)$", self.content, re.MULTILINE)
        header_set = set(headers)
        for section in REQUIRED_SECTIONS:
            self.assertTrue(
                any(section in h for h in header_set),
                f"missing required section: '{section}'",
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


if __name__ == "__main__":
    unittest.main()
