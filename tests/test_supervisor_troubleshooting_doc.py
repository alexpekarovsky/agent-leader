"""Static validation of docs/supervisor-troubleshooting.md.

Checks command syntax, script name references, and doc links.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-troubleshooting.md"

VALID_ACTIONS = {"start", "stop", "status", "restart", "clean"}
KNOWN_SCRIPTS = {
    "supervisor.sh", "manager_loop.sh", "worker_loop.sh",
    "watchdog_loop.sh", "monitor_loop.sh", "team_tmux.sh",
    "smoke_test.sh", "log_check.sh", "common.sh",
}


class SupervisorTroubleshootingDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        blocks = re.findall(r"```(?:bash)?\\n(.*?)```", cls.content, re.DOTALL)
        cls.all_code = "\n".join(blocks)

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_supervisor_commands_valid(self) -> None:
        actions = re.findall(r"supervisor\.sh\s+(\w+)", self.content)
        for action in actions:
            self.assertIn(action, VALID_ACTIONS,
                          f"unknown supervisor action: {action}")

    def test_script_references_known(self) -> None:
        # Find referenced .sh scripts
        scripts = re.findall(r"([\w_]+\.sh)", self.content)
        for script in scripts:
            self.assertIn(script, KNOWN_SCRIPTS,
                          f"unknown script reference: {script}")

    def test_symptom_sections_present(self) -> None:
        symptom_count = len(re.findall(r"^## ", self.content, re.MULTILINE))
        self.assertGreaterEqual(symptom_count, 4,
                                "fewer than 4 troubleshooting sections")

    def test_process_names_referenced(self) -> None:
        for name in ("manager", "claude", "gemini", "watchdog"):
            self.assertIn(name, self.content,
                          f"missing process reference: {name}")

    def test_cleanup_section_present(self) -> None:
        self.assertTrue(
            any("cleanup" in line.lower() or "reset" in line.lower()
                for line in self.content.splitlines()),
            "missing cleanup/reset section",
        )

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        skip = {"supervisor-process-model.md", "incident-triage-order.md"}
        for link in links:
            if link in skip:
                continue
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )


if __name__ == "__main__":
    unittest.main()
