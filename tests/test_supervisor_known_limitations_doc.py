"""Static validation of docs/supervisor-known-limitations.md.

Checks that limitation sections reference correct AUTO-M1 core task IDs,
key terms align with roadmap terminology, and doc links resolve.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-known-limitations.md"
DOCS_DIR = REPO_ROOT / "docs"

EXPECTED_CORE_REFS = [
    "AUTO-M1-CORE-01",
    "AUTO-M1-CORE-03",
    "AUTO-M1-CORE-04",
    "AUTO-M1-CORE-05",
]

EXPECTED_LIMITATION_SECTIONS = [
    "No auto-restart on crash",
    "No per-process restart",
    "No task lease recovery",
    "No dispatch acknowledgment",
    "No instance-aware identity",
    "No PID reuse detection",
]

EXPECTED_RESPONSIBILITY_OWNERS = [
    "Supervisor",
    "Orchestrator engine",
    "Watchdog",
    "Manager cycle",
]


class SupervisorKnownLimitationsDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_auto_m1_core_references(self) -> None:
        for ref in EXPECTED_CORE_REFS:
            self.assertIn(ref, self.content, f"missing core task ref: {ref}")

    def test_limitation_sections_present(self) -> None:
        for section in EXPECTED_LIMITATION_SECTIONS:
            self.assertIn(section, self.content, f"missing limitation: {section}")

    def test_workaround_and_fix_planned_per_limitation(self) -> None:
        """Each limitation subsection should have Workaround and Fix planned."""
        subsections = re.split(r"^### ", self.content, flags=re.MULTILINE)[1:]
        for sub in subsections:
            title = sub.split("\n")[0].strip()
            self.assertIn("Workaround", sub, f"'{title}' missing Workaround")
            self.assertIn("Fix planned", sub, f"'{title}' missing Fix planned")

    def test_responsibility_boundary_table(self) -> None:
        self.assertIn("Responsibility boundary", self.content)
        for owner in EXPECTED_RESPONSIBILITY_OWNERS:
            self.assertIn(owner, self.content, f"missing responsibility owner: {owner}")

    def test_supervisor_commands_referenced(self) -> None:
        self.assertIn("supervisor.sh", self.content)

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


if __name__ == "__main__":
    unittest.main()
