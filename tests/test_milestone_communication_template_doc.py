"""Static validation of docs/milestone-communication-template.md.

Checks template placeholders, required sections, category names,
example task IDs, update triggers, and doc links.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "milestone-communication-template.md"
DOCS_DIR = REPO_ROOT / "docs"

REQUIRED_PERCENT_FIELDS = ["[DONE]", "[TOTAL]", "[PERCENT]%"]
REQUIRED_TEMPLATE_SECTIONS = [
    "Overall Progress",
    "Category Breakdown",
    "Tasks Completed This Cycle",
    "Currently In Progress",
    "Blockers",
    "Next Actions",
    "Notes",
]
VALID_CATEGORIES = {"CORE", "CORE-SUPPORT", "OPS"}


class MilestoneCommunicationTemplateDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_required_percent_fields(self) -> None:
        """Template must contain [DONE], [TOTAL], [PERCENT]% placeholders."""
        for field in REQUIRED_PERCENT_FIELDS:
            self.assertIn(
                field, self.content,
                f"missing template field: {field}",
            )

    def test_template_sections_present(self) -> None:
        """All required template sections must appear."""
        for section in REQUIRED_TEMPLATE_SECTIONS:
            self.assertIn(
                section, self.content,
                f"missing template section: '{section}'",
            )

    def test_category_names_valid(self) -> None:
        """Category names CORE, CORE-SUPPORT, OPS must all appear."""
        for category in VALID_CATEGORIES:
            self.assertIn(
                category, self.content,
                f"missing category: {category}",
            )

    def test_example_section_contains_real_task_ids(self) -> None:
        """Example section must contain real TASK-{hex} IDs."""
        # The example is inside a code block, so split by top-level ## headers
        # outside of code fences to isolate the example section content.
        idx = self.content.find("## Example")
        self.assertNotEqual(idx, -1, "no Example section found")
        example_text = self.content[idx:]
        # Find TASK IDs in the example section (including code blocks)
        task_ids = re.findall(r"TASK-([0-9a-fA-F]+)", example_text)
        self.assertGreaterEqual(
            len(task_ids), 1,
            "example section has no real task IDs",
        )
        for tid in task_ids:
            self.assertGreaterEqual(
                len(tid), 6,
                f"example task ID too short: TASK-{tid}",
            )

    def test_when_to_send_updates_section_present(self) -> None:
        self.assertIn(
            "When to Send Updates", self.content,
            "missing 'When to Send Updates' section",
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


if __name__ == "__main__":
    unittest.main()
