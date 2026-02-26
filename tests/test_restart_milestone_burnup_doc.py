"""Static validation of docs/restart-milestone-burnup.md.

Checks task IDs (real hex IDs), status values, category names,
summary table structure, progress formula, and completion criteria.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "restart-milestone-burnup.md"
DOCS_DIR = REPO_ROOT / "docs"

VALID_STATUSES = {"Done", "In Progress", "Assigned"}
VALID_CATEGORIES = {"CORE", "CORE-SUPPORT", "OPS"}
SUMMARY_COLUMNS = {"Category", "Done", "In Progress", "Assigned", "Total"}


class RestartMilestoneBurnupDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_task_ids_are_real_hex(self) -> None:
        """Task IDs must be TASK-{hex} with at least 6 hex chars (real IDs)."""
        task_ids = re.findall(r"TASK-([0-9a-fA-F]+)", self.content)
        self.assertGreaterEqual(len(task_ids), 5, "expected at least 5 real task IDs")
        for tid in task_ids:
            self.assertGreaterEqual(
                len(tid), 6,
                f"task ID suffix too short for real ID: TASK-{tid}",
            )
            self.assertRegex(
                tid, r"^[0-9a-fA-F]+$",
                f"task ID suffix is not hex: TASK-{tid}",
            )

    def test_status_values_valid(self) -> None:
        """Status column values in task tables must be Done/In Progress/Assigned."""
        # Match status cells: lines starting with "| Status |" are headers;
        # data rows have status as first cell after the pipe.
        status_matches = re.findall(
            r"^\|\s*(Done|In Progress|Assigned)\s*\|",
            self.content, re.MULTILINE,
        )
        self.assertGreaterEqual(len(status_matches), 5, "too few status values found")
        for status in status_matches:
            self.assertIn(
                status, VALID_STATUSES,
                f"invalid status value: {status}",
            )

    def test_category_names_valid(self) -> None:
        """Category section headers must use known category names."""
        for category in VALID_CATEGORIES:
            self.assertIn(
                category, self.content,
                f"missing category: {category}",
            )

    def test_summary_table_columns(self) -> None:
        """Summary table must have the correct column headers."""
        # Find the summary table header row
        table_headers = re.findall(
            r"^\|(.+)\|$", self.content, re.MULTILINE,
        )
        found_summary = False
        for header_line in table_headers:
            cells = {c.strip() for c in header_line.split("|") if c.strip()}
            if SUMMARY_COLUMNS.issubset(cells):
                found_summary = True
                break
        self.assertTrue(
            found_summary,
            f"summary table missing required columns: {SUMMARY_COLUMNS}",
        )

    def test_progress_formula_section_exists(self) -> None:
        self.assertIn(
            "Progress Formula", self.content,
            "missing 'Progress Formula' section",
        )

    def test_milestone_completion_criteria_section_exists(self) -> None:
        self.assertIn(
            "Milestone Completion Criteria", self.content,
            "missing 'Milestone Completion Criteria' section",
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
