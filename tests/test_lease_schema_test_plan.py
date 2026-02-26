"""Static validation of docs/lease-schema-test-plan.md.

Checks lease field names, task references, and roadmap terminology.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "lease-schema-test-plan.md"

EXPECTED_LEASE_FIELDS = {
    "lease_id", "task_id", "owner_instance_id",
    "claimed_at", "expires_at", "renewed_at",
    "heartbeat_interval_seconds", "attempt_index",
}

EXPECTED_CONFIG_PARAMS = {
    "lease_ttl_seconds", "heartbeat_interval_seconds", "max_retries",
}


class LeaseSchemaTestPlanTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_lease_fields_documented(self) -> None:
        for field in EXPECTED_LEASE_FIELDS:
            self.assertIn(field, self.content,
                          f"missing lease field: {field}")

    def test_config_params_documented(self) -> None:
        for param in EXPECTED_CONFIG_PARAMS:
            self.assertIn(param, self.content,
                          f"missing config param: {param}")

    def test_auto_m1_core_references(self) -> None:
        for ref in ("AUTO-M1-CORE-03", "AUTO-M1-CORE-04"):
            self.assertIn(ref, self.content,
                          f"missing task reference: {ref}")

    def test_test_cases_numbered(self) -> None:
        test_ids = re.findall(r"###\s+T(\d+):", self.content)
        self.assertGreaterEqual(len(test_ids), 5,
                                "fewer than 5 test cases")
        # Verify sequential numbering
        nums = [int(x) for x in test_ids]
        self.assertEqual(nums, list(range(1, len(nums) + 1)),
                         "test case numbering is not sequential")

    def test_task_state_transitions_documented(self) -> None:
        for state in ("assigned", "in_progress", "reported", "done", "blocked"):
            self.assertIn(state, self.content,
                          f"missing task state: {state}")

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        skip = {"current-limitations-matrix.md"}
        for link in links:
            if link in skip:
                continue
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )


if __name__ == "__main__":
    unittest.main()
