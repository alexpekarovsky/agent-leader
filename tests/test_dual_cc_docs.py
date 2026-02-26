"""Static validation of dual-CC convention and operation docs.

Checks CC1/CC2 label consistency, report note prefix format,
referenced doc links, and code example syntax.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
CONVENTIONS = DOCS_DIR / "dual-cc-conventions.md"
OPERATION = DOCS_DIR / "dual-cc-operation.md"


class DualCCConventionsDocTests(unittest.TestCase):
    """Validate dual-cc-conventions.md content."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = CONVENTIONS.read_text(encoding="utf-8")

    def test_doc_exists(self) -> None:
        self.assertTrue(CONVENTIONS.exists())

    def test_cc1_cc2_labels_documented(self) -> None:
        self.assertIn("CC1", self.content)
        self.assertIn("CC2", self.content)

    def test_report_note_prefix_format(self) -> None:
        """Report note examples should use [CC1] / [CC2] bracket format."""
        self.assertIn("[CC1]", self.content)
        self.assertIn("[CC2]", self.content)

    def test_workstream_labels_documented(self) -> None:
        self.assertIn("CC-backend", self.content)

    def test_claim_override_example_present(self) -> None:
        self.assertIn("set_claim_override", self.content)

    def test_operator_checklist_present(self) -> None:
        self.assertIn("Operator Checklist", self.content)
        # Checklist items use markdown checkboxes
        checkboxes = re.findall(r"- \[ \]", self.content)
        self.assertGreaterEqual(len(checkboxes), 3, "expected at least 3 checklist items")

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        for link in links:
            path = DOCS_DIR / link
            self.assertTrue(path.exists(), f"link to {link} does not resolve")

    def test_no_duplicate_headers(self) -> None:
        headers = re.findall(r"^## (.+)$", self.content, re.MULTILINE)
        self.assertEqual(len(headers), len(set(headers)))


class DualCCOperationDocTests(unittest.TestCase):
    """Validate dual-cc-operation.md content."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = OPERATION.read_text(encoding="utf-8")

    def test_doc_exists(self) -> None:
        self.assertTrue(OPERATION.exists())

    def test_documents_core_limitation(self) -> None:
        self.assertIn("instance_id", self.content)
        self.assertIn("claude_code", self.content)

    def test_documents_workflow_options(self) -> None:
        self.assertIn("Option A", self.content)
        self.assertIn("Option B", self.content)

    def test_collision_avoidance_section(self) -> None:
        self.assertIn("Collision Avoidance", self.content)

    def test_references_swarm_mode(self) -> None:
        self.assertIn("swarm-mode.md", self.content)

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        for link in links:
            path = DOCS_DIR / link
            self.assertTrue(path.exists(), f"link to {link} does not resolve")


if __name__ == "__main__":
    unittest.main()
