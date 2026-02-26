"""Static validation of docs/milestone-communication-template.md.

Checks required headings, percentage fields, and task/blocker sections.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "milestone-communication-template.md"


class MilestoneCommunicationTemplateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_required_template_headings(self) -> None:
        for heading in ("Overall Progress", "Category Breakdown",
                        "Tasks Completed", "Blockers", "Next Actions"):
            self.assertTrue(
                any(heading.lower() in line.lower()
                    for line in self.content.splitlines()),
                f"missing template heading: {heading}",
            )

    def test_percentage_fields_present(self) -> None:
        self.assertIn("PERCENT", self.content,
                      "missing [PERCENT] placeholder")
        self.assertIn("Milestone %", self.content,
                      "missing Milestone % formula")

    def test_category_labels(self) -> None:
        for cat in ("CORE", "CORE-SUPPORT", "OPS"):
            self.assertIn(cat, self.content,
                          f"missing category label: {cat}")

    def test_example_section_present(self) -> None:
        self.assertIn("Example", self.content,
                      "missing example section")

    def test_task_id_format_in_example(self) -> None:
        task_ids = re.findall(r"TASK-[0-9a-f]+", self.content)
        self.assertGreater(len(task_ids), 0,
                           "no task IDs in example")

    def test_blocker_section_format(self) -> None:
        # Should have checkbox format for blockers
        self.assertTrue(
            "- [ ]" in self.content or "(none)" in self.content,
            "blocker section missing checkbox or (none) marker",
        )

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
