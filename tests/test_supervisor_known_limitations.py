"""Static validation of docs/supervisor-known-limitations.md.

Checks AUTO-M1 task references, key terms, and doc link resolution.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-known-limitations.md"


class SupervisorKnownLimitationsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_auto_m1_core_references(self) -> None:
        for ref in ("AUTO-M1-CORE-01", "AUTO-M1-CORE-03",
                     "AUTO-M1-CORE-04", "AUTO-M1-CORE-05"):
            self.assertIn(ref, self.content,
                          f"missing core task reference: {ref}")

    def test_key_limitation_terms(self) -> None:
        for term in ("auto-restart", "task lease", "dispatch",
                     "instance", "PID"):
            self.assertTrue(
                any(term.lower() in line.lower()
                    for line in self.content.splitlines()),
                f"missing limitation term: {term}",
            )

    def test_workaround_sections(self) -> None:
        workarounds = re.findall(r"\*\*Workaround", self.content)
        self.assertGreaterEqual(len(workarounds), 3,
                                "fewer than 3 workaround sections")

    def test_fix_planned_sections(self) -> None:
        fixes = re.findall(r"\*\*Fix planned", self.content)
        self.assertGreaterEqual(len(fixes), 3,
                                "fewer than 3 fix planned sections")

    def test_responsibility_boundary_table(self) -> None:
        self.assertIn("Responsibility boundary", self.content,
                      "missing responsibility boundary section")
        for owner in ("Supervisor", "Orchestrator"):
            self.assertIn(owner, self.content,
                          f"missing boundary owner: {owner}")

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        for link in links:
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )


if __name__ == "__main__":
    unittest.main()
