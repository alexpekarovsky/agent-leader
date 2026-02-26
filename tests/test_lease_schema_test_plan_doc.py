"""Static validation of docs/lease-schema-test-plan.md.

Checks lease field names, test case presence (T1-T8), AUTO-M1 task
references, state transitions, configuration parameters, and doc links.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "lease-schema-test-plan.md"
DOCS_DIR = REPO_ROOT / "docs"

REQUIRED_LEASE_FIELDS = [
    "lease_id",
    "task_id",
    "owner_instance_id",
    "claimed_at",
    "expires_at",
    "renewed_at",
    "heartbeat_interval_seconds",
    "attempt_index",
]
REQUIRED_TEST_CASES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
REQUIRED_AUTO_M1_REFS = [
    "AUTO-M1-CORE-03",
    "AUTO-M1-CORE-04",
    "AUTO-M1-CORE-01",
]
REQUIRED_STATE_TRANSITIONS = [
    "assigned",
    "in_progress",
    "reported",
    "done",
    "blocked",
]
REQUIRED_CONFIG_PARAMS = [
    "lease_ttl_seconds",
    "heartbeat_interval_seconds",
    "max_retries",
]


class LeaseSchemaTestPlanDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_lease_fields_are_snake_case(self) -> None:
        """All required lease field names must appear and be snake_case."""
        for field in REQUIRED_LEASE_FIELDS:
            self.assertIn(
                field, self.content,
                f"missing lease field: {field}",
            )
            self.assertRegex(
                field, r"^[a-z][a-z0-9_]*$",
                f"lease field is not snake_case: {field}",
            )

    def test_all_test_cases_present(self) -> None:
        """Test cases T1 through T8 must all be defined."""
        for tc in REQUIRED_TEST_CASES:
            self.assertRegex(
                self.content,
                rf"###\s+{tc}:",
                f"missing test case: {tc}",
            )

    def test_auto_m1_task_references_present(self) -> None:
        """AUTO-M1 task references must appear."""
        for ref in REQUIRED_AUTO_M1_REFS:
            self.assertIn(
                ref, self.content,
                f"missing AUTO-M1 reference: {ref}",
            )

    def test_task_state_transitions_documented(self) -> None:
        """All expected task states must be mentioned."""
        for state in REQUIRED_STATE_TRANSITIONS:
            self.assertIn(
                state, self.content,
                f"missing task state: {state}",
            )

    def test_configuration_parameters_present(self) -> None:
        """Configuration parameters must be documented."""
        for param in REQUIRED_CONFIG_PARAMS:
            self.assertIn(
                param, self.content,
                f"missing configuration parameter: {param}",
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
