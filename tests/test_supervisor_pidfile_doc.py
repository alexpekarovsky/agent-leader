"""Static validation of docs/supervisor-pidfile-format.md.

Checks process names, file patterns, supervisor commands,
stale PID handling, PID reuse, and section structure.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-pidfile-format.md"
DOCS_DIR = REPO_ROOT / "docs"

VALID_SUPERVISOR_ACTIONS = {"start", "stop", "status", "restart", "clean"}
REQUIRED_PROCESS_NAMES = ["manager", "claude", "gemini", "watchdog"]
REQUIRED_FILE_PATTERNS = [".pid", ".restarts"]
REQUIRED_SECTIONS = [
    "File Location",
    "Naming Convention",
    "PID File Content",
    "Restart Counter Content",
    "Stale PID Handling",
]


class SupervisorPidfileDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_process_names_mentioned(self) -> None:
        """All expected process names must appear in the doc."""
        for name in REQUIRED_PROCESS_NAMES:
            self.assertIn(
                name, self.content,
                f"missing process name: {name}",
            )

    def test_file_patterns_mentioned(self) -> None:
        """File extension patterns .pid and .restarts must appear."""
        for pattern in REQUIRED_FILE_PATTERNS:
            self.assertIn(
                pattern, self.content,
                f"missing file pattern: {pattern}",
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

    def test_stale_pid_handling_section_present(self) -> None:
        self.assertIn(
            "Stale PID Handling", self.content,
            "missing 'Stale PID Handling' section",
        )

    def test_pid_reuse_section_present(self) -> None:
        self.assertTrue(
            "PID reuse" in self.content or "pid reuse" in self.content.lower(),
            "missing PID reuse discussion",
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


if __name__ == "__main__":
    unittest.main()
