"""Static validation of docs/restart-milestone-checklist.md.

Checks command snippets, task ID formatting, and doc link resolution.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "restart-milestone-checklist.md"

VALID_SUPERVISOR_ACTIONS = {"start", "stop", "status", "restart", "clean"}
VALID_SUPERVISOR_FLAGS = {
    "--project-root", "--log-dir", "--pid-dir",
    "--manager-cli-timeout", "--worker-cli-timeout",
    "--manager-interval", "--worker-interval",
    "--max-restarts", "--backoff-base", "--backoff-max",
    "--help",
}


class RestartMilestoneChecklistTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        blocks = re.findall(r"```(?:bash)?\\n(.*?)```", cls.content, re.DOTALL)
        cls.all_code = "\n".join(blocks)

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_task_ids_formatted_correctly(self) -> None:
        task_ids = re.findall(r"TASK-[0-9a-f]+", self.content)
        self.assertGreater(len(task_ids), 0, "no TASK-xxx IDs found")
        for tid in task_ids:
            self.assertRegex(tid, r"^TASK-[0-9a-f]{8}$",
                             f"malformed task ID: {tid}")

    def test_supervisor_commands_valid(self) -> None:
        actions = re.findall(r"supervisor\.sh\s+(\w+)", self.all_code)
        for action in actions:
            self.assertIn(action, VALID_SUPERVISOR_ACTIONS,
                          f"unknown supervisor action: {action}")

    def test_required_sections_present(self) -> None:
        for heading in ("Pre-Restart Checklist", "Restart Procedure",
                        "Post-Restart Validation"):
            self.assertIn(heading, self.content,
                          f"missing section: {heading}")

    def test_status_values_referenced(self) -> None:
        for status in ("in_progress", "assigned", "running", "stopped", "dead"):
            self.assertIn(status, self.content,
                          f"missing status reference: {status}")

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        skip = {"incident-triage-order.md", "current-limitations-matrix.md"}
        for link in links:
            if link in skip:
                continue
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )


if __name__ == "__main__":
    unittest.main()
