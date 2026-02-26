"""Static validation of docs/supervisor-pidfile-format.md.

Checks pidfile naming examples, command references, and doc links.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-pidfile-format.md"

EXPECTED_PROCESS_NAMES = {"manager", "claude", "gemini", "watchdog"}
EXPECTED_FILE_TYPES = {".pid", ".restarts"}
VALID_ACTIONS = {"start", "stop", "status", "restart", "clean"}


class SupervisorPidfileFormatTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        blocks = re.findall(r"```(?:bash)?\\n(.*?)```", cls.content, re.DOTALL)
        cls.all_code = "\n".join(blocks)

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_process_names_documented(self) -> None:
        for name in EXPECTED_PROCESS_NAMES:
            self.assertIn(f"{name}.pid", self.content,
                          f"missing pidfile reference: {name}.pid")
            self.assertIn(f"{name}.restarts", self.content,
                          f"missing restarts reference: {name}.restarts")

    def test_file_location_documented(self) -> None:
        self.assertIn(".autopilot-pids", self.content,
                      "missing .autopilot-pids reference")

    def test_supervisor_commands_valid(self) -> None:
        actions = re.findall(r"supervisor\.sh\s+(\w+)", self.content)
        for action in actions:
            self.assertIn(action, VALID_ACTIONS,
                          f"unknown supervisor action: {action}")

    def test_stale_pid_section(self) -> None:
        self.assertTrue(
            any("stale" in line.lower() for line in self.content.splitlines()),
            "missing stale PID handling section",
        )

    def test_kill_zero_detection(self) -> None:
        self.assertIn("kill -0", self.content,
                      "missing kill -0 detection reference")

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        skip = {"supervisor-startup-profiles.md"}
        for link in links:
            if link in skip:
                continue
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )


if __name__ == "__main__":
    unittest.main()
