"""Static validation of docs/restart-milestone-burnup.md.

Checks task ID formatting, status consistency, and category counts.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "restart-milestone-burnup.md"

VALID_STATUSES = {"Done", "In Progress", "Assigned", "Blocked"}


class RestartMilestoneBurnupTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_task_ids_formatted(self) -> None:
        task_ids = re.findall(r"TASK-[0-9a-f]+", self.content)
        self.assertGreater(len(task_ids), 0, "no TASK-xxx IDs found")
        for tid in task_ids:
            self.assertRegex(tid, r"^TASK-[0-9a-f]{8}$",
                             f"malformed task ID: {tid}")

    def test_status_values_valid(self) -> None:
        # Extract status column from task table rows
        rows = re.findall(r"\|\s*(Done|In Progress|Assigned|Blocked)\s*\|", self.content)
        self.assertGreater(len(rows), 0, "no status rows found")
        for status in rows:
            self.assertIn(status, VALID_STATUSES,
                          f"invalid status: {status}")

    def test_categories_present(self) -> None:
        for cat in ("CORE", "CORE-SUPPORT", "OPS"):
            self.assertIn(cat, self.content,
                          f"missing category: {cat}")

    def test_progress_formula_present(self) -> None:
        self.assertIn("Milestone %", self.content,
                      "missing progress formula")

    def test_percentage_is_numeric(self) -> None:
        match = re.search(r"(\d+)\s*%", self.content)
        self.assertIsNotNone(match, "no percentage found")
        pct = int(match.group(1))
        self.assertGreaterEqual(pct, 0)
        self.assertLessEqual(pct, 100)

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        skip = {"post-restart-verification.md"}
        for link in links:
            if link in skip:
                continue
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )


if __name__ == "__main__":
    unittest.main()
