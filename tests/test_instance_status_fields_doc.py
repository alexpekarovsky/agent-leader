"""Static validation of docs/instance-aware-status-fields.md.

Checks that field names follow snake_case convention, sample row keys
match the documented field table, status values are consistent, and
doc links resolve.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "instance-aware-status-fields.md"
DOCS_DIR = REPO_ROOT / "docs"

# Canonical field names from the status fields table
EXPECTED_FIELDS = {
    "agent_name",
    "instance_id",
    "role",
    "status",
    "project_root",
    "current_task_id",
    "last_seen",
    "lease_expiry",
}

# Status values that must appear in the status values table
EXPECTED_STATUS_VALUES = {"active", "idle", "stale", "disconnected"}

# Instance ID examples must follow {agent}#{suffix} format
INSTANCE_ID_PATTERN = re.compile(r"^[a-z_]+#[\w-]+$")


class InstanceStatusFieldsDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists(), "instance-aware-status-fields.md missing")

    def test_field_names_present_in_table(self) -> None:
        """Every expected field name appears as a backtick-quoted entry."""
        for field in EXPECTED_FIELDS:
            self.assertIn(
                f"`{field}`",
                self.content,
                f"field '{field}' not found in status fields table",
            )

    def test_field_names_are_snake_case(self) -> None:
        """All backtick-quoted field names in the status table are snake_case."""
        table_started = False
        for line in self.lines:
            if line.strip().startswith("| Field"):
                table_started = True
                continue
            if table_started and line.strip().startswith("|---"):
                continue
            if table_started and line.strip().startswith("|"):
                match = re.search(r"\| `(\w+)`", line)
                if match:
                    name = match.group(1)
                    self.assertRegex(
                        name,
                        r"^[a-z][a-z0-9_]*$",
                        f"field '{name}' is not snake_case",
                    )
            elif table_started:
                break

    def test_status_values_documented(self) -> None:
        """All expected status values appear in the status values table."""
        for val in EXPECTED_STATUS_VALUES:
            self.assertIn(
                f"`{val}`",
                self.content,
                f"status value '{val}' not documented",
            )

    def test_status_field_description_lists_all_values(self) -> None:
        """The status field row mentions every status value."""
        for line in self.lines:
            if "| `status`" in line:
                for val in EXPECTED_STATUS_VALUES:
                    self.assertIn(
                        f"`{val}`",
                        line,
                        f"status field row missing value '{val}'",
                    )
                break
        else:
            self.fail("status field row not found in table")

    def test_instance_id_examples_valid_format(self) -> None:
        """Instance ID examples follow {agent_name}#{suffix} pattern."""
        examples = re.findall(r"`([a-z_]+#[\w-]+)`", self.content)
        self.assertGreater(len(examples), 0, "no instance ID examples found")
        for ex in examples:
            self.assertRegex(
                ex,
                INSTANCE_ID_PATTERN,
                f"instance ID example '{ex}' has invalid format",
            )

    def test_mvp_vs_instance_table_present(self) -> None:
        """The comparison table has expected aspect rows."""
        for aspect in ("Identity", "Heartbeat", "Status", "Task ownership", "Stale detection"):
            self.assertIn(aspect, self.content, f"missing comparison aspect: {aspect}")

    def test_example_status_output_fields_consistent(self) -> None:
        """Example output block uses instance IDs and task= keys."""
        in_example = False
        example_lines: list[str] = []
        for line in self.lines:
            if line.strip() == "```" and in_example:
                break
            if in_example:
                example_lines.append(line)
            if "Example status output" in line:
                in_example = True

        self.assertGreater(len(example_lines), 0, "example status output block not found")
        for line in example_lines:
            line = line.strip()
            if not line or line.startswith("Agent"):
                continue
            # Each entry should contain an instance ID and task=
            self.assertIn("#", line, f"example line missing instance ID: {line}")
            self.assertIn("task=", line, f"example line missing task= field: {line}")
            self.assertIn("last_seen=", line, f"example line missing last_seen= field: {line}")

    def test_doc_links_resolve(self) -> None:
        """All markdown doc links point to existing files."""
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        self.assertGreater(len(links), 0, "no doc links found")
        for link in links:
            target = DOCS_DIR / link
            self.assertTrue(
                target.exists(),
                f"link to {link} does not resolve",
            )

    def test_no_duplicate_headers(self) -> None:
        headers = re.findall(r"^## (.+)$", self.content, re.MULTILINE)
        seen: set[str] = set()
        for h in headers:
            self.assertNotIn(h, seen, f"duplicate header: '{h}'")
            seen.add(h)


if __name__ == "__main__":
    unittest.main()
